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


import shutil
import inotify.adapters
from pathlib import Path

SOURCE_DIR = Path("/media/out")
TARGET_DIR = Path("/media/in")

# Relevante Kernel-Events für fertig geschriebene oder hineinverschobene Dateien
WATCH_EVENTS = {'IN_MOVED_TO', 'IN_CLOSE_WRITE'}

def process_file(filepath: Path):
    """Prüft und verschiebt eine fertige MKV-Datei flach ins Zielverzeichnis."""
    if not filepath.is_file():
        return

    # Nur .mkv verarbeiten (.ts Dateien von Streamlink werden stumm ignoriert)
    if filepath.suffix.lower() != ".mkv":
        return

    filename = filepath.name
    dest_path = TARGET_DIR / filename
    try:
        print(f"[INFO] 🚚 Verschiebe: {filename} -> {dest_path}", flush=True)
        # Atomares mv auf derselben Partition
        shutil.move(str(filepath), str(dest_path))
        print(f"[INFO] ✅ Erfolgreich verschoben: {filename}", flush=True)
    except Exception as e:
        print(f"[WARN] Fehler beim Verschieben von {filename}: {e}", flush=True)

def scan_existing_files():
    """Verschiebt beim Container-Start bereits vorhandene fertige Dateien."""
    print("[INFO] Scanne nach bereits vorhandenen fertigen Dateien...", flush=True)
    for filepath in SOURCE_DIR.rglob("*.mkv"):
        process_file(filepath)

def main():
    print("[INFO] Starte Inotify-Mover (via inotify.adapters.InotifyTree)...", flush=True)

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Start-Cleanup durchführen
    scan_existing_files()

    # 2. Rekursive Inotify-Überwachung auf /media/in starten
    i = inotify.adapters.InotifyTree(str(SOURCE_DIR))

    for event in i.event_gen(yield_nones=False):
        (_, type_names, path, filename) = event

        # Event-Typ abgleichen
        if WATCH_EVENTS.intersection(type_names):
            full_path = Path(path) / filename
            process_file(full_path)

if __name__ == "__main__":
    main()
