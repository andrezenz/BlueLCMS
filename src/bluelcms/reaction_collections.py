"""Portable reaction-monitoring snapshots and reproducible LC integrations.

Archives are ZIP files with a versioned JSON manifest and human-readable CSV
tables. Original AIA CDFs are embedded when they match the loaded chromatograms;
offline/non-AIA traces use lossless, pickle-free NumPy arrays. Opening never
follows source paths or extracts archive members onto the filesystem.
"""

import csv
from dataclasses import dataclass, field
from io import BytesIO, StringIO
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from .aia import aia_files, aia_fingerprint, is_aia, read_chromatogram
from .mzml import Chromatogram
from .integrations import baseline_curve


FORMAT = "bluelcms-reaction-collection"
VERSION = 2
COLORS = ("#ef5350", "#42a5f5", "#66bb6a", "#ab47bc", "#ffa726", "#26c6da", "#ec407a")


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite.")
    return float(value)


def _window(start, end):
    start, end = _number(start, "Window start"), _number(end, "Window end")
    if not 0 <= start < end:
        raise ValueError("Integration windows must have 0 ≤ start < end (minutes).")
    return start, end


def validate_trace(trace):
    times, values = np.asarray(trace.times), np.asarray(trace.values)
    if (times.ndim != 1 or values.ndim != 1 or len(times) < 2 or len(times) != len(values)
            or not np.isfinite(times).all() or not np.isfinite(values).all()
            or times[0] < 0 or not np.all(np.diff(times) > 0)):
        raise ValueError(f"{trace.name}: expected finite signal and strictly increasing times with at least two points.")


@dataclass
class ReactionSample:
    id: str
    name: str
    source: str
    channels: tuple[Chromatogram, ...]
    time_min: float | None = None
    source_metadata: str = ""
    originals: dict[str, tuple[str, bytes]] = field(default_factory=dict)
    provenance: str = "Loaded chromatogram snapshot"


@dataclass
class ReactionTarget:
    id: str
    name: str
    channel: str
    start_min: float
    end_min: float
    baseline: str = "midpoint"
    color: str = COLORS[0]


@dataclass
class IndividualIntegration:
    channel: str
    start_min: float
    end_min: float
    baseline: str = "midpoint"
    baseline_start: float | None = None
    baseline_end: float | None = None


@dataclass
class ReactionCollection:
    samples: list[ReactionSample]
    targets: list[ReactionTarget] = field(default_factory=list)
    name: str = "Reaction kinetics"
    overrides: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)
    ratio_reference: str | None = None
    internal_standard: str | None = None
    integration_mode: str = "common"
    individual_integrations: dict[tuple[str, str], IndividualIntegration] = field(default_factory=dict)

    def validate(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("A collection name is required.")
        if not self.samples:
            raise ValueError("A collection needs at least one measurement.")
        for items, label in ((self.samples, "measurement"), (self.targets, "target")):
            ids = [item.id for item in items]
            if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) for value in ids) or len(ids) != len(set(ids)):
                raise ValueError(f"Invalid or duplicate {label} IDs.")
        for sample in self.samples:
            if not isinstance(sample.name, str) or not sample.name.strip():
                raise ValueError("Measurements need nonempty names.")
            if sample.time_min is not None and _number(sample.time_min, "Reaction time") < 0:
                raise ValueError("Reaction times must be non-negative minutes.")
            if not sample.channels or len({c.name for c in sample.channels}) != len(sample.channels):
                raise ValueError(f"{sample.name}: channel names must be unique and nonempty.")
            for channel in sample.channels:
                if not isinstance(channel.name, str) or not channel.name or not isinstance(channel.unit, str):
                    raise ValueError("Channels need recorded names and text units.")
                validate_trace(channel)
        channels = {c.name for sample in self.samples for c in sample.channels}
        for target in self.targets:
            if not target.name.strip() or target.channel not in channels:
                raise ValueError("Each target needs a name and a recorded channel.")
            _window(target.start_min, target.end_min)
            if target.baseline not in ("midpoint", "endpoints", "zero") or not re.fullmatch(r"#[0-9a-fA-F]{6}", target.color):
                raise ValueError("Invalid target baseline or color.")
        sample_ids, target_ids = {s.id for s in self.samples}, {t.id for t in self.targets}
        for (sample, target), window in self.overrides.items():
            if sample not in sample_ids or target not in target_ids:
                raise ValueError("A window override references an unknown measurement or target.")
            _window(*window)
        for reference in (self.ratio_reference, self.internal_standard):
            if reference is not None and reference not in target_ids:
                raise ValueError("The reference target is not in this collection.")
        if self.integration_mode not in ("common", "individual"):
            raise ValueError("Unknown collection integration mode")
        for (sample, target), spec in self.individual_integrations.items():
            if sample not in sample_ids or target not in target_ids:
                raise ValueError("An individual integral references an unknown measurement or compound")
            _window(spec.start_min, spec.end_min)
            if spec.channel not in channels or spec.baseline not in ("midpoint", "endpoints", "zero", "manual"):
                raise ValueError("Unknown integration channel or baseline")
            if spec.baseline == "manual":
                _number(spec.baseline_start, "Baseline start height")
                _number(spec.baseline_end, "Baseline end height")


