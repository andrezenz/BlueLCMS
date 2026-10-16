"""Discovery and metadata inspection for supported vendor data folders.

Binary signal decoding deliberately lives behind the two decode functions below.
The surrounding application can therefore identify one logical measurement before
the vendor-specific binary layouts have been validated against reference exports.
"""

from dataclasses import dataclass
from pathlib import Path
import re
import struct
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import numpy as np

from .mzml import DADScan, NamedTrace, Run, Scan


_DATE_PART = re.compile(r"^(20\d{2})[_-](\d{1,2})[_-](\d{1,2})$")
_SAMPLE_PART = re.compile(r"^[A-Za-z]+\d+(?:[A-Za-z]+\d+)*$")
_TRAILING_DIGITS = re.compile(r"^\d+$")
# Datx file names append the polarity source, e.g. "..._ANZ254p1F14_2_Scan2_is2.datx".
_SCAN_MARKER = re.compile(r"^Scan\d+(_is\d+)?$", re.IGNORECASE)


class VendorDecoderUnavailable(RuntimeError):
    """Raised when a measurement cannot yet be decoded to the needed detail."""


_NETCDF_TYPES = {
    1: (">i1", 1), 2: (">S1", 1), 3: (">i2", 2),
    4: (">i4", 4), 5: (">f4", 4), 6: (">f8", 8),
}


def _netcdf_string(data: memoryview, offset: int) -> tuple[str, int]:
    length = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    value = bytes(data[offset:offset + length]).decode("latin-1")
    return value, offset + ((length + 3) & ~3)


def _netcdf_attributes(data: memoryview, offset: int) -> int:
    tag = struct.unpack_from(">I", data, offset)[0]
    if tag == 0:
        # Agilent writes the optional count field even for an empty list.
        return offset + 8
    if tag != 12:
        raise ValueError("Invalid NetCDF attribute list")
    count = struct.unpack_from(">I", data, offset + 4)[0]
    offset += 8
    for _ in range(count):
        _, offset = _netcdf_string(data, offset)
        type_code, length = struct.unpack_from(">II", data, offset)
        offset += 8 + ((_NETCDF_TYPES[type_code][1] * length + 3) & ~3)
    return offset


def _read_netcdf_classic(path: Path) -> dict[str, np.ndarray]:
    """Read fixed-size variables from the NetCDF classic files Agilent AIA emits."""
    data = memoryview(path.read_bytes())
    if data[:3].tobytes() != b"CDF" or data[3] not in (1, 2):
        raise ValueError("Expected a NetCDF classic file")
    offset = 8
    dimensions = []
    tag = struct.unpack_from(">I", data, offset)[0]
    if tag:
        if tag != 10:
            raise ValueError("Invalid NetCDF dimension list")
        count = struct.unpack_from(">I", data, offset + 4)[0]
        offset += 8
        for _ in range(count):
            _, offset = _netcdf_string(data, offset)
            length = struct.unpack_from(">I", data, offset)[0]
            dimensions.append(length)
            offset += 4
    else:
        offset += 4
    offset = _netcdf_attributes(data, offset)
    tag = struct.unpack_from(">I", data, offset)[0]
    if tag == 0:
        return {}
    if tag != 11:
        raise ValueError("Invalid NetCDF variable list")
    count = struct.unpack_from(">I", data, offset + 4)[0]
    offset += 8
    variables = {}
    for _ in range(count):
        name, offset = _netcdf_string(data, offset)
        dimension_count = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        dimension_ids = struct.unpack_from(f">{dimension_count}I", data, offset) if dimension_count else ()
        offset += 4 * dimension_count
        offset = _netcdf_attributes(data, offset)
        type_code, _, begin = struct.unpack_from(">III", data, offset)
        offset += 12
        dtype, item_size = _NETCDF_TYPES[type_code]
        shape = tuple(dimensions[index] for index in dimension_ids)
        variables[name] = np.frombuffer(data, dtype=dtype, count=int(np.prod(shape, dtype=int) or 1), offset=begin).reshape(shape).copy()
    return variables


