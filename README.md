# fetchbridge 🌉🎬

`fetchbridge` ist ein leichtgewichtiger, Docker-basierter Hintergrunddienst zur automatisierten Überwachung von Verzeichnissen und zum Verarbeiten/Verschieben von Videodateien via `inotify`.

Er dient als intelligentes Bindeglied in Automated-Media-Pipelines – beispielsweise zwischen einem Stream-Recorder (`tw-recorder`) und einem Upload-Service (`yt-upload`).

---

## 🚀 Features

* **Echtzeit-Überwachung:** Reagiert ohne Verzögerung auf Dateisystem-Events (`IN_MOVED_TO`, `IN_CLOSE_WRITE`) mittels `inotify`.
* **Intelligente RW/RO-Erkennung:**
  * **Read-Write (RW):** Verschiebt Dateien direkt ins Zielverzeichnis und räumt leere Quellordner automatisch auf.
  * **Read-Only (RO):** Kopiert Dateien sicher, falls das Quellverzeichnis schreibgeschützt gemountet ist.
* **Initialer Scan:** Verarbeitet beim Start automatisch alle bereits im Quellordner vorhandenen Videos.
* **Filter-Mechanismus:** Ignoriert temporäre Downloads (`.part`, `.ytdl`, `.tmp`), versteckte Dateien sowie ununterstützte Formate.
* **Kollisionsschutz:** Benennt Zieldateien bei Namensgleichheit automatisch um (`video_1.mp4`).
* **Hot-Reloading der Konfiguration:** Überwacht die Konfigurationsdatei und übernimmt Änderungen automatisch im laufenden Betrieb (außer `source_dir`, das einen Neustart erfordert).
* **Minimales Docker-Image:** Drei Varianten (Debian, Alpine, reines Python-Image) zur Auswahl.

---

## 🛠️ Voraussetzungen & Pfade

Der Container arbeitet intern mit zwei primären Datenpfaden:

| Pfad im Container | Funktion | Standard-Format |
| :--- | :--- | :--- |
| `/media/out` | **Quellverzeichnis** (Eingang für `fetchbridge`) | `.mkv`, `.mp4`, `.webm` |
| `/media/in` | **Zielverzeichnis** (Ausgang für Folge-Tools) | `.mkv`, `.mp4`, `.webm` |
| `/log` | Log-Dateien (Optional) | Logs / App-Output |

---

## 📦 Schnellstart mit Docker Compose

Hier ist ein Beispiel für die Integration in eine bestehende `docker-compose.yml`:

```yaml
services:
  fetchbridge:
    image: ghcr.io/chaos7x/fetchbridge:latest
    container_name: fetchbridge
    hostname: fetchbridge
    user: "11107:11108"
    restart: unless-stopped
    environment:
      - TZ=Europe/Berlin
      - PYTHONUNBUFFERED=1
      - LOG_LEVEL=INFO
    volumes:
      # Quell-Ordner (Eingang aus tw-recorder)
      - /opt/docker/tw-recorder/videos:/media/out:rw
      # Ziel-Ordner (Eingang für yt-upload)
      - /opt/docker/yt-upload/videos/in:/media/in:rw
```

---

## 🛠️ Bare-Metal-Installation (ohne Docker)

`fetchbridge` läuft auch direkt auf dem Host. `inotify` ist die einzige echte Abhängigkeit (Kernfunktion, nicht optional) und kommt bewusst über den jeweiligen Paketmanager statt über PyPI, wo möglich - `pip` installiert nur das eigene Package:

```bash
apt install python3-pip python3-setuptools python3-inotify
cd /pfad/zu/fetchbridge
pip install --break-system-packages --no-deps .
```

Danach steht der Befehl `fetchbridge` systemweit zur Verfügung (`fetchbridge --version` zum Testen).

---

## 🐳 Docker-Image-Varianten

| Dockerfile | Basis | Installationsweg |
|---|---|---|
| `Dockerfile` (Standard) | `debian:trixie-slim` | `apt` für `python3-inotify` (korrektes Paket), `pip install --no-deps .` für fetchbridge selbst |
| `Dockerfile.alpine` | `alpine:3` | `inotify` **per `pip`**, nicht `apk` - Alpines `py3-inotify`-Paket packt tatsächlich ein anderes, unpassendes Projekt (`pyinotify` statt `inotify`) |
| `Dockerfile.pyimg` | `python:3-slim` | Ein einziger `pip install .` - `inotify` ist in `pyproject.toml` als Dependency deklariert, pip löst es automatisch mit auf |

