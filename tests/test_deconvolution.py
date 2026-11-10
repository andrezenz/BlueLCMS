import numpy as np
import pytest

from bluelcms.deconvolution import DeconvolutionSettings, PROTON_MASS, deconvolute_spectrum


def mixture(polarity):
    sign = 1 if polarity == "+" else -1
    points = [(mass / charge + sign * PROTON_MASS, height)
              for mass, height in ((6200.0, 100), (9530.0, 50))
              for charge in range(4, 10)]
    points.extend(((710.37, 0.1), (1520.33, 0.2)))
    points.sort()
    return np.array(points).T


@pytest.mark.parametrize("polarity", ("+", "-"))
def test_mixture_charge_sign_mass_and_signal_fractions(polarity):
    x, y = mixture(polarity)
    results = deconvolute_spectrum(x, y, polarity)
    assert len(results) == 2
    np.testing.assert_allclose([r.mass for r in results], [6200, 9530], atol=0.01)
    np.testing.assert_allclose([r.relative_abundance for r in results], [200 / 3, 100 / 3])
    assert all([a.charge for a in r.assignments] == list(range(4, 10)) for r in results)
    assert all(r.polarity == polarity and r.quality > 99 for r in results)
    assigned = [a.bins[0] for r in results for a in r.assignments]
    assert len(assigned) == len(set(assigned))


def test_cutoffs_noise_and_insufficient_charge_support():
    x, y = mixture("-")
    options = DeconvolutionSettings(minimum_mass=9000, maximum_mass=10000, minimum_charge=5, maximum_charge=8)
    results = deconvolute_spectrum(x, y, "-", options)
    assert len(results) == 1 and abs(results[0].mass - 9530) < 0.01
    assert {a.charge for a in results[0].assignments} == {5, 6, 7, 8}
    assert not deconvolute_spectrum([400, 500], [10, 20], "-")
    assert not deconvolute_spectrum([], [], "-")


def test_charge_aliases_are_not_reported_as_additional_compounds():
    charges = np.arange(4, 10)
    x = 6200 / charges - PROTON_MASS
    results = deconvolute_spectrum(x, np.ones(len(x)) * 100, "-")
    assert len(results) == 1
    assert results[0].mass == pytest.approx(6200)


def test_native_binned_peak_envelopes_keep_integrated_signal():
    points = []
    for charge in range(4, 10):
        mz = 6200 / charge - PROTON_MASS
        center = (np.floor(mz / .03125) + .5) * .03125
        points.extend(((center - .03125, 20), (center, 100), (center + .03125, 20)))
    x, y = np.array(sorted(points)).T
    result, = deconvolute_spectrum(x, y, "-")
    assert abs(result.mass - 6200) < .5
    assert result.signal == pytest.approx(y.sum())
    assert sum(len(assignment.bins) for assignment in result.assignments) == len(x)


@pytest.mark.parametrize("kwargs", ({"minimum_charge": 0}, {"maximum_mass": 1000},
                                     {"tolerance": float("nan")}, {"minimum_support": 1},
                                     {"maximum_charge": 101}))
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        DeconvolutionSettings(**kwargs)
