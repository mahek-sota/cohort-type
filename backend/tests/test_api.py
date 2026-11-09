import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phenoctx import api
from phenoctx.api import app
from phenoctx.cohort import PRESETS

HBA1C_QUERY = {"evidence": "labs", "hba1c_threshold": 6.5}
BOTH_QUERY = {"evidence": "both", "include_complications": True, "hba1c_threshold": 6.5}


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def cohort_ids(client: TestClient, judgments: dict) -> list[str]:
    response = client.post("/cohort", json=judgments)
    assert response.status_code == 200
    return [patient["id"] for patient in response.json()["patients"]]


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_presets_list_all_five_in_order(client: TestClient) -> None:
    body = client.get("/presets").json()

    assert [preset["id"] for preset in body] == list(PRESETS)
    assert all(preset["name"] and preset["rationale"] for preset in body)


@pytest.mark.parametrize(
    ("preset_id", "count", "percent"),
    [
        ("exact-code", 74, 6.4),
        ("type-2-text", 115, 10.0),
        ("diabet-text", 474, 41.1),
        ("hba1c", 41, 3.6),
        ("text-or-hba1c", 142, 12.3),
    ],
)
def test_presets_round_trip_through_the_cohort_endpoint(
    client: TestClient, preset_id: str, count: int, percent: float
) -> None:
    preset = next(p for p in client.get("/presets").json() if p["id"] == preset_id)

    body = client.post("/cohort", json=preset["judgments"]).json()

    assert body["count"] == count
    assert body["percent"] == percent
    assert body["population"] == 1153
    assert len(body["patients"]) == count
    assert all(patient["evidence_rows"] > 0 for patient in body["patients"])


@pytest.mark.parametrize(
    "judgments",
    [
        pytest.param({"evidence": "codes"}, id="no-code-group"),
        pytest.param({"evidence": "labs", "hba1c_threshold": 99}, id="threshold-out-of-range"),
        pytest.param(
            {"evidence": "codes", "include_diagnosis": True, "hba1c_threshold": 6.5},
            id="threshold-on-codes",
        ),
    ],
)
def test_invalid_judgments_return_422(client: TestClient, judgments: dict) -> None:
    assert client.post("/cohort", json=judgments).status_code == 422


def test_evidence_follows_the_definition_in_the_query(client: TestClient) -> None:
    patient_id = sorted(set(cohort_ids(client, HBA1C_QUERY)) & set(cohort_ids(client, BOTH_QUERY)))[
        0
    ]

    labs = client.get(f"/patients/{patient_id}/evidence", params=HBA1C_QUERY).json()
    union = client.get(f"/patients/{patient_id}/evidence", params=BOTH_QUERY).json()

    assert labs["patient_id"] == patient_id
    assert {row["table"] for row in labs["evidence"]} == {"observations"}
    assert len(union["evidence"]) >= len(labs["evidence"])


def test_evidence_is_empty_for_a_patient_outside_the_cohort(client: TestClient) -> None:
    prediabetes = {"evidence": "codes", "include_prediabetes": True}
    outside = sorted(set(cohort_ids(client, prediabetes)) - set(cohort_ids(client, HBA1C_QUERY)))

    response = client.get(f"/patients/{outside[0]}/evidence", params=HBA1C_QUERY)

    assert response.status_code == 200
    assert response.json()["evidence"] == []


def test_evidence_for_an_unknown_patient_returns_404(client: TestClient) -> None:
    assert client.get("/patients/nobody/evidence", params=HBA1C_QUERY).status_code == 404


def test_evidence_requires_valid_judgments(client: TestClient) -> None:
    assert client.get("/patients/nobody/evidence").status_code == 422
    params = {"evidence": "codes"}
    assert client.get("/patients/nobody/evidence", params=params).status_code == 422


def test_concurrent_requests_get_correct_counts(client: TestClient) -> None:
    payloads = [p.judgments.model_dump(exclude_none=True) for p in PRESETS.values()] * 4

    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(lambda j: client.post("/cohort", json=j).json()["count"], payloads))

    assert counts == [74, 115, 474, 41, 142] * 4


def test_agent_runs_before_any_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "AGENT_RUNS_PATH", tmp_path / "agent_runs.json")

    response = TestClient(app).get("/agent-runs")

    assert response.status_code == 200
    assert response.json() == {"available": False, "results": None}


def test_agent_runs_returns_the_saved_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "agent_runs.json"
    path.write_text(json.dumps({"question": "How many diabetics are in this dataset?"}))
    monkeypatch.setattr(api, "AGENT_RUNS_PATH", path)

    body = TestClient(app).get("/agent-runs").json()

    assert body["available"] is True
    assert body["results"]["question"] == "How many diabetics are in this dataset?"


def test_committed_results_are_served_with_their_provenance() -> None:
    body = TestClient(app).get("/agent-runs").json()

    results = body["results"]
    assert body["available"] is True
    assert results["backend"] in ("anthropic", "ollama")
    assert results["model"]
    assert results["generated_at"]
    assert len(results["runs"]) == 20
    for agent in ("naive", "context"):
        assert results["summary"][agent]["headline_numbers"]
        assert results["examples"][agent]["steps"]


def test_live_mode_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIVE_MODE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-stray-key")
    test_client = TestClient(app)

    assert test_client.get("/live/status").json()["enabled"] is False
    response = test_client.post("/live/ask", json={"question": "Hi", "agent": "naive"})
    assert response.status_code == 403
