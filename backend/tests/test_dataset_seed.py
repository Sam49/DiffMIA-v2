"""Bundled dataset seeding.

The project ships benchmark files under ``datasets/``. They are imported into
the database on boot so the Datasets page always lists what the project
contains, and repeated boots must never create duplicates.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.scripts import seed as seed_module
from app.scripts.seed import seed_bundled_datasets

BUNDLED_SAMPLE = Path(__file__).resolve().parents[2] / "datasets" / "sample.jsonl"


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _dataset_rows():
    from sqlalchemy import select

    from app.db.session import get_session_factory
    from app.models import Dataset

    session = get_session_factory()()
    try:
        return list(session.execute(select(Dataset)).scalars())
    finally:
        session.close()


def _dataset_items(dataset_id: int):
    from sqlalchemy import select

    from app.db.session import get_session_factory
    from app.models import DatasetItem

    session = get_session_factory()()
    try:
        return list(
            session.execute(
                select(DatasetItem).where(DatasetItem.dataset_id == dataset_id)
            ).scalars()
        )
    finally:
        session.close()


def _use_directory(monkeypatch, directory: Path) -> None:
    """Point the seeder at a scratch directory instead of the bundled one."""
    settings = Settings(bundled_datasets_dir=str(directory))
    monkeypatch.setattr(seed_module, "get_settings", lambda: settings)


def test_bundled_dataset_is_imported(clean_database):  # noqa: ARG001
    imported = seed_bundled_datasets()
    assert imported >= 1

    rows = _dataset_rows()
    assert len(rows) == imported
    dataset = next(row for row in rows if row.name == "diffmia_sample_algorithms")
    assert dataset.source_format == "jsonl"
    assert dataset.item_count == 12

    items = _dataset_items(dataset.id)
    assert len(items) == 12
    assert all(item.code.strip() for item in items)
    assert all(item.language == "python" for item in items)
    assert {item.external_id for item in items} == {
        json.loads(line)["id"]
        for line in BUNDLED_SAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    # Metadata from the file is preserved for the analysis pipeline.
    memorized = [
        json.loads(item.metadata_json).get("memorized")
        for item in items
    ]
    assert all(isinstance(flag, bool) for flag in memorized)


def test_seeding_twice_does_not_duplicate(clean_database):  # noqa: ARG001
    first = seed_bundled_datasets()
    assert first >= 1
    assert seed_bundled_datasets() == 0

    rows = _dataset_rows()
    assert len(rows) == first
    sample = next(row for row in rows if row.name == "diffmia_sample_algorithms")
    assert len(_dataset_items(sample.id)) == 12


def test_bundled_dataset_is_listed_by_the_api(client, admin_headers):
    seed_bundled_datasets()

    listing = client.get("/api/datasets", headers=admin_headers)
    assert listing.status_code == 200
    payload = listing.json()
    names = [item["name"] for item in payload["items"]]
    assert "diffmia_sample_algorithms" in names
    assert payload["total"] >= 1

    dataset_id = next(
        item["id"] for item in payload["items"] if item["name"] == "diffmia_sample_algorithms"
    )
    items = client.get(f"/api/datasets/{dataset_id}/items", headers=admin_headers)
    assert items.status_code == 200
    assert items.json()["total"] == 12


def test_malformed_bundled_file_is_skipped_not_fatal(monkeypatch, tmp_path, clean_database):  # noqa: ARG001
    (tmp_path / "broken.jsonl").write_text("{not json at all}\n", encoding="utf-8")
    (tmp_path / "good.jsonl").write_text(
        json.dumps(
            {
                "id": "alpha_1",
                "dataset_name": "scratch_bench",
                "code": "def alpha(x):\n    return x + 1\n",
                "language": "python",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _use_directory(monkeypatch, tmp_path)

    assert seed_bundled_datasets() == 1
    rows = _dataset_rows()
    assert [row.name for row in rows] == ["scratch_bench"]
    assert rows[0].item_count == 1


def test_unsupported_files_are_ignored(monkeypatch, tmp_path, clean_database):  # noqa: ARG001
    (tmp_path / "notes.txt").write_text("just prose, not a dataset", encoding="utf-8")
    (tmp_path / "archive.bin").write_bytes(b"\x00\x01\x02")
    _use_directory(monkeypatch, tmp_path)

    assert seed_bundled_datasets() == 0
    assert _dataset_rows() == []


def test_missing_directory_is_not_an_error(monkeypatch, tmp_path, clean_database):  # noqa: ARG001
    _use_directory(monkeypatch, tmp_path / "does-not-exist")
    assert seed_bundled_datasets() == 0


def test_every_bundled_file_imports_with_complete_python(client, admin_headers):
    """Whatever the project ships must load and be mutable end to end.

    Guards the bundled corpora: each file parses into items whose code is a
    complete, AST-valid Python function, and the API exposes every one of them.
    """
    import ast

    seed_bundled_datasets()
    listing = client.get("/api/datasets", headers=admin_headers).json()
    assert listing["total"] >= 3

    for summary in listing["items"]:
        body = client.get(
            f"/api/datasets/{summary['id']}/items", headers=admin_headers
        ).json()
        assert body["total"] == summary["item_count"]
        assert body["total"] > 0
        for item in body["items"][:25]:
            assert item["language"] == "python"
            assert item["code"].strip()
            ast.parse(item["code"], mode="exec")
        if summary["name"] == "humaneval":
            assert summary["item_count"] == 164
        if summary["name"] == "mbpp_sanitized":
            assert summary["item_count"] > 400
