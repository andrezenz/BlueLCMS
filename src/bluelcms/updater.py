"""Safe Git-based updates for the official BlueLCMS checkout."""

from pathlib import Path
import subprocess
import sys


OFFICIAL_ORIGINS = {
    "https://github.com/andrezenz/BlueLCMS.git",
    "git@github.com:andrezenz/BlueLCMS.git",
}
BRANCHES = ("dev", "stable")


class UpdateError(RuntimeError):
    pass


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True)
    if result.returncode:
        raise UpdateError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def validate_checkout(root: Path) -> None:
    origin = _run(root, "remote", "get-url", "origin")
    if origin not in OFFICIAL_ORIGINS:
        raise UpdateError("Updates are allowed only from the official BlueLCMS GitHub repository.")
    if _run(root, "status", "--porcelain"):
        raise UpdateError("Commit, stash, or discard local source changes before updating.")


def fetch(root: Path) -> None:
    validate_checkout(root)
    _run(root, "fetch", "--tags", "origin")


def releases(root: Path) -> list[str]:
    return [tag for tag in _run(root, "tag", "--list", "v*", "--sort=-version:refname").splitlines() if tag]


def status(root: Path, fetch_remote: bool = False) -> dict:
    if fetch_remote:
        fetch(root)
    validate_checkout(root)
    return {
        "branch": _run(root, "branch", "--show-current") or "detached",
        "commit": _run(root, "rev-parse", "--short", "HEAD"),
        "releases": releases(root),
    }


def update(root: Path, target: str) -> dict:
    fetch(root)
    if target in BRANCHES:
        _run(root, "switch", target)
        _run(root, "merge", "--ff-only", f"origin/{target}")
    elif target in releases(root):
        _run(root, "switch", "--detach", target)
    else:
        raise UpdateError(f"Unknown update target: {target}")
    python = root / ".venv" / "bin" / "python"
    result = subprocess.run([str(python), "-m", "pip", "install", "--editable", str(root)], cwd=root, text=True, capture_output=True)
    if result.returncode:
        raise UpdateError(f"Updated source, but dependency installation failed:\n{result.stderr.strip()}")
    return status(root)