@dataclass(frozen=True, order=True)
class MeasurementKey:
    date: str
    sample: str
    replicate: int = 1

    @property
    def label(self) -> str:
        suffix = "" if self.replicate <= 1 else f"_{self.replicate}"
        return f"{self.date}_{self.sample}{suffix}"


@dataclass(frozen=True)
class VendorMeasurement:
    """One sidebar measurement backed by independent HPLC and MS acquisitions."""
    key: MeasurementKey
    agilent: Path
    advion_positive: Path
    advion_negative: Path

    @property
    def label(self) -> str:
        return self.key.label


@dataclass(frozen=True)
class AgilentChannel:
    name: str
    wavelength_nm: float | None


@dataclass(frozen=True)
class AgilentMetadata:
    path: Path
    channels: tuple[AgilentChannel, ...]


@dataclass(frozen=True)
class AgilentReference:
    """A numeric chromatogram exported by Agilent in AIA/NetCDF format."""
    delay_minutes: float
    interval_minutes: float
    intensity: np.ndarray


@dataclass(frozen=True)
class AdvionMetadata:
    path: Path
    polarity: str
    scan_count: int | None
    point_count: int | None


@dataclass(frozen=True)
class AdvionUvTrace:
    """The CMS UV/AI-LC chromatogram recorded alongside an Advion ``.datx``."""
    name: str
    times_minutes: np.ndarray
    intensity: np.ndarray


@dataclass(frozen=True)
class AdvionScanIndex:
    """Scan times, total ion currents and mass axis declared by an Advion ``.datx``.

    Only values the vendor writes as readable metadata are decoded here. The
    per-scan intensity blocks remain undecoded, so this supports chromatogram
    display but not mass spectra.
    """
    path: Path
    polarity: str
    masses: np.ndarray
    times_minutes: np.ndarray
    tic: np.ndarray

    @property
    def scan_count(self) -> int:
        return len(self.times_minutes)


def measurement_key(path: Path) -> MeasurementKey | None:
    """Extract a normalized date/sample/replicate identity from a vendor path.

    Both instruments place a replicate as the numeric token right after the
    sample name (``ANZ254p1F14_2``). It must stay part of the identity, otherwise
    a sample and its replicate merge and both measurements are discarded.
    """
    for candidate in (path.stem, *(parent.stem for parent in path.parents)):
        tokens = [token for token in re.split(r"[_-]", candidate) if token]
        for start in range(len(tokens) - 2):
            date = _DATE_PART.match(f"{tokens[start]}_{tokens[start+1]}_{tokens[start+2]}")
            if not date:
                continue
            rest = tokens[start + 3:]
            sample = next((index for index, token in enumerate(rest) if _SAMPLE_PART.match(token)), None)
            if sample is None:
                continue
            replicate = int(rest[sample + 1]) if len(rest) > sample + 1 and _TRAILING_DIGITS.match(rest[sample + 1]) else 1
            normalized = "_".join((date[1], f"{int(date[2]):02d}", f"{int(date[3]):02d}"))
            return MeasurementKey(normalized, rest[sample].upper(), replicate)
    return None


def _xml_member(path: Path, suffix: str) -> ElementTree.Element | None:
    try:
        with ZipFile(path) as archive:
            name = next((name for name in archive.namelist() if name.lower().endswith(suffix.lower())), None)
            return ElementTree.fromstring(archive.read(name)) if name else None
    except (BadZipFile, OSError, ElementTree.ParseError):
        return None


def _member_bytes(path: Path, suffix: str) -> bytes | None:
    try:
        with ZipFile(path) as archive:
            name = next((item for item in archive.namelist() if item.lower().endswith(suffix.lower())), None)
            return archive.read(name) if name else None
    except (BadZipFile, OSError, KeyError):
        return None


def _advion_polarity(path: Path) -> str:
    """Read ESI polarity from the ion-source metadata."""
    root = _xml_member(path, ".ion")
    if root is None:
        return "?"
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() == "negative" and element.text:
            return "-" if element.text.strip().lower() == "true" else "+"
    return "?"


