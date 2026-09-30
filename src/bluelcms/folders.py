"""Filesystem entry points for desktop-mounted remote shares on Linux."""

import os
from pathlib import Path


def remote_mount_roots() -> list[Path]:
    """Locate GVFS's FUSE bridge, including the legacy home mount location.

    AFP authentication and mounting remain managed by the desktop file manager.
    Once mounted, these paths are ordinary files to the mzML reader.
    """
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    candidates = [runtime / "gvfs", Path.home() / ".gvfs"]
    return [path for path in candidates if path.is_dir()]
