#!/usr/bin/env python3
# Copyright (C) 2026 Chaos7x
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.

import os
import sys
import argparse
import configparser
import hashlib
import logging
import shutil
import time
import inotify.adapters
from pathlib import Path

__title__ = "Fetchbridge CLI"
__version__ = "1.1.1"

CONFIG_FILE = Path(os.getenv("CONFIG_FILE", "/etc/fetchbridge/fetchbridge.conf"))
CONF_D_DIR = Path(os.getenv("CONF_D_DIR", "/etc/fetchbridge/conf.d"))

SOURCE_DIR = Path("/media/out")
TARGET_DIR = Path("/media/in")
ALLOWED_EXTENSIONS = {".mkv", ".mp4", ".webm"}
TEMP_EXTENSIONS = {".part", ".ytdl", ".tmp", ".temp"}
WATCH_EVENTS = {'IN_MOVED_TO', 'IN_CLOSE_WRITE'}
CLEANUP_EMPTY_DIRS = False

CONFIG_CHECK_INTERVAL = int(os.getenv("CONFIG_CHECK_INTERVAL", "15"))


def get_config_files_state() -> dict:
    files_state = {}
    config_files = []

    if CONFIG_FILE.is_file():
        config_files.append(CONFIG_FILE)
    if CONF_D_DIR.is_dir():
        config_files.extend(sorted(CONF_D_DIR.glob("*.conf")))

    for f in config_files:
        try:
            files_state[f] = hashlib.md5(f.read_bytes()).hexdigest()
        except Exception:
            pass

    return files_state


def get_config_hash() -> tuple[str, dict]:
    state = get_config_files_state()
    combined = hashlib.md5()
    for f in sorted(state.keys()):
        combined.update(f.name.encode("utf-8"))
        combined.update(state[f].encode("utf-8"))
    return combined.hexdigest(), state


def load_config():
    config = configparser.ConfigParser(
        interpolation=None,
        delimiters=('=',),
        comment_prefixes=('#', ';'),
        allow_no_value=True
    )
    config.optionxform = str

    config_files = []
    if CONFIG_FILE.is_file():
        config_files.append(CONFIG_FILE)
    if CONF_D_DIR.is_dir():
        config_files.extend(sorted(CONF_D_DIR.glob("*.conf")))

    if config_files:
        try:
            config.read(config_files, encoding="utf-8")
        except Exception as e:
            logging.warning(f"Fehler beim Lesen der Config-Dateien: {e}")

    source_dir = Path(config.get("general", "source_dir", fallback=os.getenv("SOURCE_DIR", "/media/out")))
    target_dir = Path(config.get("general", "target_dir", fallback=os.getenv("TARGET_DIR", "/media/in")))

    allowed_raw = config.get(
        "mover", "allowed_extensions",
        fallback=os.getenv("ALLOWED_EXTENSIONS", ".mkv,.mp4,.webm")
    )
    allowed_extensions = {
        e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
        for e in allowed_raw.split(",") if e.strip()
    }

    temp_raw = config.get(
        "mover", "temp_extensions",
        fallback=os.getenv("TEMP_EXTENSIONS", ".part,.ytdl,.tmp,.temp")
    )
    temp_extensions = {
        e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
        for e in temp_raw.split(",") if e.strip()
    }

    log_level = config.get("general", "log_level", fallback=os.getenv("LOG_LEVEL", "INFO")).upper()

    cleanup_raw = config.get(
        "mover", "cleanup_empty_dirs",
        fallback=os.getenv("CLEANUP_EMPTY_DIRS", "false")
    )
    cleanup_empty_dirs_enabled = cleanup_raw.strip().lower() in ("1", "true", "yes")

    return {
        "source_dir": source_dir,
        "target_dir": target_dir,
        "allowed_extensions": allowed_extensions,
        "temp_extensions": temp_extensions,
        "log_level": log_level,
        "cleanup_empty_dirs": cleanup_empty_dirs_enabled,
        "config_obj": config
    }


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def is_writable(path: Path) -> bool:
    parent = path.parent if path.is_file() else path
    writable = os.access(parent, os.W_OK)
    logging.debug(f"Mount-Prüfung für '{parent}': Writable={writable}")
    return writable

