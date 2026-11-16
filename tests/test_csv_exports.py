import json
from pathlib import Path

import numpy as np
import pytest

from bluelcms.csv_exports import discover_csv_exports, load_csv_cached, load_csv_export
from bluelcms.mzml import discover_files, load_run, mass_histograms, write_compact_cache


RAW = r"C:\Raw Files\sample.raw"


def write_spectrum(path, polarity="+", raw=RAW, points=None):
    points = points if points is not None else [(400.000010001, 10.123456789), (400.000020002, 20.987654321), (501.123456789, 5.5)]
    lines = ["SPECTRUM - MS", raw, f" FTMS {polarity} c ESI Full ms [100.00-800.00]",
             "Scan #:225-288", "RT: 2.1-2.6", "AV: 64", f"Data points: {len(points)}", "Mass,Intensity"]
    path.write_text("\n".join(lines + [f"{x:.12f},{y:.12f}" for x, y in points]) + "\n")
    return path


def write_tic(path, raw=RAW):
    path.write_text("CHROMATOGRAM\n" + raw + "\nData points: 3\nTime(min),Relative Abundance\n0.005541667,48571597\n2.3,65527253\n5.997916667,50917797\n")
    return path


@pytest.mark.parametrize("polarity", ("+", "-"))
def test_static_spectrum_metadata_precision_and_no_synthetic_scans(tmp_path, polarity):
    source = write_spectrum(tmp_path / "spectrum.csv", polarity)
    run = load_run(source)
    assert not run.scans and not run.dad and not run.chromatograms
    spectrum, = run.exported_spectra
    assert spectrum.polarity == polarity
    assert spectrum.start_min == 2.1 and spectrum.end_min == 2.6 and spectrum.averaged_scans == 64
    assert spectrum.mz.dtype == np.float64
    np.testing.assert_array_equal(spectrum.mz, [400.000010001, 400.000020002, 501.123456789])
    first = mass_histograms(run, 2.1, 2.6)
    different_interval = mass_histograms(run, 10, 11)
    np.testing.assert_array_equal(first[polarity][0], spectrum.mz)
    np.testing.assert_array_equal(first[polarity][1], spectrum.intensity)
    np.testing.assert_array_equal(different_interval[polarity][0], spectrum.mz)
    assert not len(first["-" if polarity == "+" else "+"][0])


def test_matching_tic_is_grouped_and_unrelated_csvs_ignored(tmp_path):
    spectrum = write_spectrum(tmp_path / "sample_spectrum.CSV")
    tic = write_tic(tmp_path / "sample_TIC.csv")
    (tmp_path / "report.csv").write_text("time,value\n0,1\n")
    assert discover_files(tmp_path) == [spectrum]
    run = load_csv_export(spectrum)
    assert len(run.chromatograms) == 1 and run.chromatograms[0].name == "TIC"
    assert len(run.exported_spectra) == 1
    assert run.chromatograms[0].values[0] == 48571597  # Must not be rounded to float32.
    assert json.loads(run.source_metadata)["paired_tic"] == str(tic)
    standalone = load_csv_export(tic)
    assert not standalone.exported_spectra and len(standalone.chromatograms) == 1


def test_ambiguous_or_different_raw_source_tics_are_not_guessed(tmp_path):
    spectrum = write_spectrum(tmp_path / "spectrum.csv")
    first = write_tic(tmp_path / "first_TIC.csv", raw=r"C:\other.raw")
    assert not load_csv_export(spectrum).chromatograms
    write_tic(first)
    second = write_tic(tmp_path / "second_TIC.csv")
    run = load_csv_export(spectrum)
    assert not run.chromatograms
    assert "ambiguous" in json.loads(run.source_metadata)["association"]
    assert set(discover_csv_exports([spectrum, first, second])) == {spectrum, first, second}


def test_cache_preserves_hr_precision_companion_changes_and_offline_reopen(tmp_path):
    folder = tmp_path / "remote"; folder.mkdir()
    source = write_spectrum(folder / "spectrum.csv")
    cache = tmp_path / "spectrum.bluelcms.npz"
    initial = load_csv_cached(source, cache)
    assert initial.refresh_cache
    write_compact_cache(initial.run, cache)
    cached = load_csv_cached(source, cache)
    assert not cached.refresh_cache
    np.testing.assert_array_equal(cached.run.exported_spectra[0].mz, initial.run.exported_spectra[0].mz)
    np.testing.assert_array_equal(cached.run.exported_spectra[0].intensity, initial.run.exported_spectra[0].intensity)
    tic = write_tic(folder / "sample_TIC.csv")
    paired = load_csv_cached(source, cache)
    assert paired.refresh_cache and paired.run.chromatograms
    write_compact_cache(paired.run, cache)
    assert not load_csv_cached(source, cache).refresh_cache
    folder.rename(tmp_path / "unmounted")
    offline = load_csv_cached(source, cache)
    assert not offline.refresh_cache
    np.testing.assert_array_equal(offline.run.chromatograms[0].values, paired.run.chromatograms[0].values)
    np.testing.assert_array_equal(offline.run.exported_spectra[0].mz, initial.run.exported_spectra[0].mz)


def test_export_without_polarity_or_mismatched_point_count_is_rejected(tmp_path):
    source = write_spectrum(tmp_path / "spectrum.csv", polarity="?")
    with pytest.raises(ValueError, match="polarity"):
        load_csv_export(source)
    write_spectrum(source)
    source.write_text(source.read_text().replace("Data points: 3", "Data points: 99"))
    with pytest.raises(ValueError, match="count"):
        load_csv_export(source)
