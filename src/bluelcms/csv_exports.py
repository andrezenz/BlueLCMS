"""Thermo text/CSV exports with metadata preambles and optional same-source TICs."""

import csv
from dataclasses import dataclass
import json
import ntpath
from pathlib import Path
import re
from zipfile import BadZipFile

import numpy as np

from .mzml import Chromatogram, ExportedSpectrum, Run, load_compact_cache


def is_csv(path):
    return isinstance(path, Path) and path.suffix.lower() == ".csv"


def _decode(content):
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252")


def export_header(path):
    with path.open("rb") as source:
        lines = _decode(source.read(4096)).splitlines()
    if len(lines) < 2 or lines[0].strip().upper() not in ("SPECTRUM - MS", "CHROMATOGRAM"):
        return None
    return {"kind": lines[0].strip().upper(), "raw_source": lines[1].strip(),
            "identity": ntpath.normcase(ntpath.normpath(lines[1].strip())),
            "tic": lines[0].strip().upper() == "CHROMATOGRAM" and path.stem.casefold().endswith("_tic")}


def _headers(files):
    headers = {}
    for file in files:
        if not is_csv(file):
            continue
        try:
            header = export_header(file)
        except (OSError, UnicodeError):
            continue
        if header is not None:
            headers[file] = header
    return headers


def _matching_tics(path, header, headers):
    if header["kind"] != "SPECTRUM - MS" or not header["raw_source"]:
        return []
    return sorted((p for p, h in headers.items() if p != path and h["tic"] and h["identity"] == header["identity"]), key=lambda p: p.name.casefold())


def discover_csv_exports(files):
    """Ignore unrelated CSVs and list a paired spectrum/TIC only once."""
    headers = _headers(files)
    paired = set()
    for path, header in headers.items():
        matches = _matching_tics(path, header, headers)
        if len(matches) == 1:
            paired.add(matches[0])
    return [path for path in headers if path not in paired]


def describe_export(path):
    header = export_header(path)
    if header is None:
        raise ValueError("Unsupported CSV: expected a Thermo SPECTRUM - MS or CHROMATOGRAM preamble")
    headers = _headers(p for p in path.parent.iterdir() if p.is_file() and is_csv(p))
    matches = _matching_tics(path, header, headers)
    tic = matches[0] if len(matches) == 1 else None
    files = [path] + ([tic] if tic else [])
    fingerprint = {"path": str(path), "files": [dict(name=p.name, size=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns) for p in files],
                   "tic_candidates": [p.name for p in matches]}
    return header, tic, fingerprint


def csv_fingerprint(path):
    return describe_export(path)[2]


def _read_export(path):
    lines = _decode(path.read_bytes()).splitlines()
    kind = lines[0].strip().upper() if lines else ""
    expected = ("mass", "intensity") if kind == "SPECTRUM - MS" else ("time(min)", "relative abundance")
    start = next((i for i, line in enumerate(lines) if tuple(v.strip().casefold() for v in next(csv.reader([line]))) == expected), None)
    if kind not in ("SPECTRUM - MS", "CHROMATOGRAM") or start is None:
        raise ValueError(f"{path.name}: unsupported metadata/data headers")
    points = []
    for number, row in enumerate(csv.reader(lines[start + 1:]), start + 2):
        if not row or not any(value.strip() for value in row):
            continue
        if len(row) != 2:
            raise ValueError(f"{path.name}, row {number}: expected two numeric columns")
        try:
            points.append(tuple(float(value) for value in row))
        except ValueError as error:
            raise ValueError(f"{path.name}, row {number}: invalid numeric data") from error
    values = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if not len(values) or not np.isfinite(values).all() or (values[:, 0] < 0).any() or (values[:, 1] < 0).any():
        raise ValueError(f"{path.name}: expected finite, non-negative data")
    preamble = "\n".join(lines[:start])
    count = re.search(r"Data points:\s*(\d+)", preamble, re.IGNORECASE)
    if count and int(count[1]) != len(values):
        raise ValueError(f"{path.name}: Data points count does not match the numeric rows")
    order = np.argsort(values[:, 0], kind="stable")
    return kind, preamble, values[order, 0], values[order, 1]


