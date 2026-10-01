from pathlib import Path

import pytest

from bluelcms import updater


def test_validate_checkout_rejects_unknown_origin(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "_run", lambda root, *args: "https://example.test/not-bluelcms.git" if args[:3] == ("remote", "get-url", "origin") else "")
    with pytest.raises(updater.UpdateError, match="official"):
        updater.validate_checkout(tmp_path)


def test_update_fast_forwards_branch_and_reinstalls(monkeypatch, tmp_path):
    calls = []
    def fake_run(root, *args):
        calls.append(args)
        if args[:3] == ("remote", "get-url", "origin"):
            return "https://github.com/andrezenz/BlueLCMS.git"
        if args[:2] == ("branch", "--show-current"):
            return "dev"
        if args[:2] == ("rev-parse", "--short"):
            return "abc1234"
        if args[:2] == ("tag", "--list"):
            return "v0.4.2"
        return ""
    class Result:
        returncode = 0
        stderr = ""
    monkeypatch.setattr(updater, "_run", fake_run)
    monkeypatch.setattr(updater.subprocess, "run", lambda *args, **kwargs: Result())
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    result = updater.update(tmp_path, "dev")
    assert ("fetch", "--tags", "origin") in calls
    assert ("switch", "dev") in calls
    assert ("merge", "--ff-only", "origin/dev") in calls
    assert result["commit"] == "abc1234"


def test_update_rejects_unknown_target(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "fetch", lambda root: None)
    monkeypatch.setattr(updater, "releases", lambda root: [])
    with pytest.raises(updater.UpdateError, match="Unknown"):
        updater.update(tmp_path, "main")
