import csv
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pytest

from bluelcms.aia import load_aia
from bluelcms.mzml import Chromatogram, DADScan, Run
from bluelcms.reaction_collections import (IndividualIntegration, ReactionCollection, ReactionSample, ReactionTarget,
                                           create_collection, evaluate, integration_curve,
                                           load_collection, save_collection)
from test_aia import make_aia, write_aia_cdf


def kinetics():
    times = np.linspace(0, 5, 501)
    samples = []
    for i, (left, right) in enumerate(((10, 0), (5, 5), (0, 10))):
        signal = 10 + 2 * times + left * np.maximum(0, 1 - abs(times - 1) / .4) + right * np.maximum(0, 1 - abs(times - 3) / .4)
        samples.append(ReactionSample(f"m{i}", f"Sample {i}", f"/offline/{i}.AIA",
                                      (Chromatogram("DAD1A", times, signal, "mAU"),), i * 5.))
    return ReactionCollection(samples, [ReactionTarget("a", "Starting material", "DAD1A", .5, 1.5),
                                        ReactionTarget("b", "Product", "DAD1A", 2.5, 3.5)],
                              ratio_reference="a", internal_standard="a")


def test_endpoint_baseline_kinetics_ratios_and_zero_denominators():
    collection = kinetics()
    rows = evaluate(collection)
    np.testing.assert_allclose([r["area"] for r in rows], [4, 0, 2, 2, 0, 4], atol=1e-12)
    assert rows[0]["area_percent"] == pytest.approx(100)
    assert rows[3]["area_percent"] == pytest.approx(50)
    assert rows[3]["ratio"] == pytest.approx(1)
    assert rows[3]["normalized_area"] == pytest.approx(1)
    assert rows[-1]["ratio"] is None
    assert rows[-1]["normalized_area"] is None
    collection.targets[0].baseline = "zero"
    assert evaluate(collection)[0]["area"] == pytest.approx(16)


def test_boundary_interpolation_overrides_missing_channels_and_negative_signal():
    trace = Chromatogram("A", np.array([0., 1., 2.]), np.array([10., 14., 12.]), "mAU")
    x, y, baseline = integration_curve(trace, .5, 1.5)
    np.testing.assert_allclose(x, [.5, 1, 1.5])
    assert np.trapezoid(y - baseline, x) == pytest.approx(.75)
    collection = kinetics()
    collection.overrides[("m0", "a")] = (.8, 1.2)
    assert evaluate(collection)[0]["area"] < 4
    collection.samples[0].time_min = None
    assert evaluate(collection)[0]["reaction_time_min"] is None
    collection.samples[1].channels = (replace(collection.samples[1].channels[0], name="Other"),)
    assert evaluate(collection)[2]["area"] is None
    collection.targets[0].end_min = 6
    rows = evaluate(collection)
    assert rows[0]["area"] is not None  # Per-sample override is retained.
    assert rows[-2]["area"] is None
    assert rows[-1]["area_percent"] is None  # Missing starting material is not 100% conversion.
    collection = kinetics()
    trace = collection.samples[0].channels[0]
    collection.samples[0].channels = (replace(trace, values=-trace.values),)
    assert evaluate(collection)[0]["status"] == "Negative area"
    assert evaluate(collection)[0]["area_percent"] is None


def test_embedded_original_cdf_portable_roundtrip_and_csv(tmp_path):
    source = make_aia(tmp_path / "remote" / "sample.AIA")
    collection = create_collection([("Sample", source, load_aia(source))])
    assert collection.samples[0].time_min is None
    assert len(collection.samples[0].originals) == 2
    collection.samples[0].time_min = 15
    collection.targets = [ReactionTarget("a", "Product", "DAD1B", .55, .75)]
    collection.individual_integrations[("m001", "a")] = IndividualIntegration("DAD1B", .55, .75)
    expected = evaluate(collection)
    path = save_collection(collection, tmp_path / "kinetics.zip")
    with ZipFile(path) as archive:
        assert {"manifest.json", "measurements.csv", "targets.csv", "integrations.csv", "README.txt"} <= set(archive.namelist())
        assert len([n for n in archive.namelist() if n.endswith(".cdf")]) == 2
        csv_rows = list(csv.DictReader(StringIO(archive.read("integrations.csv").decode())))
        assert float(csv_rows[0]["reaction_time_min"]) == 15
        assert float(csv_rows[0]["area"]) == pytest.approx(expected[0]["area"])
        assert csv_rows[0]["signal_unit"] == "mAU"
    source.rename(tmp_path / "disconnected")
    reopened = load_collection(path)
    assert evaluate(reopened) == expected
    assert len(reopened.samples[0].originals) == 2
    np.testing.assert_array_equal(reopened.samples[0].channels[0].values, collection.samples[0].channels[0].values)


def test_changed_or_offline_sources_use_loaded_snapshots_and_preserve_precision(tmp_path):
    source = make_aia(tmp_path / "sample.AIA")
    run = load_aia(source)
    write_aia_cdf(source / "sample_sample_DAD1B.cdf", values=(100, 200, 300, 400))
    collection = create_collection([("Sample", source, run)])
    assert not collection.samples[0].originals
    assert "changed" in collection.samples[0].provenance
    path = save_collection(collection, tmp_path / "offline.zip")
    reopened = load_collection(path)
    for before, after in zip(run.chromatograms, reopened.samples[0].channels):
        np.testing.assert_array_equal(before.times, after.times)
        np.testing.assert_array_equal(before.values, after.values)
    source.rename(tmp_path / "gone")
    assert not create_collection([("Sample", source, run)]).samples[0].originals