def load_advion_index(path: Path) -> AdvionScanIndex:
    """Decode the readable scan index of an Advion ESI-MS ``.datx`` acquisition.

    Scan times in ``.scans`` are recorded in seconds; BlueLCMS works in minutes.
    """
    root = _xml_member(path, ".scans")
    masses_data = _member_bytes(path, ".masses")
    if root is None or masses_data is None:
        raise ValueError(f"Unsupported Advion data file: {path}")
    masses = np.frombuffer(masses_data, dtype="<f4").astype(np.float32)
    expected = root.findtext("samplesPerScan")
    if expected is not None and int(expected) != len(masses):
        raise ValueError(f"Advion mass axis has {len(masses)} points but {expected} samples per scan are declared")
    scans = root.findall("scan")
    times = np.asarray([float(scan.findtext("time")) / 60 for scan in scans], dtype=np.float32)
    tic = np.asarray([float(scan.findtext("tic")) for scan in scans], dtype=np.float32)
    if not len(times):
        raise ValueError(f"Advion data file contains no scans: {path}")
    if np.any(np.diff(times) < 0):
        order = np.argsort(times, kind="stable")
        times, tic = times[order], tic[order]
    return AdvionScanIndex(path, _advion_polarity(path), masses, times, tic)


def inspect_agilent(path: Path) -> AgilentMetadata:
    """Read declared UV signal channels without touching their binary trace data."""
    archive = next((item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".dx"), None) if path.is_dir() else path
    root = _xml_member(archive, ".acmd") if archive else None
    text = " ".join(value.strip() for value in root.itertext() if value.strip()) if root is not None else ""
    channels = tuple(
        AgilentChannel(match["name"], float(match["wavelength"]))
        for match in re.finditer(r"(?P<name>DAD\d+[A-Z]),Sig=(?P<wavelength>\d+(?:\.\d+)?)\s*,", text, re.IGNORECASE)
    )
    return AgilentMetadata(path, channels)


def load_agilent_aia(path: Path) -> AgilentReference:
    """Read an Agilent AIA NetCDF chromatogram for decoder verification."""
    variables = _read_netcdf_classic(path)
    try:
        intensity = variables["ordinate_values"].astype(np.float32)
        delay = float(variables["actual_delay_time"])
        interval = float(variables["actual_sampling_interval"])
    except KeyError as error:
        raise ValueError(f"Unsupported Agilent AIA chromatogram: missing {error.args[0]}") from error
    return AgilentReference(delay, interval, intensity)


def _agilent_trace_specs(path: Path):
    archive = next((item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".dx"), None)
    root = _xml_member(archive, ".acmd") if archive else None
    text = " ".join(value.strip() for value in root.itertext() if value.strip()) if root is not None else ""
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
    pattern = re.compile(
        rf"Signal179\s+(?P<identifier>[\da-f-]+).*?"
        rf"(?P<name>DAD\d+[A-Z]),Sig=(?P<wavelength>{number}),(?:[^\s]+)\s+Ref=off\s+"
        rf"(?P<interval>\d+)\s+\d+\s+{number}\s+{number}\s+(?P<scale>{number})\s+(?P<count>\d+)",
        re.IGNORECASE,
    )
    return tuple((match["identifier"], match["name"], float(match["wavelength"]), int(match["interval"]), float(match["scale"]), int(match["count"])) for match in pattern.finditer(text))


def load_advion_uv(path: Path) -> AdvionUvTrace:
    """Decode the scalar UV channel that Advion records next to the MS data.

    Scan times are in seconds and BlueLCMS works in minutes. Older runs may omit
    this channel, in which case a ``ValueError`` is raised.
    """
    root = _xml_member(path, ".scalar")
    if root is None:
        raise ValueError(f"Advion data file has no UV channel: {path}")
    entries = root.findall("entry")
    if not entries:
        raise ValueError(f"Advion UV channel is empty: {path}")
    times = np.asarray([float(entry.findtext("time")) / 60 for entry in entries], dtype=np.float32)
    intensity = np.asarray([float(entry.findtext("value")) for entry in entries], dtype=np.float32)
    order = np.argsort(times, kind="stable")
    return AdvionUvTrace(root.findtext("name") or "UV Scan", times[order], intensity[order])


