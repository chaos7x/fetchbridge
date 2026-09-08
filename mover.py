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
import logging
import shutil
import inotify.adapters
from pathlib import Path

__title__ = "Mediadog Mover CLI"
__version__ = "1.0.10"


# Liest das Log-Level aus den Env-Vars (Standard: INFO)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

SOURCE_DIR = Path("/media/out")
TARGET_DIR = Path("/media/in")

ALLOWED_EXTENSIONS = {".mkv", ".mp4", ".webm"}
TEMP_EXTENSIONS = {".part", ".ytdl", ".tmp", ".temp"}
WATCH_EVENTS = {'IN_MOVED_TO', 'IN_CLOSE_WRITE'}

def is_writable(path: Path) -> bool:
    """Prüft, ob der Ordner beschreibbar ist (RW) oder Read-Only (RO) gemountet wurde."""
    parent = path.parent if path.is_file() else path
    writable = os.access(parent, os.W_OK)
    logging.debug(f"Mount-Prüfung für '{parent}': Writable={writable}")
    return writable

def cleanup_empty_dirs(path: Path):
    """Löscht leere Unterordner in RW-Mounts. Ignoriert RO-Mounts und Basis-Ordner."""
    if path == SOURCE_DIR or not path.is_relative_to(SOURCE_DIR):
        logging.debug(f"Aufräumen übersprungen (Ausnahme/Basis-Ordner): {path}")
        return

    if not is_writable(path):
        logging.debug(f"Aufräumen übersprungen (RO-Mount): {path}")
        return

    try:
        current = path.parent if path.is_file() else path
        while current != SOURCE_DIR and current.parent != SOURCE_DIR and current.is_dir():
            if not any(current.iterdir()):
                current.rmdir()
                logging.info(f"🧹 Leeres Verzeichnis entfernt: {current}")
                current = current.parent
            else:
                logging.debug(f"Verzeichnis nicht leer, stoppe Aufräumen: {current}")
                break
    except Exception as e:
        logging.warning(f"Fehler beim Aufräumen von {path}: {e}")

def process_file(filepath: Path):
    """Kopiert oder verschiebt die Datei basierend auf den Schreibrechten des Mounts."""
    if not filepath.is_file():
        logging.debug(f"Ignoriere (Keine reguläre Datei oder existiert nicht mehr): {filepath}")
        return

    ext = filepath.suffix.lower()

    # Temp-Dateien und versteckte Dateien ignorieren
    if ext in TEMP_EXTENSIONS or filepath.name.startswith("."):
        logging.debug(f"Ignoriere Temp/Versteckte Datei: {filepath.name}")
        return

    # Nur erlaubte Formate verarbeiten
    if ext not in ALLOWED_EXTENSIONS:
        logging.debug(f"Ignoriere nicht unterstützte Endung '{ext}': {filepath.name}")
        return

    filename = filepath.name
    dest_path = TARGET_DIR / filename

    # Namenskollisionen vermeiden
    counter = 1
    original_dest = dest_path
    while dest_path.exists():
        dest_path = TARGET_DIR / f"{original_dest.stem}_{counter}{original_dest.suffix}"
        counter += 1
        logging.debug(f"Ziel existiert bereits. Neuer Name: {dest_path.name}")

    try:
        if is_writable(filepath):
            logging.info(f"🚚 Verschiebe (RW): {filepath.name} -> {dest_path.name}")
            shutil.move(str(filepath), str(dest_path))
            logging.info(f"✅ Verschieben erfolgreich: {dest_path.name}")
            cleanup_empty_dirs(filepath)
        else:
            logging.info(f"📋 Kopiere (RO): {filepath.name} -> {dest_path.name}")
            shutil.copy2(str(filepath), str(dest_path))
            logging.info(f"✅ Kopieren erfolgreich: {dest_path.name}")

    except Exception as e:
        logging.warning(f"Fehler bei Verarbeitung von {filename}: {e}")

def scan_existing_files():
    """Verschiebt/Kopiert beim Container-Start bereits vorhandene fertige Dateien."""
    logging.info("Scanne nach bereits vorhandenen fertigen Dateien...")
    found_count = 0
    for ext in ALLOWED_EXTENSIONS:
        for filepath in SOURCE_DIR.rglob(f"*{ext}"):
            found_count += 1
            logging.debug(f"Scan hat Datei gefunden: {filepath}")
            process_file(filepath)
    logging.debug(f"Initialer Scan beendet. {found_count} passende Datei(en) gescannt.")

def main():
    logging.info("Starte Inotify-Mover mit RO/RW-Erkennung...")

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    scan_existing_files()

    i = inotify.adapters.InotifyTree(str(SOURCE_DIR))
    logging.debug(f"InotifyTree Überwachung gestartet auf: {SOURCE_DIR}")

    for event in i.event_gen(yield_nones=False):
        (_, type_names, path, filename) = event

        # Alle Inotify-Events im Debugging sichtbar machen
        logging.debug(f"Inotify-Event empfangen: {type_names} für {path}/{filename}")

        if WATCH_EVENTS.intersection(type_names):
            full_path = Path(path) / filename
            logging.debug(f"Relevantes Event {type_names} auf {filename} -> Starte Verarbeitung")
            process_file(full_path)

if __name__ == "__main__":
    main()
