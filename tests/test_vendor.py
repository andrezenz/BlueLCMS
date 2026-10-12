"""Synthetic vendor containers only; binary signal formats await reference exports."""

import os
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest

from bluelcms.vendor import (MeasurementKey, VendorMeasurement, advion_raw_path,
    decode_advion_scans, decode_agilent_uv, discover_vendor_measurements,
    inspect_agilent, inspect_advion, load_advion_index, load_advion_uv,
    load_vendor_measurement, measurement_key)

REFERENCE_ROOT = os.environ.get("BLUELCMS_REFERENCE_DATA")

needs_reference = pytest.mark.skipif(not REFERENCE_ROOT, reason="set BLUELCMS_REFERENCE_DATA to verify against vendor exports")


def write_scans_xml(count, interval_seconds=0.9, start=0.5):
    rows = "".join(f"<scan><time>{start + index * interval_seconds:.3f}</time><index>{index * 10}</index><size>10</size><tic>{1000 + index}</tic></scan>" for index in range(count))
    return f'<?xml version="1.0" encoding="UTF-8"?><scans version="1.1"><dataType>continuum</dataType><samplesPerScan>3</samplesPerScan><storeAsFloat>false</storeAsFloat>{rows}</scans>'.encode()


def write_datx(path, negative, count=4, uv=True):
    with ZipFile(path, "w") as archive:
        archive.writestr("run.ion", f"<ion><negative>{str(negative).lower()}</negative></ion>")
        archive.writestr("run.masses", np.asarray([100, 100.05, 100.1], dtype="<f4").tobytes())
        archive.writestr("run.scans", write_scans_xml(count))
        if uv:
            archive.writestr("run.scalar", '<scalarChannel version="1.0"><name>UV Scan</name>'
                             '<entry><time>30</time><value>844000000</value></entry>'
                             '<entry><time>60</time><value>845000000</value></entry></scalarChannel>')


def write_agilent_sirslt(path, count=4):
    path.mkdir(parents=True)
    identifier = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    values = np.arange(count, dtype="<f8") - 1
    with ZipFile(path / "run.dx", "w") as archive:
        archive.writestr("injection.acmd", f"<run>Signal179 {identifier} DAD 1 DAD1A DAD1A,Sig=250,4 Ref=off 50 150 -2 4 0.5 {count} 0 0 mAU</run>")
        archive.writestr(f"{identifier}.CH", b"header" + values.tobytes())
    return path


def measurement_for(tmp_path, name="ANZ254R4"):
    agilent = write_agilent_sirslt(tmp_path / "Agilent" / f"2026_10_06_{name}.sirslt")
    folder = tmp_path / "expression" / f"2026_10_6_11_19_59_{name}_1"
    folder.mkdir(parents=True)
    positive, negative = folder / "run_Scan1_is1.datx", folder / "run_Scan2_is2.datx"
    write_datx(positive, negative=False)
    write_datx(negative, negative=True)
    key = MeasurementKey("2026_10_06", name.upper())
    return VendorMeasurement(key, agilent, positive, negative)


def test_measurement_key_normalizes_variable_date_padding(tmp_path):
    assert measurement_key(tmp_path / "2026_10_6_11_19_59_ANZ254R4_1").label == "2026_10_06_ANZ254R4"
    assert measurement_key(tmp_path / "2026_10_06_ANZ254R4.sirslt").label == "2026_10_06_ANZ254R4"


def test_replicates_are_distinct_measurements(tmp_path):
    """A trailing replicate must not merge with its base sample."""
    assert measurement_key(tmp_path / "2026_10_06_ANZ254p1F14_2.sirslt").label == "2026_10_06_ANZ254P1F14_2"
    assert measurement_key(tmp_path / "2026_10_6_11_19_59_ANZ254p1F14_2_Scan2_is2.datx").label == "2026_10_06_ANZ254P1F14_2"
    assert measurement_key(tmp_path / "2026_10_06_ANZ254p1F14.sirslt").label == "2026_10_06_ANZ254P1F14"


def test_replicate_pairs_are_both_discovered(tmp_path):
    for name in ("ANZ254p1F14", "ANZ254p1F14_2"):
        agilent = write_agilent_sirslt(tmp_path / "Agilent" / f"2026_10_06_{name}.sirslt")
        folder = tmp_path / "expression" / f"2026_10_6_11_19_59_{name}_1"
        folder.mkdir(parents=True)
        write_datx(folder / "run_Scan1_is1.datx", negative=False)
        write_datx(folder / "run_Scan2_is2.datx", negative=True)
    assert sorted(item.label for item in discover_vendor_measurements(tmp_path)) == [
        "2026_10_06_ANZ254P1F14", "2026_10_06_ANZ254P1F14_2"]


