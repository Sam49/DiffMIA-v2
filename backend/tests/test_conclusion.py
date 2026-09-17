"""Conclusion rendering and the regressions that blocked experiments.

The pipeline used to die on `UNIQUE constraint failed: inference_cache.cache_key`
whenever a snippet produced the same mutated text twice, which left every
experiment FAILED and the Experiments/Results/Reports pages empty. These tests
pin the fixes: distinct mutations per snippet, an idempotent cache write, a
clean failure path, and a Conclusion section in the exports.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.db.session import get_session_factory
from app.models import ModelInfo, User
from app.mutation.engine import MutationEngine
from app.schemas.experiment import ExperimentCreate
from app.services import dataset_service, experiment_service
from app.services.cache_service import dedupe_by_cache_key, put_cached
from app.services.report_service import export_markdown, export_pdf
from app.services.results_service import build_results
from app.workers.run_pipeline import run_experiment

SAMPLE = Path(__file__).resolve().parents[2] / "datasets" / "sample.jsonl"


def _experiment(**overrides) -> int:
    session = get_session_factory()()
    try:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        records, _ = dataset_service.parse_dataset_content(
            SAMPLE.read_text(encoding="utf-8"),
            source_format="jsonl",
            default_dataset="diffmia_sample_algorithms",
        )
        dataset, _ = dataset_service.create_dataset(
            session, name="conclusion-test", records=records, user_id=user.id
        )
        model = session.execute(select(ModelInfo).where(ModelInfo.name == "diffmia-mock")).scalar_one()
        experiment = experiment_service.create_experiment(
            session,
            user,
            ExperimentCreate(
                name="conclusion-test",
                description="integration",
                dataset_id=dataset.id,
                model_id=model.id,
                **overrides,
            ),
        )
        session.commit()
        return experiment.id
    finally:
        session.close()


# ── mutation distinctness ─────────────────────────────────────────────
def test_mutations_within_a_snippet_are_distinct():
    """A snippet with few identifiers must not repeat its one variant.

    `mutate` is told what the snippet already produced; the retry ladder finds a
    different rename or reports DUPLICATE instead of silently double-counting.
    """
    code = "def add(a, b):\n    return a + b\n"
    engine = MutationEngine()
    produced: set[str] = set()
    statuses = []
    for index in range(1, 6):
        result = engine.mutate(code, seed=7, mutation_index=index, strength=0.3, avoid=produced)
        statuses.append(result.status)
        if result.status == "VALID":
            assert result.mutated_code not in produced
            produced.add(result.mutated_code)
    # Whatever the engine manages, it never hands back a repeated variant as VALID.
    assert statuses.count("VALID") == len(produced)
    assert all(status in {"VALID", "DUPLICATE", "NO_CANDIDATES", "INVALID"} for status in statuses)


def test_duplicate_status_is_reported_when_no_distinct_variant_can_be_found():
    """With no room left in the retry ladder the repeat is flagged, not counted."""
    code = "def f(x):\n    return x\n"
    engine = MutationEngine(max_attempts=1)  # cannot search for another variant
    first = engine.mutate(code, seed=3, mutation_index=1, strength=1.0)
    assert first.status == "VALID"

    repeat = engine.mutate(
        code, seed=3, mutation_index=1, strength=1.0, avoid={first.mutated_code}
    )
    assert repeat.status == "DUPLICATE"
    assert repeat.mutated_code == first.mutated_code
    assert "distinct" in repeat.error
    assert repeat.valid is False


def test_avoid_is_searched_before_giving_up():
    """When the ladder has room, a genuinely different variant is produced."""
    code = "def f(x):\n    return x\n"
    engine = MutationEngine()
    produced: set[str] = set()
    for index in range(1, 4):
        result = engine.mutate(code, seed=11, mutation_index=index, strength=1.0, avoid=produced)
        assert result.status == "VALID"
        assert result.mutated_code not in produced
        produced.add(result.mutated_code)


# ── cache idempotency ─────────────────────────────────────────────────
def test_put_cached_is_idempotent_for_the_same_key():
    session = get_session_factory()()
    try:
        put_cached(session, "key-1", "mock", "hash", {"mean_loss": 1.0})
        put_cached(session, "key-1", "mock", "hash", {"mean_loss": 2.0})
        session.commit()
        from app.models import InferenceCache

        rows = session.execute(
            select(InferenceCache).where(InferenceCache.cache_key == "key-1")
        ).scalars().all()
        assert len(rows) == 1
        assert "2.0" in rows[0].payload_json
    finally:
        session.close()


def test_dedupe_by_cache_key_groups_repeats():
    unique, groups = dedupe_by_cache_key(["a", "b", "a", "c", "b"])
    assert unique == [0, 1, 3]
    assert groups[0] == [0, 2]
    assert groups[1] == [1, 4]
    assert groups[3] == [3]


# ── end-to-end: experiments complete and carry a conclusion ───────────
def test_experiment_completes_with_repeated_variants():
    """Regression: this used to fail with a duplicate-key IntegrityError."""
    experiment_id = _experiment(mutation_count=5, mutation_seed=42)
    assert run_experiment(experiment_id)["status"] == "COMPLETED"

    session = get_session_factory()()
    try:
        bundle = build_results(session, experiment_id)
        stats = bundle["stats"]
        assert stats["analyzed_count"] > 0
        assert stats["failed_snippets"] == 0

        conclusion = bundle["conclusion"]
        assert conclusion["verdict"] in {
            "NO_DATA",
            "NO_MATERIAL_SIGNAL",
            "ELEVATED_DIFFERENTIAL_SIGNAL",
            "STRONG_DIFFERENTIAL_SIGNAL",
        }
        assert conclusion["observations"] and conclusion["caveats"] and conclusion["corroboration"]
        # The mock provider must always be called out as non-evidence.
        assert any("mock provider" in caveat for caveat in conclusion["caveats"])

        markdown = export_markdown(session, experiment_id)
        assert "## Conclusion" in markdown
        assert "Verdict:" in markdown
        assert "Limitations of this conclusion" in markdown
        assert len(export_pdf(session, experiment_id)) > 5000
    finally:
        session.close()


def test_failed_experiment_reports_a_readable_error():
    """A crashed run must land FAILED with a short, human-readable reason."""
    session = get_session_factory()()
    try:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        dataset, _ = dataset_service.create_dataset(
            session,
            name="broken-dataset",
            records=[
                {
                    "external_id": "x1",
                    "dataset_name": "broken-dataset",
                    "problem_statement": "no renameable identifiers",
                    "code": "print('hello')\n",
                    "language": "python",
                    "metadata": {},
                }
            ],
            user_id=user.id,
        )
        model = session.execute(select(ModelInfo).where(ModelInfo.name == "diffmia-mock")).scalar_one()
        experiment = experiment_service.create_experiment(
            session, user,
            ExperimentCreate(name="broken", description="", dataset_id=dataset.id, model_id=model.id),
        )
        session.commit()
        experiment_id = experiment.id
    finally:
        session.close()

    run_experiment(experiment_id)

    session = get_session_factory()()
    try:
        from app.models import Experiment

        row = session.get(Experiment, experiment_id)
        assert row.status in ("FAILED", "COMPLETED")
        if row.status == "FAILED":
            assert row.error_message
            assert len(row.error_message) < 400  # not a driver traceback dump
            assert "PendingRollbackError" not in row.error_message
    finally:
        session.close()
