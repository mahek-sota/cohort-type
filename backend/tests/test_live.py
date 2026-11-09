"""Live questions, tested with a scripted LLM. Nothing here needs a key or a network."""

from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from phenoctx import live
from phenoctx.api import app
from phenoctx.decode import build_candidates
from phenoctx.llm import LLMFatalError, ToolCall, ToolResult, Turn

ON = {"LIVE_MODE": "on"}
QUERY = "SELECT COUNT(DISTINCT PATIENT) FROM conditions WHERE DESCRIPTION LIKE '%diabetes%'"


class FakeLLM:
    backend = "fake"
    model = "fake-model"
    effort = None
    concurrency = 1

    def __init__(self, *turns: Any) -> None:
        self.turns = list(turns)
        self.extract_calls = 0
        self.questions: list[str] = []

    def respond(self, system: str, tools: Any, messages: list[dict[str, Any]]) -> Turn:
        self.questions.append(messages[0]["content"])
        item = self.turns.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def continuation(self, turn: Turn, results: list[ToolResult]) -> list[dict[str, Any]]:
        return [{"role": "tool"}]

    def extract(self, prompt: str, schema: Any) -> Any:
        self.extract_calls += 1
        raise AssertionError("Live questions don't need scoring")


def sql_turn() -> Turn:
    return Turn("", [ToolCall("t0", "run_sql", {"query": QUERY})], "tool_use", 1, 1)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, con: duckdb.DuckDBPyConnection) -> Any:
    monkeypatch.setenv("LIVE_MODE", "on")
    monkeypatch.setattr(live, "_data", lambda: (con, build_candidates(con)))

    def use(llm: FakeLLM) -> TestClient:
        monkeypatch.setattr(live, "live_llm", lambda env: llm)
        return TestClient(app)

    return use


@pytest.mark.parametrize("env", [{}, {"LIVE_MODE": "off"}, {"ANTHROPIC_API_KEY": "key"}])
def test_live_stays_off_without_the_explicit_switch(env: dict[str, str]) -> None:
    assert live.live_llm(env) is None


def test_live_needs_the_full_csvs(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(live, "DEFAULT_CSV_DIR", tmp_path)

    assert live.live_llm(ON) is None


def test_live_defaults_to_the_local_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    for name in ("patients", "conditions"):
        (tmp_path / f"{name}.csv").touch()
    monkeypatch.setattr(live, "DEFAULT_CSV_DIR", tmp_path)

    status = live.status(ON)

    assert (status.enabled, status.backend) == (True, "ollama")


@pytest.mark.parametrize(
    "request_body",
    [
        {"question": "", "agent": "naive"},
        {"question": "x" * 301, "agent": "naive"},
        {"question": "Hi", "agent": "other"},
    ],
)
def test_invalid_questions_are_rejected(request_body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        live.LiveQuestion.model_validate(request_body)


def test_a_live_answer_is_decoded_from_the_agents_own_query(client: Any) -> None:
    llm = FakeLLM(sql_turn(), Turn("There are 465 patients.", [], "end_turn", 1, 1))

    response = client(llm).post(
        "/live/ask", json={"question": "How many have diabetes?", "agent": "naive"}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["used_tools"] is True
    assert body["answer"] == "There are 465 patients."
    assert body["decoding"]["status"] == "match"
    assert body["decoding"]["judgments"]["include_diagnosis"] is False
    assert llm.questions == ["How many have diabetes?", "How many have diabetes?"]
    assert llm.extract_calls == 0


def test_an_answer_with_no_tools_is_marked(client: Any) -> None:
    llm = FakeLLM(Turn("Probably about 100.", [], "end_turn", 1, 1))

    body = client(llm).post("/live/ask", json={"question": "Hi", "agent": "context"}).json()

    assert body["used_tools"] is False
    assert body["decoding"]["status"] == "no_count"


def test_a_model_that_cannot_run_gives_a_clear_error(client: Any) -> None:
    llm = FakeLLM(LLMFatalError("Couldn't reach Ollama. Is it running?"))

    response = client(llm).post("/live/ask", json={"question": "Hi", "agent": "naive"})

    assert response.status_code == 503
    assert "Is it running?" in response.json()["detail"]
