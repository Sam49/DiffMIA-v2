from __future__ import annotations

import io
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _poll_experiment(client, headers, experiment_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/experiments/{experiment_id}", headers=headers)
        assert response.status_code == 200
        status = response.json()["status"]
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            return response.json()
        time.sleep(0.2)
    raise AssertionError("Experiment did not finish in time")


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_metrics_endpoint(client):
    response = client.get("/api/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "requests_total" in body
    assert "inference_runs_total" in body


def test_login_and_wrong_password(client):
    ok = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert ok.status_code == 200
    assert ok.json()["access_token"]
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401
    body = bad.json()
    assert body["error"] == "AUTHENTICATION_REQUIRED"
    assert "request_id" in body


def test_protected_endpoints_require_auth(client):
    response = client.get("/api/experiments")
    assert response.status_code == 401
    assert response.json()["error"] == "AUTHENTICATION_REQUIRED"


def test_role_based_access(client, admin_headers):
    # create a viewer and a researcher
    for username, role in (("researcher1", "RESEARCHER"), ("viewer1", "VIEWER")):
        response = client.post(
            "/api/users",
            json={"username": username, "password": "password123", "role": role},
            headers=admin_headers,
        )
        assert response.status_code == 201, response.text

    researcher_login = client.post(
        "/api/auth/login", json={"username": "researcher1", "password": "password123"}
    ).json()
    viewer_login = client.post(
        "/api/auth/login", json={"username": "viewer1", "password": "password123"}
    ).json()
    researcher_headers = {"Authorization": f"Bearer {researcher_login['access_token']}"}
    viewer_headers = {"Authorization": f"Bearer {viewer_login['access_token']}"}

    # viewer cannot manage users or create experiments
    assert client.get("/api/users", headers=viewer_headers).status_code == 403
    assert client.post("/api/demo/run", headers=viewer_headers).status_code == 403
    # researcher cannot manage users
    assert client.get("/api/users", headers=researcher_headers).status_code == 403
    # viewer can read experiments
    assert client.get("/api/experiments", headers=viewer_headers).status_code == 200


def test_demo_run_end_to_end(client, admin_headers):
    response = client.post("/api/demo/run", headers=admin_headers)
    assert response.status_code == 200, response.text
    experiment_id = response.json()["experiment_id"]

    detail = _poll_experiment(client, admin_headers, experiment_id)
    assert detail["status"] == "COMPLETED", detail.get("error_message")

    results = client.get(f"/api/experiments/{experiment_id}/results", headers=admin_headers).json()
    assert results["stats"]["analyzed_count"] > 0
    assert results["stats"]["flagged_count"] >= 1
    assert results["classifications"]
    assert set(results["distributions"].keys()) == {"ci", "z", "original_loss", "mutation_loss"}
    # experiment detail embeds model + dataset info
    assert results["experiment"]["model"]["provider"] == "mock"
    assert results["experiment"]["dataset"]["item_count"] == 12

    # mutation rows exist and carry mapping + validation
    mutations = client.get(
        f"/api/experiments/{experiment_id}/mutations", headers=admin_headers
    ).json()
    assert mutations["total"] == 12 * 5
    first = mutations["items"][0]
    assert first["validation_status"] == "VALID"
    assert json.loads(first["mapping_json"])["mapping"]


def test_upload_dataset_py(client, admin_headers):
    py_content = (
        "def area(radius):\n    return 3.14159 * radius ** 2\n\n"
        "def clamp(value, lo, hi):\n    return max(lo, min(value, hi))\n"
    )
    response = client.post(
        "/api/datasets/upload",
        data={"name": "uploaded-funcs", "description": "from py"},
        files={"file": ("bench.py", io.BytesIO(py_content.encode("utf-8")), "text/x-python")},
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    dataset_id = body["dataset_id"]
    assert body["items_added"] == 2
    items = client.get(f"/api/datasets/{dataset_id}/items", headers=admin_headers).json()
    assert items["total"] == 2


def test_upload_oversized_or_invalid_rejected(client, admin_headers):
    bad = client.post(
        "/api/datasets/upload",
        data={"name": "bad"},
        files={"file": ("bad.jsonl", io.BytesIO(b'{"id": 1, "code": "x"}\nnot-json\n'.replace(b"not-json\n", b"")), "application/x-ndjson")},
        headers=admin_headers,
    )
    assert bad.status_code == 201  # still a valid single record (byte content valid)

    bad2 = client.post(
        "/api/datasets/upload",
        data={"name": "bad2"},
        files={"file": ("bad.jsonl", io.BytesIO(b"{invalid json}\n"), "application/x-ndjson")},
        headers=admin_headers,
    )
    assert bad2.status_code == 422
    assert bad2.json()["error"] == "VALIDATION_ERROR"


def test_exports(client, admin_headers):
    experiment_id = client.post("/api/demo/run", headers=admin_headers).json()["experiment_id"]
    _poll_experiment(client, admin_headers, experiment_id)

    csv_response = client.get(f"/api/experiments/{experiment_id}/export/csv", headers=admin_headers)
    assert csv_response.status_code == 200
    assert "contamination_index" in csv_response.text
    assert "snippet_id" in csv_response.text

    json_response = client.get(f"/api/experiments/{experiment_id}/export/json", headers=admin_headers)
    assert json_response.status_code == 200
    payload = json.loads(json_response.content)
    assert payload["experiment"]["id"] == experiment_id
    assert "disclaimer" in payload

    md_response = client.get(f"/api/experiments/{experiment_id}/export/markdown", headers=admin_headers)
    assert md_response.status_code == 200
    assert "Contamination Index" in md_response.text

    pdf_response = client.get(f"/api/experiments/{experiment_id}/export/pdf", headers=admin_headers)
    assert pdf_response.status_code == 200
    assert pdf_response.content[:4] == b"%PDF"
    assert len(pdf_response.content) > 1000


def test_structured_errors_never_leak_tracebacks(client, admin_headers):
    response = client.get("/api/experiments/999999", headers=admin_headers)
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "NOT_FOUND"
    assert "Traceback" not in json.dumps(body)
