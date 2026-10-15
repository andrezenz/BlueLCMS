from types import SimpleNamespace

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


def test_old_package_first_start_installs_thumbnailer_migration(monkeypatch, tmp_path):
    import os

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
    assert linux_integration.ensure_thumbnailer_registered() is True
    assert (data_home / "thumbnailers/bluelcms.thumbnailer").exists()
    assert len(calls) == 1
    assert linux_integration.ensure_thumbnailer_registered() is False
    assert len(calls) == 1
