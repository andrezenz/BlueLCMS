"""Report the immutable package version or the current source revision."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import subprocess
import tomllib


def version_from_tag(tag):
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)(?:-dev\.(\d+))?", tag)
    if match is None:
        return None
    return match[1] + (f".dev{match[2]}" if match[2] is not None else "")


def source_version(root):
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    try:
        result = subprocess.run(["git", "tag", "--points-at", "HEAD", "--sort=-version:refname"], cwd=root, capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            versions = [exact for tag in result.stdout.splitlines() if (exact := version_from_tag(tag))]
            if versions:
                def order(value):
                    base, separator, number = value.partition(".dev")
                    return (*map(int, base.split(".")), not bool(separator), int(number or 0))
                return max(versions, key=order)
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return f"{declared}+g{result.stdout.strip()}"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return declared


def application_version():
    try:
        from ._build_version import VERSION
    except ImportError:
        root = Path(__file__).resolve().parents[2]
        if (root / "pyproject.toml").is_file():
            return source_version(root)
        try:
            return version("bluelcms")
        except PackageNotFoundError:
            return "unknown"
    return VERSION
