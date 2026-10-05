"""Synthetic data only: no vendor or SynthesisMapper fixtures."""

import base64
import gzip

import numpy as np
import pytest
from pyteomics.auxiliary import unitfloat

from bluelcms.mzml import display_bin_width, discover_files, file_display_name, load_compact_cache, load_run, mass_histograms, parse_spectra, rebin_histogram, write_compact_cache


def spectrum(time=1, polarity="positive scan", level=1, **arrays):
    return {
        "scanList": {"scan": [{"scan start time": unitfloat(time, "minute")}]},
        "ms level": level, polarity: "", **arrays,
    }


def test_discovery(tmp_path):
    for name in ("2026_01_01_old.mzML", "2026_09_30_new.mzML", "z.mzML", "A.MZML", "compressed.gz", "ignore.txt"):
        (tmp_path / name).touch()
    (tmp_path / "directory.mzml").mkdir()
    paths = discover_files(tmp_path)
    assert [p.name for p in paths] == ["2026_09_30_new.mzML", "2026_01_01_old.mzML", "A.MZML", "compressed.gz", "z.mzML"]
    assert file_display_name(paths[0], False) == "new.mzML"
    assert file_display_name(paths[0], True) == "2026_09_30_new.mzML"


def test_dad_nearest_wavelength_and_sorting():
    run = parse_spectra([
        spectrum(time=2, **{"wavelength array": [250, 253.5, 260], "intensity array": [9, 3, 7]}),
        spectrum(time=1, **{"wavelength array": [250, 254, 260], "intensity array": [9, -2, 7]}),
        spectrum(time=3, **{"wavelength array": [300, 310], "intensity array": [10, 20]}),
    ])
    np.testing.assert_equal(run.times, [1, 2])
    np.testing.assert_equal(run.uv, [-2, 3])
    np.testing.assert_equal(run.wavelengths, [254, 253.5])
    times, signal, used = run.uv_trace(260)
    np.testing.assert_equal(times, [1, 2])
    np.testing.assert_equal(signal, [7, 7])
    np.testing.assert_equal(used, [260, 260])
    heat_times, heat_wavelengths, heat_values = run.heatmap()
    np.testing.assert_equal(heat_times, [1, 2, 3])
    np.testing.assert_equal(heat_wavelengths, [250, 253.5, 254, 260, 300, 310])
    assert heat_values.shape == (3, 6)


def test_ms1_polarity_inclusive_interval_and_weights():
    def scan(time, polarity="positive scan", level=1):
        return spectrum(time, polarity, level, **{"m/z array": [100.01, 100.04, 200.04], "intensity array": [2, 3, 7]})

    unknown = scan(1)
    del unknown["positive scan"]
    run = parse_spectra([scan(0), scan(1), scan(2), scan(1, "negative scan"), scan(1, level=2), unknown])
    result = mass_histograms(run, 2, 1)
    np.testing.assert_allclose(result["+"][0], [100.05, 200.05])
    np.testing.assert_equal(result["+"][1], [10, 14])
    np.testing.assert_equal(result["-"][1], [5, 7])
    assert run.skipped_scans == 1
    assert not len(run.times)
    assert not len(mass_histograms(run, 10, 11)["+"][0])
    with pytest.raises(ValueError):
        mass_histograms(run, 1, 2, 0)


def test_display_bins_retain_native_detail_when_zoomed():
    assert display_bin_width(100, 1500, 1000) == 2
    assert display_bin_width(100, 100.5, 1000) == 0.03125
    x, y = rebin_histogram(np.array([100.015625, 100.046875]), np.array([2, 3]), 0.0625)
    np.testing.assert_allclose(x, [100.03125])
    np.testing.assert_equal(y, [5])


def test_compact_cache_preserves_native_scans(tmp_path):
    run = parse_spectra([spectrum(time=1, **{"wavelength array": [250, 254], "intensity array": [2, 5]}), spectrum(time=2, **{"m/z array": [100, 100.03125], "intensity array": [3, 7]})])
    cache = write_compact_cache(run, tmp_path / "sample.bluelcms.npz")
    loaded = load_compact_cache(cache)
    assert loaded.scans[0].polarity == "+"
    np.testing.assert_allclose(loaded.scans[0].mz, [100, 100.03125])
    np.testing.assert_allclose(loaded.scans[0].intensity, [3, 7])
    np.testing.assert_allclose(loaded.dad[0].wavelength, [250, 254])