def inspect_advion(path: Path) -> AdvionMetadata:
    """Read polarity, scan count and mass-axis size without decoding intensities."""
    try:
        index = load_advion_index(path)
    except ValueError:
        return AdvionMetadata(path, _advion_polarity(path), None, None)
    return AdvionMetadata(path, index.polarity, index.scan_count, len(index.masses))


def discover_vendor_measurements(folder: Path, advion_folder: Path | None = None) -> list[VendorMeasurement]:
    """Find unambiguous Agilent HPLC/DAD and Advion ESI-MS measurement pairs.

    Both Agilent and Advion files are located recursively (``**/*``) inside the
    supplied folder(s).  When *advion_folder* is ``None`` the same *folder* is
    searched for both instrument types – this covers the common case where the
    ``Agilent/`` and ``expression/`` sub‑folders live under one data root.

    Duplicate identifiers are never guessed – a measurement is only created when
    exactly one Agilent run and one positive + one negative Advion run share the
    same date‑/sample key.
    """
    agilent: dict[str, list[Path]] = {}
    advion: dict[str, dict[str, list[Path]]] = {}

    # ---- collect Agilent paths (recursive) ------------------------------------
    for path in folder.rglob("**/*.sirslt"):
        if key := measurement_key(path):
            agilent.setdefault(key, []).append(path)

    # ---- collect Advion paths -------------------------------------------------
    advion_src = advion_folder if advion_folder is not None else folder
    for path in advion_src.rglob("**/*.datx"):
        if key := measurement_key(path):
            polarity = inspect_advion(path).polarity
            if polarity in "+-":
                advion.setdefault(key, {}).setdefault(polarity, []).append(path)

    measurements: list[VendorMeasurement] = []
    for key, hplc_paths in agilent.items():
        polarities = advion.get(key, {})
        # Exactly one Agilent run and one positive + one negative Advion run.
        if len(hplc_paths) == 1 and len(polarities.get("+", [])) == 1 and len(polarities.get("-", [])) == 1:
            measurements.append(
                VendorMeasurement(key, hplc_paths[0], polarities["+"][0], polarities["-"][0])
            )
    return sorted(measurements, key=lambda m: m.key, reverse=True)


def decode_agilent_uv(path: Path) -> tuple[DADScan, ...]:
    """Decode fixed-wavelength Agilent Signal179 DAD traces from a ``.sirslt`` run."""
    archive_path = next((item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".dx"), None)
    if archive_path is None:
        raise ValueError(f"No Agilent .dx archive in {path}")
    scans = []
    with ZipFile(archive_path) as archive:
        for identifier, _, wavelength, interval_ms, scale, count in _agilent_trace_specs(path):
            try:
                raw = archive.read(f"{identifier}.CH")
            except KeyError as error:
                raise ValueError(f"Missing Agilent trace {identifier}.CH") from error
            data_offset = len(raw) - count * np.dtype("<f8").itemsize
            if data_offset < 0:
                raise ValueError(f"Agilent trace {identifier}.CH is shorter than its declared sample count")
            # Signal179 stores integer detector counts as float64 values at the end
            # of the channel file. The XML scale converts them to the declared unit.
            intensity = np.frombuffer(raw, dtype="<f8", count=count, offset=data_offset).astype(np.float32) * scale
            axis = np.asarray([wavelength], dtype=np.float32)
            scans.extend(DADScan(index * interval_ms / 60000, axis, np.asarray([value], dtype=np.float32)) for index, value in enumerate(intensity))
    if not scans:
        raise ValueError(f"No fixed-wavelength DAD signal found in {path}")
    return tuple(scans)


