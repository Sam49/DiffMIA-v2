from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.db.session import get_session_factory
from app.models import AnalysisResult, InferenceRun, ModelInfo, Mutation, TokenLoss, User
from app.schemas.experiment import ExperimentCreate
from app.services import dataset_service, experiment_service
from app.workers.run_pipeline import run_experiment

SAMPLE = Path(__file__).resolve().parents[2] / "datasets" / "sample.jsonl"


def _make_experiment(**overrides) -> int:
    session = get_session_factory()()
    try:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        content = SAMPLE.read_text(encoding="utf-8")
        records, _ = dataset_service.parse_dataset_content(content, source_format="jsonl",
                                                           default_dataset="diffmia_sample_algorithms")
        dataset, _ = dataset_service.create_dataset(session, name="sample-test", records=records, user_id=user.id)
        model = session.execute(select(ModelInfo).where(ModelInfo.name == "diffmia-mock")).scalar_one()
        payload = ExperimentCreate(
            name="pipeline-test",
            description="integration",
            dataset_id=dataset.id,
            model_id=model.id,
            token_losses_enabled=True,
            **overrides,
        )
        experiment = experiment_service.create_experiment(session, user, payload)
        session.commit()
        return experiment.id
    finally:
        session.close()


def test_full_pipeline_persists_results():
    experiment_id = _make_experiment(mutation_count=5, mutation_seed=42)
    result = run_experiment(experiment_id)
    assert result["status"] == "COMPLETED"

    session = get_session_factory()()
    try:
        mutations = session.execute(
            select(Mutation).where(Mutation.experiment_id == experiment_id)
        ).scalars().all()
        # 12 snippets x 5 mutation indexes
        assert len(mutations) == 60
        assert all(m.validation_status == "VALID" for m in mutations)
        assert all(m.mutated_code != m.original_code for m in mutations)
        assert all(json.loads(m.mapping_json)["mapping"] for m in mutations)

        runs = session.execute(
            select(InferenceRun).where(InferenceRun.experiment_id == experiment_id)
        ).scalars().all()
        assert len(runs) == 12 * 6  # original + 5 mutations per snippet
        assert all(r.status == "SUCCESS" for r in runs)

        token_rows = session.execute(select(TokenLoss)).scalars().all()
        assert len(token_rows) > 0

        analyses = session.execute(
            select(AnalysisResult).where(AnalysisResult.experiment_id == experiment_id)
        ).scalars().all()
        assert len(analyses) == 12
        flagged = [a for a in analyses if a.flagged]
        assert len(flagged) >= 1
        assert all(a.contamination_index is not None for a in flagged)
        # memorized sample items should be flagged (deterministic demo signal)
        memorized_ids = {a.snippet.external_id for a in flagged}
        assert "sum_list_001" in memorized_ids
    finally:
        session.close()


def test_pipeline_is_reproducible():
    experiment_id = _make_experiment(mutation_count=3, mutation_seed=123)
    assert run_experiment(experiment_id)["status"] == "COMPLETED"
    session = get_session_factory()()
    try:
        first = {
            m.snippet_id: (m.mutated_code, m.mapping_json)
            for m in session.execute(select(Mutation).where(Mutation.experiment_id == experiment_id)).scalars()
        }
        first_ci = {
            a.snippet_id: a.contamination_index
            for a in session.execute(select(AnalysisResult).where(AnalysisResult.experiment_id == experiment_id)).scalars()
        }
    finally:
        session.close()

    # rerun the same experiment -> identical mutations and analysis
    assert run_experiment(experiment_id)["status"] == "COMPLETED"
    session = get_session_factory()()
    try:
        second = {
            m.snippet_id: (m.mutated_code, m.mapping_json)
            for m in session.execute(select(Mutation).where(Mutation.experiment_id == experiment_id)).scalars()
        }
        second_ci = {
            a.snippet_id: a.contamination_index
            for a in session.execute(select(AnalysisResult).where(AnalysisResult.experiment_id == experiment_id)).scalars()
        }
        assert first == second
        for snippet_id, ci in first_ci.items():
            assert second_ci[snippet_id] == ci
    finally:
        session.close()


def test_cache_hits_on_rerun():
    experiment_id = _make_experiment(mutation_count=2)
    assert run_experiment(experiment_id)["status"] == "COMPLETED"
    session = get_session_factory()()
    try:
        # second run with the same configuration should reuse cached scores
        assert run_experiment(experiment_id)["status"] == "COMPLETED"
        hits = session.execute(
            select(InferenceRun).where(InferenceRun.experiment_id == experiment_id,
                                       InferenceRun.cache_hit.is_(True))
        ).scalars().all()
        assert len(hits) == 12 * 3
    finally:
        session.close()


def test_classifications_cover_expected_buckets():
    experiment_id = _make_experiment(mutation_count=5)
    assert run_experiment(experiment_id)["status"] == "COMPLETED"
    session = get_session_factory()()
    try:
        analyses = session.execute(
            select(AnalysisResult).where(AnalysisResult.experiment_id == experiment_id)
        ).scalars().all()
        classes = {a.classification for a in analyses}
        assert "HIGH_CONTAMINATION_SIGNAL" in classes
        assert "NORMAL" in classes
        for analysis in analyses:
            assert analysis.classification_reason  # every row explains itself
    finally:
        session.close()
