"""Heartbeat-Datei und externer Healthcheck (z.B. Docker HEALTHCHECK)."""

import logging
import os
import stat
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _default_health_dir() -> str:
    """
    Verzeichnis der Heartbeat-Datei: /var/run/fetchbridge, sofern der Init-Dienst
    es angelegt hat (systemd RuntimeDirectory=, init.d bzw. FreeBSD-rc.d per
    install -d). Es gehört dem Dienstuser - ein anderer lokaler User kann die
    Datei dort weder vorab anlegen noch per Symlink unterschieben, anders als
    unter festem Namen im gemeinsamen /tmp. Außerdem findet so auch ein
    manueller `fetchbridge --healthcheck` außerhalb des PrivateTmp-Namespace der
    Unit die Datei. /var/run statt /run: unter Linux ein Symlink auf /run,
    unter FreeBSD der übliche Ort. Sonst (Docker, manueller Aufruf) wie bisher
    das Temp-Verzeichnis.
    """
    run_dir = "/var/run/fetchbridge"
    return run_dir if os.path.isdir(run_dir) else tempfile.gettempdir()


# Heartbeat-Datei für den Docker HEALTHCHECK (kein HTTP-Port vorhanden).
# Der Daemon aktualisiert den Zeitstempel dieser Datei regelmäßig; der
# Healthcheck-Subcommand (--healthcheck) prüft nur, ob sie "frisch" genug
# ist. Erkennt sowohl tote als auch hängende (deadlocked) Prozesse.
HEARTBEAT_FILE = Path(os.getenv("HEARTBEAT_FILE", str(Path(_default_health_dir()) / "fetchbridge.heartbeat")))
HEARTBEAT_MAX_AGE = int(os.getenv("HEARTBEAT_MAX_AGE", "60"))


def write_heartbeat():
    """Schreibt den aktuellen Zeitstempel in die Heartbeat-Datei."""
    try:
        # O_NOFOLLOW: liegt die Datei im gemeinsamen /tmp (Fallback ohne
        # /var/run/fetchbridge, siehe _default_health_dir()), folgt der
        # Schreibzugriff keinem von einem anderen User untergeschobenen Symlink.
        fd = os.open(HEARTBEAT_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, "w") as f:
            f.write(str(time.time()))
    except OSError as e:
        logger.warning(f"Konnte Heartbeat-Datei nicht schreiben ({HEARTBEAT_FILE}): {e}")


def check_healthcheck() -> int:
    """Prüft die Heartbeat-Datei und gibt einen Exit-Code zurück (0=healthy, 1=unhealthy).

    Wird über 'fetchbridge --healthcheck' vom Docker HEALTHCHECK aufgerufen -
    läuft als eigener kurzlebiger Prozess, unabhängig vom Daemon.
    """
    try:
        st = HEARTBEAT_FILE.lstat()
    except FileNotFoundError:
        print(f"UNHEALTHY: Heartbeat-Datei fehlt: {HEARTBEAT_FILE}")
        return 1
    except OSError as e:
        print(f"UNHEALTHY: Heartbeat-Datei nicht lesbar/ungültig: {e}")
        return 1

    # lstat statt stat: ein Symlink (z.B. von einem anderen User im gemeinsamen
    # /tmp untergeschoben) zählt nicht als gültiger Heartbeat.
    if not stat.S_ISREG(st.st_mode):
        print(f"UNHEALTHY: Heartbeat-Datei ist keine reguläre Datei: {HEARTBEAT_FILE}")
        return 1

    try:
        last_beat = float(HEARTBEAT_FILE.read_text().strip())
    except (OSError, ValueError) as e:
        print(f"UNHEALTHY: Heartbeat-Datei nicht lesbar/ungültig: {e}")
        return 1

    age = time.time() - last_beat
    if age > HEARTBEAT_MAX_AGE:
        print(f"UNHEALTHY: Letzter Heartbeat ist {age:.0f}s alt (Limit: {HEARTBEAT_MAX_AGE}s)")
        return 1

    print(f"HEALTHY: Letzter Heartbeat vor {age:.0f}s")
    return 0