**Wichtiger Hinweis zu Alpine:** Falls du selbst mal `apk add py3-inotify` für ein anderes Projekt in Erwägung ziehst - das Paket ist trotz des Namens **nicht** das hier (und in vielen ähnlichen Tools) verwendete `inotify`-Package von PyPI (`import inotify.adapters`), sondern das ältere, API-inkompatible `pyinotify`. Für `fetchbridge` wird das korrekte Package deshalb explizit per `pip` installiert.

---

## ⚙️ Konfiguration

Die Hauptkonfiguration erfolgt über `/etc/fetchbridge/fetchbridge.conf` (bzw. `fetchbridge.conf.example` als Vorlage). Zusätzlich wird `/etc/fetchbridge/conf.d/*.conf` eingelesen (alphabetisch, spätere Dateien überschreiben frühere Werte). Änderungen werden im laufenden Betrieb automatisch erkannt (Hash-Prüfung alle `CONFIG_CHECK_INTERVAL` Sekunden) - außer bei `source_dir`, das einen Neustart erfordert (`InotifyTree` ist fest an den Startpfad gebunden).

```ini
[general]
# Log-Level: DEBUG, INFO, WARNING, ERROR
# log_level = INFO

# Quellverzeichnis, das überwacht wird (Änderung erfordert Neustart)
# source_dir = /media/out

# Zielverzeichnis, in das fertige Dateien verschoben/kopiert werden
# target_dir = /media/in


[mover]
# Kommagetrennte Liste erlaubter Datei-Endungen
# allowed_extensions = .mkv,.mp4,.webm

# Kommagetrennte Liste von Endungen, die als "noch nicht fertig" gelten
# temp_extensions = .part,.ytdl,.tmp,.temp

# Leere Quell-Unterordner nach dem Verschieben automatisch entfernen (true/false)
# cleanup_empty_dirs = false
```

### CLI & Parameter
```text
fetchbridge [-h] [-D] [--healthcheck] [-V]
```

* `-D`, `--daemon` — Dämon-Modus: Dauerhafte Ordnerüberwachung (Standardmodus im Container, siehe `entrypoint.sh`)
* `--healthcheck` — Prüft die Heartbeat-Datei, Exit-Code 0 (healthy) oder 1 (unhealthy). Für Docker `HEALTHCHECK` gedacht, läuft unabhängig vom Dämon-Prozess.
* `-V`, `--version` — Versionsnummer anzeigen

### Umgebungsvariablen

* `CONFIG_FILE` — Standard `/etc/fetchbridge/fetchbridge.conf`
* `CONF_D_DIR` — Standard `/etc/fetchbridge/conf.d`
* `SOURCE_DIR` / `TARGET_DIR` — Fallback, falls nicht in der Config gesetzt (Standard `/media/out` bzw. `/media/in`)
* `ALLOWED_EXTENSIONS` / `TEMP_EXTENSIONS` — Fallback, falls nicht in der Config gesetzt
* `LOG_LEVEL` — Standard `INFO`
* `CONFIG_CHECK_INTERVAL` — Standard `15` (Sekunden zwischen Hash-Prüfungen der Config-Dateien)
* `HEARTBEAT_FILE` — Standard `/tmp/fetchbridge.heartbeat`
* `HEARTBEAT_MAX_AGE` — Standard `60` (Sekunden, bevor `--healthcheck` als "unhealthy" gilt)

---

## 🧑‍💻 Lokaler Build & Entwicklung

Ein lokales Image kann über das Build-Skript kompiliert werden:

```bash
./build.sh                    # Nutzt Name & Version aus pyproject.toml, Standard-Dockerfile
./build.sh 2.0.0               # Explizite Version, Standard-Dockerfile
./build.sh alpine               # Version aus pyproject.toml, Dockerfile.alpine
./build.sh 2.0.0 pyimg          # Explizite Version, Dockerfile.pyimg
```

Name und Standard-Version werden automatisch aus `pyproject.toml` gelesen - ein explizit übergebenes Versions-Argument überschreibt das.

### Tests & Linting
```bash
apt install python3-pytest   # oder: pip install -r requirements-test.txt
pytest -v

ruff check src/fetchbridge/
```

---

## 📄 Lizenz

Dieses Projekt steht unter der **GNU General Public License v3.0 (GPLv3)**.
