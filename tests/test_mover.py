"""
Tests für process_file() in mover.py - insbesondere die Symlink-Ablehnung
und die Stabilitätsprüfung (is_file_stable()).

filepath.is_file() (wie auch os.path.exists()) folgt Symlinks; ohne eine
explizite is_symlink()-Prüfung würden shutil.copy2()/shutil.move() den Inhalt
eines Symlink-Ziels nach TARGET_DIR kopieren/verschieben - ein Symlink mit
erlaubter Endung (z.B. "evil.mkv" -> eine beliebige lesbare Datei) in
SOURCE_DIR wäre damit ein Primitive für beliebigen Dateizugriff.
"""


def _patch_config(config, monkeypatch, source_dir, target_dir):
    monkeypatch.setattr(config, "SOURCE_DIR", source_dir)
    monkeypatch.setattr(config, "TARGET_DIR", target_dir)
    monkeypatch.setattr(config, "ALLOWED_EXTENSIONS", {".mkv", ".mp4", ".webm"})
    monkeypatch.setattr(config, "TEMP_EXTENSIONS", {".part", ".ytdl", ".tmp", ".temp"})
    monkeypatch.setattr(config, "CLEANUP_EMPTY_DIRS", False)
    # 0/2 statt der Produktions-Defaults (2s/10 Checks): process_file() ruft
    # is_file_stable() jetzt vor jedem Move/Copy auf - ohne diese Test-Werte
    # würde jeder bestehende Test hier ~2s lang künstlich schlafen.
    monkeypatch.setattr(config, "STABILITY_CHECK_INTERVAL", 0)
    monkeypatch.setattr(config, "STABILITY_MAX_CHECKS", 2)


class TestProcessFileSymlinkRejection:
    def test_symlink_to_file_outside_source_dir_is_rejected(self, mover, config, tmp_path, monkeypatch, caplog):
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        secret = tmp_path / "secret.txt"
        secret.write_text("TOP SECRET")

        malicious_link = source_dir / "evil.mkv"
        malicious_link.symlink_to(secret)

        _patch_config(config, monkeypatch, source_dir, target_dir)

        with caplog.at_level("WARNING"):
            mover.process_file(malicious_link)

        assert not (target_dir / "evil.mkv").exists()
        assert list(target_dir.iterdir()) == []
        assert any("Symlink" in r.message for r in caplog.records)

    def test_symlink_to_valid_video_is_also_rejected(self, mover, config, tmp_path, monkeypatch):
        """Die Ablehnung gilt unabhängig davon, ob das Linkziel selbst ein gültiges Video ist."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        real_video = tmp_path / "real.mkv"
        real_video.write_bytes(b"fake video content")

        link = source_dir / "link.mkv"
        link.symlink_to(real_video)

        _patch_config(config, monkeypatch, source_dir, target_dir)

        mover.process_file(link)

        assert list(target_dir.iterdir()) == []
        # Das Linkziel selbst bleibt unangetastet
        assert real_video.exists()

    def test_regular_file_is_still_moved_normally(self, mover, config, tmp_path, monkeypatch):
        """Regressionsschutz: der Fix darf normale (Nicht-Symlink-)Dateien nicht beeinträchtigen."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        video = source_dir / "video.mkv"
        video.write_bytes(b"fake video content")

        _patch_config(config, monkeypatch, source_dir, target_dir)

        mover.process_file(video)

        assert (target_dir / "video.mkv").read_bytes() == b"fake video content"
        assert not video.exists()


class TestIsFileStable:
    def test_stable_file_returns_true_after_one_wait(self, mover, config, tmp_path, monkeypatch):
        video = tmp_path / "video.mkv"
        video.write_bytes(b"fake video content")

        monkeypatch.setattr(config, "STABILITY_CHECK_INTERVAL", 0)
        monkeypatch.setattr(config, "STABILITY_MAX_CHECKS", 5)

        assert mover.is_file_stable(video) is True

    def test_still_growing_file_is_detected_and_eventually_processed(
        self, mover, config, tmp_path, monkeypatch
    ):
        """Simuliert einen Schreiber, der die Datei erst nach 2 Checks fertigstellt."""
        video = tmp_path / "video.mkv"
        video.write_bytes(b"partial")

        monkeypatch.setattr(config, "STABILITY_CHECK_INTERVAL", 0)
        monkeypatch.setattr(config, "STABILITY_MAX_CHECKS", 5)

        writes_remaining = {"n": 2}

        def fake_sleep(_seconds):
            if writes_remaining["n"] > 0:
                writes_remaining["n"] -= 1
                with video.open("ab") as f:
                    f.write(b"more data")

        monkeypatch.setattr(mover.time, "sleep", fake_sleep)

        assert mover.is_file_stable(video) is True
        assert writes_remaining["n"] == 0

    def test_file_growing_past_max_checks_is_rejected(self, mover, config, tmp_path, monkeypatch, caplog):
        """Ein Schreiber, der nie aufhört, darf process_file() nicht blockieren - Timeout statt Endlosschleife."""
        video = tmp_path / "video.mkv"
        video.write_bytes(b"partial")

        monkeypatch.setattr(config, "STABILITY_CHECK_INTERVAL", 0)
        monkeypatch.setattr(config, "STABILITY_MAX_CHECKS", 3)

        def fake_sleep(_seconds):
            with video.open("ab") as f:
                f.write(b"more data")

        monkeypatch.setattr(mover.time, "sleep", fake_sleep)

        with caplog.at_level("WARNING"):
            assert mover.is_file_stable(video) is False
        assert any("immer noch geschrieben" in r.message for r in caplog.records)

    def test_process_file_skips_unstable_file_without_moving_it(
        self, mover, config, tmp_path, monkeypatch
    ):
        """Regressionsschutz: process_file() darf eine wachsende Datei nicht anfassen."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        video = source_dir / "video.mkv"
        video.write_bytes(b"partial")

        _patch_config(config, monkeypatch, source_dir, target_dir)
        monkeypatch.setattr(config, "STABILITY_MAX_CHECKS", 2)

        def fake_sleep(_seconds):
            with video.open("ab") as f:
                f.write(b"more data")

        monkeypatch.setattr(mover.time, "sleep", fake_sleep)

        mover.process_file(video)

        assert video.exists()
        assert list(target_dir.iterdir()) == []
