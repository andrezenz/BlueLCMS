import io
from pathlib import Path
import tarfile

import pytest

from bluelcms import package_updater


def prepare_release(monkeypatch, tmp_path, members):
    installed = tmp_path / ".local" / "share" / "BlueLCMS"
    installed.mkdir(parents=True)
    executable = installed / "BlueLCMS"
    executable.write_text("old version")
    monkeypatch.setattr(package_updater.sys, "platform", "linux")
    monkeypatch.setattr(package_updater.sys, "executable", str(executable))
    monkeypatch.setattr(package_updater.releases, "release", lambda **kwargs: {
        "tag": "v1.0.1", "assets": [{"name": "BlueLCMS-linux-x86_64.tar.gz", "browser_download_url": "https://example.test/app"}]})
    def download(url, destination):
        with tarfile.open(destination, "w:gz") as archive:
            for name, content in members.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                member.mode = 0o755
                archive.addfile(member, io.BytesIO(content))
    monkeypatch.setattr(package_updater, "urlretrieve", download)
    return executable


def test_installs_selected_linux_release_and_returns_restart_path(monkeypatch, tmp_path):
    executable = prepare_release(monkeypatch, tmp_path, {
        "BlueLCMS/BlueLCMS": b"new version", "BlueLCMS/_internal/library": b"bundled dependency",
        "install.sh": b"#!/bin/sh\nset -eu\nprefix=\"$BLUELCMS_INSTALL_PREFIX\"\nrm -rf \"$prefix/share/BlueLCMS\"\nmkdir -p \"$prefix/share\"\ncp -R BlueLCMS \"$prefix/share/BlueLCMS\"\nprintf '%s' \"$prefix\" > \"$prefix/thumbnailer-registered\"\n"})
    result = package_updater.install("refs/tags/v1.0.1")
    assert result == {"version": "v1.0.1", "executable": str(executable)}
    assert executable.read_text() == "new version"
    assert (executable.parent / "_internal" / "library").read_text() == "bundled dependency"
    assert (tmp_path / ".local/thumbnailer-registered").read_text() == str(tmp_path / ".local")
    assert executable.stat().st_mode & 0o111


def test_malformed_package_preserves_installed_app(monkeypatch, tmp_path):
    executable = prepare_release(monkeypatch, tmp_path, {"unexpected": b"invalid package"})
    with pytest.raises(RuntimeError, match="missing its executable"):
        package_updater.install("refs/tags/v1.0.1")
    assert executable.read_text() == "old version"


def test_linux_package_requires_and_runs_integration_installer(monkeypatch, tmp_path):
    extracted = tmp_path / "release"
    extracted.mkdir()
    (extracted / "install.sh").write_text("#!/bin/sh\nprintf '%s' \"$BLUELCMS_INSTALL_PREFIX\" > registered\n")
    prefix = tmp_path / "prefix"
    package_updater.install_linux_package(extracted, prefix, tmp_path / "home")
    assert (extracted / "registered").read_text() == str(prefix)


def test_archive_cannot_write_outside_extraction_root(monkeypatch, tmp_path):
    executable = prepare_release(monkeypatch, tmp_path, {"../../escaped": b"invalid package"})
    with pytest.raises(tarfile.FilterError):
        package_updater.install("refs/tags/v1.0.1")
    assert executable.read_text() == "old version"


def test_failed_replacement_restores_previous_app(monkeypatch, tmp_path):
    source = tmp_path / "new"
    source.mkdir()
    (source / "BlueLCMS").write_text("new")
    destination = tmp_path / "installed"
    destination.mkdir()
    (destination / "BlueLCMS").write_text("old")
    original = Path.rename
    def rename(path, target):
        if path.parent.name.startswith(".BlueLCMS-update-") and path.name == "installed":
            raise OSError("simulated installation failure")
        return original(path, target)
    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(OSError, match="simulated"):
        package_updater.replace_application(source, destination)
    assert (destination / "BlueLCMS").read_text() == "old"
