"""Website-distributed bootstrap installer for BlueLCMS release assets."""

import sys
import tempfile
from pathlib import Path
from urllib.request import urlretrieve

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from . import releases


ASSET_NAMES = {
    "linux": "BlueLCMS-linux-x86_64.tar.gz",
    "darwin": "BlueLCMS-macos.dmg",
    "win32": "BlueLCMS-windows-setup.exe",
}


def platform_asset(release: dict[str, object]) -> tuple[str, str] | None:
    name = ASSET_NAMES.get(sys.platform)
    if not name:
        return None
    for asset in release["assets"]:
        if asset.get("name") == name and isinstance(asset.get("browser_download_url"), str):
            return name, asset["browser_download_url"]
    return None


def install(channel: str) -> str:
    release = releases.release(channel)
    if not release:
        raise RuntimeError(f"No {channel} release is available from GitHub.")
    asset = platform_asset(release)
    if not asset:
        raise RuntimeError(f"The {release['tag']} release has no installer for this platform.")
    directory = Path(tempfile.mkdtemp(prefix="BlueLCMS-"))
    target = directory / asset[0]
    urlretrieve(asset[1], target)
    if sys.platform == "win32":
        if not QProcess.startDetached(str(target)):
            raise RuntimeError("The Windows installer could not be started.")
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
    return str(release["tag"])


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("BlueLCMS Installer")
    channel, accepted = QInputDialog.getItem(None, "Install BlueLCMS", "Release channel:", ("stable", "development"), 0, False)
    if not accepted:
        return 0
    try:
        tag = install(channel)
    except Exception as error:
        QMessageBox.critical(None, "Installation failed", str(error))
        return 1
    QMessageBox.information(None, "BlueLCMS installer", f"Downloaded {tag}. Complete the platform installer that just opened.")
    return 0
