"""Pure statistical helpers for differential-loss analysis.

All functions are deterministic and side-effect free so they can be unit
tested in isolation. Loss here means mean per-token negative log likelihood
(NLL) of a code sequence under a model.

Terminology (documented for researchers)
----------------------------------------
L_orig    – mean NLL of the original benchmark code
L_mut[i]  – mean NLL of mutation i (semantically equivalent identifier renames)

Contamination index (CI):
    CI = (mean(L_mut) - L_orig) / max(|L_orig|, epsilon)

A memorized original should be "easier" for the model (lower loss) than its
never-seen equivalent mutations, so CI > 0 is the signal direction. CI is a
*relative* behavioural signal, not an absolute probability of contamination.
"""
from __future__ import annotations

import math

EPSILON = 1e-9


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def std(values: list[float], ddof: int = 1) -> float | None:
    if ddof < 0 or len(values) <= ddof or not all(math.isfinite(v) for v in values):
        return None
    mu = mean(values)
    variance = sum((v - mu) ** 2 for v in values) / (len(values) - ddof)
    return math.sqrt(max(variance, 0.0))


def contamination_index(original_loss: float, mutation_losses: list[float]) -> float | None:
    if original_loss is None or not math.isfinite(original_loss):
        return None
    if not mutation_losses or not all(math.isfinite(v) for v in mutation_losses):
        return None
    mutated_mean = mean(mutation_losses)
    denom = max(abs(original_loss), EPSILON)
    return (mutated_mean - original_loss) / denom


def absolute_delta(original_loss: float, mutation_losses: list[float]) -> float | None:
    if (
        original_loss is None
        or not math.isfinite(original_loss)
        or not mutation_losses
        or not all(math.isfinite(v) for v in mutation_losses)
    ):
        return None
    return mean(mutation_losses) - original_loss


def relative_delta(original_loss: float, mutation_losses: list[float]) -> float | None:
    delta = absolute_delta(original_loss, mutation_losses)
    if delta is None:
        return None
    return delta / max(abs(original_loss), EPSILON)


def effect_size(original_loss: float, mutation_losses: list[float]) -> float | None:
    """Standardized mutation gap using mutation-loss variability as spread.

    There is only one original sequence, so this is not a two-sample Cohen's
    d.  It remains a useful signed effect measure: positive values mean the
    original is easier than its mutations in units of mutation variability.
    """
    spread = std(mutation_losses, ddof=1)
    if spread is None or spread <= EPSILON:
        return None
    return (mean(mutation_losses) - original_loss) / spread


def z_score(value: float, population: list[float]) -> float | None:
    """Standard score of ``value`` against a population distribution."""
    if not math.isfinite(value) or len(population) < 2 or not all(math.isfinite(v) for v in population):
        return None
    pop_std = std(population, ddof=1)
    if pop_std is None or pop_std <= EPSILON:
        return None
    return (value - mean(population)) / pop_std


def leave_one_out_z_score(value: float, population: list[float]) -> float | None:
    """Score ``value`` against all *other* values in a baseline population.

    Including the value being evaluated shrinks its own z-score, especially
    in small experiments, and can make configured alert thresholds
    unattainable.  Remove one numerically matching occurrence before applying
    the ordinary sample z-score.
    """
    reference = list(population)
    for index, candidate in enumerate(reference):
        if math.isclose(candidate, value, rel_tol=1e-12, abs_tol=1e-15):
            del reference[index]
            break
    return z_score(value, reference)


def percentile_rank(value: float, population: list[float]) -> float | None:
    """Mid-rank percentile (0..100), with ties receiving half credit."""
    if not math.isfinite(value) or not population or not all(math.isfinite(v) for v in population):
        return None
    below = sum(1 for v in population if v < value)
    equal = sum(1 for v in population if v == value)
    return ((below + 0.5 * equal) / len(population)) * 100.0
