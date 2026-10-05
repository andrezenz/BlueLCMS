"""Qt-independent mzML loading and intensity-weighted MS1 aggregation."""

from dataclasses import dataclass
import gzip
from pathlib import Path
import re

import numpy as np
from pyteomics.mzml import MzML


@dataclass(frozen=True)
class Scan:
    time: float  # minutes
    polarity: str
    mz: np.ndarray
    intensity: np.ndarray


@dataclass(frozen=True)
class DADScan:
    time: float
    wavelength: np.ndarray
    intensity: np.ndarray


@dataclass(frozen=True)
class Run:
    dad: tuple[DADScan, ...]
    scans: tuple[Scan, ...]
    skipped_scans: int = 0

    @property
    def times(self):
        return self.uv_trace(254)[0]

    @property
    def uv(self):
        return self.uv_trace(254)[1]

    @property
    def wavelengths(self):
        return self.uv_trace(254)[2]

    def uv_trace(self, target: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        points = []
        for scan in self.dad:
            if len(scan.wavelength) and scan.wavelength.min() <= target <= scan.wavelength.max():
                index = int(np.argmin(np.abs(scan.wavelength - target)))
                points.append((scan.time, scan.intensity[index], scan.wavelength[index]))
        values = np.asarray(sorted(points), dtype=float).reshape(-1, 3)
        return values[:, 0], values[:, 1], values[:, 2]

    def heatmap(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if not self.dad:
            return np.array([]), np.array([]), np.empty((0, 0))
        times = np.asarray([scan.time for scan in self.dad])
        wavelengths = np.unique(np.concatenate([scan.wavelength for scan in self.dad]))
        values = np.vstack([np.interp(wavelengths, scan.wavelength, scan.intensity) for scan in self.dad])
        return times, wavelengths, values


DATE_PREFIX = re.compile(r"^(\d{4}_\d{2}_\d{2})_?")
NATIVE_BIN_WIDTH = 0.03125
COMPACT_CACHE_FORMAT = "bluelcms-compact-v1"


def file_display_name(path: Path, show_date_prefix: bool) -> str:
    return path.name if show_date_prefix else DATE_PREFIX.sub("", path.name)


def discover_files(folder: Path) -> list[Path]:
    """List mzML files and gzip-compressed mzML files newest-first."""
    def order(path):
        match = DATE_PREFIX.match(path.name)
        return (0, -int(match.group(1).replace("_", "")), path.name.casefold()) if match else (1, 0, path.name.casefold())
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".mzml", ".gz"}),
        key=order,
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
    x = np.asarray(record.get(axis, []), dtype=np.float32)
    y = np.asarray(record.get("intensity array", []), dtype=np.float32)
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
        raise ValueError(f"Invalid {axis} / intensity arrays in {record.get('id', 'spectrum')}")
    valid = np.isfinite(x) & np.isfinite(y)
    return (x, y) if valid.all() else (x[valid], y[valid])


def parse_spectra(spectra, wavelength: float = 254.0, dad_callback=None, scan_callback=None) -> Run:
    dad = []
    scans = []
    skipped = 0
    shared_wavelength = None
    shared_mz = None
    for spectrum in spectra:
        time = retention_time(spectrum)
        if "wavelength array" in spectrum:
            if time is None:
                continue
            axis, intensity = paired_arrays(spectrum, "wavelength array")
            # mzML wavelength arrays use nanometers (MS:1000617).
            if len(axis):
                if shared_wavelength is None:
                    shared_wavelength = axis
                elif np.array_equal(axis, shared_wavelength):
                    axis = shared_wavelength
                scan = DADScan(time, axis, intensity)
                dad.append(scan)
                if dad_callback:
                    dad_callback(scan)
        elif int(spectrum.get("ms level", 0)) == 1:
            positive = "positive scan" in spectrum
            negative = "negative scan" in spectrum
            if time is None or positive == negative:
                skipped += 1
                continue
            mz, intensity = paired_arrays(spectrum, "m/z array")
            valid = (mz > 0) & (intensity >= 0)
            mz, intensity = mz[valid], intensity[valid]
            if shared_mz is None:
                shared_mz = mz
            elif np.array_equal(mz, shared_mz):
                mz = shared_mz
            scan = Scan(time, "+" if positive else "-", mz, intensity)
            scans.append(scan)
            if scan_callback:
                scan_callback(scan)
    dad.sort(key=lambda scan: scan.time)
    return Run(tuple(dad), tuple(scans), skipped)


class ProgressReader:
    """File wrapper that reports streamed mzML input without retaining it."""
    def __init__(self, file, progress):
        self.file, self.progress, self.total = file, progress, file.seek(0, 2)
        file.seek(0)

    def read(self, size=-1):
        data = self.file.read(size)
        self.progress(self.file.tell(), self.total)
        return data

    def __getattr__(self, name):
        return getattr(self.file, name)


def load_run(path: Path, wavelength: float = 254.0, progress=None, dad_callback=None, scan_callback=None) -> Run:
    if path.name.endswith(".bluelcms.npz"):
        return load_compact_cache(path, dad_callback, scan_callback)
    # Streaming avoids retaining the mzML XML tree; decoded MS1 arrays are cached
    # in the active Run for repeated time-region selection.
    if progress is None:
        if path.suffix.lower() == ".gz":
            with path.open("rb") as file, gzip.GzipFile(fileobj=file) as compressed, MzML(compressed, use_index=False) as reader:
                return parse_spectra(reader, wavelength, dad_callback, scan_callback)
        with MzML(str(path), use_index=False) as reader:
            return parse_spectra(reader, wavelength, dad_callback, scan_callback)
    with path.open("rb") as file:
        reader_source = ProgressReader(file, progress)
        if path.suffix.lower() == ".gz":
            with gzip.GzipFile(fileobj=reader_source) as compressed, MzML(compressed, use_index=False) as reader:
                return parse_spectra(reader, wavelength, dad_callback, scan_callback)
        with MzML(reader_source, use_index=False) as reader:
            return parse_spectra(reader, wavelength, dad_callback, scan_callback)


