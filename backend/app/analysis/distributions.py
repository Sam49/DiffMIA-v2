"""Distribution helpers used for dashboard charts and reports.

Implements histograms and a lightweight Gaussian KDE in pure Python so the
backend has no numpy/scipy dependency (required for lightweight deployment).
"""
from __future__ import annotations

import math


def _silverman_bandwidth(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 1.0
    mu = sum(values) / n
    variance = sum((v - mu) ** 2 for v in values) / (n - 1)
    sigma = math.sqrt(variance) if variance > 0 else 1e-6
    iqr = sorted(values)[int(n * 0.75)] - sorted(values)[int(n * 0.25)]
    sigma_robust = min(sigma, iqr / 1.349) if iqr > 0 else sigma
    return max(0.886 * sigma_robust * (n ** -0.2), 1e-4)


def histogram(values: list[float], bins: int = 30) -> tuple[list[float], list[int]]:
    """Return (bin_centers, counts)."""
    if not values:
        return [], []
    lo, hi = min(values), max(values)
    if lo == hi:
        lo -= 0.5
        hi += 0.5
    width = (hi - lo) / bins
    counts = [0] * bins
    centers = [lo + width * (i + 0.5) for i in range(bins)]
    for value in values:
        index = min(int((value - lo) / width), bins - 1)
        counts[index] += 1
    return centers, counts


def kde(values: list[float], grid_points: int = 96, bandwidth: float | None = None) -> tuple[list[float], list[float]]:
    """Gaussian kernel density estimate over the observed range."""
    if not values:
        return [], []
    if bandwidth is None:
        bandwidth = _silverman_bandwidth(values)
    lo, hi = min(values), max(values)
    pad = max((hi - lo) * 0.2, bandwidth * 3.0)
    xs = [lo - pad + (hi - lo + 2 * pad) * i / (grid_points - 1) for i in range(grid_points)]
    n = len(values)
    constant = 1.0 / (n * bandwidth * math.sqrt(2.0 * math.pi))
    ys: list[float] = []
    for x in xs:
        acc = 0.0
        for v in values:
            z = (x - v) / bandwidth
            acc += math.exp(-0.5 * z * z)
        ys.append(constant * acc)
    return xs, ys
