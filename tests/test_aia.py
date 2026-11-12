import json
import os
from pathlib import Path
import struct

import numpy as np
import pytest

from bluelcms.aia import aia_fingerprint, load_aia, load_aia_cached, read_chromatogram
from bluelcms.integrations import integrate_trace, load_integrations, save_integrations
from bluelcms.mzml import discover_files, load_compact_cache, load_run, write_compact_cache
from bluelcms.thumbnails import preview_series


def write_aia_cdf(path, values=(-2., 1., 4., 1.), *, unit="Minutes", delay=0.5,
                  interval=.1, version=1, uniform="Y", times=None):
    """Small standards-shaped classic NetCDF fixture, independent of the reader."""
    def string(text):
        content = text.encode("latin-1")
        return struct.pack(">I", len(content)) + content + b"\0" * (-len(content) % 4)

    def attributes(entries):
        if not entries:
            return struct.pack(">II", 0, 0)
        content = struct.pack(">II", 12, len(entries))
        for name, value in entries.items():
            raw = value.encode("latin-1")
            content += string(name) + struct.pack(">II", 2, len(raw)) + raw + b"\0" * (-len(raw) % 4)
        return content

    dimensions = struct.pack(">II", 10, 1) + string("point_number") + struct.pack(">I", len(values))
    global_attrs = attributes({"retention_unit": unit, "detector_unit": "mAU", "sample_name": "sample",
                               "detection_method_name": "SM8.amx", "raw_data_table_name": "DAD1ARawDataTable"})
    specs = [("ordinate_values", (0,), values, {"uniform_sampling_flag": uniform}),
             ("actual_delay_time", (), [delay], {}), ("actual_sampling_interval", (), [interval], {}),
             ("raw_data_retention", (0,), np.zeros(len(values)) if times is None else times, {})]
    arrays = [np.asarray(values, dtype=">f8").tobytes() for _, _, values, _ in specs]

    def header(offsets):
        content = b"CDF" + bytes([version]) + struct.pack(">I", 0) + dimensions + global_attrs
        content += struct.pack(">II", 11, len(specs))
        for (name, dims, _, attrs), array, offset in zip(specs, arrays, offsets):
            content += string(name) + struct.pack(">I", len(dims))
            content += b"".join(struct.pack(">I", dim) for dim in dims) + attributes(attrs)
            content += struct.pack(">II", 6, len(array)) + struct.pack(">Q" if version == 2 else ">I", offset)
        return content

    start = len(header([0] * len(specs)))
    offsets = []
    for array in arrays:
        offsets.append(start); start += len(array)
    path.write_bytes(header(offsets) + b"".join(arrays))
    return path


def make_aia(folder):
    folder.mkdir(parents=True)
    write_aia_cdf(folder / "sample_sample_DAD1B.cdf")
    write_aia_cdf(folder / "sample_sample_DAD1C.cdf", values=(0., 2., 8., 2.))
    return folder


@pytest.mark.parametrize("version", (1, 2))
def test_classic_channels_zero_retention_axis_and_no_invented_wavelength(tmp_path, version):
    path = write_aia_cdf(tmp_path / "sample_DAD1B.cdf", version=version)
    trace, metadata = read_chromatogram(path)
    assert trace.name == "DAD1B" and trace.unit == "mAU" and trace.wavelength_nm is None
    assert metadata["sample_name"] == "sample"
    np.testing.assert_allclose(trace.times, [.5, .6, .7, .8])
    np.testing.assert_allclose(trace.values, [-2, 1, 4, 1])
    assert trace.values.dtype == np.float32
    assert load_run(path).chromatograms[0].name == "DAD1B"


def test_seconds_and_nonuniform_axes_are_normalized_to_minutes(tmp_path):
    path = write_aia_cdf(tmp_path / "seconds.cdf", unit="Seconds", delay=30, interval=6)
    trace, _ = read_chromatogram(path)
    np.testing.assert_allclose(trace.times, [.5, .6, .7, .8])
    path = write_aia_cdf(path, unit="Seconds", uniform="N", times=[30, 36, 48, 60])
    trace, _ = read_chromatogram(path)
    np.testing.assert_allclose(trace.times, [.5, .6, .8, 1.])


@pytest.mark.parametrize("options,match", (({"interval": 0}, "sampling interval"),
                                          ({"unit": "unknown"}, "retention-time unit"),
                                          ({"uniform": "N"}, "Nonuniform"),
                                          ({"values": [1, np.nan]}, "finite")))
