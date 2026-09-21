# 🏗️ Architektur

Dieses Dokument beschreibt den Aufbau von `fetchbridge` auf Modulebene: welche Komponente was tut und wie Quell-/Zielverzeichnis, Konfiguration und Healthcheck zusammenspielen. Für Betriebsanleitungen (Docker, Pfade, `fetchbridge.conf`) siehe [README.md](README.md).

## Überblick

```mermaid
flowchart TD

subgraph group_runtime["Runtime Control"]
  node_cli["CLI Entry<br/>[main.py]"]
  node_daemon["Daemon Controller<br/>[daemon.py]"]
  node_watcher["Inotify Watcher<br/>[daemon.py]"]
end

subgraph group_processing["File Processing"]
  node_scanner["Initial Scanner<br/>[mover.py]"]
  node_processor["File Filter<br/>[mover.py]"]
  node_stability["Stability Check<br/>[mover.py]"]
  node_transfer["RW/RO Transfer<br/>[mover.py]"]
  node_cleanup["Directory Cleanup<br/>[mover.py]"]
end

subgraph group_configuration["Configuration"]
  node_config["Config Manager<br/>[config.py]"]
  node_config_files["Config Files"]
end

subgraph group_operations["Operations"]
  node_logging["Logging Setup<br/>[logging_setup.py]"]
  node_heartbeat["Heartbeat Writer<br/>[healthcheck.py]"]
  node_healthcheck["Healthcheck Command<br/>[healthcheck.py]"]
end

node_operator(("Operator"))
node_recorder(("Stream Recorder"))
node_uploader(("Upload Service"))
node_source["Recordings Directory"]
node_target["Incoming Directory"]
node_log_sinks["Log Sinks"]
node_syslog(("Syslog Daemon"))

node_operator -->|"invokes"| node_cli
node_recorder -->|"writes videos"| node_source
node_uploader -->|"reads videos"| node_target
node_cli -->|"starts daemon"| node_daemon
node_cli -->|"runs check"| node_healthcheck
node_daemon -->|"loads config"| node_config
node_config_files -->|"provides settings"| node_config
node_daemon -->|"configures logs"| node_logging
node_daemon -->|"starts watcher"| node_watcher
node_source -->|"emits events"| node_watcher
node_watcher -->|"dispatches events"| node_daemon
node_daemon -->|"scans startup"| node_scanner
node_daemon -->|"processes events"| node_processor
node_scanner -->|"processes files"| node_processor
node_processor -->|"checks stability"| node_stability
node_processor -->|"transfers file"| node_transfer
node_transfer -->|"reads or removes"| node_source
node_transfer -->|"writes output"| node_target
node_processor -->|"cleans folders"| node_cleanup
node_daemon -->|"writes heartbeat"| node_heartbeat
node_healthcheck -->|"reads heartbeat"| node_heartbeat
node_logging -->|"writes logs"| node_log_sinks
node_logging -.->|"uses syslog"| node_syslog
node_daemon -->|"reloads config"| node_config

click node_cli "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/main.py"
click node_daemon "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/daemon.py"
click node_watcher "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/daemon.py"
click node_config "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/config.py"
click node_scanner "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/mover.py"
click node_processor "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/mover.py"
click node_stability "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/mover.py"
click node_transfer "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/mover.py"
click node_cleanup "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/mover.py"
click node_logging "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/logging_setup.py"
click node_heartbeat "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/healthcheck.py"
click node_healthcheck "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/healthcheck.py"

classDef toneNeutral fill:#f8fafc,stroke:#334155,stroke-width:1.5px,color:#0f172a
classDef toneBlue fill:#dbeafe,stroke:#2563eb,stroke-width:1.5px,color:#172554
classDef toneAmber fill:#fef3c7,stroke:#d97706,stroke-width:1.5px,color:#78350f
classDef toneMint fill:#dcfce7,stroke:#16a34a,stroke-width:1.5px,color:#14532d
classDef toneRose fill:#ffe4e6,stroke:#e11d48,stroke-width:1.5px,color:#881337
classDef toneIndigo fill:#e0e7ff,stroke:#4f46e5,stroke-width:1.5px,color:#312e81
classDef toneTeal fill:#ccfbf1,stroke:#0f766e,stroke-width:1.5px,color:#134e4a
class node_cli,node_daemon,node_watcher toneBlue
class node_scanner,node_processor,node_stability,node_transfer,node_cleanup toneAmber
class node_config,node_config_files toneMint
class node_logging,node_heartbeat,node_healthcheck toneRose
class node_operator,node_recorder,node_uploader,node_source,node_target,node_log_sinks,node_syslog toneIndigo
```

## Komponenten

### Entry and Daemon

