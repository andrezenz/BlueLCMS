from types import SimpleNamespace
import struct
import zlib

from bluelcms import linux_integration


def test_thumbnailer_registration_writes_user_mime_and_thumbnailer_idempotently(monkeypatch, tmp_path):
    helper = tmp_path / "thumbnailer.py"
    helper.write_text("print('headless thumbnailer')\n")
    mime = tmp_path / "mime.xml"
    mime.write_text("<mime-info/>\n")
    data_home = tmp_path / "data"
    calls = []
    monkeypatch.setattr(linux_integration.shutil, "which", lambda name: "/usr/bin/update-mime-database")
    monkeypatch.setattr(linux_integration.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert linux_integration.register_thumbnailer(data_home, (helper, mime))
    thumbnailer = (data_home / "thumbnailers/bluelcms.thumbnailer").read_text()
    assert "TryExec=/usr/bin/python3" in thumbnailer
    assert "application/x-bluelcms-cache" in thumbnailer
    assert "application/x-bluelcms-mzml-gzip" in thumbnailer
    assert "thumbnailer" in thumbnailer
    assert (data_home / "mime/packages/bluelcms.xml").read_text() == "<mime-info/>\n"
    assert len(calls) == 1
    assert not linux_integration.register_thumbnailer(data_home, (helper, mime))
    assert len(calls) == 1, "unchanged desktop registrations should not rebuild the MIME database"


def test_startup_migration_only_runs_on_linux(monkeypatch):
    monkeypatch.setattr(linux_integration, "sys", SimpleNamespace(platform="darwin"))
    assert linux_integration.ensure_thumbnailer_registered() is None


def test_mime_refresh_failure_is_retried_until_database_updates(monkeypatch, tmp_path):
    helper = tmp_path / "thumbnailer.py"
    helper.write_text("pass\n")
    mime = tmp_path / "mime.xml"
    mime.write_text("<mime-info/>\n")
    monkeypatch.setattr(linux_integration.shutil, "which", lambda name: "/usr/bin/update-mime-database")
    def failure(*args, **kwargs):
        raise linux_integration.subprocess.CalledProcessError(1, "update-mime-database", stderr="bad mime data")
    monkeypatch.setattr(linux_integration.subprocess, "run", failure)
    with __import__("pytest").raises(linux_integration.subprocess.CalledProcessError):
        linux_integration.register_thumbnailer(tmp_path / "data", (helper, mime))
    stamp = tmp_path / "data/mime/packages/bluelcms.thumbnailer-stamp"
    assert not stamp.exists()
    monkeypatch.setattr(linux_integration.subprocess, "run", lambda *args, **kwargs: None)
    assert linux_integration.register_thumbnailer(tmp_path / "data", (helper, mime))
    assert stamp.exists()
    assert not linux_integration.register_thumbnailer(tmp_path / "data", (helper, mime))


def png_with_text(**entries):
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xffffffff)
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    texts = b"".join(chunk(b"tEXt", key.encode() + b"\0" + value.encode()) for key, value in entries.items())
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + texts + chunk(b"IDAT", zlib.compress(b"\0\0\0\0")) + chunk(b"IEND", b"")


def test_registration_migration_clears_only_blue_lcms_failure_records(tmp_path):
    failed = tmp_path / "cache/thumbnails/fail/gnome-thumbnail-factory"
    unrelated = tmp_path / "cache/thumbnails/fail/other"
    failed.mkdir(parents=True); unrelated.mkdir(parents=True)
    mzml = failed / "mzml.png"
    cache = failed / "cache.png"
    photo = failed / "photo.png"
    other = unrelated / "mzml.png"
    mzml.write_bytes(png_with_text(**{"Thumb::URI": "file:///data/run.mzML.gz"}))
    cache.write_bytes(png_with_text(**{"Thumb::URI": "file:///cache/run.bluelcms.npz"}))
    photo.write_bytes(png_with_text(**{"Thumb::URI": "file:///data/photo.png"}))
    other.write_bytes(png_with_text(**{"Thumb::URI": "file:///data/run.mzML"}))
    assert linux_integration.clear_cached_thumbnail_failures(tmp_path / "cache") == 2
    assert not mzml.exists() and not cache.exists()
    assert photo.exists() and other.exists()


def test_old_package_first_start_installs_thumbnailer_migration(monkeypatch, tmp_path):
    helper = tmp_path / "thumbnailer.py"
    helper.write_text("print('thumbnailer')\n")
    mime = tmp_path / "mime.xml"
    mime.write_text("<mime-info/>\n")
    data_home = tmp_path / "user-data"
    calls = []
    monkeypatch.setattr(linux_integration, "integration_assets", lambda: (helper, mime))
    monkeypatch.setattr(linux_integration, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(linux_integration.shutil, "which", lambda name: "/usr/bin/update-mime-database")
    monkeypatch.setattr(linux_integration.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "user-cache"))
    assert linux_integration.ensure_thumbnailer_registered() is True
    assert (data_home / "thumbnailers/bluelcms.thumbnailer").exists()
    assert len(calls) == 1
    assert linux_integration.ensure_thumbnailer_registered() is False
    assert len(calls) == 1


def test_thumbnailer_migration_retries_previous_gnome_failures(monkeypatch, tmp_path):
    helper = tmp_path / "thumbnailer.py"
    helper.write_text("print('new thumbnailer')\n")
    mime = tmp_path / "mime.xml"
    mime.write_text("<mime-info/>\n")
    data_home = tmp_path / "data"
    cache_home = tmp_path / "cache"
    failed = cache_home / "thumbnails/fail/gnome-thumbnail-factory"
    failed.mkdir(parents=True)
    record = failed / "old-failure.png"
    record.write_bytes(png_with_text(**{"Thumb::URI": "file:///data/measurement.mzML"}))
    calls = []
    monkeypatch.setattr(linux_integration.shutil, "which", lambda name: "/usr/bin/update-mime-database")
    monkeypatch.setattr(linux_integration.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    assert linux_integration.register_thumbnailer(data_home, (helper, mime))
    assert not record.exists()
    assert calls
