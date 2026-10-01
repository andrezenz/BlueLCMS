import json
import os

import numpy as np
import pytest

from bluelcms.integrations import (
    fallback_sidecar, integrate_trace, load_integrations, save_integrations,
)


def test_integrate_trace_interpolates_exact_boundaries():
    assert integrate_trace([0, 1, 2], [0, 2, 0], 0.5, 1.5) == pytest.approx(1.5)
    with pytest.raises(ValueError, match="outside"):
        integrate_trace([0, 1], [0, 1], -1, 1)


def test_sidecar_round_trip_and_stale_detection(tmp_path):
    source = tmp_path / "sample.mzML"
    source.write_bytes(b"raw")
    fallback = tmp_path / "fallback"
    integrations = [{"start_min": 1.0, "stop_min": 2.0, "wavelength_nm": 254, "absolute_integral": 42.0}]
    sidecar = save_integrations(source, fallback, integrations)
    assert sidecar == source.with_suffix(".mzML.bluelcms-integrations.json")
    assert load_integrations(source, fallback) == (integrations, sidecar, False)
    source.write_bytes(b"changed")
    assert load_integrations(source, fallback) == ([], sidecar, True)


def test_fallback_sidecar_name_is_source_specific(tmp_path):
    source = tmp_path / "sample.mzML"
    assert fallback_sidecar(source, tmp_path / "cache") != fallback_sidecar(tmp_path / "other" / "sample.mzML", tmp_path / "cache")