def integration_curve(trace, start, end, baseline="midpoint", baseline_start=None, baseline_end=None):
    """Interpolate boundary samples and return the recorded and baseline curves."""
    validate_trace(trace)
    start, end = _window(start, end)
    if start < trace.times[0] or end > trace.times[-1]:
        raise ValueError("Window outside recorded chromatogram")
    return baseline_curve(trace.times, trace.values, start, end, baseline, baseline_start, baseline_end)


def evaluate(collection):
    """Areas are signed detector-signal integrals, never implied concentrations.

    Fractions share a channel/unit group. Ratios require matching units; negative
    areas, missing windows/channels and non-positive denominators remain blank.
    Missing reaction times do not prevent integration, but are not plotted.
    """
    collection.validate()
    results = []
    for sample in collection.samples:
        rows = {}
        for target in collection.targets:
            spec = collection.individual_integrations.get((sample.id, target.id))
            assigned = collection.integration_mode == "common" or spec is not None
            start, end = collection.overrides.get((sample.id, target.id), (target.start_min, target.end_min))
            channel, baseline = target.channel, target.baseline
            if spec is not None:
                start, end, channel, baseline = spec.start_min, spec.end_min, spec.channel, spec.baseline
            trace = next((c for c in sample.channels if c.name == channel), None)
            row = dict(sample_id=sample.id, measurement=sample.name, reaction_time_min=sample.time_min,
                       target_id=target.id, target=target.name, channel=channel, assigned=assigned,
                       start_min=start, end_min=end, baseline=baseline,
                       baseline_start=None if spec is None else spec.baseline_start,
                       baseline_end=None if spec is None else spec.baseline_end,
                       signal_unit="" if trace is None else trace.unit,
                       area=None, area_percent=None, ratio=None, normalized_area=None, status="ok")
            if not assigned:
                row["status"] = "Not integrated"
            elif trace is None:
                row["status"] = "Missing channel"
            else:
                expected = trace.unit
                for other in collection.samples:
                    other_spec = collection.individual_integrations.get((other.id, target.id))
                    if collection.integration_mode == "individual" and other_spec is None:
                        continue
                    other_channel = other_spec.channel if other_spec is not None else target.channel
                    reference_trace = next((c for c in other.channels if c.name == other_channel), None)
                    if reference_trace is not None:
                        expected = reference_trace.unit
                        break
                if trace.unit != expected:
                    row["status"] = "Incompatible signal units"
                else:
                    try:
                        x, y, base = integration_curve(trace, start, end, baseline, row["baseline_start"], row["baseline_end"])
                        row["baseline_start"], row["baseline_end"] = float(base[0]), float(base[-1])
                        area = float(np.trapezoid(y - base, x))
                        tolerance = 64 * np.finfo(float).eps * max(1., float(np.max(abs(y))), float(np.max(abs(base)))) * (end - start)
                        row["area"] = 0. if abs(area) <= tolerance else area
                        if not math.isfinite(area):
                            row["area"] = None
                            row["status"] = "Non-finite integrated area"
                        elif row["area"] < 0:
                            row["status"] = "Negative area"
                    except ValueError as error:
                        row["status"] = str(error)
            rows[target.id] = row
        for row in rows.values():
            if row["area"] is None or row["area"] < 0:
                continue
            group = [other for other in rows.values() if other["assigned"] and other["channel"] == row["channel"]
                     and other["signal_unit"] == row["signal_unit"]]
            # An incomplete group must not masquerade as a 100% product fraction.
            if all(other["area"] is not None and other["area"] >= 0 for other in group):
                total = sum(other["area"] for other in group)
                if total > 0:
                    row["area_percent"] = 100 * row["area"] / total
            for reference, column in ((collection.ratio_reference, "ratio"), (collection.internal_standard, "normalized_area")):
                denominator = rows.get(reference)
                if (denominator is not None and denominator["area"] is not None and denominator["area"] > 0
                        and denominator["signal_unit"] == row["signal_unit"]):
                    row[column] = row["area"] / denominator["area"]
        results.extend(rows.values())
    return results


