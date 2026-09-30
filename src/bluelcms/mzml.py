"""Qt-independent mzML loading and intensity-weighted MS1 aggregation."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pyteomics.mzml import MzML


@dataclass(frozen=True)
class Scan:
    time: float  # minutes
    polarity: str
    mz: np.ndarray
    intensity: np.ndarray


@dataclass(frozen=True)
class Run:
    times: np.ndarray
    uv: np.ndarray
    wavelengths: np.ndarray
    scans: tuple[Scan, ...]
    skipped_scans: int = 0


def discover_files(folder: Path) -> list[Path]:
    """List files directly in the selected directory, ignoring extension case."""
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mzml"),
        key=lambda p: (p.name.casefold(), p.name),
    )


def retention_time(spectrum: dict) -> float | None:
    scans = spectrum.get("scanList", {}).get("scan", [])
    if not scans or "scan start time" not in scans[0]:
        return None
    value = scans[0]["scan start time"]
    unit = str(getattr(value, "unit_info", "minute")).lower()
    factors = {"minute": 1, "second": 1 / 60, "millisecond": 1 / 60000, "hour": 60}
    if unit not in factors:
        return None
    time = float(value) * factors[unit]
    return time if np.isfinite(time) else None


def paired_arrays(record: dict, axis: str) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(record.get(axis, []), dtype=float)
    y = np.asarray(record.get("intensity array", []), dtype=float)
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
        raise ValueError(f"Invalid {axis} / intensity arrays in {record.get('id', 'spectrum')}")
    valid = np.isfinite(x) & np.isfinite(y)
    return x[valid], y[valid]


def parse_spectra(spectra, wavelength: float = 254.0) -> Run:
    uv_points = []
    scans = []
    skipped = 0
    for spectrum in spectra:
        time = retention_time(spectrum)
        if "wavelength array" in spectrum:
            if time is None:
                continue
            axis, intensity = paired_arrays(spectrum, "wavelength array")
            # mzML wavelength arrays use nanometers (MS:1000617).
            if len(axis) and axis.min() <= wavelength <= axis.max():
                index = int(np.argmin(np.abs(axis - wavelength)))
                uv_points.append((time, intensity[index], axis[index]))
        elif int(spectrum.get("ms level", 0)) == 1:
            positive = "positive scan" in spectrum
            negative = "negative scan" in spectrum
            if time is None or positive == negative:
                skipped += 1
                continue
            mz, intensity = paired_arrays(spectrum, "m/z array")
            valid = (mz > 0) & (intensity >= 0)
            scans.append(Scan(time, "+" if positive else "-", mz[valid], intensity[valid]))
    uv_points.sort(key=lambda point: point[0])
    values = np.asarray(uv_points, dtype=float).reshape(-1, 3)
    return Run(values[:, 0], values[:, 1], values[:, 2], tuple(scans), skipped)


def load_run(path: Path, wavelength: float = 254.0) -> Run:
    # Streaming avoids retaining the mzML XML tree; decoded MS1 arrays are cached
    # in the active Run for repeated time-region selection.
    with MzML(str(path), use_index=False) as reader:
        return parse_spectra(reader, wavelength)


def mass_histograms(run: Run, start: float, end: float, bin_width: float = 0.1):
    """Sum MS1 intensities in fixed, zero-aligned m/z bins (inclusive times).

    Return only occupied bins to avoid allocating a huge dense histogram.
    Unknown polarity spectra are excluded by the reader, never guessed.
    """
    if not np.isfinite(bin_width) or bin_width <= 0:
        raise ValueError("Bin width must be finite and positive")
    start, end = sorted((start, end))
    result = {}
    for polarity in ("+", "-"):
        selected = [s for s in run.scans if s.polarity == polarity and start <= s.time <= end]
        if not selected:
            result[polarity] = (np.array([]), np.array([]))
            continue
        mz = np.concatenate([s.mz for s in selected])
        intensity = np.concatenate([s.intensity for s in selected])
        bins, inverse = np.unique(np.floor(mz / bin_width), return_inverse=True)
        result[polarity] = ((bins + 0.5) * bin_width, np.bincount(inverse, weights=intensity))
    return result