def _pack_scans(scans, axis_name: str):
    axes = [getattr(scan, axis_name) for scan in scans]
    shared = bool(axes) and all(np.array_equal(axis, axes[0]) for axis in axes[1:])
    values = [scan.intensity.astype(np.float32, copy=False) for scan in scans]
    if shared:
        return {"shared": np.array(True), "axis": axes[0].astype(np.float32, copy=False), "intensity": np.stack(values)}
    offsets = np.cumsum([0, *[len(axis) for axis in axes]], dtype=np.int64)
    return {"shared": np.array(False), "offsets": offsets, "axis": np.concatenate(axes).astype(np.float32), "intensity": np.concatenate(values)}


def _unpack_scans(data, prefix: str, times, constructor, extra=None):
    shared = bool(data[f"{prefix}_shared"])
    if shared:
        axis = data[f"{prefix}_axis"]
        values = data[f"{prefix}_intensity"]
        return tuple(constructor(time, axis.copy(), intensity, *(() if extra is None else (extra[index],))) for index, (time, intensity) in enumerate(zip(times, values)))
    offsets, axes, values = data[f"{prefix}_offsets"], data[f"{prefix}_axis"], data[f"{prefix}_intensity"]
    return tuple(constructor(time, axes[offsets[index]:offsets[index + 1]], values[offsets[index]:offsets[index + 1]], *(() if extra is None else (extra[index],))) for index, time in enumerate(times))


def write_compact_cache(run: Run, path: Path) -> Path:
    """Persist only data BlueLCMS needs, using float32 arrays and zlib compression."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.part")
    dad = _pack_scans(run.dad, "wavelength") if run.dad else {"shared": np.array(True), "axis": np.array([], dtype=np.float32), "intensity": np.empty((0, 0), dtype=np.float32)}
    ms = _pack_scans(run.scans, "mz") if run.scans else {"shared": np.array(True), "axis": np.array([], dtype=np.float32), "intensity": np.empty((0, 0), dtype=np.float32)}
    payload = {
        "format": np.array(COMPACT_CACHE_FORMAT), "skipped_scans": np.array(run.skipped_scans),
        "dad_times": np.asarray([scan.time for scan in run.dad]), "dad_shared": dad["shared"], "dad_axis": dad["axis"], "dad_intensity": dad["intensity"],
        "ms_times": np.asarray([scan.time for scan in run.scans]), "ms_polarity": np.asarray([scan.polarity for scan in run.scans]), "ms_shared": ms["shared"], "ms_axis": ms["axis"], "ms_intensity": ms["intensity"],
    }
    if not bool(dad["shared"]): payload["dad_offsets"] = dad["offsets"]
    if not bool(ms["shared"]): payload["ms_offsets"] = ms["offsets"]
    try:
        with temporary.open("wb") as output:
            np.savez_compressed(output, **payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def load_compact_cache(path: Path, dad_callback=None, scan_callback=None) -> Run:
    with np.load(path, allow_pickle=False) as data:
        if str(data["format"]) != COMPACT_CACHE_FORMAT:
            raise ValueError("Unsupported BlueLCMS cache format")
        dad = _unpack_scans(data, "dad", data["dad_times"], lambda time, axis, intensity: DADScan(float(time), axis, intensity))
        scans = _unpack_scans(data, "ms", data["ms_times"], lambda time, axis, intensity, polarity: Scan(float(time), str(polarity), axis, intensity), data["ms_polarity"])
        skipped = int(data["skipped_scans"])
    if dad_callback:
        for scan in dad: dad_callback(scan)
    if scan_callback:
        for scan in scans: scan_callback(scan)
    return Run(dad, scans, skipped)




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
        selected = [s for s in run.scans if s.polarity == polarity and start <= s.time <= end and len(s.mz)]
        if not selected:
            result[polarity] = (np.array([]), np.array([]))
            continue
        lower = min(int(np.floor(scan.mz.min() / bin_width)) for scan in selected if len(scan.mz))
        upper = max(int(np.floor(scan.mz.max() / bin_width)) for scan in selected if len(scan.mz))
        sums = np.zeros(upper - lower + 1)
        for scan in selected:
            bins = np.floor(scan.mz / bin_width).astype(int) - lower
            sums += np.bincount(bins, weights=scan.intensity, minlength=len(sums))
        occupied = np.flatnonzero(sums)
        result[polarity] = ((occupied + lower + 0.5) * bin_width, sums[occupied])
    return result


def display_bin_width(minimum: float, maximum: float, pixels: int) -> float:
    """Choose a native-grid multiple wide enough for the current view."""
    span = maximum - minimum
    if not np.isfinite(span) or span <= 0 or pixels < 1:
        return NATIVE_BIN_WIDTH
    width = NATIVE_BIN_WIDTH
    while width < span / pixels:
        width *= 2
    return width


def rebin_histogram(x: np.ndarray, y: np.ndarray, bin_width: float) -> tuple[np.ndarray, np.ndarray]:
    """Sum native histogram bins into zero-aligned display bins."""
    if not np.isfinite(bin_width) or bin_width <= 0:
        raise ValueError("Bin width must be finite and positive")
    if not len(x):
        return np.array([]), np.array([])
    bins, inverse = np.unique(np.floor(x / bin_width), return_inverse=True)
    return (bins + .5) * bin_width, np.bincount(inverse, weights=y)
