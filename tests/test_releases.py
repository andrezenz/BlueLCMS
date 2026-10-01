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
    monkeypatch.setattr(releases, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    assert releases.latest_release() is None