def advion_raw_path(path: Path) -> Path | None:
    """Locate the expanded float32 matrix Advion writes beside a ``.datx``.

    Advion Mass Express materialises a ``.raw`` file when a run is opened. It is
    a plain ``scan_count * samples_per_scan`` float32 array in scan order and is
    the only currently readable source of per-scan intensities.
    """
    sibling = path.parent / f"{path.stem}/{path.stem}.raw"
    if sibling.is_file():
        return sibling
    alongside = path.with_suffix(".raw")
    return alongside if alongside.is_file() else None


def decode_advion_raw(path: Path) -> np.ndarray:
    """Read the expanded Advion ``.raw`` matrix as one float32 row per scan.

    The row count and width must agree with the metadata in the matching
    ``.datx``; anything else means the file does not belong to this run.
    """
    raw = advion_raw_path(path)
    if raw is None:
        raise ValueError(f"No expanded Advion .raw file beside {path.name}; open the run in Advion Mass Express once")
    data = raw.read_bytes()
    index = load_advion_index(path)
    expected = index.scan_count * len(index.masses)
    if len(data) != expected * 4:
        raise ValueError(f"Unexpected Advion .raw size for {path.name}: {len(data)} bytes, expected {expected * 4}")
    return np.frombuffer(data, dtype="<f4").reshape(index.scan_count, len(index.masses))


def decode_advion_scans(path: Path, polarity: str = "") -> tuple[Scan, ...]:
    """Decode per-scan Advion spectra from the expanded ``.raw`` matrix.

    The proprietary ``.spectra`` blocks inside the ``.datx`` remain undecoded:
    their sizes range from about 0.94 to 1.98 bytes per point, which fits no
    fixed-width or presence-bitmap layout, so per-scan intensities are read from
    the ``.raw`` file Advion writes when the run is opened.
    """
    index = load_advion_index(path)
    polarity = polarity or index.polarity
    if polarity not in ("+", "-"):
        raise ValueError(f"Unknown Advion polarity {polarity!r} for {path.name}")
    matrix = decode_advion_raw(path)
    # Every scan shares one mass axis, so it is held once rather than per scan.
    axis = index.masses
    return tuple(
        Scan(float(time), polarity, axis, matrix[row])
        for row, time in enumerate(index.times_minutes)
    )


def load_vendor_measurement(measurement: VendorMeasurement, progress=None) -> Run:
    """Combine an Agilent HPLC/DAD run with its matched Advion ESI-MS acquisitions.

    The Agilent UV trace becomes the displayable UV signal. Advion contributes
    positive and negative total ion currents from its scan index, plus any CMS UV
    channel. Mass spectra are attached when an expanded ``.raw`` matrix exists.
    """
    def report(done, total):
        if progress:
            progress(done, total)

    total = 3 + sum(1 for source in (measurement.advion_positive, measurement.advion_negative) if advion_raw_path(source))
    step = 0
    dad = decode_agilent_uv(measurement.agilent)
    report(step := step + 1, total)
    auxiliary = {}
    tic = []
    scans = []
    for source in (measurement.advion_positive, measurement.advion_negative):
        index = load_advion_index(source)
        tic.extend((float(time), float(total_ions), index.polarity) for time, total_ions in zip(index.times_minutes, index.tic))
        report(step := step + 1, total)
        # Both polarities can record the same CMS channel; plot it once.
        try:
            uv = load_advion_uv(source)
        except ValueError:
            pass
        else:
            auxiliary.setdefault(uv.name, NamedTrace(uv.name, uv.times_minutes, uv.intensity))
        if raw := advion_raw_path(source):
            decoded = decode_advion_scans(source)
            # Both polarities share one mass axis; reuse the first to save memory.
            if scans:
                shared = scans[0].mz
                decoded = tuple(scan if scan.mz is shared else Scan(scan.time, scan.polarity, shared, scan.intensity) for scan in decoded)
            scans.extend(decoded)
            report(step := step + 1, total)
    return Run(tuple(dad), tuple(scans), 0, tuple(sorted(tic)), tuple(auxiliary.values()))
