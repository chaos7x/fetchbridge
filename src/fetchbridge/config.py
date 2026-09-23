"""Konfiguration & Standard-Pfade."""

import configparser
import contextlib
import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "fetchbridge"

CONFIG_FILE = Path(os.getenv("CONFIG_FILE", "/etc/fetchbridge/fetchbridge.conf"))
CONF_D_DIR = Path(os.getenv("CONF_D_DIR", "/etc/fetchbridge/conf.d"))

ALLOWED_EXTENSIONS = {".mkv", ".mp4", ".webm"}
TEMP_EXTENSIONS = {".part", ".ytdl", ".tmp", ".temp"}
WATCH_EVENTS = {"IN_MOVED_TO", "IN_CLOSE_WRITE"}
CLEANUP_EMPTY_DIRS = False
# Absicherung gegen den seltenen Fall, dass ein Schreiber die Datei nach dem
# IN_CLOSE_WRITE-Event erneut öffnet (z.B. ein Tool mit Flush-Close-Reopen-
# Verhalten) - process_file() vergleicht die Dateigröße STABILITY_MAX_CHECKS
# mal im Abstand von STABILITY_CHECK_INTERVAL Sekunden, bevor verschoben/
# kopiert wird.
STABILITY_CHECK_INTERVAL = float(os.getenv("STABILITY_CHECK_INTERVAL", "2"))
STABILITY_MAX_CHECKS = int(os.getenv("STABILITY_MAX_CHECKS", "10"))

CONFIG_CHECK_INTERVAL = int(os.getenv("CONFIG_CHECK_INTERVAL", "15"))


def _is_dedicated_mount(path: Path) -> bool:
    """
    Prüft, ob path auf einem eigens eingehängten Docker-Volume/Bind-Mount
    liegt statt nur in einem gewöhnlichen Verzeichnis, das das Dockerfile per
    `mkdir -p` fest ins Image gebacken hat (z.B. /media/in, /media/out, /log)
    - eine reine is_dir()-Prüfung kann diese beiden Fälle nicht unterscheiden,
    da `mkdir -p` das Verzeichnis auch ganz ohne jeden Mount anlegt (derselbe
    Bug wie bei yt-upload/tw-recorder: Datei-Logging bzw. Datenverzeichnisse
    liefen unbemerkt gegen den flüchtigen Container-Layer).
    Vergleicht dazu die Geräte-ID (st_dev) von path gegen die des
    Container-Root-Dateisystems (/) statt nur gegen path.parent: ein Vergleich
    ausschließlich mit dem direkten Elternverzeichnis würde einen Mount
    übersehen, der eine Ebene höher liegt als path selbst - z.B. wenn
    SOURCE_DIR (/srv/media-pipeline/recordings) und TARGET_DIR
    (/srv/media-pipeline/incoming) nicht mehr je einzeln, sondern gemeinsam
    als EIN Mount auf /srv/media-pipeline eingehängt sind (siehe
    docker-compose.yaml.example, wegen os.rename()/EXDEV zwischen getrennten
    Mounts nötig) - path und sein direkter Parent lägen dann auf demselben
    Gerät, obwohl tatsächlich ein Mount existiert. Eine andere st_dev als das
    Root-Dateisystem bedeutet dagegen unabhängig von der Mount-Tiefe, dass
    irgendwo zwischen path und / tatsächlich ein Volume/Bind-Mount eingehängt
    ist.
    """
    if not path.is_dir():
        return False
    try:
        return path.stat().st_dev != Path("/").stat().st_dev
    except OSError:
        return False


