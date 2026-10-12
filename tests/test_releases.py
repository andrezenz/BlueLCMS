import json

from bluelcms import releases


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.payload).encode()


def test_latest_release_reads_github_payload(monkeypatch):
    monkeypatch.setattr(releases, "urlopen", lambda *args, **kwargs: Response({"tag_name": "v0.4.4", "html_url": "https://example.test/release", "assets": []}))
    assert releases.latest_release() == {"tag": "v0.4.4", "url": "https://example.test/release", "assets": []}


def test_latest_release_handles_network_failure(monkeypatch):
    monkeypatch.setattr(releases, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(releases.URLError("offline")))
    try:
        releases.latest_release()
    except releases.ReleaseError as error:
        assert "offline" in str(error)
    else:
        raise AssertionError("network failures must be reported")


def test_only_newer_stable_versions_trigger_alerts():
    assert releases.newer_stable_version("v1.0.10", "1.0.2")
    assert not releases.newer_stable_version("v1.0.1", "1.0.1")
    assert not releases.newer_stable_version("v1.0.0", "1.0.1")
    assert releases.newer_stable_version("v1.1.0", "1.1.0-dev.1")
    assert releases.newer_stable_version("v1.0.2", "1.0.2.dev1")
    assert releases.newer_stable_version("v1.0.2", "1.0.2.dev2+gabc123")
    assert not releases.newer_stable_version("dev-latest", "1.0.1")
