"""Install published application packages without Git or a Python environment."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlretrieve

from . import releases
from .bootstrap import platform_asset


def replace_application(source: Path, destination: Path) -> None:
    """Stage a complete application before replacing the installed directory."""
    if not source.is_dir():
        raise RuntimeError("The downloaded package contains no BlueLCMS application.")
    staging = Path(tempfile.mkdtemp(prefix=".BlueLCMS-update-", dir=destination.parent))
    new = staging / destination.name
    backup = staging / "previous"
    try:
        shutil.copytree(source, new, symlinks=True)
        if destination.exists():
            destination.rename(backup)
        try:
            new.rename(destination)
        except OSError:
            if backup.exists():
                backup.rename(destination)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def install(target: str) -> dict:
    tag = target.removeprefix("refs/tags/")
    release = releases.release(tag=tag)
    if not release:
        raise RuntimeError(f"GitHub release {tag} is unavailable.")
    asset = platform_asset(release)
    if not asset:
        raise RuntimeError(f"Release {tag} has no application package for this platform.")
    directory = Path(tempfile.mkdtemp(prefix="BlueLCMS-update-"))
    download = directory / asset[0]
    try:
        urlretrieve(asset[1], download)
        executable = Path(sys.executable).resolve()
        if sys.platform == "linux":
            extracted = directory / "extracted"
            extracted.mkdir()
            with tarfile.open(download) as archive:
                archive.extractall(extracted, filter="data")
            application = extracted / "BlueLCMS"
            if not (application / "BlueLCMS").is_file():
                raise RuntimeError("The Linux package is missing its executable.")
            replace_application(application, executable.parent)
            return {"version": tag, "executable": str(executable)}
        if sys.platform == "darwin":
            bundle = next((parent for parent in executable.parents if parent.suffix == ".app"), None)
            if bundle is None:
                raise RuntimeError("Run BlueLCMS from its installed .app bundle before updating.")
            mount = directory / "mounted"
            mount.mkdir()
            subprocess.run(["hdiutil", "attach", str(download), "-mountpoint", str(mount), "-nobrowse", "-quiet"], check=True)
            try:
                application = next(mount.glob("*.app"), None)
                if application is None:
                    raise RuntimeError("The macOS package contains no application bundle.")
                replace_application(application, bundle)
            finally:
                subprocess.run(["hdiutil", "detach", str(mount), "-quiet"], check=True)
            return {"version": tag, "executable": str(executable)}
        if sys.platform == "win32":
            # Windows locks the running executable. A separate helper installs
            # after this process exits, then asks whether to start the new app.
            def quoted(value):
                return "'" + str(value).replace("'", "''") + "'"
            script = directory / "install.ps1"
            install_directory = '/DIR="' + str(executable.parent) + '"'
            script.write_text(
                f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue\n"
                f"$p = Start-Process -FilePath {quoted(download)} -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', {quoted(install_directory)}) -Wait -PassThru\n"
                "Add-Type -AssemblyName PresentationFramework\n"
                "if ($p.ExitCode -ne 0) { [System.Windows.MessageBox]::Show('BlueLCMS installation failed. Run the downloaded installer manually.', 'Update failed'); exit 1 }\n"
                "if ([System.Windows.MessageBox]::Show('Update installed. Restart BlueLCMS now?', 'Update complete', 'YesNo') -eq 'Yes') {\n"
                f"Start-Process -FilePath {quoted(executable)}\n"
                "}\n", encoding="utf-8")
            return {"version": tag, "helper": str(script), "executable": str(executable)}
        raise RuntimeError("This platform is not supported by the updater.")
    finally:
        if sys.platform != "win32":
            shutil.rmtree(directory, ignore_errors=True)
