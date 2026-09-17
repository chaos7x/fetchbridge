"""
Tests für process_file() in mover.py - insbesondere die Symlink-Ablehnung.

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
