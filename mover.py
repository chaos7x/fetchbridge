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

# Liest das Log-Level aus den Env-Vars (Standard: INFO)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

SOURCE_DIR = Path("/media/out")
TARGET_DIR = Path("/media/in")

# Erlaubte Video-Endungen (Streamlink + Tubesync)
ALLOWED_EXTENSIONS = {".mkv", ".mp4", ".webm"}

# Temporäre Download-Dateien strikt ignorieren
TEMP_EXTENSIONS = {".part", ".ytdl", ".tmp", ".temp"}

# Relevante Kernel-Events
WATCH_EVENTS = {'IN_MOVED_TO', 'IN_CLOSE_WRITE'}

def is_writable(path: Path) -> bool:
    """Prüft, ob der Ordner beschreibbar ist (RW) oder Read-Only (RO) gemountet wurde."""
    parent = path.parent if path.is_file() else path
    return os.access(parent, os.W_OK)

def cleanup_empty_dirs(path: Path):
    """Löscht leere Unterordner in RW-Mounts. Ignoriert RO-Mounts und Basis-Ordner."""
    if path == SOURCE_DIR or not path.is_relative_to(SOURCE_DIR):
        return
    
    # Auf RO-Mounts erst gar nicht versuchen zu löschen
    if not is_writable(path):
        return

    try:
        current = path.parent if path.is_file() else path
        # Stoppt direkt unterhalb von /media/out (z. B. /media/out/twitch)
        while current != SOURCE_DIR and current.parent != SOURCE_DIR and current.is_dir():
            if not any(current.iterdir()):
                current.rmdir()
                print(f"[INFO] 🧹 Leeres Verzeichnis entfernt: {current}", flush=True)
                current = current.parent
            else:
                break
    except Exception as e:
        print(f"[WARN] Fehler beim Aufräumen von {path}: {e}", flush=True)

def process_file(filepath: Path):
    """Kopiert oder verschiebt die Datei basierend auf den Schreibrechten des Mounts."""
    if not filepath.is_file():
        return

    ext = filepath.suffix.lower()

    # Temp-Dateien und versteckte Dateien ignorieren
    if ext in TEMP_EXTENSIONS or filepath.name.startswith("."):
        return

    # Nur erlaubte Formate verarbeiten
    if ext not in ALLOWED_EXTENSIONS:
        return

    filename = filepath.name
    dest_path = TARGET_DIR / filename

    # Namenskollisionen in /media/in vermeiden
    counter = 1
    original_dest = dest_path
    while dest_path.exists():
        dest_path = TARGET_DIR / f"{original_dest.stem}_{counter}{original_dest.suffix}"
        counter += 1

    try:
        # Dynamische Unterscheidung: RW -> move, RO -> copy
        if is_writable(filepath):
            print(f"[INFO] 🚚 Verschiebe (RW): {filepath.name} -> {dest_path.name}", flush=True)
            shutil.move(str(filepath), str(dest_path))
            print(f"[INFO] ✅ Verschieben erfolgreich: {dest_path.name}", flush=True)
            cleanup_empty_dirs(filepath)
        else:
            print(f"[INFO] 📋 Kopiere (RO): {filepath.name} -> {dest_path.name}", flush=True)
            shutil.copy2(str(filepath), str(dest_path))
            print(f"[INFO] ✅ Kopieren erfolgreich: {dest_path.name}", flush=True)

    except Exception as e:
        print(f"[WARN] Fehler bei Verarbeitung von {filename}: {e}", flush=True)

def scan_existing_files():
    """Verschiebt/Kopiert beim Container-Start bereits vorhandene fertige Dateien."""
    print("[INFO] Scanne nach bereits vorhandenen fertigen Dateien...", flush=True)
    for ext in ALLOWED_EXTENSIONS:
        for filepath in SOURCE_DIR.rglob(f"*{ext}"):
            process_file(filepath)

def main():
    print("[INFO] Starte Inotify-Mover mit RO/RW-Erkennung...", flush=True)

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Start-Cleanup / Scan
    scan_existing_files()

    # 2. Inotify-Überwachung
    i = inotify.adapters.InotifyTree(str(SOURCE_DIR))

    for event in i.event_gen(yield_nones=False):
        (_, type_names, path, filename) = event

        if WATCH_EVENTS.intersection(type_names):
            full_path = Path(path) / filename
            process_file(full_path)

if __name__ == "__main__":
    main()
