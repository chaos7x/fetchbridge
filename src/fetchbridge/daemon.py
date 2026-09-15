"""Dämon-Modus: Inotify-Überwachung des Quellverzeichnisses, Config-Hot-Reload."""

import logging
import sys
import time
from pathlib import Path

from fetchbridge import config
from fetchbridge.healthcheck import write_heartbeat
from fetchbridge.mover import process_file, scan_existing_files

logger = logging.getLogger(__name__)


def run_daemon():
    # Lazy statt Modul-Top-Level-Import: --healthcheck/--version sollen auch
    # funktionieren, wenn inotify aus irgendeinem Grund nicht importierbar
    # ist (z.B. eine kaputte/inkompatible Installation) - nur der Dämon-Modus
    # braucht es tatsächlich.
    import inotify.adapters
    import inotify.constants

    cfg = config.load_config()
    config.SOURCE_DIR = cfg["source_dir"]
    config.TARGET_DIR = cfg["target_dir"]
    config.ALLOWED_EXTENSIONS = cfg["allowed_extensions"]
    config.TEMP_EXTENSIONS = cfg["temp_extensions"]
    config.CLEANUP_EMPTY_DIRS = cfg["cleanup_empty_dirs"]
    logging.getLogger().setLevel(cfg["log_level"])

    logger.info("Starte Inotify-Fetchbridge mit RO/RW-Erkennung...")

    # Aufgelöste Konfiguration sichtbar machen - sonst ist bei falschem
    # source_dir/target_dir (z.B. durch Config-Datei oder Env-Var) im Log
    # nicht erkennbar, welche Pfade tatsächlich verwendet werden.
    used_config_files = [str(f) for f in ([config.CONFIG_FILE] if config.CONFIG_FILE.is_file() else [])] + \
        [str(f) for f in (sorted(config.CONF_D_DIR.glob("*.conf")) if config.CONF_D_DIR.is_dir() else [])]
    logger.info(
        f"Aufgelöste Konfiguration: source_dir={config.SOURCE_DIR} target_dir={config.TARGET_DIR} "
        f"allowed_extensions={sorted(config.ALLOWED_EXTENSIONS)} log_level={cfg['log_level']} "
        f"cleanup_empty_dirs={config.CLEANUP_EMPTY_DIRS} "
        f"config_files={used_config_files if used_config_files else 'keine (nur Defaults/Env)'}"
    )

    # Fail-fast mit klarer Meldung statt eines kryptischen OSError aus
    # InotifyTree, falls source_dir nicht existiert (z.B. falscher/fehlender
    # Mount oder falscher Pfad in Config/Env-Var).
    if not config.SOURCE_DIR.is_dir():
        logger.critical(
            f"❌ source_dir existiert nicht oder ist kein Verzeichnis: '{config.SOURCE_DIR}'. "
            "Prüfe Docker-Volume-Mount sowie SOURCE_DIR in Env/Config. Beende Prozess."
        )
        sys.exit(1)

    try:
        config.TARGET_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.critical(f"❌ target_dir '{config.TARGET_DIR}' konnte nicht angelegt werden: {e}. Beende Prozess.")
        sys.exit(1)

    scan_existing_files()
    write_heartbeat()

    # Watch-Mask auf die tatsächlich relevanten Events beschränkt (abgeschlossene
    # Schreibvorgänge und Verschiebungen ins Verzeichnis). Ohne diese Einschränkung
    # abonniert InotifyTree ALLE Event-Typen, inkl. reiner Verzeichnis-Lesezugriffe -
    # genau solche erzeugt cleanup_empty_dirs() selbst (iterdir()/rmdir() auf dem
    # überwachten Baum), was sonst unnötige Selbst-Events erzeugen würde.
    watch_mask = inotify.constants.IN_CLOSE_WRITE | inotify.constants.IN_MOVED_TO
    try:
        i = inotify.adapters.InotifyTree(str(config.SOURCE_DIR), mask=watch_mask)
    except Exception as e:  # noqa: BLE001 - inotify-Bibliothek hat keine eng gefasste Exception-Hierarchie; jeder Fehler hier soll fail-fast mit klarer Meldung beenden statt mit kryptischem Traceback
        logger.critical(f"❌ Konnte InotifyTree für '{config.SOURCE_DIR}' nicht starten: {e}. Beende Prozess.")
        sys.exit(1)
    logger.debug(f"InotifyTree Überwachung gestartet auf: {config.SOURCE_DIR}")

    last_cfg_hash, _ = config.get_config_hash()
    last_cfg_check = time.monotonic()

    # WICHTIG: event_gen() mit timeout_s beendet sich nach einem einzigen
    # Idle-Timeout ohne Event selbst (StopIteration) - es ist KEIN
    # wiederkehrender periodischer Wecker! Ohne die äußere while-Schleife
    # stirbt der komplette Daemon-Prozess (exit code 0, ohne Exception),
    # sobald z.B. mal >CONFIG_CHECK_INTERVAL Sekunden lang keine Datei
    # reinkommt - Docker startet ihn dann per Restart-Policy endlos neu.
    while True:
        for event in i.event_gen(yield_nones=True, timeout_s=config.CONFIG_CHECK_INTERVAL):
            if (time.monotonic() - last_cfg_check) >= config.CONFIG_CHECK_INTERVAL:
                last_cfg_check = time.monotonic()
                current_cfg_hash, _ = config.get_config_hash()
                if current_cfg_hash != last_cfg_hash:
                    last_cfg_hash = current_cfg_hash
                    logger.info("🔄 Config-Änderung erkannt, lade neu...")
                    cfg = config.load_config()
                    if cfg["source_dir"] != config.SOURCE_DIR:
                        logger.warning(
                            f"source_dir geändert ({config.SOURCE_DIR} -> {cfg['source_dir']}), "
                            "dies erfordert einen Neustart des Fetchbridge-Prozesses, da "
                            "InotifyTree fest an den Startpfad gebunden ist. "
                            "Änderung wird ignoriert, bis der Prozess neu gestartet wird."
                        )
                    else:
                        config.TARGET_DIR = cfg["target_dir"]
                        config.ALLOWED_EXTENSIONS = cfg["allowed_extensions"]
                        config.TEMP_EXTENSIONS = cfg["temp_extensions"]
                        config.CLEANUP_EMPTY_DIRS = cfg["cleanup_empty_dirs"]
                        logging.getLogger().setLevel(cfg["log_level"])
                        config.TARGET_DIR.mkdir(parents=True, exist_ok=True)

            if event is None:
                continue

            (_, type_names, path, filename) = event

            logger.debug(f"Inotify-Event empfangen: {type_names} für {path}/{filename}")

            if config.WATCH_EVENTS.intersection(type_names):
                full_path = Path(path) / filename
                logger.debug(f"Relevantes Event {type_names} auf {filename} -> Starte Verarbeitung")
                process_file(full_path)
                write_heartbeat()

        # event_gen() ist idle-timeout-bedingt ausgelaufen -> neu anstoßen,
        # statt den Daemon zu beenden.
        logger.debug("event_gen() Idle-Timeout erreicht, starte Watch-Zyklus neu.")
        write_heartbeat()
