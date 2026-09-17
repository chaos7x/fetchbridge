"""Datei-Verarbeitung: RW/RO-Erkennung, Verschieben/Kopieren, Aufräumen leerer Ordner."""

import logging
import os
import shutil
from pathlib import Path

from fetchbridge import config

logger = logging.getLogger(__name__)


def is_writable(path: Path) -> bool:
    parent = path.parent if path.is_file() else path
    writable = os.access(parent, os.W_OK)
    logger.debug(f"Mount-Prüfung für '{parent}': Writable={writable}")
    return writable


def cleanup_empty_dirs(directory: Path):
    if directory == config.SOURCE_DIR or not directory.is_relative_to(config.SOURCE_DIR):
        logger.debug(f"Aufräumen übersprungen (Ausnahme/Basis-Ordner): {directory}")
        return

    if not is_writable(directory):
        logger.debug(f"Aufräumen übersprungen (RO-Mount): {directory}")
        return

    try:
        current = directory
        while current != config.SOURCE_DIR and current.is_dir():
            if not any(current.iterdir()):
                current.rmdir()
                logger.info(f"🧹 Leeres Verzeichnis entfernt: {current}")
                current = current.parent
            else:
                logger.debug(f"Verzeichnis nicht leer, stoppe Aufräumen: {current}")
                break
    except OSError as e:
        logger.warning(f"Fehler beim Aufräumen von {directory}: {e}")


def process_file(filepath: Path):
    # Symlinks explizit ablehnen, BEVOR is_file() (folgt Symlinks!) geprüft
    # wird: shutil.copy2()/shutil.move() folgen Symlinks standardmäßig und
    # würden den Inhalt des Linkziels nach TARGET_DIR kopieren/verschieben -
    # ein Symlink mit erlaubter Endung (z.B. "x.mkv -> /etc/shadow") in
    # SOURCE_DIR wäre damit ein Primitive für beliebigen Dateizugriff.
    if filepath.is_symlink():
        logger.warning(f"⚠️ Ignoriere Symlink (Sicherheitsrisiko, wird nicht verfolgt): {filepath}")
        return

    if not filepath.is_file():
        logger.debug(f"Ignoriere (Keine reguläre Datei oder existiert nicht mehr): {filepath}")
        return

    ext = filepath.suffix.lower()

    if ext in config.TEMP_EXTENSIONS or filepath.name.startswith("."):
        logger.debug(f"Ignoriere Temp/Versteckte Datei: {filepath.name}")
        return

    if ext not in config.ALLOWED_EXTENSIONS:
        logger.debug(f"Ignoriere nicht unterstützte Endung '{ext}': {filepath.name}")
        return

    filename = filepath.name
    dest_path = config.TARGET_DIR / filename

    counter = 1
    original_dest = dest_path
    while dest_path.exists():
        dest_path = config.TARGET_DIR / f"{original_dest.stem}_{counter}{original_dest.suffix}"
        counter += 1
        logger.debug(f"Ziel existiert bereits. Neuer Name: {dest_path.name}")

    source_parent = filepath.parent

    try:
        if is_writable(filepath):
            logger.info(f"🚚 Verschiebe (RW): {filepath.name} -> {dest_path.name}")
            shutil.move(str(filepath), str(dest_path))
            logger.info(f"✅ Verschieben erfolgreich: {dest_path.name}")
            if config.CLEANUP_EMPTY_DIRS:
                cleanup_empty_dirs(source_parent)
        else:
            logger.info(f"📋 Kopiere (RO): {filepath.name} -> {dest_path.name}")
            shutil.copy2(str(filepath), str(dest_path))
            logger.info(f"✅ Kopieren erfolgreich: {dest_path.name}")

    except OSError as e:
        logger.warning(f"Fehler bei Verarbeitung von {filename}: {e}")


def scan_existing_files():
    logger.info("Scanne nach bereits vorhandenen fertigen Dateien...")
    found_count = 0
    for filepath in config.SOURCE_DIR.rglob("*"):
        if filepath.is_file() and filepath.suffix.lower() in config.ALLOWED_EXTENSIONS:
            found_count += 1
            logger.debug(f"Scan hat Datei gefunden: {filepath}")
            process_file(filepath)
    logger.debug(f"Initialer Scan beendet. {found_count} passende Datei(en) gescannt.")
