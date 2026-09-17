from __future__ import annotations

import pytest

from app.analysis import metrics as M
from app.analysis.classifier import ClassificationThresholds, classify_snippet
from app.models.enums import Classification


def test_contamination_index_formula():
    original = 2.0
    mutations = [2.4, 2.6]
    expected = ((2.4 + 2.6) / 2 - 2.0) / 2.0  # 0.25
    assert M.contamination_index(original, mutations) == pytest.approx(expected)


def test_contamination_index_epsilon():
    assert M.contamination_index(0.0, [0.1]) > 0
    assert M.contamination_index(1.0, []) is None
    assert M.contamination_index(None, [1.0]) is None


def test_absolute_and_relative_delta():
    assert M.absolute_delta(2.0, [2.5, 2.5]) == pytest.approx(0.5)
    assert M.relative_delta(2.0, [2.5, 2.5]) == pytest.approx(0.25)


def test_median_and_std():
    assert M.median([]) is None
    assert M.median([3.0, 1.0]) == pytest.approx(2.0)
    assert M.median([1.0, 2.0, 3.0]) == pytest.approx(2.0)
    assert M.std([1.0]) is None
    assert M.std([1.0, 1.0, 1.0], ddof=1) == pytest.approx(0.0)


def test_effect_size():
    # d = (mean_mut - orig) / std_mut
    d = M.effect_size(2.0, [3.0, 3.0, 3.0])
    assert d is None  # zero spread
    d = M.effect_size(2.0, [2.5, 3.5, 3.0])  # mean 3.0, std 0.5
    assert d == pytest.approx(2.0)


def test_z_score_and_percentile():
    population = [0.0, 0.0, 1.0, 1.0, 0.0]
    z = M.z_score(1.0, population)
    assert z is not None and z > 0
    assert M.z_score(1.0, [1.0]) is None  # insufficient population
    assert M.percentile_rank(1.0, [0.0, 0.5, 2.0]) == pytest.approx(2 / 3 * 100)


def test_leave_one_out_z_score_and_tie_aware_percentile():
    # Scoring an extreme item against the other observations avoids damping its
    # anomaly score by including that item in its own baseline.
    assert M.leave_one_out_z_score(3.0, [0.0, 1.0, 3.0]) == pytest.approx(2.5 / 0.70710678)
    assert M.percentile_rank(1.0, [0.0, 1.0, 1.0, 2.0]) == pytest.approx(50.0)


def test_statistics_reject_non_finite_inputs():
    assert M.contamination_index(float("nan"), [1.0]) is None
    assert M.contamination_index(1.0, [float("inf")]) is None
    assert M.z_score(1.0, [0.0, float("nan")]) is None


def test_classifier_ci_possible_threshold():
    decision = classify_snippet(
        contamination_index=0.16, z_score=None, mutation_count_used=5,
        mutation_count_requested=5, thresholds=ClassificationThresholds(),
        baseline_available=True,
    )
    assert decision.classification == Classification.POSSIBLE_CONTAMINATION
    assert decision.flagged


def test_classifier_ci_high_threshold():
    decision = classify_snippet(
        contamination_index=0.40, z_score=0.5, mutation_count_used=5,
        mutation_count_requested=5, thresholds=ClassificationThresholds(),
        baseline_available=True,
    )
    assert decision.classification == Classification.HIGH_CONTAMINATION_SIGNAL


def test_classifier_z_score_threshold():
    decision = classify_snippet(
        contamination_index=0.01, z_score=2.2, mutation_count_used=5,
        mutation_count_requested=5, thresholds=ClassificationThresholds(),
        baseline_available=True,
    )
    assert decision.classification == Classification.POSSIBLE_CONTAMINATION


def test_classifier_normal_with_baseline():
    decision = classify_snippet(
        contamination_index=-0.01, z_score=0.1, mutation_count_used=5,
        mutation_count_requested=5, thresholds=ClassificationThresholds(),
        baseline_available=True,
    )
    assert decision.classification == Classification.NORMAL
    assert not decision.flagged


def test_classifier_low_evidence_without_baseline_or_coverage():
    d1 = classify_snippet(
        contamination_index=0.02, z_score=None, mutation_count_used=5,
        mutation_count_requested=5, thresholds=ClassificationThresholds(),
        baseline_available=False,
    )
    assert d1.classification == Classification.LOW_EVIDENCE
    d2 = classify_snippet(
        contamination_index=0.02, z_score=None, mutation_count_used=0,
        mutation_count_requested=5, thresholds=ClassificationThresholds(),
        baseline_available=True,
    )
    assert d2.classification == Classification.LOW_EVIDENCE
    d3 = classify_snippet(
        contamination_index=0.02, z_score=None, mutation_count_used=5,
        mutation_count_requested=5, thresholds=ClassificationThresholds(),
        baseline_available=True, original_available=False,
    )
    assert d3.classification == Classification.LOW_EVIDENCE


def test_classifier_configurable_thresholds():
    thresholds = ClassificationThresholds(ci_possible=0.5)
    decision = classify_snippet(
        contamination_index=0.2, z_score=0.0, mutation_count_used=3,
        mutation_count_requested=3, thresholds=thresholds, baseline_available=True,
    )
    assert decision.classification == Classification.ELEVATED


def test_elevated_when_ci_between_thresholds():
    decision = classify_snippet(
        contamination_index=0.06, z_score=0.3, mutation_count_used=5,
        mutation_count_requested=5, thresholds=ClassificationThresholds(),
        baseline_available=True,
    )
    assert decision.classification == Classification.ELEVATED