def test_discovers_one_unambiguous_vendor_measurement(tmp_path):
    agilent = tmp_path / "Agilent" / "2026_10_06_ANZ254R4.sirslt"
    agilent.mkdir(parents=True)
    with ZipFile(agilent / "run.dx", "w") as archive:
        archive.writestr("injection.acmd", "<run>DAD1A,Sig=250,4 Ref=off</run>")
    expression = tmp_path / "expression" / "2026_10_6_11_19_59_ANZ254R4_1"
    expression.mkdir(parents=True)
    write_datx(expression / "Scan1.datx", negative=False)
    write_datx(expression / "Scan2.datx", negative=True)
    measurements = discover_vendor_measurements(tmp_path)
    assert [(item.label, item.advion_positive.name, item.advion_negative.name) for item in measurements] == [
        ("2026_10_06_ANZ254R4", "Scan1.datx", "Scan2.datx")]
    metadata = inspect_advion(measurements[0].advion_positive)
    assert metadata.polarity == "+"
    assert metadata.point_count == 3
    assert inspect_agilent(agilent).channels[0].wavelength_nm == 250


def test_duplicate_sources_are_not_guessed(tmp_path):
    (tmp_path / "2026_10_06_ANZ254R4.sirslt").mkdir()
    (tmp_path / "other_2026_10_06_ANZ254R4.sirslt").mkdir()
    expression = tmp_path / "2026_10_6_11_19_59_ANZ254R4_1"
    expression.mkdir()
    write_datx(expression / "Scan1.datx", negative=False)
    write_datx(expression / "Scan2.datx", negative=True)
    assert discover_vendor_measurements(tmp_path) == []


def test_decodes_agilent_fixed_wavelength_signal(tmp_path):
    run = tmp_path / "2026_10_06_ANZ254R4.sirslt"
    run.mkdir()
    identifier = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    metadata = f"<run>Signal179 {identifier} DAD 1 DAD1A DAD1A,Sig=250,4 Ref=off 50 150 -2 4 0.5 3 0 0 mAU</run>"
    with ZipFile(run / "run.dx", "w") as archive:
        archive.writestr("injection.acmd", metadata)
        archive.writestr(f"{identifier}.CH", b"header" + np.asarray([-4, 0, 8], dtype="<f8").tobytes())
    scans = decode_agilent_uv(run)
    np.testing.assert_allclose([scan.time for scan in scans], [0, 50 / 60000, 100 / 60000])
    np.testing.assert_allclose([scan.intensity[0] for scan in scans], [-2, 0, 4])
    np.testing.assert_equal(scans[0].wavelength, [250])


def test_advion_index_converts_seconds_to_minutes(tmp_path):
    path = tmp_path / "Scan2.datx"
    write_datx(path, negative=True, count=3)
    index = load_advion_index(path)
    assert index.polarity == "-"
    assert index.scan_count == 3
    np.testing.assert_allclose(index.times_minutes, [0.5 / 60, 1.4 / 60, 2.3 / 60], rtol=1e-5)
    np.testing.assert_allclose(index.tic, [1000, 1001, 1002])
    np.testing.assert_allclose(index.masses, [100, 100.05, 100.1])


def test_advion_index_rejects_mismatched_mass_axis(tmp_path):
    path = tmp_path / "Scan1.datx"
    with ZipFile(path, "w") as archive:
        archive.writestr("run.ion", "<ion><negative>false</negative></ion>")
        archive.writestr("run.masses", np.asarray([100, 100.05], dtype="<f4").tobytes())
        archive.writestr("run.scans", write_scans_xml(2))
    with pytest.raises(ValueError, match="samples per scan"):
        load_advion_index(path)


def test_advion_uv_channel_uses_minutes(tmp_path):
    path = tmp_path / "Scan1.datx"
    write_datx(path, negative=False)
    uv = load_advion_uv(path)
    assert uv.name == "UV Scan"
    np.testing.assert_allclose(uv.times_minutes, [0.5, 1.0])
    np.testing.assert_allclose(uv.intensity, [844000000, 845000000])


def test_advion_without_uv_channel_reports_clearly(tmp_path):
    path = tmp_path / "Scan2.datx"
    write_datx(path, negative=True, uv=False)
    with pytest.raises(ValueError, match="no UV channel"):
        load_advion_uv(path)


