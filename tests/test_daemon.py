"""
Tests für _ensure_source_dir_ready() und _ensure_target_dir_ready()
(daemon.py) - die Fail-Fast-Validierung von source_dir/target_dir vor dem
Start des InotifyTree-Watchers - sowie für den SIGTERM/SIGINT-Graceful-
Shutdown-Mechanismus (install_signal_handlers()/shutdown_requested()).

run_daemon() selbst wird hier bewusst nicht getestet: es importiert die
inotify-Bibliothek erst innerhalb der Funktion (siehe Kommentar dort) und
startet eine Endlosschleife - die beiden Validierungsfunktionen sowie die
Signal-Handling-Logik wurden gerade deshalb aus run_daemon() herausgezogen,
damit sie isoliert und ohne inotify-Abhängigkeit testbar sind.
"""

import signal

import pytest


@pytest.fixture(autouse=True)
def reset_shutdown_flag(daemon):
    """Isoliert das Modul-Flag zwischen Tests."""
    daemon._shutdown_requested = False
    yield
    daemon._shutdown_requested = False


class _RaisingMkdirPath:
    """Minimales Path-Double, dessen mkdir() immer fehlschlägt - vermeidet
    ein globales Monkeypatchen von pathlib.Path.mkdir (das auch pytest-
    eigene Path-Operationen während des Tests treffen könnte)."""

    def mkdir(self, **kwargs):
        raise OSError("Permission denied")

    def __str__(self):
        return "/fake/target"


class TestEnsureSourceDirReady:
    def test_missing_source_dir_exits(self, daemon, config, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "SOURCE_DIR", tmp_path / "does-not-exist")
        monkeypatch.setattr(config, "_running_in_container", lambda: False)

        with pytest.raises(SystemExit) as exc_info:
            daemon._ensure_source_dir_ready()

        assert exc_info.value.code == 1

    def test_existing_dir_outside_container_is_fine(self, daemon, config, monkeypatch, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        monkeypatch.setattr(config, "SOURCE_DIR", source)
        monkeypatch.setattr(config, "_running_in_container", lambda: False)

        daemon._ensure_source_dir_ready()  # darf nicht werfen

    def test_dedicated_mount_inside_container_is_fine(self, daemon, config, monkeypatch, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        monkeypatch.setattr(config, "SOURCE_DIR", source)
        monkeypatch.setattr(config, "_running_in_container", lambda: True)
        monkeypatch.setattr(config, "_is_dedicated_mount", lambda p: True)

        daemon._ensure_source_dir_ready()  # darf nicht werfen

    def test_plain_baked_in_dir_inside_container_exits(self, daemon, config, monkeypatch, tmp_path):
        """Der eigentlich gemeldete Bug: existiert, aber kein echtes Volume, innerhalb eines Containers."""
        source = tmp_path / "source"
        source.mkdir()
        monkeypatch.setattr(config, "SOURCE_DIR", source)
        monkeypatch.setattr(config, "_running_in_container", lambda: True)
        monkeypatch.setattr(config, "_is_dedicated_mount", lambda p: False)

        with pytest.raises(SystemExit) as exc_info:
            daemon._ensure_source_dir_ready()

        assert exc_info.value.code == 1


class TestEnsureTargetDirReady:
    def test_creates_missing_target_dir(self, daemon, config, monkeypatch, tmp_path):
        target = tmp_path / "does-not-exist-yet"
        monkeypatch.setattr(config, "TARGET_DIR", target)
        monkeypatch.setattr(config, "_running_in_container", lambda: False)

        daemon._ensure_target_dir_ready()

        assert target.is_dir()

    def test_mkdir_failure_exits(self, daemon, config, monkeypatch):
        monkeypatch.setattr(config, "TARGET_DIR", _RaisingMkdirPath())

        with pytest.raises(SystemExit) as exc_info:
            daemon._ensure_target_dir_ready()

        assert exc_info.value.code == 1

    def test_dedicated_mount_inside_container_is_fine(self, daemon, config, monkeypatch, tmp_path):
        target = tmp_path / "target"
        monkeypatch.setattr(config, "TARGET_DIR", target)
        monkeypatch.setattr(config, "_running_in_container", lambda: True)
        monkeypatch.setattr(config, "_is_dedicated_mount", lambda p: True)

        daemon._ensure_target_dir_ready()  # darf nicht werfen
        assert target.is_dir()

    def test_plain_baked_in_dir_inside_container_exits(self, daemon, config, monkeypatch, tmp_path):
        """Ohne echtes Volume gingen verschobene Dateien beim Container-Neustart verloren."""
        target = tmp_path / "target"
        monkeypatch.setattr(config, "TARGET_DIR", target)
        monkeypatch.setattr(config, "_running_in_container", lambda: True)
        monkeypatch.setattr(config, "_is_dedicated_mount", lambda p: False)

        with pytest.raises(SystemExit) as exc_info:
            daemon._ensure_target_dir_ready()

        assert exc_info.value.code == 1


class TestInstallSignalHandlers:
    def test_registers_handler_for_sigterm_and_sigint(self, daemon, monkeypatch):
        registered = {}

        def fake_signal(sig, handler):
            registered[sig] = handler

        monkeypatch.setattr(daemon.signal, "signal", fake_signal)

        daemon.install_signal_handlers()

        assert registered[signal.SIGTERM] is daemon._handle_shutdown_signal
        assert registered[signal.SIGINT] is daemon._handle_shutdown_signal

    def test_handler_sets_shutdown_flag(self, daemon):
        assert daemon.shutdown_requested() is False

        daemon._handle_shutdown_signal(signal.SIGTERM, None)

        assert daemon.shutdown_requested() is True
