# fetchbridge 🌉🎬

`fetchbridge` ist ein leichtgewichtiger, Docker-basierter Hintergrunddienst zur automatisierten Überwachung von Verzeichnissen und zum Verarbeiten/Verschieben von Videodateien via `inotify`.

Er dient als intelligentes Bindeglied in Automated-Media-Pipelines – beispielsweise zwischen einem Stream-Recorder (`tw-recorder`) und einem Upload-Service (`yt-upload`).

Eine Übersicht der internen Architektur (Module, Datenfluss, Diagramm) findet sich in [ARCHITECTURE.md](ARCHITECTURE.md).

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
| `/srv/media-pipeline/recordings` | **Quellverzeichnis** (Eingang für `fetchbridge`, geteilt mit `tw-recorder`s `STORAGE_DIR`) | `.mkv`, `.mp4`, `.webm` |
| `/srv/media-pipeline/incoming` | **Zielverzeichnis** (Ausgang für Folge-Tools, geteilt mit `yt-upload`s `IN_DIR`) | `.mkv`, `.mp4`, `.webm` |
| `/log` | Log-Dateien (Optional, siehe unten) | Logs / App-Output |

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
      - /opt/docker/tw-recorder/recordings:/srv/media-pipeline/recordings:rw
      # Ziel-Ordner (Eingang für yt-upload) - zeigt bewusst auf die "incoming"-
      # Unterordner von yt-uploads eigenem yt-upload-data-Mount (der dort
      # direkt auf /srv/media-pipeline gemountet ist) statt auf ein eigenes
      # Top-Level-Verzeichnis, spart yt-upload dadurch einen zweiten
      # Bind-Mount (siehe yt-upload/docker-compose.yaml.example)
      - /opt/docker/yt-upload/yt-upload-data/incoming:/srv/media-pipeline/incoming:rw
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

Die Logdatei landet je nach Umgebung automatisch am sinnvollsten Ort (`/var/log/fetchbridge/`, sofern beschreibbar und ein klassischer Syslog-Daemon läuft, sonst nur auf `stdout`/journald) - siehe `log_file`-Konfigurationsoption, falls ein fester Pfad gewünscht ist. Läuft ein Syslog-Daemon, rotiert die App die Datei bewusst **nicht** selbst (kein `RotatingFileHandler`) - das übernimmt das mitgelieferte `/etc/logrotate.d/fetchbridge` (nur im `.deb`-Paket enthalten; bei einer reinen `pip`-Installation ohne `.deb` selbst einrichten, falls gewünscht). Nur bei explizit gesetztem `log_file` oder einem gemounteten Docker-`/log`-Volume rotiert die App eigenständig, da dort sonst niemand rotieren würde.

### Alternative: Fertiges Debian-Paket (.deb)

