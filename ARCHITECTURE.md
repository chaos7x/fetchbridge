# 🏗️ Architektur

Dieses Dokument beschreibt den Aufbau von `fetchbridge` auf Modulebene: welche Komponente was tut und wie Quell-/Zielverzeichnis, Konfiguration und Healthcheck zusammenspielen. Für Betriebsanleitungen (Docker, Pfade, `fetchbridge.conf`) siehe [README.md](README.md).

## Überblick

```mermaid
flowchart TD

subgraph group_entry["Entry and Daemon"]
  node_cli["CLI Entry<br/>[main.py]"]
  node_daemon["Daemon Loop<br/>[daemon.py]"]
end

subgraph group_configuration["Configuration and Logs"]
  node_config_loader["Config Loader<br/>[config.py]"]
  node_config_files["Config Files"]
  node_logging_setup["Logging Setup<br/>[logging_setup.py]"]
end

subgraph group_processing["File Processing"]
  node_initial_scan["Initial Scan<br/>[mover.py]"]
  node_file_processor["File Processor<br/>[mover.py]"]
  node_stability_check["Stability Check<br/>[mover.py]"]
  node_collision_guard["Collision Guard<br/>[mover.py]"]
  node_transfer["Move or Copy<br/>[mover.py]"]
  node_cleanup["Directory Cleanup<br/>[mover.py]"]
end

subgraph group_observability["Health and Storage"]
  node_source_dir[("Source /media/out")]
  node_target_dir[("Target /media/in")]
  node_heartbeat["Heartbeat Writer<br/>[healthcheck.py]"]
  node_healthcheck["Healthcheck Command<br/>[healthcheck.py]"]
  node_heartbeat_file[("Heartbeat File")]
end

node_upstream_recorder(("Stream Recorder"))
node_downstream_tools(("Media Tools"))
node_docker_monitor(("Docker Monitor"))
node_inotify["Inotify Watcher"]

node_upstream_recorder -->|"writes videos"| node_source_dir
node_source_dir -->|"emits events"| node_inotify
node_inotify -->|"delivers events"| node_daemon
node_cli -->|"starts daemon"| node_daemon
node_cli -->|"runs check"| node_healthcheck
node_daemon -->|"loads config"| node_config_loader
node_config_files -->|"reads settings"| node_config_loader
node_config_loader -->|"returns settings"| node_daemon
node_daemon -->|"configures logging"| node_logging_setup
node_daemon -->|"starts scan"| node_initial_scan
node_initial_scan -->|"reads files"| node_source_dir
node_initial_scan -->|"dispatches files"| node_file_processor
node_daemon -->|"starts watch"| node_inotify
node_daemon -->|"dispatches events"| node_file_processor
node_file_processor -->|"checks stability"| node_stability_check
node_file_processor -->|"resolves names"| node_collision_guard
node_file_processor -->|"requests transfer"| node_transfer
node_transfer -->|"moves or reads"| node_source_dir
node_transfer -->|"writes output"| node_target_dir
node_transfer -.->|"triggers cleanup"| node_cleanup
node_cleanup -.->|"removes folders"| node_source_dir
node_daemon -->|"updates beat"| node_heartbeat
node_heartbeat -->|"writes timestamp"| node_heartbeat_file
node_docker_monitor -.->|"invokes check"| node_healthcheck
node_healthcheck -->|"reads timestamp"| node_heartbeat_file
node_healthcheck -.->|"returns status"| node_docker_monitor
node_target_dir -.->|"provides videos"| node_downstream_tools
node_daemon -->|"polls changes"| node_config_loader

click node_cli "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/main.py"
click node_daemon "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/daemon.py"
click node_initial_scan "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/mover.py"
click node_config_loader "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/config.py"
click node_logging_setup "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/logging_setup.py"
click node_file_processor "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/mover.py"
click node_stability_check "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/mover.py"
click node_collision_guard "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/mover.py"
click node_transfer "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/mover.py"
click node_cleanup "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/mover.py"
click node_heartbeat "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/healthcheck.py"
click node_healthcheck "https://github.com/chaos7x/fetchbridge/blob/main/src/fetchbridge/healthcheck.py"

classDef toneNeutral fill:#f8fafc,stroke:#334155,stroke-width:1.5px,color:#0f172a
classDef toneBlue fill:#dbeafe,stroke:#2563eb,stroke-width:1.5px,color:#172554
classDef toneAmber fill:#fef3c7,stroke:#d97706,stroke-width:1.5px,color:#78350f
classDef toneMint fill:#dcfce7,stroke:#16a34a,stroke-width:1.5px,color:#14532d
classDef toneRose fill:#ffe4e6,stroke:#e11d48,stroke-width:1.5px,color:#881337
classDef toneIndigo fill:#e0e7ff,stroke:#4f46e5,stroke-width:1.5px,color:#312e81
classDef toneTeal fill:#ccfbf1,stroke:#0f766e,stroke-width:1.5px,color:#134e4a
class node_cli,node_daemon toneBlue
class node_config_loader,node_config_files,node_logging_setup toneAmber
class node_initial_scan,node_file_processor,node_stability_check,node_collision_guard,node_transfer,node_cleanup toneMint
class node_source_dir,node_target_dir,node_heartbeat,node_healthcheck,node_heartbeat_file toneRose
class node_upstream_recorder,node_downstream_tools,node_docker_monitor,node_inotify toneIndigo
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
- **Source `/media/out`** — Quellverzeichnis, typischerweise von einem vorgelagerten Tool (z. B. `tw-recorder`) befüllt.
- **Target `/media/in`** — Zielverzeichnis, aus dem nachgelagerte Tools (z. B. `yt-upload`) Dateien übernehmen.
- **Heartbeat-Datei** — von `healthcheck.py` geschrieben/gelesen, Grundlage für `--healthcheck` und Docker/Kubernetes-Liveness-Probes.

## Einordnung in die Medien-Pipeline

`fetchbridge` ist das Bindeglied zwischen `tw-recorder` (schreibt fertige Aufnahmen nach `/media/out`) und `yt-upload` (verarbeitet neue Dateien aus `/media/in`) — die RW/RO-Erkennung erlaubt dabei, `/media/out` je nach Setup entweder als gemeinsames beschreibbares Volume oder als read-only-Mount einzubinden, ohne dass sich am Verhalten von `fetchbridge` etwas ändert.
