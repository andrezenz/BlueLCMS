"""Manual UV integration calculations and immutable-mzML sidecar storage."""

import json
import os
from pathlib import Path
import tempfile

import numpy as np


def integrate_trace(times, signal, start: float, stop: float) -> float:
    """Integrate a selected UV interval in recorded units times minutes."""
    start, stop = sorted((float(start), float(stop)))
    times, signal = np.asarray(times, dtype=float), np.asarray(signal, dtype=float)
    if len(times) < 2 or len(times) != len(signal) or start == stop:
        raise ValueError("Integration requires a non-empty interval on a UV trace")
    order = np.argsort(times)
    times, signal = times[order], signal[order]
    if start < times[0] or stop > times[-1]:
        raise ValueError("Integration interval is outside the UV trace")
    inside = (times > start) & (times < stop)
    x = np.concatenate(([start], times[inside], [stop]))
    y = np.interp(x, times, signal)
    return abs(float(np.trapezoid(y, x)))


def source_fingerprint(source: Path) -> dict:
    stat = source.stat()
    return {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def fallback_sidecar(source: Path, fallback_folder: Path) -> Path:
    import hashlib
    identity = hashlib.sha256(str(source).encode()).hexdigest()[:16]
    return fallback_folder / f"{source.stem}-{identity}.bluelcms-integrations.json"


def source_sidecar(source: Path) -> Path:
    return source.with_suffix(source.suffix + ".bluelcms-integrations.json")


def sidecar_candidates(source: Path, fallback_folder: Path) -> tuple[Path, Path]:
    return source_sidecar(source), fallback_sidecar(source, fallback_folder)


def load_integrations(source: Path, fallback_folder: Path) -> tuple[list[dict], Path | None, bool]:
    """Load matching records and report whether a found sidecar is stale."""
    fingerprint = source_fingerprint(source)
    for path in sidecar_candidates(source, fallback_folder):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("source") != fingerprint:
            return [], path, True
        return list(data.get("integrations", [])), path, False
    return [], None, False


def save_integrations(source: Path, fallback_folder: Path, integrations: list[dict]) -> Path:
    """Save beside a writable raw file, otherwise atomically fall back locally."""
    data = {"format": 1, "source": source_fingerprint(source), "integrations": integrations}
    primary, fallback = sidecar_candidates(source, fallback_folder)
    for path in (primary, fallback):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(path, data)
            return path
        except OSError:
            continue
    raise OSError("Unable to write integration sidecar")


def _write_json(path: Path, data: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, sort_keys=True)
            file.write("\n")
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)
