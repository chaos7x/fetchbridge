"""Tests für write_heartbeat() und check_healthcheck() (healthcheck.py)."""

import time


class TestHeartbeatAndHealthcheck:
    def test_missing_heartbeat_file_is_unhealthy(self, healthcheck, tmp_path, monkeypatch):
        monkeypatch.setattr(healthcheck, "HEARTBEAT_FILE", tmp_path / "does-not-exist.heartbeat")
        assert healthcheck.check_healthcheck() == 1

    def test_fresh_heartbeat_is_healthy(self, healthcheck, tmp_path, monkeypatch):
        heartbeat_file = tmp_path / "fetchbridge.heartbeat"
        monkeypatch.setattr(healthcheck, "HEARTBEAT_FILE", heartbeat_file)
        monkeypatch.setattr(healthcheck, "HEARTBEAT_MAX_AGE", 60)

        healthcheck.write_heartbeat()

        assert heartbeat_file.is_file()
        assert healthcheck.check_healthcheck() == 0

    def test_stale_heartbeat_is_unhealthy(self, healthcheck, tmp_path, monkeypatch):
        heartbeat_file = tmp_path / "fetchbridge.heartbeat"
        monkeypatch.setattr(healthcheck, "HEARTBEAT_FILE", heartbeat_file)
        monkeypatch.setattr(healthcheck, "HEARTBEAT_MAX_AGE", 60)

        stale_timestamp = time.time() - 120
        heartbeat_file.write_text(str(stale_timestamp))

        assert healthcheck.check_healthcheck() == 1

    def test_invalid_heartbeat_content_is_unhealthy(self, healthcheck, tmp_path, monkeypatch):
        heartbeat_file = tmp_path / "fetchbridge.heartbeat"
        heartbeat_file.write_text("not-a-timestamp")
        monkeypatch.setattr(healthcheck, "HEARTBEAT_FILE", heartbeat_file)

        assert healthcheck.check_healthcheck() == 1

    def test_write_heartbeat_does_not_raise_if_unwritable(self, healthcheck, monkeypatch):
        """Ein Healthcheck-Problem darf den Dämon nicht zum Absturz bringen."""

        class UnwritablePath:
            def write_text(self, content):
                raise OSError("Permission denied")

        monkeypatch.setattr(healthcheck, "HEARTBEAT_FILE", UnwritablePath())

        healthcheck.write_heartbeat()  # darf nicht raisen
