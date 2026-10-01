"""Read public BlueLCMS releases without requiring a local Git checkout."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RELEASES_URL = "https://api.github.com/repos/andrezenz/BlueLCMS/releases/latest"
DEVELOPMENT_RELEASE_URL = "https://api.github.com/repos/andrezenz/BlueLCMS/releases/tags/dev-latest"


class ReleaseError(RuntimeError):
    pass


def release(channel="stable") -> dict[str, object] | None:
    url = RELEASES_URL if channel == "stable" else DEVELOPMENT_RELEASE_URL
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
