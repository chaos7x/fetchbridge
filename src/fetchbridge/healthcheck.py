"""Heartbeat-Datei und externer Healthcheck (z.B. Docker HEALTHCHECK)."""

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Heartbeat-Datei für den Docker HEALTHCHECK (kein HTTP-Port vorhanden).
# Der Daemon aktualisiert den Zeitstempel dieser Datei regelmäßig; der
# Healthcheck-Subcommand (--healthcheck) prüft nur, ob sie "frisch" genug
# ist. Erkennt sowohl tote als auch hängende (deadlocked) Prozesse.
HEARTBEAT_FILE = Path(os.getenv("HEARTBEAT_FILE", "/tmp/fetchbridge.heartbeat"))
HEARTBEAT_MAX_AGE = int(os.getenv("HEARTBEAT_MAX_AGE", "60"))


def write_heartbeat():
    """Schreibt den aktuellen Zeitstempel in die Heartbeat-Datei."""
    try:
        HEARTBEAT_FILE.write_text(str(time.time()))
    except OSError as e:
        logger.warning(f"Konnte Heartbeat-Datei nicht schreiben ({HEARTBEAT_FILE}): {e}")


def check_healthcheck() -> int:
    """Prüft die Heartbeat-Datei und gibt einen Exit-Code zurück (0=healthy, 1=unhealthy).

    Wird über 'fetchbridge --healthcheck' vom Docker HEALTHCHECK aufgerufen -
    läuft als eigener kurzlebiger Prozess, unabhängig vom Daemon.
    """
    if not HEARTBEAT_FILE.is_file():
        print(f"UNHEALTHY: Heartbeat-Datei fehlt: {HEARTBEAT_FILE}")
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
