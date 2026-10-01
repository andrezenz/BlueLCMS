"""Read public BlueLCMS releases without requiring a local Git checkout."""

import json
from urllib.request import Request, urlopen


RELEASES_URL = "https://api.github.com/repos/andrezenz/BlueLCMS/releases/latest"


def latest_release() -> dict[str, str] | None:
    request = Request(RELEASES_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "BlueLCMS"})
    try:
        with urlopen(request, timeout=5) as response:
            release = json.load(response)
    except OSError:
        return None
    tag = release.get("tag_name")
    url = release.get("html_url")
    return {"tag": tag, "url": url} if isinstance(tag, str) and isinstance(url, str) else None
