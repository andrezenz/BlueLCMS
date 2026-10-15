"""Install per-user Linux MIME and Nautilus thumbnailer registrations."""

import base64
import os
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys


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
    mime_digest = hashlib.sha256(mime_content).hexdigest()
    indexed = stamp.is_file() and stamp.read_text(encoding="ascii") == mime_digest
    changed = changed_mime or changed_thumbnailer or not indexed
    if changed:
        database = shutil.which("update-mime-database")
        if database:
            subprocess.run([database, str(data_home / "mime")], check=True, capture_output=True, text=True)
            stamp.write_text(mime_digest, encoding="ascii")
    return changed


def ensure_thumbnailer_registered():
    """Best-effort update-start migration; registration must not block launch."""
    if sys.platform != "linux":
        return None
    try:
        return register_thumbnailer()
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return error
