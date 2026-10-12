"""Read public BlueLCMS releases without requiring a local Git checkout."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RELEASES_URL = "https://api.github.com/repos/andrezenz/BlueLCMS/releases/latest"
DEVELOPMENT_RELEASE_URL = "https://api.github.com/repos/andrezenz/BlueLCMS/releases/tags/dev-latest"


class ReleaseError(RuntimeError):
    pass


def release(channel="stable", tag=None) -> dict[str, object] | None:
    from urllib.parse import quote
    url = f"https://api.github.com/repos/andrezenz/BlueLCMS/releases/tags/{quote(tag, safe='')}" if tag else RELEASES_URL if channel == "stable" else DEVELOPMENT_RELEASE_URL
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "BlueLCMS"})
    try:
        with urlopen(request, timeout=5) as response:
            release = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise ReleaseError(f"GitHub Releases returned HTTP {error.code}.") from error
    except URLError as error:
        raise ReleaseError(f"GitHub Releases could not be reached: {error.reason}") from error
    tag = release.get("tag_name")
    page = release.get("html_url")
    assets = release.get("assets")
    return {"tag": tag, "url": page, "assets": assets} if isinstance(tag, str) and isinstance(page, str) and isinstance(assets, list) else None


def latest_release() -> dict[str, object] | None:
    return release()


def published_versions() -> dict[str, str]:
    """Return published release labels mapped to their Git tags."""
    versions = {}
    page = 1
    while True:
        request = Request(
            f"https://api.github.com/repos/andrezenz/BlueLCMS/releases?per_page=100&page={page}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "BlueLCMS"})
        try:
            with urlopen(request, timeout=10) as response:
                entries = json.load(response)
        except (HTTPError, URLError) as error:
            raise ReleaseError(f"GitHub releases could not be loaded: {error}") from error
        for entry in entries:
            tag = entry.get("tag_name")
            if entry.get("draft") or not isinstance(tag, str):
                continue
            name = entry.get("name") or tag
            label = name if name == tag else f"{name} ({tag})"
            if entry.get("prerelease"):
                label += " — prerelease"
            versions[label] = f"refs/tags/{tag}"
        if len(entries) < 100:
            return versions
        page += 1