def test_compact_cache_preserves_variable_axes(tmp_path):
    run = parse_spectra([
        spectrum(time=1, **{"m/z array": [100, 100.03125], "intensity array": [3, 7]}),
        spectrum(time=2, polarity="negative scan", **{"m/z array": [200], "intensity array": [11]}),
    ])
    loaded = load_compact_cache(write_compact_cache(run, tmp_path / "variable.bluelcms.npz"))
    assert [scan.polarity for scan in loaded.scans] == ["+", "-"]
    np.testing.assert_allclose(loaded.scans[1].mz, [200])
    np.testing.assert_allclose(loaded.scans[1].intensity, [11])


def test_time_units_and_invalid_arrays():
    record = spectrum(**{"m/z array": [100], "intensity array": [3]})
    record["scanList"]["scan"][0]["scan start time"] = unitfloat(90, "second")
    assert parse_spectra([record]).scans[0].time == 1.5
    record["intensity array"] = [1, 2]
    with pytest.raises(ValueError, match="Invalid"):
        parse_spectra([record])


def write_mzml(path):
    """Small mzML with genuine base64 arrays, DAD and both MS polarities."""
    def cv(accession, name, value="", units=""):
        return f'<cvParam cvRef="MS" accession="MS:{accession}" name="{name}" value="{value}" {units}/>'

    def array(accession, name, values):
        binary = base64.b64encode(np.asarray(values, dtype="<f8").tobytes()).decode()
        return f'<binaryDataArray encodedLength="{len(binary)}">{cv("1000523", "64-bit float")}{cv("1000576", "no compression")}{cv(accession, name)}<binary>{binary}</binary></binaryDataArray>'

    records = []
    for index, (kind, axis, values, signal) in enumerate([
        ("dad", "wavelength array", [250, 254, 260], [1, 12, 3]),
        ("positive", "m/z array", [100, 200, 300], [2, 4, 6]),
        ("negative", "m/z array", [150, 250, 350], [3, 5, 7]),
    ]):
        params = cv("1000806", "absorption spectrum") if kind == "dad" else cv("1000511", "ms level", 1) + cv("1000130" if kind == "positive" else "1000129", f"{kind} scan")
        time = cv("1000016", "scan start time", 60, 'unitCvRef="UO" unitAccession="UO:0000010" unitName="second"')
        arrays = array("1000617" if kind == "dad" else "1000514", axis, values) + array("1000515", "intensity array", signal)
        records.append(f'<spectrum index="{index}" id="scan={index + 1}" defaultArrayLength="3">{params}<scanList count="1"><scan>{time}</scan></scanList><binaryDataArrayList count="2">{arrays}</binaryDataArrayList></spectrum>')
    path.write_text('<?xml version="1.0"?><mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0"><run id="synthetic"><spectrumList count="3">' + ''.join(records) + '</spectrumList></run></mzML>')
    return path


def test_real_mzml_decoding(tmp_path):
    path = write_mzml(tmp_path / "sample.mzML")
    progress = []
    dad = []
    ms_scans = []
    run = load_run(path, progress=lambda copied, total: progress.append((copied, total)), dad_callback=dad.append, scan_callback=ms_scans.append)
    np.testing.assert_equal(run.times, [1])
    np.testing.assert_equal(run.uv, [12])
    assert [s.polarity for s in run.scans] == ["+", "-"]
    assert all(s.time == 1 for s in run.scans)
    assert progress[-1] == (path.stat().st_size, path.stat().st_size)
    assert [(scan.time, scan.wavelength.tolist()) for scan in dad] == [(1, [250.0, 254.0, 260.0])]
    assert [scan.intensity.sum() for scan in ms_scans] == [12, 15]


def test_gzip_mzml_decoding_and_compressed_progress(tmp_path):
    source = write_mzml(tmp_path / "sample.mzML")
    compressed = tmp_path / "sample.gz"
    with source.open("rb") as input_file, gzip.open(compressed, "wb") as output_file:
        output_file.write(input_file.read())
    progress = []
    run = load_run(compressed, progress=lambda copied, total: progress.append((copied, total)))
    assert [scan.polarity for scan in run.scans] == ["+", "-"]
    assert progress[-1] == (compressed.stat().st_size, compressed.stat().st_size)
