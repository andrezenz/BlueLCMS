"""Filesystem entry points for desktop-mounted remote shares on Linux."""

import os
import time
import hashlib
from pathlib import Path


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
    return cache_folder / f"{source.stem}-{identity}.bluelcms.npz"


def copy_to_cache(source: Path, cache: Path, progress=None) -> Path:
    """Copy a complete remote file atomically; incomplete copies are invisible."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_name(f".{cache.name}.part")
    total = source.stat().st_size
    copied = 0
    try:
        with source.open("rb") as input_file, temporary.open("wb") as output_file:
            while chunk := input_file.read(1024 * 1024):
                output_file.write(chunk)
                copied += len(chunk)
                if progress:
                    progress(copied, total)
        temporary.replace(cache)
    finally:
        temporary.unlink(missing_ok=True)
    return cache


def cleanup_expired_cache(cache_folder: Path | None, expiry_days: int) -> int:
    """Remove cache files older than expiry_days. Returns count of removed files."""
    if cache_folder is None or expiry_days <= 0:
        return 0
    if not cache_folder.is_dir():
        return 0
    cutoff = time.time() - (expiry_days * 86400)
    removed = 0
    for item in cache_folder.iterdir():
        if item.is_file() and not item.name.startswith("."):
            try:
                if item.stat().st_mtime < cutoff:
                    item.unlink()
                    removed += 1
            except OSError:
                pass
    return removed