def create_collection(entries, wavelength=254):
    """Snapshot loaded measurements, including all AIA channels or one mzML UV trace.

    entries are (display name, original path, loaded Run). Source CDFs are only
    retained when their manifest AND decoded traces match the loaded data.
    """
    samples = []
    for index, (name, source, run) in enumerate(entries, 1):
        channels = run.chromatograms
        if not channels:
            times, values, used = run.uv_trace(wavelength)
            if not len(times):
                raise ValueError(f"{name}: no chromatogram at {wavelength} nm")
            actual = np.unique(used)
            if len(actual) != 1:
                raise ValueError(f"{name}: selected UV wavelength changes across scans")
            channels = (Chromatogram(f"UV {actual[0]:g} nm", times, values, "recorded UV units", float(actual[0])),)
        snapshots = tuple(Chromatogram(c.name, np.array(c.times, dtype=np.float64, copy=True),
                                      np.array(c.values, copy=True), c.unit, c.wavelength_nm) for c in channels)
        sample = ReactionSample(f"m{index:03d}", name, str(source), snapshots, source_metadata=run.source_metadata)
        if is_aia(source):
            try:
                metadata = json.loads(run.source_metadata)
                before = aia_fingerprint(source)
                if metadata.get("fingerprint") != before:
                    raise ValueError("Source no longer matches loaded data")
                originals = {}
                for file in aia_files(source):
                    content = file.read_bytes()
                    decoded, _ = read_chromatogram(file, content)
                    loaded = next(c for c in snapshots if c.name == decoded.name)
                    if (decoded.unit != loaded.unit or not np.array_equal(decoded.times, loaded.times)
                            or not np.array_equal(decoded.values, loaded.values)):
                        raise ValueError("Source no longer matches loaded data")
                    originals[loaded.name] = (file.name, content)
                if aia_fingerprint(source) != before or len(originals) != len(snapshots):
                    raise ValueError("Source changed during snapshot")
                sample.originals = originals
                sample.provenance = "Original AIA CDF files verified against loaded chromatograms"
            except (OSError, ValueError, KeyError, StopIteration, TypeError):
                sample.provenance = "Loaded chromatogram arrays; original AIA source unavailable or changed"
        samples.append(sample)
    collection = ReactionCollection(samples, integration_mode="individual")
    collection.validate()
    return collection


def _csv(columns, rows):
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue()