# SOURCE_DIR/TARGET_DIR zeigen einheitlich (Docker wie Bare-Metal) auf die
# gemeinsamen Uebergabeverzeichnisse der Pipeline statt auf rein private,
# Package-relative Pfade oder die inzwischen abgeloesten /media/out,
# /media/in-Mountpunkte: SOURCE_DIR ist derselbe Pfad wie tw-recorder.config.
# STORAGE_DIR (dessen Schreiber), TARGET_DIR derselbe wie yt_upload.config.
# IN_DIR (dessen Leser) - identisch zum Docker-Compose-Setup, wo die
# jeweiligen Container-Paare denselben Host-Pfad mounten. Das .deb-Postinst
# legt beide Verzeichnisse mit einer gemeinsamen Gruppe an, damit alle drei
# Systemuser (tw-recorder, fetchbridge, yt-upload) tatsaechlich zugreifen
# koennen. _ensure_source_dir_ready()/_ensure_target_dir_ready() in daemon.py
# pruefen weiterhin per _is_dedicated_mount(), ob hier innerhalb eines
# Containers tatsaechlich ein echtes Volume gemountet ist, unabhaengig vom
# konkreten Pfad.
SOURCE_DIR = Path("/srv/media-pipeline/recordings")
TARGET_DIR = Path("/srv/media-pipeline/incoming")


def _running_in_container() -> bool:
    """
    Erkennt zuverlässig, ob der Prozess in einem Docker-Container läuft -
    unabhängig davon, ob SOURCE_DIR/TARGET_DIR echte Volumes sind (die legt
    das Dockerfile selbst bedingungslos per `mkdir -p` an, siehe
    _is_dedicated_mount()). /.dockerenv wird von Docker selbst in jedem
    Container angelegt, unabhängig vom Image-Inhalt - im Gegensatz zu
    /media/*, das dieses Projekt selbst im Dockerfile erzeugt und das
    deshalb als Erkennungsmerkmal ungeeignet ist.
    """
    return Path("/.dockerenv").exists()


def get_config_files_state() -> dict:
    files_state = {}
    config_files = []

    if CONFIG_FILE.is_file():
        config_files.append(CONFIG_FILE)
    if CONF_D_DIR.is_dir():
        config_files.extend(sorted(CONF_D_DIR.glob("*.conf")))

    for f in config_files:
        with contextlib.suppress(OSError):
            files_state[f] = hashlib.md5(f.read_bytes(), usedforsecurity=False).hexdigest()

    return files_state


def get_config_hash() -> tuple[str, dict]:
    state = get_config_files_state()
    combined = hashlib.md5(usedforsecurity=False)
    for f in sorted(state.keys()):
        combined.update(f.name.encode())
        combined.update(state[f].encode())
    return combined.hexdigest(), state


def _get(config_obj, section, option, fallback):
    """
    Wie config_obj.get(), aber robust gegen einen Schlüssel ohne "= wert"
    (z.B. "log_level" statt "log_level = INFO") - allow_no_value=True lässt
    das als gültige Syntax durch, ConfigParser.get() liefert dafür None
    zurück und ignoriert dabei den fallback (der nur greift, wenn Section/
    Option komplett fehlen, nicht wenn der Wert nur leer ist). Ungeprüft
    würde das bei jedem nachgelagerten .strip()/.upper()/int()/float()/
    Path() mit einem AttributeError/TypeError crashen (siehe der in
    tw-recorder gefixte, identische Bug in dessen [channels]-Sektion).
    """
    value = config_obj.get(section, option, fallback=fallback)
    return fallback if value is None else value


