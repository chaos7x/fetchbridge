# fetchbridge 🌉🎬

`fetchbridge` ist ein leichtgewichtiger, Docker-basierter Hintergrunddienst zur automatisierten Überwachung von Verzeichnissen und zum Verarbeiten/Verschieben von Videodateien via `inotify`.

Er dient als intelligentes Bindeglied in Automated-Media-Pipelines – beispielsweise zwischen einem Stream-Recorder (`streamlink-recorder`) und einem Upload-Service (`yt-upload`).

---

## 🚀 Features

* **Echtzeit-Überwachung:** Reagiert ohne Verzögerung auf Dateisystem-Events (`IN_MOVED_TO`, `IN_CLOSE_WRITE`) mittels `python3-inotify`.
* **Intelligente RW/RO-Erkennung:**
  * **Read-Write (RW):** Verschiebt Dateien direkt ins Zielverzeichnis und räumt leere Quellordner automatisch auf.
  * **Read-Only (RO):** Kopiert Dateien sicher, falls das Quellverzeichnis schreibgeschützt gemountet ist.
* **Initialer Scan:** Verarbeitet beim Start automatisch alle bereits im Quellordner vorhandenen Videos.
* **Filter-Mechanismus:** Ignoriert temporäre Downloads (`.part`, `.ytdl`, `.tmp`), versteckte Dateien sowie ununterstützte Formate.
* **Kollisionsschutz:** Benennt Zieldateien bei Namensgleichheit automatisch um (`video_1.mp4`).
* **Minimales Docker-Image:** Basierend auf Debian Trixie Slim mit einer schlanken 3-Layer-Architektur.

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
      # Quell-Ordner (Eingang aus streamlink-recorder)
      - /opt/docker/streamlink-recorder/videos:/media/out:rw
      # Ziel-Ordner (Eingang für yt-upload)
      - /opt/docker/yt-upload/videos/in:/media/in:rw
```
---

## 🛠️ Lokaler Build & Entwicklung

Ein lokales Image kann über das Build-Skript kompiliert werden:

./build.sh v1.0.0

---

## 📄 Lizenz

Dieses Projekt steht unter der **GNU General Public License v3.0 (GPLv3)**.
