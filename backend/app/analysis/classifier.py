"""Statistical classification of per-snippet contamination signals.

Classification buckets (spec §10):

    LOW_EVIDENCE              – insufficient data to evaluate
    NORMAL                    – no elevated signal
    ELEVATED                  – mild positive differential signal
    POSSIBLE_CONTAMINATION    – CI > ci_possible OR z > z_possible (defaults 0.15 / 2.0)
    HIGH_CONTAMINATION_SIGNAL – CI > ci_high   OR z > z_high   (defaults 0.35 / 3.5)

Important scientific caveat (surfaced in the UI and reports): these labels
describe *behavioural evidence consistent with memorization*. They do not
establish that any example was present in training data. Other explanations —
tokenization effects, identifier familiarity, mutation artifacts, code-style
priors — can produce the same pattern.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis import metrics as M
from app.models.enums import Classification

FLAGGED_CLASSES = {
    Classification.POSSIBLE_CONTAMINATION,
    Classification.HIGH_CONTAMINATION_SIGNAL,
}


@dataclass
class ClassificationThresholds:
    ci_possible: float = 0.15
    z_possible: float = 2.0
    ci_high: float = 0.35
    z_high: float = 3.5
    ci_elevated: float = 0.05
    z_elevated: float = 1.3
    min_items_for_baseline: int = 3
    max_allowed_mutation_failure_rate: float = 0.5

    @classmethod
    def from_dict(cls, data: dict | None) -> "ClassificationThresholds":
        if not data:
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ClassificationDecision:
    classification: Classification
    reason: str
    flagged: bool


def classify_snippet(
    *,
    contamination_index: float | None,
    z_score: float | None,
    mutation_count_used: int,
    mutation_count_requested: int,
    thresholds: ClassificationThresholds,
    baseline_available: bool,
    original_available: bool = True,
) -> ClassificationDecision:
    """Classify one snippet from its differential statistics."""
    reasons: list[str] = []

    if not original_available:
        return ClassificationDecision(
            Classification.LOW_EVIDENCE,
            "No original-sequence loss available; snippet could not be scored.",
            False,
        )

    if mutation_count_used < 1:
        return ClassificationDecision(
            Classification.LOW_EVIDENCE,
            "No valid mutation losses were produced (no renameable identifiers or all runs failed).",
            False,
        )

    if mutation_count_used < mutation_count_requested:
        failure_rate = 1.0 - (mutation_count_used / max(1, mutation_count_requested))
        if failure_rate > thresholds.max_allowed_mutation_failure_rate:
            return ClassificationDecision(
                Classification.LOW_EVIDENCE,
                f"Too many mutation runs failed ({mutation_count_used}/{mutation_count_requested} usable); "
                "evidence is unreliable.",
                False,
            )
        reasons.append(f"partial mutation coverage ({mutation_count_used}/{mutation_count_requested})")

    ci = contamination_index if contamination_index is not None else 0.0
    z = z_score

    decision: Classification = Classification.NORMAL
    if z is not None and z >= thresholds.z_high:
        decision = Classification.HIGH_CONTAMINATION_SIGNAL
    elif ci >= thresholds.ci_high:
        decision = Classification.HIGH_CONTAMINATION_SIGNAL
    elif z is not None and z >= thresholds.z_possible:
        decision = Classification.POSSIBLE_CONTAMINATION
    elif ci >= thresholds.ci_possible:
        decision = Classification.POSSIBLE_CONTAMINATION
    elif z is not None and z >= thresholds.z_elevated:
        decision = Classification.ELEVATED
    elif ci >= thresholds.ci_elevated:
        decision = Classification.ELEVATED
    else:
        decision = Classification.NORMAL if baseline_available else Classification.LOW_EVIDENCE

    if decision in (Classification.NORMAL, Classification.LOW_EVIDENCE) and not baseline_available:
        if ci < thresholds.ci_possible:
            reasons.append("baseline too small for a Z-score; CI below possible-contamination threshold")

    label = decision.value
    reason_parts = []
    if decision in (Classification.HIGH_CONTAMINATION_SIGNAL, Classification.POSSIBLE_CONTAMINATION, Classification.ELEVATED):
        if ci >= thresholds.ci_high:
            reason_parts.append(f"CI={ci:.3f} >= {thresholds.ci_high}")
        elif ci >= thresholds.ci_possible:
            reason_parts.append(f"CI={ci:.3f} >= {thresholds.ci_possible}")
        elif ci >= thresholds.ci_elevated:
            reason_parts.append(f"CI={ci:.3f} >= {thresholds.ci_elevated}")
        if z is not None and z >= thresholds.z_high:
            reason_parts.append(f"Z={z:.2f} >= {thresholds.z_high}")
        elif z is not None and z >= thresholds.z_possible:
            reason_parts.append(f"Z={z:.2f} >= {thresholds.z_possible}")
        elif z is not None and z >= thresholds.z_elevated:
            reason_parts.append(f"Z={z:.2f} >= {thresholds.z_elevated}")
    if not reason_parts:
        reason_parts.append("signal below all configured thresholds")
    if reasons:
        reason_parts.append("; ".join(reasons))
    reason = " | ".join(reason_parts)
    flagged = decision in FLAGGED_CLASSES
    return ClassificationDecision(decision, reason, flagged)