def cleanup_empty_dirs(directory: Path):
    if directory == SOURCE_DIR or not directory.is_relative_to(SOURCE_DIR):
        logging.debug(f"Aufräumen übersprungen (Ausnahme/Basis-Ordner): {directory}")
        return

    if not is_writable(directory):
        logging.debug(f"Aufräumen übersprungen (RO-Mount): {directory}")
        return

    try:
        current = directory
        while current != SOURCE_DIR and current.is_dir():
            if not any(current.iterdir()):
                current.rmdir()
                logging.info(f"🧹 Leeres Verzeichnis entfernt: {current}")
                current = current.parent
            else:
                logging.debug(f"Verzeichnis nicht leer, stoppe Aufräumen: {current}")
                break
    except Exception as e:
        logging.warning(f"Fehler beim Aufräumen von {directory}: {e}")

def process_file(filepath: Path):
    if not filepath.is_file():
        logging.debug(f"Ignoriere (Keine reguläre Datei oder existiert nicht mehr): {filepath}")
        return

    ext = filepath.suffix.lower()

    if ext in TEMP_EXTENSIONS or filepath.name.startswith("."):
        logging.debug(f"Ignoriere Temp/Versteckte Datei: {filepath.name}")
        return

    if ext not in ALLOWED_EXTENSIONS:
        logging.debug(f"Ignoriere nicht unterstützte Endung '{ext}': {filepath.name}")
        return

    filename = filepath.name
    dest_path = TARGET_DIR / filename

    counter = 1
    original_dest = dest_path
    while dest_path.exists():
        dest_path = TARGET_DIR / f"{original_dest.stem}_{counter}{original_dest.suffix}"
        counter += 1
        logging.debug(f"Ziel existiert bereits. Neuer Name: {dest_path.name}")

    source_parent = filepath.parent

    try:
        if is_writable(filepath):
            logging.info(f"🚚 Verschiebe (RW): {filepath.name} -> {dest_path.name}")
            shutil.move(str(filepath), str(dest_path))
            logging.info(f"✅ Verschieben erfolgreich: {dest_path.name}")
            if CLEANUP_EMPTY_DIRS:
                cleanup_empty_dirs(source_parent)
        else:
            logging.info(f"📋 Kopiere (RO): {filepath.name} -> {dest_path.name}")
            shutil.copy2(str(filepath), str(dest_path))
            logging.info(f"✅ Kopieren erfolgreich: {dest_path.name}")

    except Exception as e:
        logging.warning(f"Fehler bei Verarbeitung von {filename}: {e}")

def scan_existing_files():
    logging.info("Scanne nach bereits vorhandenen fertigen Dateien...")
    found_count = 0
    for filepath in SOURCE_DIR.rglob("*"):
        if filepath.is_file() and filepath.suffix.lower() in ALLOWED_EXTENSIONS:
            found_count += 1
            logging.debug(f"Scan hat Datei gefunden: {filepath}")
            process_file(filepath)
    logging.debug(f"Initialer Scan beendet. {found_count} passende Datei(en) gescannt.")

