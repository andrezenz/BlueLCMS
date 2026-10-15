"""Install per-user Linux MIME and Nautilus thumbnailer registrations."""

import base64
import os
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from urllib.parse import unquote, urlparse


def integration_assets():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    if getattr(sys, "frozen", False):
        return root / "bluelcms-thumbnailer.py", root / "bluelcms-mime.xml"
    assets = root / "packaging" / "linux"
    return assets / "bluelcms-thumbnailer.py", assets / "bluelcms-mime.xml"


def _atomic_write(path: Path, content: bytes) -> bool:
    if path.is_file() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def clear_cached_thumbnail_failures(cache_home: Path | None = None) -> int:
    """Remove GNOME's negative-cache records for BlueLCMS-supported inputs."""
    cache_home = cache_home or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    failures = cache_home / "thumbnails/fail"
    removed = 0
    for directory in failures.iterdir() if failures.is_dir() else ():
        if not directory.is_dir() or directory.name != "gnome-thumbnail-factory":
            continue
        for path in directory.glob("*.png"):
            try:
                data = path.read_bytes()
                offset, uri = 8, None
                while offset + 12 <= len(data):
                    length = struct.unpack_from(">I", data, offset)[0]
                    kind = data[offset + 4:offset + 8]
                    end = offset + 12 + length
                    if end > len(data):
                        break
                    if kind == b"tEXt":
                        field = data[offset + 8:offset + 8 + length]
                        key, separator, value = field.partition(b"\0")
                        if separator and key == b"Thumb::URI":
                            uri = value.decode("utf-8", errors="replace")
                            break
                    offset = end
                    if kind == b"IEND":
                        break
                source = unquote(urlparse(uri).path).lower() if uri else ""
                if source.endswith((".mzml", ".mzml.gz", ".bluelcms.npz")):
                    path.unlink()
                    removed += 1
            except OSError:
                continue
    return removed


def register_thumbnailer(data_home: Path | None = None, assets=None) -> bool:
    """Register the user-level MIME thumbnailer; return whether files changed."""
    data_home = data_home or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    helper, mime = assets or integration_assets()
    helper_code = helper.read_bytes()
    mime_content = mime.read_bytes()
    encoded = base64.b64encode(helper_code).decode("ascii")
    thumbnailer = (
        "[Thumbnailer Entry]\n"
        "TryExec=/usr/bin/python3\n"
        f"Exec=/usr/bin/python3 -c \"import base64;exec(compile(base64.b64decode('{encoded}'),'<bluelcms-thumbnailer>','exec'))\" %s %i %o\n"
        "MimeType=application/x-bluelcms-cache;application/x-bluelcms-mzml;application/x-bluelcms-mzml-gzip;\n"
    ).encode("utf-8")
    changed_mime = _atomic_write(data_home / "mime/packages/bluelcms.xml", mime_content)
    changed_thumbnailer = _atomic_write(data_home / "thumbnailers/bluelcms.thumbnailer", thumbnailer)
    stamp = data_home / "mime/packages/bluelcms.thumbnailer-stamp"
    # Bump this token when thumbnailer behavior changes so migration also clears
    # GNOME's negative-cache records from a previous, failing thumbnailer.
    mime_digest = hashlib.sha256(b"bluelcms-thumbnailer-migration-v2\0" + mime_content + helper_code).hexdigest()
    indexed = stamp.is_file() and stamp.read_text(encoding="ascii") == mime_digest
    changed = changed_mime or changed_thumbnailer or not indexed
    if changed:
        database = shutil.which("update-mime-database")
        if database:
            subprocess.run([database, str(data_home / "mime")], check=True, capture_output=True, text=True)
            stamp.write_text(mime_digest, encoding="ascii")
            clear_cached_thumbnail_failures()
    return changed


def ensure_thumbnailer_registered():
    """Best-effort update-start migration; registration must not block launch."""
    if sys.platform != "linux":
        return None
    try:
        return register_thumbnailer()
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return error
