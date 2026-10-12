import io
from pathlib import Path
import tarfile

import pytest

from bluelcms import package_updater


def prepare_release(monkeypatch, tmp_path, members):
    installed = tmp_path / "installed" / "BlueLCMS"
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
        "BlueLCMS/BlueLCMS": b"new version", "BlueLCMS/_internal/library": b"bundled dependency"})
    result = package_updater.install("refs/tags/v1.0.1")
    assert result == {"version": "v1.0.1", "executable": str(executable)}
    assert executable.read_text() == "new version"
    assert (executable.parent / "_internal" / "library").read_text() == "bundled dependency"
    assert executable.stat().st_mode & 0o111


def test_malformed_package_preserves_installed_app(monkeypatch, tmp_path):
    executable = prepare_release(monkeypatch, tmp_path, {"unexpected": b"invalid package"})
    with pytest.raises(RuntimeError, match="missing its executable"):
        package_updater.install("refs/tags/v1.0.1")
    assert executable.read_text() == "old version"


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
