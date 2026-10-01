from bluelcms import bootstrap


def test_platform_asset_selects_matching_download(monkeypatch):
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    release = {"assets": [{"name": "BlueLCMS-windows-setup.exe", "browser_download_url": "https://example.test/setup.exe"}]}
    assert bootstrap.platform_asset(release) == ("BlueLCMS-windows-setup.exe", "https://example.test/setup.exe")


def test_platform_asset_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")
    assert bootstrap.platform_asset({"assets": []}) is None