def load_csv_export(path, progress=None):
    header, tic, fingerprint = describe_export(path)
    total = sum(entry["size"] for entry in fingerprint["files"])
    if progress:
        progress(0, total)
    kind, preamble, axis, intensity = _read_export(path)
    spectra, chromatograms = (), ()
    if kind == "SPECTRUM - MS":
        if (axis <= 0).any():
            raise ValueError(f"{path.name}: m/z values must be positive")
        scan_filter = next((line.strip() for line in preamble.splitlines() if re.search(r"\b(?:FTMS|ITMS|TOFMS|MS)\s+[+-]\s", line, re.IGNORECASE)), "")
        match = re.search(r"\b(?:FTMS|ITMS|TOFMS|MS)\s+([+-])\s", scan_filter, re.IGNORECASE)
        if match is None:
            raise ValueError(f"{path.name}: no explicit positive/negative polarity in the scan filter")
        rt = re.search(r"\bRT:\s*(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?", preamble, re.IGNORECASE)
        start, end = (float(rt[1]), float(rt[2] or rt[1])) if rt else (None, None)
        if start is not None and start > end:
            raise ValueError(f"{path.name}: invalid exported RT interval")
        averages = re.search(r"\bAV:\s*(\d+)", preamble, re.IGNORECASE)
        if averages and int(averages[1]) <= 0:
            raise ValueError(f"{path.name}: invalid averaged-scan count")
        spectra = (ExportedSpectrum(match[1], axis, intensity, start, end, int(averages[1]) if averages else None, scan_filter),)
    else:
        if len(axis) < 2 or not np.all(np.diff(axis) > 0):
            raise ValueError(f"{path.name}: chromatogram times must be strictly increasing")
        chromatograms = (Chromatogram("TIC" if header["tic"] else "Exported chromatogram", axis, intensity, "Relative Abundance (exported)"),)
    if tic is not None:
        _, _, times, values = _read_export(tic)
        if len(times) < 2 or not np.all(np.diff(times) > 0):
            raise ValueError(f"{tic.name}: chromatogram times must be strictly increasing")
        chromatograms = (Chromatogram("TIC", times, values, "Relative Abundance (exported)"),)
    if csv_fingerprint(path) != fingerprint:
        raise OSError("CSV export or TIC association changed while loading; retry after export finishes")
    metadata = json.dumps(dict(path=str(path), source_type="thermo-csv", raw_source=header["raw_source"],
                               fingerprint=fingerprint, paired_tic=str(tic) if tic else None,
                               fixed_spectrum=bool(spectra), preamble=preamble,
                               association="ambiguous TICs; not paired" if len(fingerprint["tic_candidates"]) > 1 else ""))
    if progress:
        progress(total, total)
    return Run((), (), chromatograms=chromatograms, source_metadata=metadata, exported_spectra=spectra)


@dataclass(frozen=True)
class CsvLoadResult:
    run: Run
    refresh_cache: bool


def load_csv_cached(path, cache, progress=None):
    if not path.is_file():
        if cache and cache.is_file():
            return CsvLoadResult(load_compact_cache(cache), False)
        raise OSError(f"CSV source unavailable: {path}")
    fingerprint = csv_fingerprint(path)
    if cache and cache.is_file():
        try:
            with np.load(cache, allow_pickle=False) as data:
                metadata = json.loads(str(data["source_metadata"]))
            if isinstance(metadata, dict) and metadata.get("source_type") == "thermo-csv" and metadata.get("fingerprint") == fingerprint:
                return CsvLoadResult(load_compact_cache(cache), False)
        except (OSError, ValueError, KeyError, IndexError, TypeError, BadZipFile, EOFError):
            pass
    return CsvLoadResult(load_csv_export(path, progress), True)
