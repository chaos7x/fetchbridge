"""Tests für load_config, get_config_hash, get_config_files_state (config.py)."""

from pathlib import Path


def _write_main_config(tmp_path, content):
    path = tmp_path / "fetchbridge.conf"
    path.write_text(content, encoding="utf-8")
    return path


class TestConfigHashing:
    def test_hash_changes_when_file_content_changes(self, config, tmp_path, monkeypatch):
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[general]\nsource_dir = /media/out\n")

        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)

        hash_before, _ = config.get_config_hash()
        main_conf.write_text(main_conf.read_text() + "\n# comment\n")
        hash_after, _ = config.get_config_hash()

        assert hash_before != hash_after

    def test_hash_stable_without_changes(self, config, tmp_path, monkeypatch):
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[general]\nsource_dir = /media/out\n")

        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)

        hash1, _ = config.get_config_hash()
        hash2, _ = config.get_config_hash()

        assert hash1 == hash2

    def test_conf_d_files_included_in_state(self, config, tmp_path, monkeypatch):
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[general]\nsource_dir = /media/out\n")
        (conf_d / "extra.conf").write_text("[mover]\ncleanup_empty_dirs = true\n", encoding="utf-8")

        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)

        state = config.get_config_files_state()
        names = {p.name for p in state.keys()}

        assert names == {"fetchbridge.conf", "extra.conf"}

    def test_missing_config_files_yield_empty_state(self, config, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "does-not-exist.conf")
        monkeypatch.setattr(config, "CONF_D_DIR", tmp_path / "does-not-exist-dir")

        assert config.get_config_files_state() == {}


class TestLoadConfig:
    def test_reads_general_and_mover_settings(self, config, tmp_path, monkeypatch):
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, (
            "[general]\n"
            "source_dir = /custom/source\n"
            "target_dir = /custom/target\n"
            "log_level = DEBUG\n"
            "\n"
            "[mover]\n"
            "allowed_extensions = mkv, mp4\n"
            "cleanup_empty_dirs = true\n"
        ))
        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)

        cfg = config.load_config()

        assert cfg["source_dir"] == Path("/custom/source")
        assert cfg["target_dir"] == Path("/custom/target")
        assert cfg["log_level"] == "DEBUG"
        assert cfg["allowed_extensions"] == {".mkv", ".mp4"}
        assert cfg["cleanup_empty_dirs"] is True

    def test_allowed_extensions_normalizes_leading_dot(self, config, tmp_path, monkeypatch):
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[mover]\nallowed_extensions = .mkv,mp4,.WEBM\n")
        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)

        cfg = config.load_config()

        assert cfg["allowed_extensions"] == {".mkv", ".mp4", ".webm"}

    def test_falls_back_to_defaults_without_config_file(self, config, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.conf")
        monkeypatch.setattr(config, "CONF_D_DIR", tmp_path / "missing-dir")
        monkeypatch.delenv("SOURCE_DIR", raising=False)
        monkeypatch.delenv("TARGET_DIR", raising=False)

        cfg = config.load_config()

        assert cfg["source_dir"] == Path("/media/out")
        assert cfg["target_dir"] == Path("/media/in")
        assert cfg["cleanup_empty_dirs"] is False

    def test_conf_d_overrides_main_config(self, config, tmp_path, monkeypatch):
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[general]\nlog_level = INFO\n")
        (conf_d / "override.conf").write_text("[general]\nlog_level = DEBUG\n", encoding="utf-8")

        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)

        cfg = config.load_config()

        assert cfg["log_level"] == "DEBUG"
