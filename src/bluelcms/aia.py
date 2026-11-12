"""Read Agilent AIA folders as primary, named LC chromatograms.

No wavelength is inferred from a channel letter. Sources are read-only; local
caches carry the exact source-file manifest so re-exports can be detected.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import struct
from zipfile import BadZipFile

import numpy as np

from .mzml import Chromatogram, Run, load_compact_cache
from .vendor import _read_netcdf_classic


def is_aia(path):
    return isinstance(path, Path) and path.suffix.lower() in (".aia", ".cdf")


def aia_files(path):
    if path.suffix.lower() == ".cdf" and path.is_file():
        return (path,)
    if path.suffix.lower() != ".aia" or not path.is_dir():
        raise OSError(f"AIA source is unavailable: {path}")
    files = tuple(sorted((p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".cdf"), key=lambda p: p.name.casefold()))
    if not files:
        raise ValueError(f"No CDF chromatograms in {path.name}")
    return files


def aia_fingerprint(path):
    manifest = []
    for file in aia_files(path):
        stat = file.stat()
        manifest.append({"name": file.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return {"path": str(path), "files": manifest}


def _time_factor(unit):
    units = {"minutes": 1., "minute": 1., "min": 1., "seconds": 1 / 60,
             "second": 1 / 60, "s": 1 / 60, "sec": 1 / 60,
             "hours": 60., "hour": 60., "h": 60.}
    try:
        return units[str(unit).strip().casefold()]
    except KeyError as error:
        raise ValueError(f"Missing or unsupported retention-time unit: {unit!r}") from error


def read_chromatogram(path, content=None):
    try:
        variables, attributes, variable_attributes = _read_netcdf_classic(path, include_metadata=True, content=content)
        values = np.asarray(variables["ordinate_values"], dtype=np.float32)
        if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
            raise ValueError("Expected a non-empty, finite, one-dimensional ordinate_values array")
        factor = _time_factor(attributes.get("retention_unit", ""))
        raw_times = variables.get("raw_data_retention", np.array([]))
        uniform = variable_attributes.get("ordinate_values", {}).get("uniform_sampling_flag", "").upper()
        valid_times = (raw_times.ndim == 1 and len(raw_times) == len(values)
                       and np.isfinite(raw_times).all() and len(raw_times) > 1
                       and raw_times[0] >= 0 and np.all(np.diff(raw_times) > 0))
        if valid_times and uniform != "Y":
            times = raw_times.astype(np.float64) * factor
        else:
            if uniform == "N":
                raise ValueError("Nonuniform sampling requires a valid raw_data_retention axis")
            def scalar(name):
                data = np.asarray(variables[name])
                if data.size != 1:
                    raise ValueError(f"Expected one {name} value")
                return float(data.reshape(-1)[0])
            delay = scalar("actual_delay_time") * factor
            interval = scalar("actual_sampling_interval") * factor
            if not np.isfinite(delay) or not np.isfinite(interval) or delay < 0 or interval <= 0:
                raise ValueError("Invalid chromatogram delay or sampling interval")
            # OpenLAB exports can contain an entirely zero-filled retention axis.
            # Do not stretch samples to actual_run_time_length (it can differ by
            # one sampling interval from the reconstructed last sample).
            times = delay + np.arange(len(values), dtype=np.float64) * interval
        channel = re.search(r"(DAD\d+[A-Z])(?:RawDataTable)?$", path.stem, re.IGNORECASE)
        if channel is None:
            channel = re.search(r"(DAD\d+[A-Z])RawDataTable", attributes.get("raw_data_table_name", ""), re.IGNORECASE)
        name = channel[1].upper() if channel else path.stem
        unit = str(attributes.get("detector_unit", ""))
        return Chromatogram(name, times, values, unit), attributes
    except (ValueError, KeyError, IndexError, struct.error, OverflowError) as error:
        raise ValueError(f"Cannot read {path.name}: {error}") from error


def load_aia(path, progress=None):
    before = aia_fingerprint(path)
    files = aia_files(path)
    channels, details = [], []
    total = sum(item["size"] for item in before["files"])
    done = 0
    if progress:
        progress(done, total)
    for file in files:
        channel, attrs = read_chromatogram(file)
        if any(existing.name == channel.name for existing in channels):
            raise ValueError(f"Duplicate channel {channel.name} in {path.name}; channel identity is ambiguous")
        channels.append(channel)
        details.append({"channel": channel.name, "sample": attrs.get("sample_name", ""),
                        "method": attrs.get("detection_method_name", ""), "file": file.name})
        done += file.stat().st_size
        if progress:
            progress(done, total)
    if aia_fingerprint(path) != before:
        raise OSError(f"AIA export changed while being read: {path.name}; retry after export finishes")
    metadata = json.dumps({"path": str(path), "source_type": "aia", "fingerprint": before, "channels": details})
    return Run((), (), chromatograms=tuple(channels), source_metadata=metadata)


@dataclass(frozen=True)
class AiaLoadResult:
    run: Run
    refresh_cache: bool


def load_aia_cached(path, cache, progress=None):
    available = path.is_dir() if path.suffix.lower() == ".aia" else path.is_file()
    if not available:
        if cache and cache.is_file():
            return AiaLoadResult(load_compact_cache(cache), False)
        raise OSError(f"AIA source is unavailable: {path}")
    fingerprint = aia_fingerprint(path)
    if cache and cache.is_file():
        try:
            with np.load(cache, allow_pickle=False) as data:
                metadata = json.loads(str(data["source_metadata"]))
            if isinstance(metadata, dict) and metadata.get("source_type") == "aia" and metadata.get("fingerprint") == fingerprint:
                return AiaLoadResult(load_compact_cache(cache), False)
        except (OSError, ValueError, KeyError, IndexError, TypeError, BadZipFile, EOFError):
            pass  # Rebuild an obsolete or damaged cache from the readable export.
    return AiaLoadResult(load_aia(path, progress), True)
