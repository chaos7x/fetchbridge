"""
Tests für load_config, get_config_hash, get_config_files_state,
_is_dedicated_mount, _running_in_container und _get (config.py).
"""

import configparser
from pathlib import Path


def _write_main_config(tmp_path, content):
    path = tmp_path / "fetchbridge.conf"
    path.write_text(content, encoding="utf-8")
    return path


class _FakeStat:
    def __init__(self, st_dev):
        self.st_dev = st_dev


class TestIsDedicatedMount:
    """
    Unterscheidet ein echtes Docker-Volume/Bind-Mount von einem gewöhnlichen,
    per `mkdir -p` fest ins Image gebackenen Verzeichnis (z.B. /media/out) -
    ohne diese Unterscheidung würde ein solches Verzeichnis fälschlich als
    "gemountet" durchgehen (siehe der in yt-upload/tw-recorder gefixte Bug).

    stat() wird bewusst NICHT pauschal für alle Path-Instanzen ersetzt,
    sondern mit Fallback auf die echte Methode für nicht getestete Pfade -
    pytest ruft Path.stat() auch intern für eigene Zwecke auf.
    """

    def test_returns_false_if_path_does_not_exist(self, config, monkeypatch):
        monkeypatch.setattr(Path, "is_dir", lambda self: False)
        assert config._is_dedicated_mount(Path("/media/out")) is False

    def test_returns_false_for_plain_baked_in_directory_same_device(self, config, monkeypatch):
        """Gleiche st_dev wie das Elternverzeichnis = kein echter Mount, nur ein normaler Ordner."""
        real_stat = Path.stat
        monkeypatch.setattr(Path, "is_dir", lambda self: True)
        monkeypatch.setattr(
            Path, "stat",
            lambda self: _FakeStat(st_dev=1) if str(self) in ("/media/out", "/media") else real_stat(self)
        )

        assert config._is_dedicated_mount(Path("/media/out")) is False

    def test_returns_true_for_real_mount_different_device(self, config, monkeypatch):
        """Unterschiedliche st_dev zum Elternverzeichnis = tatsächlich eingehängtes Volume/Bind-Mount."""
        real_stat = Path.stat
        monkeypatch.setattr(Path, "is_dir", lambda self: True)

        def fake_stat(self):
            if str(self) == "/media/out":
                return _FakeStat(st_dev=2)
            if str(self) == "/media":
                return _FakeStat(st_dev=1)
            return real_stat(self)

        monkeypatch.setattr(Path, "stat", fake_stat)

        assert config._is_dedicated_mount(Path("/media/out")) is True

    def test_permission_error_on_stat_returns_false(self, config, monkeypatch):
        real_stat = Path.stat
        monkeypatch.setattr(Path, "is_dir", lambda self: True)

        def raise_or_real_stat(self):
            if str(self) in ("/media/out", "/media"):
                raise OSError("Permission denied")
            return real_stat(self)

        monkeypatch.setattr(Path, "stat", raise_or_real_stat)

        assert config._is_dedicated_mount(Path("/media/out")) is False


class TestRunningInContainer:
    def test_true_when_dockerenv_present(self, config, monkeypatch):
        monkeypatch.setattr(config.Path, "exists", lambda self: str(self) == "/.dockerenv")
        assert config._running_in_container() is True

    def test_false_when_dockerenv_absent(self, config, monkeypatch):
        monkeypatch.setattr(config.Path, "exists", lambda self: False)
        assert config._running_in_container() is False


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


