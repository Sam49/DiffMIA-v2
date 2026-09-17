from __future__ import annotations

import json

import pytest

from app.core.exceptions import ValidationError
from app.db.session import get_session_factory
from app.services import dataset_service
from app.services.dataset_parsers import parse_dataset_content

PY_FILE = '''"""Module docstring."""
import math


def area(radius):
    """Area of a circle."""
    return math.pi * radius ** 2


def clamp(value, low, high):
    return max(low, min(value, high))
'''


def test_parse_jsonl():
    lines = [
        {"id": "a1", "code": "def f(x):\n    return x", "problem_statement": "identity"},
        {"id": "a2", "code": "def g(y):\n    return y + 1", "metadata": {"k": 1}},
    ]
    records, skipped = parse_dataset_content(
        "\n".join(json.dumps(x) for x in lines), source_format="jsonl", default_dataset="ds"
    )
    assert len(records) == 2 and skipped == 0
    assert records[0]["external_id"] == "a1"
    assert records[0]["problem_statement"] == "identity"
    assert records[1]["metadata"] == {"k": 1}


def test_parse_json_object_and_array():
    records, _ = parse_dataset_content(json.dumps({"code": "x=1"}), source_format="json", default_dataset="d")
    assert records[0]["external_id"].startswith("item_")
    records, _ = parse_dataset_content(
        json.dumps([{"id": "b", "code": "y=2"}] * 2), source_format="json", default_dataset="d"
    )
    assert len(records) == 2


def test_parse_csv_requires_code_column():
    with pytest.raises(ValidationError):
        parse_dataset_content("name,age\nalice,3\n", source_format="csv", default_dataset="d")


def test_parse_csv():
    content = (
        "id,problem_statement,code,language\n"
        'c1,sum numbers,"def s(ns):\n    return sum(ns)",python\n'
    )
    records, _ = parse_dataset_content(content, source_format="csv", default_dataset="d")
    assert records[0]["external_id"] == "c1"
    assert records[0]["code"] == "def s(ns):\n    return sum(ns)"


def test_parse_python_splits_functions_without_executing():
    records, _ = parse_dataset_content(PY_FILE, source_format="py", default_dataset="d")
    names = {r["external_id"].split("_")[0] for r in records}
    assert names == {"area", "clamp"}
    for record in records:
        assert record["code"].startswith("def ")
    # module-level import line is not part of a function item (never executed)
    assert all("import math" not in r["code"] for r in records)


def test_malformed_jsonl_rejected_with_row():
    with pytest.raises(ValidationError):
        parse_dataset_content('{"id": "x", "code": "a"}\n{not json}\n', source_format="jsonl", default_dataset="d")


def test_missing_code_rejected():
    with pytest.raises(ValidationError):
        parse_dataset_content(json.dumps([{"id": "x"}]), source_format="json", default_dataset="d")


def test_unsupported_format_rejected():
    with pytest.raises(ValidationError):
        parse_dataset_content("hello", source_format="docx", default_dataset="d")


def test_create_dataset_persists_and_hashes_deterministically():
    session = get_session_factory()()
    try:
        records = [
            {"external_id": "a", "dataset_name": "dd", "problem_statement": "p",
             "code": "def f(x):\n    return x", "language": "python", "metadata": {}},
            {"external_id": "a", "dataset_name": "dd", "problem_statement": "dup",
             "code": "def f(x):\n    return x", "language": "python", "metadata": {}},
            {"external_id": "b", "dataset_name": "dd", "problem_statement": "q",
             "code": "def g(y):\n    return y", "language": "python", "metadata": {}},
        ]
        dataset, skipped = dataset_service.create_dataset(
            session, name="dups", records=records, user_id=None
        )
        assert skipped == 1
        assert dataset.item_count == 2
        assert dataset.content_hash
        items, total = dataset_service.list_items(session, dataset.id)
        assert total == 2
        second_records = [records[0], records[2]]
        dataset2, _ = dataset_service.create_dataset(
            session, name="dups2", records=second_records, user_id=None
        )
        assert dataset2.content_hash == dataset.content_hash
    finally:
        session.rollback()
        session.close()


def test_non_python_language_rejected_at_experiment_time():
    from app.schemas.experiment import ExperimentCreate
    from app.services.experiment_service import create_experiment

    session = get_session_factory()()
    try:
        records = [{"external_id": "js", "code": "function f() {}", "language": "javascript", "metadata": {}}]
        dataset, _ = dataset_service.create_dataset(session, name="js-set", records=records, user_id=None)
        from sqlalchemy import select

        from app.models import ModelInfo, User

        user = session.execute(select(User).limit(1)).scalar_one()
        model = session.execute(select(ModelInfo).where(ModelInfo.provider == "mock")).scalars().first()
        with pytest.raises(ValidationError) as exc:
            create_experiment(
                session, user,
                ExperimentCreate(name="bad", dataset_id=dataset.id, model_id=model.id),
            )
        assert exc.value.code == "UNSUPPORTED_LANGUAGE"
    finally:
        session.rollback()
        session.close()