def test_invalid_chromatograms_report_file_and_problem(tmp_path, options, match):
    path = write_aia_cdf(tmp_path / "bad.cdf", **options)
    with pytest.raises(ValueError, match=match):
        read_chromatogram(path)


def test_discovery_groups_aia_folders_and_preserves_standalone_cdf(tmp_path):
    root = tmp_path / "ANZ" / "ANZ260"
    export = make_aia(root / "2026_10_29_ANZ260P1.aIa")
    standalone = write_aia_cdf(root / "single.CDF")
    (root / "empty.AIA").mkdir()
    assert set(discover_files(tmp_path)) == {export, standalone}
    assert discover_files(export) == [export]
    assert discover_files(root / "empty.AIA") == []
    progress = []
    run = load_aia(export, lambda done, total: progress.append((done, total)))
    assert [channel.name for channel in run.chromatograms] == ["DAD1B", "DAD1C"]
    assert not run.dad and not run.scans and not run.auxiliary and not run.tic
    assert progress[-1][0] == progress[-1][1] > 0


def test_cache_roundtrip_manifest_refresh_offline_integrations_and_preview(tmp_path):
    source = make_aia(tmp_path / "sample.AIA")
    cache = tmp_path / "sample.bluelcms.npz"
    result = load_aia_cached(source, cache)
    assert result.refresh_cache
    write_compact_cache(result.run, cache)
    cached = load_compact_cache(cache)
    assert [c.name for c in cached.chromatograms] == ["DAD1B", "DAD1C"]
    for expected, actual in zip(result.run.chromatograms, cached.chromatograms):
        np.testing.assert_array_equal(expected.times, actual.times)
        np.testing.assert_array_equal(expected.values, actual.values)
        assert actual.unit == "mAU" and actual.wavelength_nm is None
    assert preview_series(cached)[0][1] == "DAD1B"
    assert not load_aia_cached(source, cache).refresh_cache
    original = aia_fingerprint(source)
    channel = source / "sample_sample_DAD1B.cdf"
    write_aia_cdf(channel, values=(10, 20, 30, 40))
    os.utime(channel, ns=(channel.stat().st_atime_ns, original["files"][0]["mtime_ns"] + 1000000))
    changed = load_aia_cached(source, cache)
    assert changed.refresh_cache and aia_fingerprint(source) != original
    write_compact_cache(changed.run, cache)
    record = {"start_min": .5, "stop_min": .8, "channel": "DAD1B", "unit": "mAU", "wavelength_nm": None,
              "absolute_integral": integrate_trace(changed.run.chromatograms[0].times, changed.run.chromatograms[0].values, .5, .8)}
    fingerprint = json.loads(changed.run.source_metadata)["fingerprint"]
    sidecar = save_integrations(source, tmp_path / "integrations", [record], False, fingerprint=fingerprint)
    assert sidecar.parent == tmp_path / "integrations"
    source.rename(tmp_path / "disconnected")
    offline = load_aia_cached(source, cache)
    assert not offline.refresh_cache
    np.testing.assert_array_equal(offline.run.chromatograms[0].values, [10, 20, 30, 40])
    assert load_integrations(source, tmp_path / "integrations", False,
                             fingerprint=json.loads(offline.run.source_metadata)["fingerprint"]) == ([record], sidecar, False)


def test_added_or_removed_channels_invalidate_cache(tmp_path):
    source = make_aia(tmp_path / "sample.AIA")
    cache = tmp_path / "sample.bluelcms.npz"
    write_compact_cache(load_aia(source), cache)
    (source / "sample_sample_DAD1C.cdf").unlink()
    assert load_aia_cached(source, cache).refresh_cache
    write_aia_cdf(source / "sample_DAD1A.cdf")
    assert load_aia_cached(source, cache).refresh_cache


def test_duplicate_channels_and_truncated_files_fail_clearly(tmp_path):
    source = make_aia(tmp_path / "sample.AIA")
    write_aia_cdf(source / "duplicate_DAD1B.cdf")
    with pytest.raises(ValueError, match="Duplicate channel"):
        load_aia(source)
    bad = tmp_path / "truncated.cdf"
    bad.write_bytes(b"CDF")
    with pytest.raises(ValueError, match="Cannot read truncated.cdf"):
        read_chromatogram(bad)