class TestGetHelper:
    """
    _get() muss den fallback auch dann liefern, wenn der Schlüssel zwar
    existiert, aber keinen Wert hat ("key" statt "key = value") - reines
    ConfigParser.get(fallback=...) ignoriert den fallback in diesem Fall
    und liefert None (allow_no_value=True lässt diese Syntax zu).
    """

    def test_returns_value_when_present(self, config):
        cfg_obj = configparser.ConfigParser(allow_no_value=True)
        cfg_obj.read_string("[general]\nlog_level = DEBUG\n")

        assert config._get(cfg_obj, "general", "log_level", "INFO") == "DEBUG"

    def test_returns_fallback_when_section_missing(self, config):
        cfg_obj = configparser.ConfigParser(allow_no_value=True)
        cfg_obj.read_string("[general]\n")

        assert config._get(cfg_obj, "general", "log_level", "INFO") == "INFO"

    def test_returns_fallback_when_key_present_but_valueless(self, config):
        """Der eigentlich gemeldete Bug: 'log_level' ohne '= wert'."""
        cfg_obj = configparser.ConfigParser(allow_no_value=True)
        cfg_obj.read_string("[general]\nlog_level\n")

        assert config._get(cfg_obj, "general", "log_level", "INFO") == "INFO"


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

        assert cfg["source_dir"] == Path("/srv/media-pipeline/recordings")
        assert cfg["target_dir"] == Path("/srv/media-pipeline/incoming")
        assert cfg["cleanup_empty_dirs"] is False

    def test_forgotten_equals_sign_does_not_crash_and_uses_default(self, config, tmp_path, monkeypatch):
        """
        Regression: eine Zeile ganz ohne "= wert" (z.B. vergessenes "= INFO")
        darf load_config() nicht mit AttributeError/TypeError crashen lassen -
        derselbe Bug wie in tw-recorder's [channels]-Sektion, hier aber
        potenziell an jeder einzelnen Config-Zeile, da allow_no_value=True
        global für den ganzen Parser gilt.
        """
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[general]\nlog_level\nsource_dir\n")
        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.delenv("SOURCE_DIR", raising=False)

        cfg = config.load_config()

        assert cfg["log_level"] == "INFO"
        assert cfg["source_dir"] == Path("/srv/media-pipeline/recordings")

    def test_debug_env_var_is_an_alias_for_log_level_debug(self, config, tmp_path, monkeypatch):
        """DEBUG=true/yes/1 vereinheitlicht mit tw-recorder/yt-upload, die nur dieses eine Flag kennen."""
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[general]\nsource_dir = /whatever\n")
        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.setenv("DEBUG", "true")

        cfg = config.load_config()

        assert cfg["log_level"] == "DEBUG"

    def test_explicit_log_level_takes_precedence_over_debug(self, config, tmp_path, monkeypatch):
        """DEBUG ist nur der Default - eine explizit gesetzte log_level/LOG_LEVEL gewinnt immer."""
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[general]\nlog_level = WARNING\n")
        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)
        monkeypatch.setenv("DEBUG", "true")

        cfg = config.load_config()

        assert cfg["log_level"] == "WARNING"

    def test_debug_false_does_not_override_default_info(self, config, tmp_path, monkeypatch):
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[general]\nsource_dir = /whatever\n")
        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.setenv("DEBUG", "false")

        cfg = config.load_config()

        assert cfg["log_level"] == "INFO"

    def test_conf_d_overrides_main_config(self, config, tmp_path, monkeypatch):
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[general]\nlog_level = INFO\n")
        (conf_d / "override.conf").write_text("[general]\nlog_level = DEBUG\n", encoding="utf-8")

        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)

        cfg = config.load_config()

        assert cfg["log_level"] == "DEBUG"

    def test_broken_conf_d_file_does_not_block_later_conf_d_files(self, config, tmp_path, monkeypatch):
        """
        Regression: config.read() mit der GESAMTEN Dateiliste auf einmal
        bricht beim ersten Parse-Fehler komplett ab - jede danach folgende
        Datei (auch gültige!) wurde dadurch stillschweigend nie gelesen.
        Alphabetisch sortiert landet die kaputte Datei zwischen zwei gültigen.
        """
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[general]\nsource_dir = /from-main\n")
        (conf_d / "10-good.conf").write_text("[general]\nlog_level = DEBUG\n", encoding="utf-8")
        (conf_d / "20-broken.conf").write_text("this is not valid ini at all !!! ===\n", encoding="utf-8")
        (conf_d / "30-more.conf").write_text("[general]\ntarget_dir = /from-30-more\n", encoding="utf-8")

        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)

        cfg = config.load_config()

        assert cfg["source_dir"] == Path("/from-main")
        assert cfg["log_level"] == "DEBUG"

    def test_unreadable_conf_d_file_is_skipped_with_a_warning(self, config, tmp_path, monkeypatch, caplog):
        """
        Regression: config.read(f, ...) laesst configparser die Datei selbst
        oeffnen - ein dabei auftretender OSError (z.B. Permission denied,
        real reproduziert: eine conf.d-Datei gehoerte einem persoenlichen
        User statt der erwarteten Gruppe) wird von ConfigParser.read()
        INTERN abgefangen und NIE an aufrufenden Code durchgereicht. Die
        Datei wurde dadurch komplett kommentarlos ignoriert, ohne jede
        Log-Warnung. Fix: die Datei selbst oeffnen (config.read_file()),
        damit ein Berechtigungsfehler in unser eigenes except laeuft.
        """
        conf_d = tmp_path / "conf.d"
        conf_d.mkdir()
        main_conf = _write_main_config(tmp_path, "[general]\nsource_dir = /from-main\n")
        unreadable = conf_d / "secret.conf"
        unreadable.write_text("[general]\ntarget_dir = /secret-target\n", encoding="utf-8")

        monkeypatch.setattr(config, "CONFIG_FILE", main_conf)
        monkeypatch.setattr(config, "CONF_D_DIR", conf_d)

        real_open = open

        def fake_open(path, *args, **kwargs):
            if str(path) == str(unreadable):
                raise PermissionError(13, "Permission denied", str(unreadable))
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(config, "open", fake_open, raising=False)

        with caplog.at_level("WARNING"):
            cfg = config.load_config()

        assert cfg["source_dir"] == Path("/from-main")
        assert cfg["target_dir"] != Path("/secret-target")
        assert "secret.conf" in caplog.text