Jedes [GitHub Release](https://github.com/chaos7x/fetchbridge/releases) enthält zusätzlich ein `fetchbridge_<version>_all.deb` als Anhang - keine manuelle `pip`-Installation nötig, `apt`/`dpkg` löst die Abhängigkeit (`python3-inotify`) automatisch mit auf:

```bash
wget https://github.com/chaos7x/fetchbridge/releases/latest/download/fetchbridge_<version>_all.deb
apt install ./fetchbridge_<version>_all.deb
```

Das Paket legt einen dedizierten Systemuser (`fetchbridge`) an und startet den Dienst bewusst nicht automatisch - erst `/etc/fetchbridge/fetchbridge.conf` (bzw. `conf.d/`) anpassen, dann:

```bash
systemctl enable --now fetchbridge
```

**Devuan / Debian ohne systemd (`sysvinit-core`):** Das Paket bringt zusätzlich ein klassisches `/etc/init.d/fetchbridge`-Skript mit, das `postinst` automatisch anstelle des systemd-Service registriert, wenn kein systemd läuft:

```bash
service fetchbridge start
```

### Alternative: Standalone .pyz (kein pip/apt nötig)

`./build-pyz.sh` baut aus `src/` ein einziges, selbst-enthaltenes `fetchbridge.pyz` samt `inotify` - läuft auf jedem System mit einem nackten `python3`, ganz ohne vorherige `pip install`/`apt install`:

```bash
./build-pyz.sh
./fetchbridge.pyz --version
```

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

# Fester Pfad für die Logdatei (bei explizitem log_file oder gemountetem
# /log-Docker-Volume rotierend, max. 10 MB, 5 Backups - läuft stattdessen ein
# klassischer Syslog-Daemon, übernimmt logrotate die Rotation, siehe README).
# Ohne diese Angabe wird automatisch geloggt, sobald /log tatsächlich als
# Docker-Volume gemountet ist (reines Vorhandensein des Verzeichnisses
# reicht nicht, siehe unten) oder ein klassischer Syslog-Daemon läuft -
# sonst nur nach stdout (journald/docker logs erfassen das bereits).
# log_file = /log/fetchbridge.log

# Quellverzeichnis, das überwacht wird (Änderung erfordert Neustart)
# source_dir = /srv/media-pipeline/recordings

# Zielverzeichnis, in das fertige Dateien verschoben/kopiert werden
# target_dir = /srv/media-pipeline/incoming


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
fetchbridge [-h] [-D] [--healthcheck] [-v]
```

* `-D`, `--daemon` — Dämon-Modus: Dauerhafte Ordnerüberwachung (Standardmodus im Container, siehe `entrypoint.sh`)
* `--healthcheck` — Prüft die Heartbeat-Datei, Exit-Code 0 (healthy) oder 1 (unhealthy). Für Docker `HEALTHCHECK` gedacht, läuft unabhängig vom Dämon-Prozess.
* `-v`, `--version` — Versionsnummer anzeigen

### Umgebungsvariablen

* `CONFIG_FILE` — Standard `/etc/fetchbridge/fetchbridge.conf`
* `CONF_D_DIR` — Standard `/etc/fetchbridge/conf.d`
* `SOURCE_DIR` / `TARGET_DIR` — Fallback, falls nicht in der Config gesetzt. Standard `/srv/media-pipeline/recordings` (dasselbe Verzeichnis wie `tw-recorder`s `STORAGE_DIR`) bzw. `/srv/media-pipeline/incoming` (dasselbe Verzeichnis wie `yt-upload`s `IN_DIR`), einheitlich für Docker und Bare-Metal. Das `.deb`-Postinst legt beide mit einer gemeinsamen Gruppe (`media-pipeline`) an, damit alle drei Dienste darauf zugreifen können.
* `ALLOWED_EXTENSIONS` / `TEMP_EXTENSIONS` — Fallback, falls nicht in der Config gesetzt
* `LOG_LEVEL` — Standard `INFO`
* `LOG_FILE` — Fallback, falls nicht in der Config gesetzt; siehe `[general]`-Sektion oben
* `CONFIG_CHECK_INTERVAL` — Standard `15` (Sekunden zwischen Hash-Prüfungen der Config-Dateien)
* `HEARTBEAT_FILE` — Standard `/tmp/fetchbridge.heartbeat`
* `HEARTBEAT_MAX_AGE` — Standard `60` (Sekunden, bevor `--healthcheck` als "unhealthy" gilt)

---

## 🏷️ Versionierung

Reguläre Releases folgen `vX.Y.Z` (SemVer) und entstehen manuell zusammen mit einer echten Code-Änderung.

Zusätzlich prüft ein monatlicher Workflow (`os-patch-release.yml`, 1. jeden Monats), ob das Debian-/Alpine-Basis-Image ungenutzte Security-Patches hat, die `docker-refresh.yml`'s wöchentliches `latest`-Update zwar schon mitnimmt, die aber an den fixen `vX.Y.Z`-Tags vorbeilaufen (die frieren für immer auf ihrem Build-Zeitpunkt ein). Findet der Workflow etwas, hängt er eine **vierte Versionsstelle** an, die ausschließlich für solche reinen OS-Patch-Releases reserviert ist: `v1.3.1` → `v1.3.1.1` → `v1.3.1.2` (jeweils ohne Code-Änderung, nur aktualisierte System-Pakete). Bleibt die vierte Stelle bei Nichts-zu-patchen-Läufen einfach aus, gibt es auch keinen neuen Tag - kein Rauschen in der Release-Historie.

Der nächste echte Code-Release setzt diese vierte Stelle **nicht fort**, sondern lässt sie weg: auf `v1.3.1.2` folgt bei einer echten Änderung `v1.3.2`, nicht `v1.3.2.0` oder `v1.3.1.3`.

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
