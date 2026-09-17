"""Experiment conclusion: the plain-language verdict that follows the numbers.

Everything here is derived from the experiment's own statistics — no external
knowledge and no claim of confirmed contamination. The wording is deliberately
about *evidence*: what was observed, how strong it is, what it cannot show, and
what would corroborate or falsify it.

Used by the results API (so the UI can show it) and by the report exports
(Markdown / PDF / JSON), which keeps one definition of "the conclusion" instead
of three drifting copies.
"""
from __future__ import annotations

from typing import Any

#: Share of flagged snippets at which the corpus-wide signal stops looking incidental.
ELEVATED_SHARE = 0.10
HIGH_SHARE = 0.30


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _verdict(stats: dict, flagged_share: float) -> str:
    analyzed = int(stats.get("analyzed_count") or 0)
    if analyzed == 0:
        return "NO_DATA"
    if flagged_share >= HIGH_SHARE:
        return "STRONG_DIFFERENTIAL_SIGNAL"
    if flagged_share >= ELEVATED_SHARE:
        return "ELEVATED_DIFFERENTIAL_SIGNAL"
    return "NO_MATERIAL_SIGNAL"


def _verdict_text(verdict: str, provider: str) -> str:
    if verdict == "NO_DATA":
        return "No analysed snippets were available, so no conclusion can be drawn."
    prefix = {
        "STRONG_DIFFERENTIAL_SIGNAL": (
            "A large share of snippets shows a differential-loss signal consistent with "
            "memorization of the original examples."
        ),
        "ELEVATED_DIFFERENTIAL_SIGNAL": (
            "A minority of snippets shows a differential-loss signal consistent with "
            "memorization, above what would be expected by chance."
        ),
        "NO_MATERIAL_SIGNAL": (
            "The differential-loss pattern is within the range expected from identifier "
            "familiarity, tokenization and mutation artifacts alone."
        ),
    }[verdict]
    if provider == "mock":
        prefix += (
            " These numbers come from the deterministic mock provider, so they demonstrate "
            "the measurement pipeline rather than the behaviour of a real model."
        )
    return prefix


def build_conclusion(bundle: dict) -> dict:
    """Turn a results bundle into a structured, defensible conclusion."""
    stats: dict = bundle.get("stats") or {}
    analyses: list[dict] = bundle.get("analyses") or []
    experiment: dict = bundle.get("experiment") or {}
    model: dict | None = experiment.get("model") or {}

    analyzed = int(stats.get("analyzed_count") or 0)
    flagged = int(stats.get("flagged_count") or 0)
    high = int(stats.get("high_signal_count") or 0)
    low_evidence = int(stats.get("low_evidence_count") or 0)
    failed = int(stats.get("failed_snippets") or 0)
    flagged_share = (flagged / analyzed) if analyzed else 0.0
    verdict = _verdict(stats, flagged_share)

    ranked = sorted(
        (row for row in analyses if row.get("contamination_index") is not None),
        key=lambda row: row["contamination_index"],
        reverse=True,
    )
    strongest = ranked[0] if ranked else None
    provider = str(model.get("provider") or "") if model else ""
    dataset = experiment.get("dataset") or {}
    mutation_count = experiment.get("mutation_count")

    observations: list[str] = [
        f"{analyzed} snippet(s) analysed: {flagged} ({flagged_share * 100:.1f}%) show a "
        f"contamination signal, {high} of them at the highest severity.",
        f"Mean contamination index {_fmt(stats.get('mean_ci'))} "
        f"(median {_fmt(stats.get('median_ci'))}, sd {_fmt(stats.get('std_ci'))}); "
        f"mean original loss {_fmt(stats.get('mean_original_loss'))} vs mean mutated loss "
        f"{_fmt(stats.get('mean_mutation_loss'))}.",
    ]
    mean_ci = stats.get("mean_ci")
    if mean_ci is not None:
        direction = (
            "the original examples are on average *easier* for the model than their "
            "identifier-mutated equivalents"
            if mean_ci > 0
            else "the original examples are on average *harder* for the model than their "
            "equivalents, i.e. no memorization signature"
        )
        observations.append(f"Direction: {direction}.")
    if strongest is not None:
        observations.append(
            f"Strongest single signal: {strongest.get('external_id')} "
            f"(CI {_fmt(strongest.get('contamination_index'))}, "
            f"Z {_fmt(strongest.get('z_score'))}, {strongest.get('classification')})."
        )
    if dataset:
        observations.append(
            f"Scope: {dataset.get('name')} ({dataset.get('item_count')} items) with "
            f"{mutation_count} identifier mutation(s) per snippet."
        )
    if low_evidence:
        observations.append(
            f"{low_evidence} snippet(s) were classified LOW_EVIDENCE (too few distinct "
            "mutations to support a verdict)."
        )
    if failed:
        observations.append(f"{failed} snippet(s) could not be scored and were excluded.")

    caveats = [
        "A differential loss measures behaviour, not training-data provenance: "
        "identifier familiarity, tokenization, code style and mutation artifacts can "
        "produce the same pattern.",
        "Snippets with few renameable identifiers contribute weaker evidence; the "
        "mutation count is an upper bound on distinct variants.",
        "These are 'contamination signals'. Treat a flag as a prompt for corroboration, "
        "never as confirmed contamination.",
    ]
    if provider == "mock":
        caveats.insert(
            0,
            "The mock provider emits deterministic synthetic log-likelihoods: this run "
            "validates the pipeline, and no claim about a real model can be made from it.",
        )

    corroboration = [
        "Run the same experiment with a real provider (local Transformers or an "
        "OpenAI-compatible endpoint exposing input log-probabilities).",
        "Search a released training corpus for a near-exact match of the flagged snippet.",
        "Compare against a model of the same family that could not have seen the "
        "benchmark, and check that the gap does not appear there.",
    ]

    evidence_level = {
        "NO_DATA": "none",
        "NO_MATERIAL_SIGNAL": "no material signal",
        "ELEVATED_DIFFERENTIAL_SIGNAL": "moderate (behavioural only)",
        "STRONG_DIFFERENTIAL_SIGNAL": "strong (behavioural only)",
    }[verdict]

    narrative = "\n".join(
        [
            f"**Verdict: {verdict.replace('_', ' ')}** — {_verdict_text(verdict, provider)}",
            "",
            "Observations:",
            *[f"- {line}" for line in observations],
            "",
            "What this cannot show:",
            *[f"- {line}" for line in caveats],
            "",
            "To corroborate or falsify:",
            *[f"- {line}" for line in corroboration],
        ]
    )

    return {
        "verdict": verdict,
        "evidence_level": evidence_level,
        "flagged_share": round(flagged_share, 6),
        "headline": _verdict_text(verdict, provider),
        "observations": observations,
        "caveats": caveats,
        "corroboration": corroboration,
        "narrative_markdown": narrative,
    }
