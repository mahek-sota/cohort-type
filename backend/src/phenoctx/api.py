import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ValidationError

from phenoctx.cohort import PRESETS, Evidence, Judgments, build_cohort, patient_evidence
from phenoctx.db import REPO_ROOT, connect

AGENT_RUNS_PATH = REPO_ROOT / "data" / "agent_runs.json"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.con = connect()
    yield
    app.state.con.close()


app = FastAPI(title="Cohort Definition Explorer", lifespan=lifespan)


def get_cursor(request: Request) -> Iterator[duckdb.DuckDBPyConnection]:
    """Give each request its own cursor, because handlers run on a thread pool."""
    cursor = request.app.state.con.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


Cursor = Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)]


class PresetSummary(BaseModel):
    id: str
    name: str
    judgments: Judgments
    rationale: str


class CohortPatient(BaseModel):
    id: str
    evidence_rows: int


class CohortResponse(BaseModel):
    count: int
    population: int
    percent: float
    patients: list[CohortPatient]


class EvidenceResponse(BaseModel):
    """Evidence is empty when the patient exists but is outside this definition's cohort."""

    patient_id: str
    evidence: list[Evidence]


class AgentRunsResponse(BaseModel):
    available: bool
    results: dict[str, Any] | None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/presets")
def presets() -> list[PresetSummary]:
    return [PresetSummary(id=key, **preset.model_dump()) for key, preset in PRESETS.items()]


@app.post("/cohort")
def cohort(judgments: Judgments, cursor: Cursor) -> CohortResponse:
    result = build_cohort(cursor, judgments)
    return CohortResponse(
        count=result.count,
        population=result.population,
        percent=result.percent,
        patients=[
            CohortPatient(id=patient_id, evidence_rows=len(rows))
            for patient_id, rows in sorted(result.evidence_by_patient.items())
        ],
    )


@app.get("/patients/{patient_id}/evidence")
def evidence(
    patient_id: str, judgments: Annotated[Judgments, Query()], cursor: Cursor
) -> EvidenceResponse:
    """Return the rows that qualify a patient under the judgments in the query string."""
    if cursor.execute("SELECT 1 FROM patients WHERE Id = ?", [patient_id]).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"Unknown patient: {patient_id}")
    return EvidenceResponse(
        patient_id=patient_id, evidence=patient_evidence(cursor, judgments, patient_id)
    )


@app.get("/live/status")
def live_status() -> dict[str, Any]:
    """Say whether live questions are available. Imports the LLM code only when they might be."""
    if os.environ.get("LIVE_MODE", "").strip().lower() != "on":
        return {"enabled": False, "backend": None, "model": None}
    from phenoctx import live

    return live.status().model_dump()


@app.post("/live/ask")
def live_ask(request: dict[str, Any]) -> dict[str, Any]:
    if os.environ.get("LIVE_MODE", "").strip().lower() != "on":
        raise HTTPException(status_code=403, detail="Live mode is off.")
    from phenoctx import live
    from phenoctx.llm import LLMFatalError

    try:
        question = live.LiveQuestion.model_validate(request)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="Invalid question.") from error
    try:
        answer = live.ask(question)
    except (LLMFatalError, FileNotFoundError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if answer is None:
        raise HTTPException(status_code=403, detail="Live mode isn't available.")
    return answer.model_dump()


@app.get("/agent-runs")
def agent_runs() -> AgentRunsResponse:
    """Return the saved comparison, or `available: false` before the agents have been run."""
    if not AGENT_RUNS_PATH.is_file():
        return AgentRunsResponse(available=False, results=None)
    return AgentRunsResponse(available=True, results=json.loads(AGENT_RUNS_PATH.read_text()))
