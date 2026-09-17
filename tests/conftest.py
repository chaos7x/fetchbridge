"""Gemeinsame Test-Infrastruktur für das fetchbridge-Package (src/fetchbridge/)."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(scope="session")
def config():
    from fetchbridge import config
    return config


@pytest.fixture(scope="session")
def mover():
    from fetchbridge import mover
    return mover
