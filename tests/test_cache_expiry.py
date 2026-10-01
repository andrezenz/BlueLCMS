import time
from pathlib import Path

from bluelcms.folders import cleanup_expired_cache


def test_cleanup_removes_old_files(tmp_path):
    old_file = tmp_path / "old.mzML"
    old_file.write_text("old")
    old_time = time.time() - (10 * 86400)
    old_file.touch()
    import os
    os.utime(old_file, (old_time, old_time))

    new_file = tmp_path / "new.mzML"
    new_file.write_text("new")

    removed = cleanup_expired_cache(tmp_path, 7)
    assert removed == 1
    assert not old_file.exists()
    assert new_file.exists()


def test_cleanup_respects_zero_expiry(tmp_path):
    old_file = tmp_path / "old.mzML"
    old_file.write_text("old")
    old_time = time.time() - (10 * 86400)
    import os
    os.utime(old_file, (old_time, old_time))

    removed = cleanup_expired_cache(tmp_path, 0)
    assert removed == 0
    assert old_file.exists()


def test_cleanup_handles_missing_folder():
    removed = cleanup_expired_cache(Path("/nonexistent/path"), 7)
    assert removed == 0


def test_cleanup_ignores_hidden_files(tmp_path):
    hidden = tmp_path / ".hidden.mzML"
    hidden.write_text("hidden")
    old_time = time.time() - (10 * 86400)
    import os
    os.utime(hidden, (old_time, old_time))

    removed = cleanup_expired_cache(tmp_path, 7)
    assert removed == 0
    assert hidden.exists()
