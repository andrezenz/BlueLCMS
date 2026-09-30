"""Filesystem entry points for desktop-mounted remote shares on Linux."""

import os
import hashlib
from pathlib import Path
import shutil


def remote_mount_roots() -> list[Path]:
    """Locate GVFS's FUSE bridge, including the legacy home mount location.

    AFP authentication and mounting remain managed by the desktop file manager.
    Once mounted, these paths are ordinary files to the mzML reader.
    """
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    candidates = [runtime / "gvfs", Path.home() / ".gvfs"]
    return [path for path in candidates if path.is_dir()]


def is_afp_path(path: Path) -> bool:
    """True only for a GVFS AFP volume, not arbitrary network-like paths."""
    return any(part.startswith("afp-volume:") for part in path.parts)


def cached_path(source: Path, cache_folder: Path | None) -> Path | None:
    if cache_folder is None or not is_afp_path(source):
        return None
    identity = hashlib.sha256(str(source).encode()).hexdigest()[:16]
    return cache_folder / f"{source.stem}-{identity}{source.suffix}"


def copy_to_cache(source: Path, cache: Path) -> Path:
    """Copy a complete remote file atomically; incomplete copies are invisible."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_name(f".{cache.name}.part")
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(cache)
    finally:
        temporary.unlink(missing_ok=True)
    return cache
