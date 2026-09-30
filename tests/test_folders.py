from bluelcms.folders import cached_path, copy_to_cache, is_afp_path, remote_mount_roots
from bluelcms.mzml import discover_files
from bluelcms import settings
from PySide6.QtCore import QSettings


def test_gvfs_afp_path_discovery_and_persistence(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    home = tmp_path / "home"
    home.mkdir()
    gvfs = runtime / "gvfs"
    share = gvfs / "afp-volume:host=lab.local,user=scientist,volume=LC MS"
    folder = share / "Run 1"
    folder.mkdir(parents=True)
    sample = folder / "sample.mzML"
    sample.touch()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("HOME", str(home))
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    assert remote_mount_roots() == [gvfs]
    assert discover_files(folder) == [sample]
    settings.set_data_folder(folder)
    assert settings.data_folder() == folder


def test_unmounted_and_legacy_gvfs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert remote_mount_roots() == []
    legacy = tmp_path / ".gvfs"
    legacy.mkdir()
    assert remote_mount_roots() == [legacy]


def test_afp_cache_has_unique_atomic_local_copy(tmp_path):
    source = tmp_path / "gvfs" / "afp-volume:host=lab,volume=LC" / "sample.mzML"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"mzML data")
    cache_root = tmp_path / "cache"
    cache = cached_path(source, cache_root)
    assert is_afp_path(source)
    assert cache.parent == cache_root
    assert cache != cached_path(tmp_path / "gvfs" / "afp-volume:host=other,volume=LC" / "sample.mzML", cache_root)
    progress = []
    assert copy_to_cache(source, cache, lambda copied, total: progress.append((copied, total))) == cache
    assert cache.read_bytes() == b"mzML data"
    assert progress == [(len(b"mzML data"), len(b"mzML data"))]
    assert not list(cache_root.glob("*.part"))
    assert cached_path(tmp_path / "local.mzML", cache_root) is None


def test_cache_folder_setting(tmp_path, monkeypatch):
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    settings.set_cache_folder(tmp_path / "cache")
    assert settings.cache_folder() == tmp_path / "cache"
