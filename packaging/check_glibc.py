"""Reject Linux release bundles requiring a newer glibc than the build host."""

from pathlib import Path
import re
import subprocess
import sys


def glibc_requirements(path):
    result = subprocess.run(["readelf", "--version-info", str(path)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Cannot inspect ELF dependency {path}: {result.stderr.strip()}")
    # Restrict to version-needs entries, avoiding symbol definitions/exported
    # versions that do not express dependencies on the host runtime.
    needs = result.stdout.partition("Version needs section")[2]
    return {tuple(map(int, value.split("."))) for value in re.findall(r"Name: GLIBC_(\d+(?:\.\d+)+)", needs)}


def check_bundle(root, maximum):
    offenders = []
    for path in Path(root).rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as file:
            if file.read(4) != b"\x7fELF":
                continue
        versions = glibc_requirements(path)
        if versions and max(versions) > maximum:
            offenders.append((path, max(versions)))
    return offenders


if __name__ == "__main__":
    root = Path(sys.argv[1])
    maximum = tuple(map(int, sys.argv[2].split(".")))
    offenders = check_bundle(root, maximum)
    for path, version in offenders:
        print(f"{path}: requires GLIBC_{'.'.join(map(str, version))}", file=sys.stderr)
    if offenders:
        raise SystemExit(f"Bundle exceeds supported GLIBC_{sys.argv[2]} baseline")
    print(f"All ELF dependencies require GLIBC_{sys.argv[2]} or older.")
