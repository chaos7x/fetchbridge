"""CLI-Einstiegspunkt: Argument-Parsing und Moduswahl."""

import argparse
import logging
import os
import sys

from fetchbridge import __title__, __version__
from fetchbridge.daemon import run_daemon
from fetchbridge.healthcheck import check_healthcheck

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def main():
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

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
        "--healthcheck",
        action="store_true",
        help="Prüft die Heartbeat-Datei und beendet sich mit Exit-Code 0 (healthy) oder 1 (unhealthy). Für Docker HEALTHCHECK."
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"{__title__} v{__version__}"
    )
    args = parser.parse_args()

    if args.healthcheck:
        sys.exit(check_healthcheck())

    if not args.daemon:
        parser.print_usage()
        print("Hinweis: Zum Starten bitte -D oder --daemon verwenden.")
        return

    run_daemon()


if __name__ == "__main__":
    main()