def test_advion_spectra_require_an_expanded_raw_file(tmp_path):
    path = tmp_path / "Scan1.datx"
    write_datx(path, negative=False)
    assert advion_raw_path(path) is None
    with pytest.raises(ValueError, match="Mass Express"):
        decode_advion_scans(path, "+")


def write_raw_matrix(source, rows, points=3, offset=0):
    """Write the expanded matrix Advion materialises beside a datx."""
    path = source.parent / f"{source.stem}/{source.stem}.raw"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((np.arange(rows * points, dtype="<f4") + offset).tobytes())
    return path


def test_measurement_loads_chromatograms_without_spectra(tmp_path):
    run = load_vendor_measurement(measurement_for(tmp_path))
    assert len(run.dad) == 4
    np.testing.assert_allclose(run.uv_wavelengths(), [250])
    np.testing.assert_allclose([scan.intensity[0] for scan in run.dad], [-0.5, 0, 0.5, 1])
    assert sorted({polarity for _, _, polarity in run.tic}) == ["+", "-"]
    assert [trace.name for trace in run.auxiliary] == ["UV Scan"]
    # No expanded .raw, so no mass data is invented.
    assert run.scans == ()
    assert run.tic_points() == run.tic


def test_expanded_raw_file_enables_mass_spectra(tmp_path):
    measurement = measurement_for(tmp_path)
    write_raw_matrix(measurement.advion_positive, rows=4)
    write_raw_matrix(measurement.advion_negative, rows=4, offset=100)
    run = load_vendor_measurement(measurement)
    assert len(run.scans) == 8
    assert sorted({scan.polarity for scan in run.scans}) == ["+", "-"]
    np.testing.assert_allclose(run.scans[0].mz, [100, 100.05, 100.1])
    np.testing.assert_allclose(run.scans[0].intensity, [0, 1, 2])
    np.testing.assert_allclose(run.scans[4].intensity, [100, 101, 102])
    # One shared mass axis keeps a 527 x 20996 run small.
    assert all(scan.mz is run.scans[0].mz for scan in run.scans)


def test_mismatched_raw_size_is_rejected(tmp_path):
    measurement = measurement_for(tmp_path)
    write_raw_matrix(measurement.advion_positive, rows=5)
    with pytest.raises(ValueError, match="Unexpected Advion .raw size"):
        decode_advion_scans(measurement.advion_positive)


@needs_reference
def test_real_datx_index_matches_acquisition_metadata():
    """Vendor runs must expose a monotonic time axis, TICs and the declared mass axis."""
    root = Path(REFERENCE_ROOT) / "expression"
    checked = 0
    for path in sorted(root.rglob("*.datx")):
        index = load_advion_index(path)
        assert index.polarity in "+-"
        assert index.scan_count == 527
        assert len(index.masses) == 20996
        assert 149.6 < float(index.masses[0]) and float(index.masses[-1]) < 1199.5
        assert np.all(np.diff(index.times_minutes) > 0)
        assert np.all(index.tic > 0)
        checked += 1
    assert checked, f"no .datx files found under {root}"


@needs_reference
def test_real_advion_uv_matches_reported_scan_range():
    """The CMS UV channel must be monotonic in time and span the reported run."""
    root = Path(REFERENCE_ROOT) / "expression"
    checked = 0
    for path in sorted(root.rglob("*.datx")):
        try:
            uv = load_advion_uv(path)
        except ValueError:
            continue
        assert uv.name == "UV Scan"
        assert np.all(np.diff(uv.times_minutes) > 0)
        assert len(uv.times_minutes) == 1054
        assert 7.9 < float(uv.times_minutes[-1]) < 8.1
        assert np.all(uv.intensity > 0)
        checked += 1
    assert checked, f"no Advion UV channels found under {root}"


@needs_reference
def test_real_agilent_uv_matches_aia_export():
    """The Signal179 decoder must reproduce every exported AIA absorbance value."""
    root = Path(REFERENCE_ROOT) / "Agilent"
    pairs = [(run, run.with_suffix(".AIA")) for run in sorted(root.glob("*.sirslt")) if run.with_suffix(".AIA").is_dir()]
    for run, aia in pairs:
        export = next(iter(aia.glob("*.cdf")), None)
        if export is None:
            continue
        from bluelcms.vendor import load_agilent_aia
        expected = load_agilent_aia(export).intensity
        decoded = np.asarray([scan.intensity[0] for scan in decode_agilent_uv(run)])
        np.testing.assert_allclose(decoded, expected, rtol=0, atol=0)
    assert pairs, f"no .sirslt runs with .AIA exports under {root}"