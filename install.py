#!/usr/bin/env python3
"""Install BlueLCMS's local environment and per-user Linux desktop shortcut."""

import os
from pathlib import Path
import subprocess
import sys
import venv


def desktop_argument(value: str) -> str:
    """Quote an Exec argument through both desktop-entry escaping layers."""
    if "\n" in value or "\r" in value:
        raise ValueError("Desktop launcher paths cannot contain newlines")
    for character in ("\\", '"', "`", "$"):
        value = value.replace(character, "\\" + character)
    return '"' + value.replace("\\", "\\\\").replace("%", "%%") + '"'


def desktop_entry(root: Path) -> str:
    python = desktop_argument(str(root / ".venv" / "bin" / "python"))
    launcher = desktop_argument(str(root / "launch.py"))
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=⌊Blue⌋ LCMS\n"
        "Comment=LC-MS and DAD viewer — current local checkout\n"
        f"Exec={python} {launcher}\n"
        "Icon=applications-science\n"
        "Terminal=false\n"
        "Categories=Science;\n"
        "StartupNotify=false\n"
    )


def main() -> int:
    if not sys.platform.startswith("linux"):
        print("This desktop installer requires Linux.", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parent
    python = root / ".venv" / "bin" / "python"
    try:
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(root / ".venv")
        subprocess.run([str(python), "-m", "pip", "install", "--editable", str(root)], check=True)
        data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        if not data_home.is_absolute():
            raise ValueError("XDG_DATA_HOME must be an absolute path")
        applications = data_home / "applications"
        applications.mkdir(parents=True, exist_ok=True)
        target = applications / "bluelcms.desktop"
        target.write_text(desktop_entry(root), encoding="utf-8")
        target.chmod(0o644)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Installation failed: {error}", file=sys.stderr)
        return 1
    print(f"Installed {target}")
    print(f"⌊Blue⌋ LCMS will run the current local code in {root}")
    print("Open ⌊Blue⌋ LCMS from your application menu. Rerun this installer after moving the checkout or changing dependencies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
