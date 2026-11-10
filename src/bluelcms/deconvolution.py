"""Bounded, polarity-aware charge-envelope matching of interval MS1 spectra.

Masses are proton-only envelope estimates, not isotope-resolved monoisotopic
assignments. Signal fractions describe assigned ion signal, not concentration.
"""

from dataclasses import asdict, dataclass
import math

import numpy as np


PROTON_MASS = 1.007276466621
SPECIES_COLORS = ("#ef5350", "#42a5f5", "#66bb6a", "#ab47bc", "#ffa726", "#26c6da", "#ec407a", "#d4e157")


@dataclass(frozen=True)
class DeconvolutionSettings:
    minimum_mass: float = 2000.0
    maximum_mass: float = 30000.0
    minimum_charge: int = 2
    maximum_charge: int = 30
    tolerance: float = 0.2
    minimum_signal_percent: float = 1.0
    minimum_support: int = 3
    maximum_highlighted_species: int = 7

    def __post_init__(self):
        if not all(math.isfinite(value) for value in asdict(self).values()):
            raise ValueError("Deconvolution settings must be finite.")
        if not 0 < self.minimum_mass < self.maximum_mass <= 1e7:
            raise ValueError("Mass cutoffs must be increasing and positive (maximum 10,000,000 Da).")
        if not all(isinstance(value, int) and not isinstance(value, bool)
                   for value in (self.minimum_charge, self.maximum_charge, self.minimum_support)):
            raise ValueError("Charge cutoffs and supporting-state count must be integers.")
        if not 1 <= self.minimum_charge <= self.maximum_charge <= 100:
            raise ValueError("Charge magnitudes must be between 1 and 100.")
        if not 2 <= self.minimum_support <= self.maximum_charge - self.minimum_charge + 1:
            raise ValueError("Require at least two supporting states within the charge range.")
        if not 0.001 <= self.tolerance <= 2 or not 0 < self.minimum_signal_percent <= 100:
            raise ValueError("Tolerance must be 0.001–2 Th and signal threshold must be >0–100%.")
        if (not isinstance(self.maximum_highlighted_species, int)
                or isinstance(self.maximum_highlighted_species, bool)
                or not 0 <= self.maximum_highlighted_species <= 100):
            raise ValueError("Maximum highlighted species must be an integer between 0 and 100.")


@dataclass(frozen=True)
class ChargeAssignment:
    mz: float
    intensity: float
    charge: int
    # Source histogram bins belonging to this peak; independent of display zoom.
    bins: tuple[int, ...]


@dataclass(frozen=True)
class Species:
    mass: float
    polarity: str
    assignments: tuple[ChargeAssignment, ...]
    signal: float
    relative_abundance: float
    quality: float


def _peaks(x, y, options):
    """Pick local maxima and integrate their non-overlapping peak neighborhoods."""
    x, y = np.asarray(x), np.asarray(y)
    valid = np.isfinite(x) & np.isfinite(y) & (x > 0) & (y > 0)
    indices = np.flatnonzero(valid)
    if not len(indices):
        return ()
    order = indices[np.argsort(x[indices], kind="stable")]
    threshold = float(y[order].max()) * options.minimum_signal_percent / 100
    # Sparse histograms omit empty bins: a large gap starts a new peak.
    ordered_mz, ordered_y = x[order], y[order]
    gaps = np.diff(ordered_mz) > options.tolerance
    left = np.r_[True, gaps | (ordered_y[1:] > ordered_y[:-1])]
    right = np.r_[gaps | (ordered_y[:-1] >= ordered_y[1:]), True]
    candidates = order[left & right & (ordered_y >= threshold)]
    # Bound candidate work even on dense/noisy full-run intervals.
    candidates = candidates[np.argsort(-y[candidates], kind="stable")[:500]]
    claimed, peaks = set(), []
    for index in candidates:
        lower = np.searchsorted(ordered_mz, x[index] - options.tolerance / 2, side="left")
        upper = np.searchsorted(ordered_mz, x[index] + options.tolerance / 2, side="right")
        members = order[lower:upper]
        members = tuple(int(i) for i in members if int(i) not in claimed)
        if not members or index not in members:
            continue
        claimed.update(members)
        intensity = float(y[list(members)].sum())
        centroid = float(np.average(x[list(members)], weights=y[list(members)]))
        peaks.append((centroid, intensity, members))
    return tuple(sorted(peaks))


def deconvolute_spectrum(x, y, polarity, options=None):
    """Find disjoint probable charge envelopes; never invent unsupported states.

    At least one adjacent charge pair is required to suppress integer-multiple
    mass aliases. Competing candidates share no assigned peaks. This is a
    conservative heuristic, not an adduct/isotope identification engine.
    """
    options = options or DeconvolutionSettings()
    if polarity not in ("+", "-"):
        raise ValueError("Polarity must be '+' or '-'.")
    peaks = _peaks(x, y, options)
    if len(peaks) < options.minimum_support:
        return ()
    mz = np.array([peak[0] for peak in peaks])
    intensity = np.array([peak[1] for peak in peaks])
    charges = np.arange(options.minimum_charge, options.maximum_charge + 1)
    correction = PROTON_MASS if polarity == "+" else -PROTON_MASS
    seeds = np.argsort(intensity)[-100:]
    candidates = ((mz[seeds, None] - correction) * charges).ravel()
    candidates = np.unique(candidates[(candidates >= options.minimum_mass) & (candidates <= options.maximum_mass)])
    if not len(candidates):
        return ()
    predicted = candidates[:, None] / charges + correction
    right = np.clip(np.searchsorted(mz, predicted), 0, len(mz) - 1)
    left = np.maximum(right - 1, 0)
    nearest = np.where(abs(mz[left] - predicted) < abs(mz[right] - predicted), left, right)
    matched = abs(mz[nearest] - predicted) <= options.tolerance
    scores = np.sum(np.where(matched, intensity[nearest], 0), axis=1) * np.sum(matched, axis=1)
    used, results = set(), []
    for candidate_index in np.argsort(-scores, kind="stable"):
        indices = nearest[candidate_index]
        available = matched[candidate_index] & np.array([int(i) not in used for i in indices])
        supported = charges[available]
        chosen = indices[available]
        if len(supported) < options.minimum_support or len(np.unique(chosen)) != len(chosen):
            continue
        if not np.any(np.diff(supported) == 1):
            continue
        mass = float(np.average((mz[chosen] - correction) * supported, weights=intensity[chosen]))
        errors = np.abs(mz[chosen] - (mass / supported + correction))
        if not options.minimum_mass <= mass <= options.maximum_mass or np.any(errors > options.tolerance):
            continue
        assignments = tuple(ChargeAssignment(float(mz[i]), float(intensity[i]), int(z), peaks[i][2])
                            for i, z in zip(chosen, supported))
        signal = float(intensity[chosen].sum())
        quality = float(100 * max(0, 1 - np.average(errors, weights=intensity[chosen]) / options.tolerance))
        results.append(Species(mass, polarity, assignments, signal, 0.0, quality))
        used.update(int(i) for i in chosen)
        if len(results) == 40:
            break
    total = sum(result.signal for result in results)
    return tuple(Species(result.mass, polarity, result.assignments, result.signal,
                         100 * result.signal / total, result.quality)
                 for result in sorted(results, key=lambda result: -result.signal))


def deconvolute_histograms(histograms, options):
    """Keep measurements and polarities separate; input bins are never mutated."""
    return {path: {polarity: deconvolute_spectrum(*result[polarity], polarity, options)
                   for polarity in ("+", "-")} for path, result in histograms.items()}
