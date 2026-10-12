"""Allocate immutable numbered dev tags and stamp a release build's version."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import tomllib


VERSION = re.compile(r"^(\d+\.\d+\.\d+)(?:\.dev(\d+))?$")
TAG = re.compile(r"^v(\d+\.\d+\.\d+)(?:-dev\.(\d+))?$")


def remote_tags():
    result = subprocess.run(["git", "ls-remote", "--tags", "origin"], check=True, capture_output=True, text=True)
    tags = {}
    for line in result.stdout.splitlines():
        sha, ref = line.split("\t", 1)
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            tags[name[:-3]] = sha
        else:
            tags.setdefault(name, sha)
    return tags


def reserve_tag(repository, tag, sha):
    result = subprocess.run([
        "gh", "api", "--method", "POST", f"repos/{repository}/git/refs",
        "-f", f"ref=refs/tags/{tag}", "-f", f"sha={sha}"], capture_output=True, text=True)
    if result.returncode and "422" in result.stderr:
        return False
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Could not create the development tag.")
    return True


def allocate_development_tag(declared, sha, repository):
    match = VERSION.fullmatch(declared)
    if not match:
        raise ValueError(f"Unsupported project version: {declared}")
    base, minimum = match[1], int(match[2] or 0)
    for _ in range(10):
        tags = remote_tags()
        numbered = {tag: int(parsed[2]) for tag in tags
                    if (parsed := TAG.fullmatch(tag)) and parsed[1] == base and parsed[2] is not None}
        existing = [tag for tag in numbered if tags[tag] == sha]
        if existing:
            return max(existing, key=numbered.get)
        tag = f"v{base}-dev.{max([max(0, minimum - 1), *numbered.values()]) + 1}"
        if reserve_tag(repository, tag, sha):
            return tag
    raise RuntimeError("Development version allocation repeatedly collided; retry the workflow.")


def version_for_tag(tag):
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError(f"Unsupported release tag: {tag}")
    return match[1] + (f".dev{match[2]}" if match[2] is not None else ""), match[2] is not None


def stamp(root, version):
    if not VERSION.fullmatch(version):
        raise ValueError(f"Unsupported build version: {version}")
    project = root / "pyproject.toml"
    text, count = re.subn(r'(?m)^version = "[^"]+"$', f'version = "{version}"', project.read_text(), count=1)
    if count != 1:
        raise ValueError("Project version could not be stamped.")
    project.write_text(text)
    (root / "src/bluelcms/_build_version.py").write_text(f'VERSION = "{version}"\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stamp", help="Stamp a matrix build with an allocated version")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if arguments.stamp:
        stamp(root, arguments.stamp)
        return
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    ref = os.environ["GITHUB_REF"]
    if ref == "refs/heads/dev":
        tag = allocate_development_tag(declared, os.environ["GITHUB_SHA"], os.environ["GITHUB_REPOSITORY"])
        version, prerelease = version_for_tag(tag)
    elif ref.startswith("refs/tags/"):
        tag = ref.removeprefix("refs/tags/")
        version, prerelease = version_for_tag(tag)
    else:
        version = declared
        tag = ""
        prerelease = ".dev" in version
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"tag={tag}\nversion={version}\nprerelease={str(prerelease).lower()}\n")


if __name__ == "__main__":
    main()
