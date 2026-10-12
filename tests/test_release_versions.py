import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from bluelcms import version as app_version


spec = importlib.util.spec_from_file_location("release_version", Path(__file__).parents[1] / "packaging/release_version.py")
release_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_version)


def test_development_number_advances_past_existing_tags(monkeypatch):
    monkeypatch.setattr(release_version, "remote_tags", lambda: {"v1.0.2-dev.2": "old", "v1.0.2-dev.10": "other", "v1.0.1": "stable"})
    created = []
    monkeypatch.setattr(release_version, "reserve_tag", lambda repository, tag, sha: created.append((tag, sha)) or True)
    assert release_version.allocate_development_tag("1.0.2.dev2", "new", "owner/repo") == "v1.0.2-dev.11"
    assert created == [("v1.0.2-dev.11", "new")]


def test_first_number_honors_declared_development_version(monkeypatch):
    monkeypatch.setattr(release_version, "remote_tags", lambda: {})
    monkeypatch.setattr(release_version, "reserve_tag", lambda *args: True)
    assert release_version.allocate_development_tag("1.0.2.dev2", "new", "owner/repo") == "v1.0.2-dev.2"


def test_rerun_reuses_tag_for_same_commit(monkeypatch):
    monkeypatch.setattr(release_version, "remote_tags", lambda: {"v1.0.2-dev.3": "same"})
    monkeypatch.setattr(release_version, "reserve_tag", lambda *args: pytest.fail("A rerun must not allocate a new tag"))
    assert release_version.allocate_development_tag("1.0.2.dev2", "same", "owner/repo") == "v1.0.2-dev.3"


def test_concurrent_allocation_retries_without_moving_tag(monkeypatch):
    tags = {}
    attempts = []
    monkeypatch.setattr(release_version, "remote_tags", lambda: dict(tags))
    def reserve(repository, tag, sha):
        attempts.append(tag)
        if len(attempts) == 1:
            tags[tag] = "competing commit"
            return False
        tags[tag] = sha
        return True
    monkeypatch.setattr(release_version, "reserve_tag", reserve)
    assert release_version.allocate_development_tag("1.0.2.dev2", "new", "owner/repo") == "v1.0.2-dev.3"
    assert tags["v1.0.2-dev.2"] == "competing commit"


def test_release_tags_classify_stable_and_development():
    assert release_version.version_for_tag("v1.0.2") == ("1.0.2", False)
    assert release_version.version_for_tag("v1.0.2-dev.3") == ("1.0.2.dev3", True)
    with pytest.raises(ValueError):
        release_version.version_for_tag("dev-latest")


def test_stamped_package_and_project_report_same_version(tmp_path):
    (tmp_path / "src/bluelcms").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.2.dev2"\n')
    release_version.stamp(tmp_path, "1.0.2.dev7")
    assert 'version = "1.0.2.dev7"' in (tmp_path / "pyproject.toml").read_text()
    assert (tmp_path / "src/bluelcms/_build_version.py").read_text() == 'VERSION = "1.0.2.dev7"\n'


def test_source_reports_numbered_tag_or_commit_identity(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.2.dev2"\n')
    def git(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="dev-latest\nv1.0.2-dev.7\n")
    monkeypatch.setattr(app_version.subprocess, "run", git)
    assert app_version.source_version(tmp_path) == "1.0.2.dev7"
    def untagged(args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="dev-latest\n" if "tag" in args else "abc123\n")
    monkeypatch.setattr(app_version.subprocess, "run", untagged)
    assert app_version.source_version(tmp_path) == "1.0.2.dev2+gabc123"


def test_stable_tag_takes_precedence_when_commit_is_promoted(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.2.dev2"\n')
    monkeypatch.setattr(app_version.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="v1.0.2-dev.7\nv1.0.2\n"))
    assert app_version.source_version(tmp_path) == "1.0.2"