def test_mzml_selected_wavelength_snapshot_and_independent_arrays(tmp_path):
    run = Run(tuple(DADScan(time, np.array([254., 280.]), np.array([value, value * 2]))
                    for time, value in ((0., 0.), (1., 2.), (2., 0.))), ())
    collection = create_collection([("UV", Path("/unavailable/run.mzML"), run)], wavelength=280)
    trace = collection.samples[0].channels[0]
    assert trace.name == "UV 280 nm" and trace.wavelength_nm == 280
    run.dad[1].intensity[:] = 100
    np.testing.assert_array_equal(trace.values, [0, 4, 0])
    path = save_collection(collection, tmp_path / "uv.zip")
    np.testing.assert_array_equal(load_collection(path).samples[0].channels[0].values, trace.values)


def test_checksum_unknown_format_invalid_times_and_atomic_save(tmp_path):
    collection = kinetics()
    path = save_collection(collection, tmp_path / "valid.zip")
    original = path.read_bytes()
    collection.samples[0].time_min = float("nan")
    with pytest.raises(ValueError, match="finite"):
        save_collection(collection, path)
    assert path.read_bytes() == original
    with ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    member = next(name for name in contents if name.endswith(".npy"))
    contents[member] = b"corrupted"
    bad = tmp_path / "bad.zip"
    with ZipFile(bad, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match="Checksum mismatch"):
        load_collection(bad)
    manifest = json.loads(contents["manifest.json"]); manifest["version"] = 999
    contents["manifest.json"] = json.dumps(manifest).encode()
    with ZipFile(bad, "w") as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match="format/version"):
        load_collection(bad)


def test_incompatible_units_are_not_compared_and_replicate_times_are_preserved():
    collection = kinetics()
    collection.samples[1].channels = (replace(collection.samples[1].channels[0], unit="AU"),)
    rows = evaluate(collection)
    assert rows[2]["area"] is None and rows[2]["status"] == "Incompatible signal units"
    collection.samples[1].time_min = 0
    assert [row["reaction_time_min"] for row in evaluate(collection) if row["target_id"] == "a"] == [0, 0, 10]


def test_optional_csv_chromatograms_are_portable_and_reopenable(tmp_path):
    collection = kinetics()
    path = save_collection(collection, tmp_path / "csv-copy.zip", include_csv=True)
    with ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        channel = manifest["samples"][0]["channels"][0]
        csv_data = np.loadtxt(StringIO(archive.read(channel["csv"]["member"]).decode()), delimiter=",", skiprows=1)
        np.testing.assert_array_equal(csv_data[:, 0], collection.samples[0].channels[0].times)
        np.testing.assert_array_equal(csv_data[:, 1], collection.samples[0].channels[0].values)
    assert evaluate(load_collection(path)) == evaluate(collection)


def test_individual_compound_assignments_percentages_manual_baseline_and_roundtrip(tmp_path):
    collection = kinetics(); collection.integration_mode = "individual"
    collection.individual_integrations = {
        ("m0", "a"): IndividualIntegration("DAD1A", .5, 1.5),
        ("m1", "a"): IndividualIntegration("DAD1A", .5, 1.5),
        ("m1", "b"): IndividualIntegration("DAD1A", 2.5, 3.5),
        ("m2", "b"): IndividualIntegration("DAD1A", 2.5, 3.5),
    }
    rows = evaluate(collection)
    assert rows[0]["area_percent"] == pytest.approx(100)
    assert rows[1]["area"] is None and rows[1]["status"] == "Not integrated"
    assert rows[2]["area_percent"] == pytest.approx(50)
    assert rows[3]["area_percent"] == pytest.approx(50)
    assert rows[-1]["area_percent"] == pytest.approx(100)
    collection.individual_integrations[("m1", "b")] = IndividualIntegration("DAD1A", 2.5, 3.5, "manual", 15., 15.)
    rows = evaluate(collection)
    assert rows[3]["area"] == pytest.approx(3)
    assert rows[3]["area_percent"] == pytest.approx(60)
    path = save_collection(collection, tmp_path / "individual.zip")
    restored = load_collection(path)
    assert restored.integration_mode == "individual"
    assert restored.individual_integrations[("m1", "b")].baseline_start == 15.
    assert evaluate(restored) == rows


def test_horizontal_midpoint_and_manual_baselines_are_reproducible():
    trace = Chromatogram("DAD1A", np.array([0., 1., 2.]), np.array([0., 5., 2.]), "mAU")
    x, y, baseline = integration_curve(trace, 0, 2, "midpoint")
    np.testing.assert_array_equal(baseline, [1, 1, 1])
    assert np.trapezoid(y - baseline, x) == pytest.approx(4)
    _, _, baseline = integration_curve(trace, 0, 2)
    np.testing.assert_array_equal(baseline[[0, -1]], trace.values[[0, -1]])
    x, y, baseline = integration_curve(trace, 0, 2, "manual", 3, 3)
    assert np.trapezoid(y - baseline, x) == pytest.approx(0)


def test_legacy_collection_defaults_to_common_window_mode(tmp_path):
    path = save_collection(kinetics(), tmp_path / "legacy.zip")
    with ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["version"] = 1
    manifest.pop("integration_mode"); manifest.pop("individual_integrations")
    members["manifest.json"] = json.dumps(manifest).encode()
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    restored = load_collection(path)
    assert restored.integration_mode == "common"
    assert evaluate(restored) == evaluate(kinetics())
