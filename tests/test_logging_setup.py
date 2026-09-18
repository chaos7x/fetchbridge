"""
Tests für _is_syslog_daemon_running(), _resolve_log_file_path() und
setup_logging() (logging_setup.py).

_is_dedicated_mount() selbst wird bereits ausführlich in test_config.py
getestet - hier wird es nur noch als Kollaborator gemockt, nicht erneut
in seiner eigenen Logik geprüft.
"""

import logging

import pytest


@pytest.fixture
def clean_root_logger():
    """
    setup_logging() manipuliert den echten Root-Logger direkt (nicht nur
    logging.basicConfig()) - ohne Aufräumen blieben nach einem direkten Test
    von setup_logging() zusätzliche Handler (u.a. ein offener
    RotatingFileHandler auf eine tmp_path-Datei) über das Testende hinaus am
    Prozess-weiten Root-Logger hängen.
    """
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    yield
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
        h.close()
    for h in original_handlers:
        root_logger.addHandler(h)
    root_logger.setLevel(original_level)


class FakePidDir:
    """Simuliert ein Path-Objekt für /proc/<pid> mit steuerbarem comm-Inhalt."""

    def __init__(self, name, comm_content=None, raise_on_read=False):
        self.name = name
        self._comm_content = comm_content
        self._raise_on_read = raise_on_read

    def __truediv__(self, other):
        return FakeCommFile(self._comm_content, self._raise_on_read)


class FakeCommFile:
    def __init__(self, content, raise_on_read):
        self._content = content
        self._raise_on_read = raise_on_read

    def read_text(self, encoding="utf-8", errors="ignore"):
        if self._raise_on_read:
            raise OSError("Permission denied")
        return self._content


class TestIsSyslogDaemonRunning:
    def test_returns_false_without_proc_directory(self, logging_setup, monkeypatch):
        monkeypatch.setattr(logging_setup.Path, "is_dir", lambda self: False)
        assert logging_setup._is_syslog_daemon_running() is False

    def test_detects_running_rsyslogd(self, logging_setup, monkeypatch):
        fake_pids = [FakePidDir("111", "bash"), FakePidDir("222", "rsyslogd")]

        monkeypatch.setattr(logging_setup.Path, "is_dir", lambda self: True)
        monkeypatch.setattr(logging_setup.Path, "iterdir", lambda self: iter(fake_pids))

        assert logging_setup._is_syslog_daemon_running() is True

    def test_returns_false_when_no_matching_process(self, logging_setup, monkeypatch):
        fake_pids = [FakePidDir("111", "bash"), FakePidDir("222", "python3")]

        monkeypatch.setattr(logging_setup.Path, "is_dir", lambda self: True)
        monkeypatch.setattr(logging_setup.Path, "iterdir", lambda self: iter(fake_pids))

        assert logging_setup._is_syslog_daemon_running() is False

    def test_unreadable_comm_file_is_skipped(self, logging_setup, monkeypatch):
        fake_pids = [
            FakePidDir("111", raise_on_read=True),
            FakePidDir("222", "syslog-ng"),
        ]

        monkeypatch.setattr(logging_setup.Path, "is_dir", lambda self: True)
        monkeypatch.setattr(logging_setup.Path, "iterdir", lambda self: iter(fake_pids))

        assert logging_setup._is_syslog_daemon_running() is True


class TestResolveLogFilePath:
    def test_explicit_path_wins(self, logging_setup):
        result = logging_setup._resolve_log_file_path("fetchbridge", "/custom/path.log")
        assert result == logging_setup.Path("/custom/path.log")

    def test_prefers_docker_log_dir_if_dedicated_mount(self, logging_setup, config, monkeypatch):
        monkeypatch.setattr(config, "_is_dedicated_mount", lambda p: str(p) == "/log")

        result = logging_setup._resolve_log_file_path("fetchbridge", "")
        assert result == logging_setup.Path("/log/fetchbridge.log")

    def test_falls_back_to_var_log_if_writable(self, logging_setup, config, monkeypatch):
        monkeypatch.setattr(config, "_is_dedicated_mount", lambda p: False)
        # Verhindert echtes Anlegen von /var/log/<app> während des Tests
        monkeypatch.setattr(logging_setup.Path, "mkdir", lambda self, **k: None)
        monkeypatch.setattr(logging_setup.os, "access", lambda *a, **k: True)

        result = logging_setup._resolve_log_file_path("fetchbridge-test", "")
        assert result == logging_setup.Path("/var/log/fetchbridge-test/fetchbridge-test.log")

    def test_final_fallback_when_var_log_unwritable(self, logging_setup, config, monkeypatch):
        monkeypatch.setattr(config, "_is_dedicated_mount", lambda p: False)

        def raise_oserror(self, **kwargs):
            raise OSError("Permission denied")

        monkeypatch.setattr(logging_setup.Path, "mkdir", raise_oserror)

        result = logging_setup._resolve_log_file_path("fetchbridge-test", "")
        assert result.name == "fetchbridge-test.log"
        assert "/var/log" not in str(result)


class TestSetupLoggingFileTrigger:
    """
    Verifiziert direkt, dass setup_logging() denselben Bug wie in
    yt-upload/tw-recorder von Anfang an vermeidet: ohne echtes /log-Volume
    (nur das vom Dockerfile fest angelegte Verzeichnis) darf KEIN
    Datei-Handler aktiviert werden.
    """

    def test_plain_baked_in_log_dir_without_real_mount_stays_stdout_only(self, logging_setup, config, monkeypatch, clean_root_logger):
        monkeypatch.setattr(config, "_is_dedicated_mount", lambda p: False)
        monkeypatch.setattr(logging_setup, "_is_syslog_daemon_running", lambda: False)
        monkeypatch.delenv("LOG_FILE", raising=False)

        logging_setup.setup_logging(cfg={})

        root_handlers = logging.getLogger().handlers
        assert len(root_handlers) == 1
        assert isinstance(root_handlers[0], logging.StreamHandler)

    def test_real_log_volume_mount_adds_file_handler(self, logging_setup, config, monkeypatch, tmp_path, clean_root_logger):
        monkeypatch.setattr(config, "_is_dedicated_mount", lambda p: True)
        monkeypatch.setattr(logging_setup, "_is_syslog_daemon_running", lambda: False)
        monkeypatch.setattr(
            logging_setup, "_resolve_log_file_path",
            lambda app_name, explicit_path: tmp_path / "test.log"
        )
        monkeypatch.delenv("LOG_FILE", raising=False)

        logging_setup.setup_logging(cfg={})

        assert len(logging.getLogger().handlers) == 2

    def test_explicit_log_file_adds_file_handler_even_without_mount(self, logging_setup, config, monkeypatch, tmp_path, clean_root_logger):
        monkeypatch.setattr(config, "_is_dedicated_mount", lambda p: False)
        monkeypatch.setattr(logging_setup, "_is_syslog_daemon_running", lambda: False)
        monkeypatch.delenv("LOG_FILE", raising=False)

        logging_setup.setup_logging(cfg={"log_file": str(tmp_path / "explicit.log")})

        assert len(logging.getLogger().handlers) == 2

    def test_idempotent_does_not_duplicate_handlers(self, logging_setup, config, monkeypatch, clean_root_logger):
        monkeypatch.setattr(config, "_is_dedicated_mount", lambda p: False)
        monkeypatch.setattr(logging_setup, "_is_syslog_daemon_running", lambda: False)
        monkeypatch.delenv("LOG_FILE", raising=False)

        logging_setup.setup_logging(cfg={})
        logging_setup.setup_logging(cfg={})

        assert len(logging.getLogger().handlers) == 1
