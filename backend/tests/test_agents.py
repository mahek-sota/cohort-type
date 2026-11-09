"""Agent logic, tested with a scripted LLM. Nothing here needs a key or a network."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import duckdb
import pytest

from phenoctx import agents
from phenoctx.agents import (
    CONTEXT_SYSTEM,
    CONTEXT_TOOLS,
    NAIVE_TOOLS,
    QUESTION,
    Agent,
    AnswerReading,
    AnswerScore,
    ToolFailure,
    naive_system,
    open_read_only,
    run_context_tool,
    run_naive_tool,
    run_once,
    run_sql,
)
from phenoctx.cohort import PRESETS, Judgments, build_cohort
from phenoctx.db import DEFAULT_CSV_DIR
from phenoctx.llm import LLMError, LLMFatalError, ToolCall, ToolResult, Turn

HBA1C = PRESETS["hba1c"].judgments.model_dump(exclude_none=True)


def answer(text: str, stop_reason: str = "end_turn") -> Turn:
    return Turn(text, [], stop_reason, 10, 5)


def tool_turn(*calls: tuple[str, dict[str, Any]]) -> Turn:
    tool_calls = [ToolCall(f"t{i}", name, args) for i, (name, args) in enumerate(calls)]
    return Turn("", tool_calls, "tool_use", 10, 5)


class ScriptedLLM:
    """A fake LLM that replays canned turns in order."""

    backend = "fake"
    model = "fake-model"
    effort = None
    concurrency = 1

    def __init__(self, *turns: Any, reading: AnswerReading | None = None) -> None:
        self.turns = list(turns)
        self.reading = reading or AnswerReading(headline_number=74, all_numbers=[74])
        self.requests: list[dict[str, Any]] = []
        self.prompts: list[str] = []

    def respond(self, system: str, tools: Any, messages: list[dict[str, Any]]) -> Turn:
        self.requests.append({"system": system, "tools": tools, "messages": list(messages)})
        item = self.turns.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def continuation(self, turn: Turn, results: list[ToolResult]) -> list[dict[str, Any]]:
        return [{"role": "tool", "results": results}]

    def extract(self, prompt: str, schema: Any) -> tuple[AnswerReading, int, int]:
        self.prompts.append(prompt)
        return self.reading, 1, 1


@pytest.fixture(scope="module")
def locked() -> duckdb.DuckDBPyConnection:
    if not (DEFAULT_CSV_DIR / "patients.csv").is_file():
        pytest.skip("Synthea CSVs not present; see data/README.md")
    return open_read_only()


@pytest.fixture
def naive(locked: duckdb.DuckDBPyConnection) -> Agent:
    return Agent("naive", "system", NAIVE_TOOLS, run_naive_tool)


def test_run_sql_returns_rows(locked: duckdb.DuckDBPyConnection) -> None:
    body = json.loads(run_sql(locked, "SELECT count(*) AS n FROM patients"))

    assert body == {"columns": ["n"], "rows": [[1153]], "truncated": False}


def test_run_sql_reports_truncation(locked: duckdb.DuckDBPyConnection) -> None:
    body = json.loads(run_sql(locked, "SELECT Id FROM patients"))

    assert len(body["rows"]) == agents.MAX_SQL_ROWS
    assert body["truncated"] is True


@pytest.mark.parametrize(
    "query",
    [
        "DROP TABLE patients",
        "SELECT 1; DROP TABLE patients",
        "CREATE TABLE x AS SELECT 1",
        "COPY patients TO 'out.csv'",
        "SET lock_configuration = false",
    ],
)
def test_run_sql_rejects_anything_but_one_select(
    locked: duckdb.DuckDBPyConnection, query: str
) -> None:
    with pytest.raises(ToolFailure):
        run_sql(locked, query)


def test_run_sql_cannot_read_files(locked: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(duckdb.PermissionException):
        run_sql(locked, f"SELECT * FROM read_csv('{DEFAULT_CSV_DIR / 'patients.csv'}')")


def test_naive_prompt_describes_tables_without_hinting_at_diabetes(
    locked: duckdb.DuckDBPyConnection,
) -> None:
    prompt = naive_system(locked)

    assert all(table in prompt for table in ("patients", "conditions", "observations"))
    assert "DESCRIPTION" in prompt
    assert not any(hint in prompt.lower() for hint in ("diabet", "hba1c", "snomed", "44054006"))


def test_both_agents_get_the_same_question(locked: duckdb.DuckDBPyConnection) -> None:
    first_messages = []
    for agent in (
        Agent("naive", "a", NAIVE_TOOLS, run_naive_tool),
        Agent("context", CONTEXT_SYSTEM, CONTEXT_TOOLS, run_context_tool),
    ):
        llm = ScriptedLLM(answer("Done"))
        run_once(llm, locked, agent, 1)
        first_messages.append(llm.requests[0]["messages"])

    assert first_messages[0] == first_messages[1] == [{"role": "user", "content": QUESTION}]


def test_context_tools_reproduce_preset_counts(locked: duckdb.DuckDBPyConnection) -> None:
    listed = json.loads(run_context_tool(locked, "list_presets", {}))
    counts = [
        json.loads(run_context_tool(locked, "get_cohort", {"judgments": p["judgments"]}))["count"]
        for p in listed
    ]

    assert counts == [74, 115, 474, 41, 142]


def test_explain_patient_returns_qualifying_rows(locked: duckdb.DuckDBPyConnection) -> None:
    cohort = json.loads(run_context_tool(locked, "get_cohort", {"judgments": HBA1C}))
    patient_id = cohort["sample_patient_ids"][0]

    rows = json.loads(
        run_context_tool(locked, "explain_patient", {"patient_id": patient_id, "judgments": HBA1C})
    )

    assert rows
    assert all(float(row["value"]) >= 6.5 for row in rows)


def test_loop_feeds_tool_results_back_and_scores_the_answer(
    locked: duckdb.DuckDBPyConnection, naive: Agent
) -> None:
    llm = ScriptedLLM(tool_turn(("run_sql", {"query": "SELECT 1 AS one"})), answer("There are 74."))

    run = run_once(llm, locked, naive, 3)

    result = llm.requests[1]["messages"][-1]["results"][0]
    assert result.call.id == "t0"
    assert result.is_error is False
    assert run["answer"] == "There are 74."
    assert run["tool_calls"] == 1
    assert run["score"]["headline_number"] == 74
    assert run["input_tokens"] == 21
    assert run["error"] is None


def score(answer_text: str, headline: int | None = None, numbers: Any = ()) -> AnswerScore:
    reading = AnswerReading(headline_number=headline, all_numbers=list(numbers))
    return agents.score_answer(ScriptedLLM(reading=reading), answer_text)[0]


@pytest.mark.parametrize(
    "text",
    [
        "I counted patients with SNOMED 44054006.",
        "Any HbA1c at or above 6.5.",
        "Rows whose description contains the text.",
        "Includes prediabetes.",
        "Counting Type 2 only.",
    ],
)
def test_answers_naming_criteria_state_a_definition(text: str) -> None:
    assert score(text, headline=7).states_definition is False
    assert score(f"{text} That gives 7.", headline=7).states_definition is True


@pytest.mark.parametrize(
    "text",
    [
        "There are 465 patients in the dataset who have been recorded as having diabetes.",
        "There are 74 diabetics in the dataset.",
        "Based on the judgments applied, there are 74 diabetics.",
    ],
)
def test_vague_answers_do_not_state_a_definition(text: str) -> None:
    result = score(text, headline=74)

    assert result.states_definition is False
    assert result.definition_terms == []


@pytest.mark.parametrize(
    "text",
    [
        "It depends on the definition.",
        "This is ambiguous.",
        "Other definitions give other counts.",
        "That depends on how you define it.",
        "Different thresholds and criteria can be used.",
        "Could you please specify what you mean?",
    ],
)
def test_answers_flagging_ambiguity_are_detected(text: str) -> None:
    assert score(text).flags_ambiguity is True


def test_a_plain_count_does_not_flag_ambiguity() -> None:
    assert score("There are 74 diabetics, using SNOMED 44054006.").flags_ambiguity is False


def test_matched_terms_are_saved_for_auditing() -> None:
    result = score("It depends on the code and the HbA1c: 74.", headline=74)

    assert result.definition_terms == ["code", "hba1c"]
    assert result.ambiguity_terms == ["depends on"]


def test_numbers_must_appear_in_the_answer() -> None:
    result = score("Counts were 1,153 and 74.", headline=999, numbers=[74, 1153, 41])

    assert result.headline_number is None
    assert result.all_numbers == [74, 1153]


def test_numbers_no_tool_returned_are_flagged() -> None:
    steps = [
        {"type": "tool_call", "is_error": False, "result": '{"count": 74, "percent": 6.4}'},
        {"type": "tool_call", "is_error": True, "result": "Error at position 82"},
        {"type": "text", "text": "71"},
    ]

    result = score("Counts: 74, 71 and 82.", headline=None, numbers=[74, 71, 82])

    assert agents.untraced_numbers(result, steps) == [71, 82]


def test_a_run_with_an_invented_number_is_counted(
    locked: duckdb.DuckDBPyConnection, naive: Agent
) -> None:
    llm = ScriptedLLM(
        tool_turn(("run_sql", {"query": "SELECT 5"})),
        answer("There are 74."),
    )

    run = run_once(llm, locked, naive, 1)

    assert run["untraced_numbers"] == [74]
    assert agents.summarize([run])["invented_numbers"] == 1


def test_scorer_sees_only_the_answer_text(locked: duckdb.DuckDBPyConnection, naive: Agent) -> None:
    llm = ScriptedLLM(answer("There are 74."))

    run_once(llm, locked, naive, 1)

    assert "There are 74." in llm.prompts[0]
    assert "naive" not in llm.prompts[0].lower()


@pytest.mark.parametrize(
    "tool_input",
    [
        pytest.param({"query": "SELECT nope FROM patients"}, id="bad-sql"),
        pytest.param({}, id="missing-argument"),
        pytest.param({"query": 7}, id="wrong-type"),
    ],
)
def test_tool_errors_go_back_to_the_model(
    locked: duckdb.DuckDBPyConnection, naive: Agent, tool_input: dict[str, Any]
) -> None:
    llm = ScriptedLLM(tool_turn(("run_sql", tool_input)), answer("Fixed."))

    run = run_once(llm, locked, naive, 1)

    assert llm.requests[1]["messages"][-1]["results"][0].is_error is True
    assert run["steps"][0]["is_error"] is True
    assert run["answer"] == "Fixed."


def test_every_parallel_tool_call_gets_a_result(
    locked: duckdb.DuckDBPyConnection, naive: Agent
) -> None:
    llm = ScriptedLLM(
        tool_turn(("run_sql", {"query": "SELECT 1"}), ("run_sql", {"query": "SELECT 2"})),
        answer("Done."),
    )

    run_once(llm, locked, naive, 1)

    results = llm.requests[1]["messages"][-1]["results"]
    assert [result.call.id for result in results] == ["t0", "t1"]


@pytest.mark.parametrize(
    ("turn", "expected"),
    [
        (answer("", "refusal"), "Stopped with reason: refusal"),
        (answer("cut off", "max_tokens"), "Stopped with reason: max_tokens"),
        (answer(""), "Finished without an answer"),
    ],
)
def test_a_non_answer_is_recorded_as_a_failure(
    locked: duckdb.DuckDBPyConnection, naive: Agent, turn: Turn, expected: str
) -> None:
    run = run_once(ScriptedLLM(turn), locked, naive, 1)

    assert run["error"] == expected
    assert run["score"] is None


def test_turn_limit_is_recorded_as_a_failure(
    locked: duckdb.DuckDBPyConnection, naive: Agent
) -> None:
    looping = [tool_turn(("run_sql", {"query": "SELECT 1"})) for _ in range(agents.MAX_TURNS)]

    run = run_once(ScriptedLLM(*looping), locked, naive, 1)

    assert "No final answer" in run["error"]


def test_a_failed_request_is_recorded_but_a_fatal_one_stops_the_script(
    locked: duckdb.DuckDBPyConnection, naive: Agent
) -> None:
    run = run_once(ScriptedLLM(LLMError("timed out")), locked, naive, 1)
    assert run["error"] == "timed out"

    with pytest.raises(LLMFatalError):
        run_once(ScriptedLLM(LLMFatalError("no credit")), locked, naive, 1)


def scored(agent: str, index: int, number: int | None, stated: bool) -> dict[str, Any]:
    score = AnswerScore(
        headline_number=number,
        all_numbers=[] if number is None else [number],
        states_definition=stated,
        flags_ambiguity=not stated,
    )
    return {
        "agent": agent,
        "run": index,
        "steps": [
            {
                "type": "tool_call",
                "name": "run_sql",
                "input": {"query": "SELECT 1"},
                "result": "1",
                "is_error": False,
            },
            {"type": "text", "text": "Answer"},
        ],
        "tool_calls": 1,
        "input_tokens": 10,
        "output_tokens": 5,
        "answer": "Answer",
        "score": score.model_dump(),
        "untraced_numbers": [],
        "error": None,
    }


def test_summary_counts_numbers_and_failures() -> None:
    failed = {**scored("naive", 3, 1, True), "score": None, "error": "boom"}

    summary = agents.summarize(
        [scored("naive", 1, 74, True), scored("naive", 2, None, False), failed]
    )

    assert summary["headline_numbers"] == {"74": 1, "no single number": 1}
    assert summary["runs"] == 3
    assert summary["answered"] == 2
    assert summary["failed"] == 1
    assert summary["stated_definition"] == 1
    assert summary["flagged_ambiguity"] == 1


def test_example_is_the_first_answered_run_whatever_it_says() -> None:
    failed = {**scored("naive", 1, 1, True), "score": None}
    runs = [scored("naive", 3, 999, False), failed, scored("naive", 2, 74, True)]

    assert agents.first_answered(runs)["run"] == 2


def test_saved_results_match_the_api_shape_and_write_assets(tmp_path: Path) -> None:
    runs = [scored("naive", 1, 74, True)], [scored("context", 1, None, True)]
    results = {
        "question": QUESTION,
        "backend": "fake",
        "model": "fake-model",
        "generated_at": "now",
        "summary": {"naive": agents.summarize(runs[0]), "context": agents.summarize(runs[1])},
        "examples": {"naive": runs[0][0], "context": runs[1][0]},
    }
    path = tmp_path / "data" / "agent_runs.json"

    agents.save(results, path, tmp_path / "assets")

    assert json.loads(path.read_text())["question"] == QUESTION
    comparison = (tmp_path / "assets" / "comparison.md").read_text()
    assert "Backend: fake. Model: `fake-model`." in comparison
    assert "74 (x1)" in comparison
    assert "no single number (x1)" in comparison
    assert "`run_sql`" in (tmp_path / "assets" / "transcript_naive.md").read_text()
    assert (tmp_path / "assets" / "transcript_context.md").is_file()


def test_results_record_the_backend_and_model(locked: duckdb.DuckDBPyConnection) -> None:
    results = agents.compare(ScriptedLLM(answer("74"), answer("74")), locked, 1)

    assert (results["backend"], results["model"]) == ("fake", "fake-model")
    assert results["summary"]["naive"]["answered"] == 1
    assert results["summary"]["context"]["answered"] == 1


def test_agents_refuse_to_run_on_the_extract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results_path = tmp_path / "agent_runs.json"
    monkeypatch.setattr(agents, "DEFAULT_CSV_DIR", tmp_path / "no-full-csvs")
    monkeypatch.setattr(agents, "RESULTS_PATH", results_path)
    monkeypatch.setattr(agents, "select_llm", lambda env: ScriptedLLM())

    assert agents.main([]) == 1

    assert "full Synthea CSVs" in capsys.readouterr().err
    assert not results_path.exists()


def clear_llm_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AGENT_BACKEND", "ANTHROPIC_API_KEY", "OLLAMA_MODEL", "OLLAMA_HOST"):
        monkeypatch.delenv(name, raising=False)


def test_unconfigured_run_explains_both_options_and_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clear_llm_settings(monkeypatch)
    monkeypatch.setattr(agents, "open_read_only", lambda: pytest.fail("must not load data"))

    assert agents.main([]) == 0

    output = capsys.readouterr().out
    assert "ANTHROPIC_API_KEY" in output
    assert "OLLAMA_MODEL" in output
    assert "optional" in output


def stub_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, llm: ScriptedLLM) -> Path:
    results_path = tmp_path / "agent_runs.json"
    results_path.write_text("saved")
    monkeypatch.setattr(agents, "select_llm", lambda env: llm)
    monkeypatch.setattr(agents, "open_read_only", lambda: None)
    monkeypatch.setattr(agents, "RESULTS_PATH", results_path)
    monkeypatch.setattr(agents, "ASSETS_DIR", tmp_path / "assets")
    return results_path


def test_a_fatal_error_keeps_the_saved_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = stub_run(monkeypatch, tmp_path, ScriptedLLM())

    def fail(*args: Any) -> None:
        raise LLMFatalError("no credit")

    monkeypatch.setattr(agents, "compare", fail)

    assert agents.main([]) == 1
    assert path.read_text() == "saved"


def test_a_run_with_no_answers_keeps_the_saved_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = stub_run(monkeypatch, tmp_path, ScriptedLLM())
    failed = {"naive": {"answered": 0}, "context": {"answered": 0}}
    monkeypatch.setattr(
        agents,
        "compare",
        lambda *args: {"summary": failed, "runs": [{"error": "boom"}]},
    )

    assert agents.main([]) == 1
    assert path.read_text() == "saved"


def test_the_app_never_imports_an_llm() -> None:
    code = (
        "import sys, phenoctx.api; "
        "print([m for m in ('anthropic', 'phenoctx.llm', 'phenoctx.agents') if m in sys.modules])"
    )

    output = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert output.stdout.strip() == "[]"


def committed_results() -> dict[str, Any]:
    return json.loads(agents.RESULTS_PATH.read_text())


def test_decoded_answers_are_real_settings_and_real_quotes(
    con: duckdb.DuckDBPyConnection,
) -> None:
    results = committed_results()

    for item in results["review"]["decoded"]:
        runs = [
            run
            for run in results["runs"]
            if run["agent"] == item["agent"] and run["score"]["headline_number"] == item["number"]
        ]
        assert len(runs) == item["runs"]
        assert any(item["said"] in run["answer"] for run in runs)
        if item["judgments"]:
            cohort = build_cohort(con, Judgments.model_validate(item["judgments"]))
            assert cohort.count == item["number"]


def patients_from(con: duckdb.DuckDBPyConnection, query: str) -> set[str]:
    return {row[0] for row in con.execute(query).fetchall()}


@pytest.mark.parametrize(
    ("number", "operator"), [(465, "LIKE"), (474, "ILIKE")], ids=["case-sensitive", "any-case"]
)
def test_decoded_settings_select_the_same_patients_as_the_agents_query(
    con: duckdb.DuckDBPyConnection, number: int, operator: str
) -> None:
    decoded = next(d for d in committed_results()["review"]["decoded"] if d["number"] == number)

    from_sql = patients_from(
        con, f"SELECT DISTINCT PATIENT FROM conditions WHERE DESCRIPTION {operator} '%diabetes%'"
    )

    cohort = build_cohort(con, Judgments.model_validate(decoded["judgments"]))
    assert set(cohort.evidence_by_patient) == from_sql


def test_748_is_the_465_search_without_removing_duplicates(
    con: duckdb.DuckDBPyConnection,
) -> None:
    rows, patients = con.execute(
        "SELECT count(*), count(DISTINCT PATIENT) FROM conditions "
        "WHERE DESCRIPTION LIKE '%diabetes%'"
    ).fetchone()

    assert (rows, patients) == (748, 465)