RESULT_COLUMNS = ("sample_id", "measurement", "reaction_time_min", "target_id", "target", "channel",
                  "start_min", "end_min", "baseline", "baseline_start", "baseline_end", "assigned", "signal_unit", "area", "area_percent", "ratio", "normalized_area", "status")


def save_collection(collection, path, include_csv=False):
    """Atomically save a self-contained, versioned ZIP with CSV result tables."""
    results = evaluate(collection)
    path = Path(path)
    manifest = dict(format=FORMAT, version=VERSION, name=collection.name, reaction_time_unit="min",
                    retention_time_unit="min", integration_method="signed trapezoidal; interpolated endpoints",
                    chromatogram_csv_copies=bool(include_csv),
                    integration_mode=collection.integration_mode,
                    individual_integrations=[dict(sample_id=s, target_id=t, **vars(spec)) for (s, t), spec in collection.individual_integrations.items()],
                    ratio_reference=collection.ratio_reference, internal_standard=collection.internal_standard,
                    targets=[vars(target) for target in collection.targets],
                    overrides=[dict(sample_id=s, target_id=t, start_min=w[0], end_min=w[1]) for (s, t), w in collection.overrides.items()],
                    samples=[])
    handle = tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".part", dir=path.parent, delete=False)
    temporary = Path(handle.name); handle.close()
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            def embed(member, content):
                archive.writestr(member, content)
                return {"member": member, "sha256": hashlib.sha256(content).hexdigest()}
            for sample in collection.samples:
                record = {key: getattr(sample, key) for key in ("id", "name", "source", "time_min", "source_metadata", "provenance")}
                record["channels"] = []
                for index, trace in enumerate(sample.channels, 1):
                    descriptor = dict(name=trace.name, unit=trace.unit, wavelength_nm=trace.wavelength_nm)
                    if trace.name in sample.originals:
                        filename, content = sample.originals[trace.name]
                        filename = Path(filename).name
                        member = f"source_data/{sample.id}/{index:03d}_{filename}"
                        descriptor.update(encoding="cdf", original_name=filename, data=embed(member, content))
                    else:
                        buffer = BytesIO(); np.save(buffer, trace.values, allow_pickle=False)
                        descriptor.update(encoding="numpy", values=embed(f"chromatograms/{sample.id}/{index:03d}_signal.npy", buffer.getvalue()))
                        step = float(trace.times[1] - trace.times[0])
                        if np.array_equal(trace.times, trace.times[0] + np.arange(len(trace.times)) * step):
                            descriptor["time_grid"] = dict(start=float(trace.times[0]), step=step, count=len(trace.times))
                        else:
                            buffer = BytesIO(); np.save(buffer, trace.times, allow_pickle=False)
                            descriptor["times"] = embed(f"chromatograms/{sample.id}/{index:03d}_time.npy", buffer.getvalue())
                    if include_csv:
                        text = StringIO()
                        fmt = "%.9g" if trace.values.dtype == np.float32 else "%.17g"
                        np.savetxt(text, np.column_stack((trace.times, trace.values)), delimiter=",",
                                   fmt=("%.17g", fmt), header="time_min,signal", comments="")
                        descriptor["csv"] = embed(f"chromatogram_csv/{sample.id}/{index:03d}.csv", text.getvalue().encode("utf-8"))
                    record["channels"].append(descriptor)
                manifest["samples"].append(record)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, allow_nan=False))
            archive.writestr("measurements.csv", _csv(("id", "name", "time_min", "source", "provenance"), [vars(s) for s in collection.samples]))
            archive.writestr("targets.csv", _csv(("id", "name", "channel", "start_min", "end_min", "baseline", "color"), [vars(t) for t in collection.targets]))
            archive.writestr("integrations.csv", _csv(RESULT_COLUMNS, results))
            archive.writestr("README.txt", "BlueLCMS reaction collection, format version 2 (also reads version 1).\n"
                             "Open CSV tables in Excel/LibreOffice/Python/R after unzipping.\n"
                             "manifest.json is authoritative; opening recalculates integrations.\n"
                             "Reaction and retention times are minutes. Blank time means unassigned.\n"
                             "Default midpoint baseline is horizontal at the average signal at the two limits.\n"
                             "Manual baseline endpoint heights and individual measurement/compound windows are stored in the manifest and integrations.csv.\n"
                             "Common-window mode, endpoint-line and zero baselines remain supported.\n"
                             "Areas are SIGNED signal-unit * minute integrals. Negative/missing areas are not used in ratios.\n"
                             "Percentages are within each target channel/unit group, not chemical conversion.\n"
                             "ratio = target area / ratio_reference area; normalized_area = target area / internal_standard area.\n"
                             "Non-positive/missing denominators leave ratios blank. Detector response factors are not calibrated.\n"
                             "source_data contains original CDFs when available and verified.\n"
                             "Offline/non-AIA snapshots use pickle-free .npy arrays and exact time grids or explicit times.\n"
                             "Member SHA-256 checksums verify embedded data integrity; no source paths are required to reopen.\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def load_collection(path):
    """Open an embedded snapshot without consulting NAS files or extracting ZIPs."""
    with ZipFile(path) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Duplicate collection archive members")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != FORMAT or manifest.get("version") not in (1, VERSION):
            raise ValueError("Unsupported reaction collection format/version")
        if manifest.get("reaction_time_unit") != "min" or manifest.get("retention_time_unit") != "min":
            raise ValueError("Unsupported collection time units")
        def read(descriptor):
            content = archive.read(descriptor["member"])
            if hashlib.sha256(content).hexdigest() != descriptor["sha256"]:
                raise ValueError(f"Checksum mismatch: {descriptor['member']}")
            return content
        samples = []
        for record in manifest["samples"]:
            channels, originals = [], {}
            for descriptor in record["channels"]:
                if descriptor["encoding"] == "cdf":
                    content = read(descriptor["data"])
                    trace, _ = read_chromatogram(Path(descriptor["original_name"]), content)
                    if trace.name != descriptor["name"] or trace.unit != descriptor["unit"]:
                        raise ValueError("CDF channel metadata does not match manifest")
                    originals[trace.name] = (descriptor["original_name"], content)
                elif descriptor["encoding"] == "numpy":
                    values = np.load(BytesIO(read(descriptor["values"])), allow_pickle=False)
                    if "time_grid" in descriptor:
                        grid = descriptor["time_grid"]
                        if grid["count"] != len(values):
                            raise ValueError("Time-grid length does not match signal")
                        times = _number(grid["start"], "Time-grid start") + np.arange(len(values)) * _number(grid["step"], "Time-grid step")
                    else:
                        times = np.load(BytesIO(read(descriptor["times"])), allow_pickle=False)
                    trace = Chromatogram(descriptor["name"], times, values, descriptor["unit"], descriptor.get("wavelength_nm"))
                else:
                    raise ValueError("Unknown chromatogram encoding")
                channels.append(trace)
                if "csv" in descriptor:
                    read(descriptor["csv"])
            samples.append(ReactionSample(record["id"], record["name"], record["source"], tuple(channels), record.get("time_min"),
                                          record.get("source_metadata", ""), originals, record.get("provenance", "")))
        overrides = {(r["sample_id"], r["target_id"]): (r["start_min"], r["end_min"]) for r in manifest.get("overrides", [])}
        individual = {(r["sample_id"], r["target_id"]): IndividualIntegration(**{key: value for key, value in r.items() if key not in ("sample_id", "target_id")})
                      for r in manifest.get("individual_integrations", [])}
        collection = ReactionCollection(samples, [ReactionTarget(**t) for t in manifest["targets"]], manifest["name"], overrides,
                                        manifest.get("ratio_reference"), manifest.get("internal_standard"),
                                        manifest.get("integration_mode", "common"), individual)
    collection.validate()
    return collection