- **`main.py`** — argparse-CLI mit `-D`/`--daemon` (startet den Dauerbetrieb) und `--healthcheck` (prüft nur die Heartbeat-Datei und beendet sich sofort, für Docker `HEALTHCHECK`). Konfiguriert bewusst noch kein Logging: das würde bereits für `--healthcheck`/`--version` einen stdout-Handler ohne Datei-Erkennung fest einrichten, obwohl diese Aufrufe kein Logging brauchen — `setup_logging()` läuft daher erst innerhalb von `run_daemon()`.
- **`daemon.py`** — `run_daemon()` lädt die Konfiguration, validiert `SOURCE_DIR`/`TARGET_DIR` (`_ensure_source_dir_ready()`/`_ensure_target_dir_ready()` — in einem Container muss es sich um ein echtes Docker-Volume handeln, nicht nur um das vom Dockerfile per `mkdir -p` angelegte Verzeichnis, sonst würden verarbeitete Dateien beim nächsten Neustart unbemerkt verloren gehen), führt einen initialen Scan (`scan_existing_files()`) durch und startet danach einen `InotifyTree`-Watch (nur `IN_CLOSE_WRITE`/`IN_MOVED_TO`, um keine Selbst-Events durch das eigene `cleanup_empty_dirs()` zu erzeugen). Die äußere `while True`-Schleife um `event_gen()` ist notwendig, weil dessen Idle-Timeout ohne sie den gesamten Prozess mit Exit-Code 0 beenden würde, sobald mal länger keine Datei ankommt. Config-Änderungen werden per Hash-Vergleich erkannt und hot-reloaded — außer bei einer Änderung von `source_dir`, die einen Neustart erfordert, da `InotifyTree` fest an seinen Startpfad gebunden ist.

### Configuration and Logs

- **`config.py`** — liest `fetchbridge.conf` und alphabetisch sortiert alle `conf.d/*.conf` ein, mit Fallback auf Environment-Variablen pro Einstellung. `get_config_hash()` bildet die Grundlage für das Hot-Reload im Daemon. `_is_dedicated_mount()` unterscheidet per `st_dev`-Vergleich zwischen einem echten Docker-Volume/Bind-Mount und einem vom Image nur fest angelegten Verzeichnis; `_running_in_container()` erkennt die Container-Umgebung zuverlässig über `/.dockerenv`.
- **`logging_setup.py`** — richtet das Logging (Konsole/Datei) anhand der geladenen Konfiguration ein, inklusive einer INFO-Zusammenfassung, welches Log-System gerade aktiv ist.

### File Processing

- **`mover.py`** — enthält den gesamten Verarbeitungspfad:
  - `scan_existing_files()` — initialer Scan von `SOURCE_DIR` beim Start, damit bereits vorhandene Dateien nicht auf ein Inotify-Event warten müssen.
  - `is_file_stable()` — vergleicht die Dateigröße über die Zeit, um sicherzustellen, dass eine Datei nicht mehr von einem anderen Prozess (z. B. `tw-recorder`s FFmpeg-Remux) beschrieben wird; zusätzliche Absicherung neben der Watch-Maske für Flush-Close-Reopen-Verhalten oder verzögerte Events auf Netzwerk-Mounts.
  - `process_file()` — lehnt Symlinks explizit ab (sonst wäre ein Symlink mit erlaubter Endung ein Primitive für beliebigen Dateizugriff über `shutil.copy2`/`shutil.move`), filtert Temp-/versteckte Dateien und nicht unterstützte Endungen, löst Namenskollisionen im Ziel auf (`video_1.mp4`), und entscheidet dann zwischen Verschieben (RW-Quelle) und Kopieren (RO-Quelle, per `is_writable()`-Prüfung auf das Elternverzeichnis).
  - `_move_file()` — versucht zuerst einen atomaren `os.rename()`; schlägt der fehl (z. B. `EXDEV` bei unterschiedlichen Mounts), wird explizit auf Kopieren+Löschen zurückgefallen und der konkrete Fehlschlag-Grund geloggt, statt das (wie `shutil.move()`) stillschweigend zu tun.
  - `cleanup_empty_dirs()` — räumt nach einem erfolgreichen Verschieben (nur RW, nur wenn `CLEANUP_EMPTY_DIRS` aktiv ist) rekursiv leer gewordene Unterverzeichnisse unterhalb von `SOURCE_DIR` auf, bis zur Quellwurzel selbst oder zum ersten nicht-leeren Verzeichnis.

### Health and Storage

- **`healthcheck.py`** — `write_heartbeat()` wird bei jedem verarbeiteten Event und bei jedem Idle-Zyklus des Daemons aufgerufen; `check_healthcheck()` (CLI: `--healthcheck`) prüft als eigener kurzlebiger Prozess nur Existenz und Alter der Heartbeat-Datei, unabhängig vom laufenden Daemon — erkennt damit sowohl tote als auch hängende (deadlocked) Prozesse.
- **Source `/srv/media-pipeline/recordings`** — Quellverzeichnis, typischerweise von einem vorgelagerten Tool (z. B. `tw-recorder`) befüllt.
- **Target `/srv/media-pipeline/incoming`** — Zielverzeichnis, aus dem nachgelagerte Tools (z. B. `yt-upload`) Dateien übernehmen.
- **Heartbeat-Datei** — von `healthcheck.py` geschrieben/gelesen, Grundlage für `--healthcheck` und Docker/Kubernetes-Liveness-Probes.

## Einordnung in die Medien-Pipeline

`fetchbridge` ist das Bindeglied zwischen `tw-recorder` (schreibt fertige Aufnahmen nach `/srv/media-pipeline/recordings`) und `yt-upload` (verarbeitet neue Dateien aus `/srv/media-pipeline/incoming`) — die RW/RO-Erkennung erlaubt dabei, `/srv/media-pipeline/recordings` je nach Setup entweder als gemeinsames beschreibbares Volume oder als read-only-Mount einzubinden, ohne dass sich am Verhalten von `fetchbridge` etwas ändert.
