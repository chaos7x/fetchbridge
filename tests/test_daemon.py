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

import os
import signal
import stat

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

    def is_dir(self):
        return False

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
        assert stat.S_IMODE(target.stat().st_mode) == 0o2775

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


class TestMkdirGroupWritable:
    """
    Regression: mkdir(parents=True, exist_ok=True) ohne explizites mode=
    verliert das Gruppen-Schreibrecht durchs Prozess-Umask (Standard-Mode
    0o777 wird umask-maskiert, z.B. auf 0o755 bei umask 022) - das Setgid-
    Bit selbst wird zwar vom Elternverzeichnis geerbt, das für die
    media-pipeline-Gruppe eigentlich nötige g+w aber nicht. Derselbe Bug
    wurde real auf einem tw-recorder-Host gefunden (Kanal-Unterordner unter
    /srv/media-pipeline standen auf 2755 statt 2775).
    """

    def test_newly_created_dir_gets_2775_regardless_of_umask(self, daemon, tmp_path):
        old_umask = os.umask(0o022)
        try:
            target = tmp_path / "incoming"
            daemon._mkdir_group_writable(target)
            assert stat.S_IMODE(target.stat().st_mode) == 0o2775
        finally:
            os.umask(old_umask)

    def test_existing_dir_permissions_are_not_overwritten(self, daemon, tmp_path):
        """Eine bewusste Admin-Anpassung (z.B. chmod 777) darf nicht überschrieben werden."""
        target = tmp_path / "incoming"
        target.mkdir()
        target.chmod(0o777)

        daemon._mkdir_group_writable(target)

        assert stat.S_IMODE(target.stat().st_mode) == 0o777

    def test_chmod_failure_logs_warning_without_raising(self, daemon, tmp_path, monkeypatch, caplog):
        target = tmp_path / "incoming"

        def raise_oserror(self, mode):
            raise OSError("Operation not permitted")

        monkeypatch.setattr(type(target), "chmod", raise_oserror)

        with caplog.at_level("WARNING"):
            daemon._mkdir_group_writable(target)  # darf nicht raisen

        assert target.is_dir()
        assert "2775" in caplog.text


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