def run_daemon():
    global SOURCE_DIR, TARGET_DIR, ALLOWED_EXTENSIONS, TEMP_EXTENSIONS, CLEANUP_EMPTY_DIRS

    cfg = load_config()
    SOURCE_DIR = cfg["source_dir"]
    TARGET_DIR = cfg["target_dir"]
    ALLOWED_EXTENSIONS = cfg["allowed_extensions"]
    TEMP_EXTENSIONS = cfg["temp_extensions"]
    CLEANUP_EMPTY_DIRS = cfg["cleanup_empty_dirs"]
    logging.getLogger().setLevel(cfg["log_level"])

    logging.info("Starte Inotify-Fetchbridge mit RO/RW-Erkennung...")

    # Aufgelöste Konfiguration sichtbar machen - sonst ist bei falschem
    # source_dir/target_dir (z.B. durch Config-Datei oder Env-Var) im Log
    # nicht erkennbar, welche Pfade tatsächlich verwendet werden.
    used_config_files = [str(f) for f in ([CONFIG_FILE] if CONFIG_FILE.is_file() else [])] + \
        [str(f) for f in (sorted(CONF_D_DIR.glob("*.conf")) if CONF_D_DIR.is_dir() else [])]
    logging.info(
        f"Aufgelöste Konfiguration: source_dir={SOURCE_DIR} target_dir={TARGET_DIR} "
        f"allowed_extensions={sorted(ALLOWED_EXTENSIONS)} log_level={cfg['log_level']} "
        f"cleanup_empty_dirs={CLEANUP_EMPTY_DIRS} "
        f"config_files={used_config_files if used_config_files else 'keine (nur Defaults/Env)'}"
    )

    # Fail-fast mit klarer Meldung statt eines kryptischen OSError aus
    # InotifyTree, falls source_dir nicht existiert (z.B. falscher/fehlender
    # Mount oder falscher Pfad in Config/Env-Var).
    if not SOURCE_DIR.is_dir():
        logging.critical(
            f"❌ source_dir existiert nicht oder ist kein Verzeichnis: '{SOURCE_DIR}'. "
            "Prüfe Docker-Volume-Mount sowie SOURCE_DIR in Env/Config. Beende Prozess."
        )
        sys.exit(1)

    try:
        TARGET_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logging.critical(f"❌ target_dir '{TARGET_DIR}' konnte nicht angelegt werden: {e}. Beende Prozess.")
        sys.exit(1)

    scan_existing_files()

    try:
        i = inotify.adapters.InotifyTree(str(SOURCE_DIR))
    except Exception as e:
        logging.critical(f"❌ Konnte InotifyTree für '{SOURCE_DIR}' nicht starten: {e}. Beende Prozess.")
        sys.exit(1)
    logging.debug(f"InotifyTree Überwachung gestartet auf: {SOURCE_DIR}")

    last_cfg_hash, _ = get_config_hash()
    last_cfg_check = time.monotonic()

    for event in i.event_gen(yield_nones=True, timeout_s=CONFIG_CHECK_INTERVAL):
        if (time.monotonic() - last_cfg_check) >= CONFIG_CHECK_INTERVAL:
            last_cfg_check = time.monotonic()
            current_cfg_hash, _ = get_config_hash()
            if current_cfg_hash != last_cfg_hash:
                last_cfg_hash = current_cfg_hash
                logging.info("🔄 Config-Änderung erkannt, lade neu...")
                cfg = load_config()
                if cfg["source_dir"] != SOURCE_DIR:
                    logging.warning(
                        f"source_dir geändert ({SOURCE_DIR} -> {cfg['source_dir']}), "
                        "dies erfordert einen Neustart des Fetchbridge-Prozesses, da "
                        "InotifyTree fest an den Startpfad gebunden ist. "
                        "Änderung wird ignoriert, bis der Prozess neu gestartet wird."
                    )
                else:
                    TARGET_DIR = cfg["target_dir"]
                    ALLOWED_EXTENSIONS = cfg["allowed_extensions"]
                    TEMP_EXTENSIONS = cfg["temp_extensions"]
                    CLEANUP_EMPTY_DIRS = cfg["cleanup_empty_dirs"]
                    logging.getLogger().setLevel(cfg["log_level"])
                    TARGET_DIR.mkdir(parents=True, exist_ok=True)

        if event is None:
            continue

        (_, type_names, path, filename) = event

        logging.debug(f"Inotify-Event empfangen: {type_names} für {path}/{filename}")

        if WATCH_EVENTS.intersection(type_names):
            full_path = Path(path) / filename
            logging.debug(f"Relevantes Event {type_names} auf {filename} -> Starte Verarbeitung")
            process_file(full_path)

def main():
    parser = argparse.ArgumentParser(
        prog="fetchbridge",
        description=f"{__title__} v{__version__}"
    )
    parser.add_argument(
        "-D", "--daemon",
        action="store_true",
        help="Dämon-Modus: Dauerhafte Ordnerüberwachung"
    )
    parser.add_argument(
         "-V", "--version",
        action="version",
        version=f"{__title__} v{__version__}"
    )
    args = parser.parse_args()

    if not args.daemon:
        parser.print_usage()
        print("Hinweis: Zum Starten bitte -D oder --daemon verwenden.")
        return

    run_daemon()

if __name__ == "__main__":
    main()
