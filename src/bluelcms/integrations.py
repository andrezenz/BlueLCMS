"""Manual UV integration calculations and immutable-mzML sidecar storage."""

import json
import os
from pathlib import Path
import tempfile

import numpy as np


def baseline_curve(times, signal, start, stop, method="midpoint", baseline_start=None, baseline_end=None):
    """Interpolate limits and construct a horizontal, endpoint, zero or manual baseline."""
    times, signal = np.asarray(times, dtype=float), np.asarray(signal, dtype=float)
    if (times.ndim != 1 or signal.ndim != 1 or len(times) < 2 or len(times) != len(signal)
            or not np.isfinite(times).all() or not np.isfinite(signal).all()
            or not np.all(np.diff(times) > 0)):
        raise ValueError("Integration requires finite signals and strictly increasing times")
    start, stop = float(start), float(stop)
    if not np.isfinite([start, stop]).all() or not times[0] <= start < stop <= times[-1]:
        raise ValueError("Integration interval is outside the UV trace or empty")
    x = np.r_[start, times[(times > start) & (times < stop)], stop]
    y = np.interp(x, times, signal)
    if method == "midpoint":
        base = np.full(len(x), (y[0] + y[-1]) / 2)
    elif method == "endpoints":
        base = y[0] + (y[-1] - y[0]) * (x - start) / (stop - start)
    elif method == "zero":
        base = np.zeros(len(x))
    elif method == "manual":
        if baseline_start is None or baseline_end is None or not np.isfinite([baseline_start, baseline_end]).all():
            raise ValueError("Manual baseline requires two finite endpoint heights")
        base = baseline_start + (baseline_end - baseline_start) * (x - start) / (stop - start)
    else:
        raise ValueError("Unknown baseline method")
    return x, y, base


def integrate_trace(times, signal, start: float, stop: float, baseline="zero", baseline_start=None, baseline_end=None) -> float:
    """Integrate a selected UV interval in recorded units times minutes."""
    start, stop = sorted((float(start), float(stop)))
    times, signal = np.asarray(times, dtype=float), np.asarray(signal, dtype=float)
    if len(times) < 2 or len(times) != len(signal) or start == stop:
        raise ValueError("Integration requires a non-empty interval on a UV trace")
    order = np.argsort(times)
    times, signal = times[order], signal[order]
    if start < times[0] or stop > times[-1]:
        raise ValueError("Integration interval is outside the UV trace")
    x, y, base = baseline_curve(times, signal, start, stop, baseline, baseline_start, baseline_end)
    return abs(float(np.trapezoid(y - base, x)))


def source_fingerprint(source: Path) -> dict:
    if (source.suffix.lower() == ".aia" and source.is_dir()) or (source.suffix.lower() == ".cdf" and source.is_file()):
        from .aia import aia_fingerprint
        return aia_fingerprint(source)
    try:
        stat = source.stat()
    except OSError:
        return {"path": str(source)}
    return {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def fallback_sidecar(source: Path, fallback_folder: Path) -> Path:
    import hashlib
    identity = hashlib.sha256(str(source).encode()).hexdigest()[:16]
    return fallback_folder / f"{source.stem}-{identity}.bluelcms-integrations.json"


def source_sidecar(source: Path) -> Path:
    return source.with_suffix(source.suffix + ".bluelcms-integrations.json")


def sidecar_candidates(source: Path, fallback_folder: Path, beside_source: bool = True) -> tuple[Path, ...]:
    """Candidate sidecar locations; read-only vendor folders store only locally."""
    fallback = fallback_sidecar(source, fallback_folder)
    return (source_sidecar(source), fallback) if beside_source else (fallback,)


def load_integrations(source: Path, fallback_folder: Path, beside_source: bool = True, fingerprint=None) -> tuple[list[dict], Path | None, bool]:
    """Load matching records and report whether a found sidecar is stale."""
    fingerprint = fingerprint if fingerprint is not None else source_fingerprint(source)
    for path in sidecar_candidates(source, fallback_folder, beside_source):
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


def save_integrations(source: Path, fallback_folder: Path, integrations: list[dict], beside_source: bool = True, fingerprint=None) -> Path:
    """Save beside a writable raw file, otherwise atomically fall back locally."""
    data = {"format": 1, "source": fingerprint if fingerprint is not None else source_fingerprint(source), "integrations": integrations}
    for path in sidecar_candidates(source, fallback_folder, beside_source):
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