def load_config():
    config = configparser.ConfigParser(
        interpolation=None,
        delimiters=("=",),
        comment_prefixes=("#", ";"),
        allow_no_value=True
    )
    config.optionxform = str

    config_files = []
    if CONFIG_FILE.is_file():
        config_files.append(CONFIG_FILE)
    if CONF_D_DIR.is_dir():
        config_files.extend(sorted(CONF_D_DIR.glob("*.conf")))

    # Dateien einzeln einlesen (spätere Dateien überschreiben frühere Werte).
    # Bewusst NICHT config.read(config_files, ...) mit der ganzen Liste auf
    # einmal: ConfigParser.read() bricht beim ersten Parse-Fehler in der Liste
    # komplett ab, wodurch jede DANACH folgende Datei (auch eine gültige!)
    # stillschweigend gar nicht mehr gelesen wird - ein Tippfehler in einer
    # frühen conf.d-Datei würde sonst alle alphabetisch späteren unsichtbar
    # deaktivieren, ohne dass das aus der Warnung ersichtlich wäre.
    # Und bewusst config.read_file() auf einem selbst geöffneten Handle statt
    # config.read(f, ...): Letzteres öffnet die Datei intern und FÄNGT einen
    # dabei auftretenden OSError (z.B. Permission denied, falls eine
    # conf.d-Datei versehentlich dem falschen User/einer falschen Gruppe
    # gehört) STILL AB, ohne ihn je an aufrufenden Code durchzureichen - das
    # except unten würde so einen Fall nie sehen, die Datei würde ohne jede
    # Warnung einfach ignoriert. Mit dem eigenen open() landet ein
    # Berechtigungsfehler dagegen in unserem eigenen except.
    for f in config_files:
        try:
            with open(f, encoding="utf-8") as fp:
                config.read_file(fp, source=str(f))
        except (OSError, configparser.Error, UnicodeDecodeError) as e:
            logger.warning(f"Fehler beim Lesen von {f}: {e}")

    source_dir = Path(_get(config, "general", "source_dir", os.getenv("SOURCE_DIR", str(SOURCE_DIR))))
    target_dir = Path(_get(config, "general", "target_dir", os.getenv("TARGET_DIR", str(TARGET_DIR))))

    allowed_raw = _get(
        config, "mover", "allowed_extensions",
        os.getenv("ALLOWED_EXTENSIONS", ".mkv,.mp4,.webm")
    )
    allowed_extensions = {
        e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
        for e in allowed_raw.split(",") if e.strip()
    }

    temp_raw = _get(
        config, "mover", "temp_extensions",
        os.getenv("TEMP_EXTENSIONS", ".part,.ytdl,.tmp,.temp")
    )
    temp_extensions = {
        e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
        for e in temp_raw.split(",") if e.strip()
    }

    # DEBUG=true/yes/1 ist ein Alias für log_level=DEBUG, einheitlich mit
    # tw-recorder/yt-upload (die nur dieses eine Bool-Flag kennen) - nur der
    # Default-Wert, falls WEDER log_level in der Config NOCH LOG_LEVEL als
    # ENV explizit gesetzt sind. Wer die feinere Kontrolle braucht (z.B.
    # WARNING/ERROR zum Rauschen reduzieren), setzt weiterhin log_level/
    # LOG_LEVEL direkt - das hat immer Vorrang vor DEBUG.
    debug_enabled = os.getenv("DEBUG", "").strip().lower() in ("true", "yes", "1")
    default_log_level = "DEBUG" if debug_enabled else "INFO"
    log_level = _get(config, "general", "log_level", os.getenv("LOG_LEVEL", default_log_level)).upper()
    log_file = _get(config, "general", "log_file", os.getenv("LOG_FILE", "")).strip()

    cleanup_raw = _get(
        config, "mover", "cleanup_empty_dirs",
        os.getenv("CLEANUP_EMPTY_DIRS", "false")
    )
    cleanup_empty_dirs_enabled = cleanup_raw.strip().lower() in ("1", "true", "yes")

    stability_check_interval = float(_get(
        config, "mover", "stability_check_interval",
        os.getenv("STABILITY_CHECK_INTERVAL", "2")
    ))
    stability_max_checks = int(_get(
        config, "mover", "stability_max_checks",
        os.getenv("STABILITY_MAX_CHECKS", "10")
    ))

    return {
        "source_dir": source_dir,
        "target_dir": target_dir,
        "allowed_extensions": allowed_extensions,
        "temp_extensions": temp_extensions,
        "log_level": log_level,
        "log_file": log_file,
        "cleanup_empty_dirs": cleanup_empty_dirs_enabled,
        "stability_check_interval": stability_check_interval,
        "stability_max_checks": stability_max_checks,
        "config_obj": config
    }
