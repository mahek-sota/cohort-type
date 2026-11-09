"""Compare a naive SQL agent with a context-aware agent on one question.

This is optional: the app only displays the saved results and never calls an LLM. Run it with
`make agents`, on Anthropic or a local Ollama model (see `phenoctx.llm`). Results are saved to
data/agent_runs.json and article_assets/.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel, ValidationError

from phenoctx.cohort import PRESETS, Judgments, build_cohort, patient_evidence
from phenoctx.db import DEFAULT_CSV_DIR, REPO_ROOT, connect
from phenoctx.llm import DEFAULT_OLLAMA_MODEL, LLM, LLMError, LLMFatalError, ToolResult, select_llm

MAX_TURNS = 20
MAX_SQL_ROWS = 200
COHORT_SAMPLE_SIZE = 20
QUESTION = "How many diabetics are in this dataset?"

RESULTS_PATH = REPO_ROOT / "data" / "agent_runs.json"
ASSETS_DIR = REPO_ROOT / "article_assets"

NOT_CONFIGURED = f"""\
No LLM is configured, so `make agents` has nothing to run.

This step is optional. The app works without it and shows the saved results.

To regenerate the results, set one of these in .env:

  Local, free, no account:  AGENT_BACKEND=ollama
                            OLLAMA_MODEL=<model>  (default: {DEFAULT_OLLAMA_MODEL})
                            Needs Ollama running, with the model pulled.

  Anthropic API:            ANTHROPIC_API_KEY=<your key>
"""

TABLE_NOTES = {
    "patients": "One row per patient.",
    "conditions": "One row per recorded condition. PATIENT references patients.Id.",
    "observations": (
        "One row per recorded measurement or lab result. PATIENT references patients.Id."
    ),
}

CONTEXT_SYSTEM = """\
You answer questions about a synthetic patient dataset using the cohort tools.

Never give a count without naming the definition you used and its judgments. If a question is \
ambiguous, say so and show how the count changes across definitions."""

JUDGMENTS_SCHEMA = {
    "type": "object",
    "description": (
        "Judgments for a definition, in the same shape list_presets returns. Leave out any "
        "judgment that does not apply."
    ),
    "properties": {
        "evidence": {"type": "string", "enum": ["codes", "labs", "both"]},
        "include_diagnosis": {"type": "boolean"},
        "include_complications": {"type": "boolean"},
        "include_other_complications": {"type": "boolean"},
        "include_prediabetes": {"type": "boolean"},
        "hba1c_threshold": {"type": ["number", "null"]},
    },
    "required": ["evidence"],
}

NAIVE_TOOLS = [
    {
        "name": "run_sql",
        "description": "Run one read-only DuckDB SELECT query and return the rows.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
]

CONTEXT_TOOLS = [
    {
        "name": "list_presets",
        "description": "List the saved cohort definitions with their judgments and rationales.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_cohort",
        "description": (
            "Count the patients matching a set of judgments. Returns the count, the percentage "
            f"of the population, and up to {COHORT_SAMPLE_SIZE} patient ids."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"judgments": JUDGMENTS_SCHEMA},
            "required": ["judgments"],
        },
    },
    {
        "name": "explain_patient",
        "description": "Return the source rows that qualify one patient under a set of judgments.",
        "input_schema": {
            "type": "object",
            "properties": {"patient_id": {"type": "string"}, "judgments": JUDGMENTS_SCHEMA},
            "required": ["patient_id", "judgments"],
        },
    },
]


class ToolFailure(Exception):
    """A tool problem the model can read and recover from."""


def schema_description(con: duckdb.DuckDBPyConnection) -> str:
    """Describe the tables from the database itself, so the text can't drift from the data."""
    sections = []
    for table, note in TABLE_NOTES.items():
        columns = ", ".join(
            f"{row[0]} {row[1]}" for row in con.execute(f"DESCRIBE {table}").fetchall()
        )
        sections.append(f"{table}: {note}\nColumns: {columns}")
    return "\n\n".join(sections)


def naive_system(con: duckdb.DuckDBPyConnection) -> str:
    return (
        "You answer questions about a synthetic patient dataset by querying a DuckDB database "
        f"with the run_sql tool.\n\n{schema_description(con)}"
    )


def run_sql(con: duckdb.DuckDBPyConnection, query: str) -> str:
    """Run one SELECT. The connection is locked to the loaded tables, see `open_read_only`."""
    statements = duckdb.extract_statements(query)
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise ToolFailure("Only a single SELECT statement is allowed.")
    cursor = con.cursor()
    try:
        result = cursor.execute(query)
        columns = [column[0] for column in result.description]
        rows = result.fetchmany(MAX_SQL_ROWS + 1)
    finally:
        cursor.close()
    return json.dumps(
        {"columns": columns, "rows": rows[:MAX_SQL_ROWS], "truncated": len(rows) > MAX_SQL_ROWS},
        default=str,
    )


def run_naive_tool(con: duckdb.DuckDBPyConnection, name: str, tool_input: dict[str, Any]) -> str:
    if name != "run_sql":
        raise ToolFailure(f"Unknown tool: {name}")
    return run_sql(con, tool_input["query"])


def run_context_tool(con: duckdb.DuckDBPyConnection, name: str, tool_input: dict[str, Any]) -> str:
    if name == "list_presets":
        presets = [
            {"id": key, **preset.model_dump(exclude_none=True)} for key, preset in PRESETS.items()
        ]
        return json.dumps(presets)
    if name not in ("get_cohort", "explain_patient"):
        raise ToolFailure(f"Unknown tool: {name}")

    judgments = Judgments.model_validate(tool_input["judgments"])
    cursor = con.cursor()
    try:
        if name == "explain_patient":
            evidence = patient_evidence(cursor, judgments, tool_input["patient_id"])
            return json.dumps([item.model_dump() for item in evidence])
        cohort = build_cohort(cursor, judgments)
    finally:
        cursor.close()
    return json.dumps(
        {
            "count": cohort.count,
            "population": cohort.population,
            "percent": cohort.percent,
            "sample_patient_ids": sorted(cohort.evidence_by_patient)[:COHORT_SAMPLE_SIZE],
        }
    )


@dataclass(frozen=True)
class Agent:
    name: str
    system: str
    tools: list[dict[str, Any]]
    run_tool: Callable[[duckdb.DuckDBPyConnection, str, dict[str, Any]], str]


class AnswerReading(BaseModel):
    """The numbers a scorer model read from an answer. Checked against the text before use."""

    headline_number: int | None
    all_numbers: list[int]


class AnswerScore(BaseModel):
    """Facts about a final answer, read without knowing which agent wrote it."""

    headline_number: int | None
    all_numbers: list[int]
    states_definition: bool
    flags_ambiguity: bool
    definition_terms: list[str] = []
    ambiguity_terms: list[str] = []


# Fixed rules, not a model's judgment: a small local model was unreliable at both of these. The
# rules are the same for both agents and backends, and each match is saved so it can be audited.
# They are crude, so saved results are also reviewed by reading every answer.
DEFINITION_TERMS = re.compile(
    r"\b(snomed|icd|loinc|hba1c|a1c|codes?|coded|labs?|threshold|complications?"
    r"|prediabetes|description|type\s*(?:1|2|i|ii))\b",
    re.IGNORECASE,
)
AMBIGUITY_TERMS = re.compile(
    r"\b(depends? on|ambiguous|ambiguity|(?:different|other|several|multiple|various) definitions?"
    r"|different (?:criteria|thresholds)|across definitions|how (?:you|we|one) defines?"
    r"|could you (?:please )?(?:specify|provide)|varies|vary)\b",
    re.IGNORECASE,
)

SCORER_PROMPT = """\
An assistant was asked: "{question}"

Its final answer is below. Report these facts about the text only. Don't judge if it is correct.

- headline_number: the single patient count the answer presents as its answer. Use null if it \
presents several counts without choosing one.
- all_numbers: every patient count it reports for a candidate definition of diabetic. Leave out \
percentages and the total population.

<answer>
{answer}
</answer>"""


def _verified_numbers(numbers: list[int], answer: str) -> list[int]:
    """Keep numbers that are really in the answer, so an invented one can't score."""
    present = {int(n) for n in re.findall(r"\d+", re.sub(r"(?<=\d),(?=\d)", "", answer))}
    return [number for number in numbers if number in present]


def _matched_terms(pattern: re.Pattern[str], answer: str) -> list[str]:
    return sorted({" ".join(match.group(0).lower().split()) for match in pattern.finditer(answer)})


def untraced_numbers(score: AnswerScore, steps: list[dict[str, Any]]) -> list[int]:
    """Return reported counts that no tool ever returned, which means the model made them up."""
    seen: set[int] = set()
    for step in steps:
        if step["type"] == "tool_call" and not step["is_error"]:
            seen.update(int(n) for n in re.findall(r"\b\d+\b", step["result"]))
    reported = set(score.all_numbers)
    if score.headline_number is not None:
        reported.add(score.headline_number)
    return sorted(reported - seen)


def score_answer(llm: LLM, answer: str, question: str = QUESTION) -> tuple[AnswerScore, int, int]:
    reading, input_tokens, output_tokens = llm.extract(
        SCORER_PROMPT.format(question=question, answer=answer), AnswerReading
    )
    headline = _verified_numbers(
        [] if reading.headline_number is None else [reading.headline_number], answer
    )
    numbers = _verified_numbers(reading.all_numbers, answer)
    gave_a_count = bool(headline or numbers)
    definition_terms = _matched_terms(DEFINITION_TERMS, answer) if gave_a_count else []
    ambiguity_terms = _matched_terms(AMBIGUITY_TERMS, answer)
    score = AnswerScore(
        headline_number=headline[0] if headline else None,
        all_numbers=numbers,
        states_definition=bool(definition_terms),
        flags_ambiguity=bool(ambiguity_terms),
        definition_terms=definition_terms,
        ambiguity_terms=ambiguity_terms,
    )
    return score, input_tokens, output_tokens


def run_once(
    llm: LLM,
    con: duckdb.DuckDBPyConnection,
    agent: Agent,
    index: int,
    question: str = QUESTION,
    score: bool = True,
) -> dict[str, Any]:
    """Run one fresh conversation. Failures are recorded, not hidden or retried here."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    run: dict[str, Any] = {
        "agent": agent.name,
        "run": index,
        "steps": [],
        "tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "answer": None,
        "score": None,
        "untraced_numbers": [],
        "error": None,
    }
    try:
        for _ in range(MAX_TURNS):
            turn = llm.respond(agent.system, agent.tools, messages)
            run["input_tokens"] += turn.input_tokens
            run["output_tokens"] += turn.output_tokens
            if turn.text:
                run["steps"].append({"type": "text", "text": turn.text})

            if turn.stop_reason == "end_turn":
                run["answer"] = turn.text
                if not turn.text:
                    run["error"] = "Finished without an answer"
                break
            if turn.stop_reason != "tool_use":
                run["error"] = f"Stopped with reason: {turn.stop_reason}"
                break

            results = []
            for call in turn.tool_calls:
                run["tool_calls"] += 1
                try:
                    output, is_error = agent.run_tool(con, call.name, call.input), False
                except (ToolFailure, duckdb.Error, ValidationError, KeyError, TypeError) as error:
                    output, is_error = f"Error: {error}", True
                run["steps"].append(
                    {
                        "type": "tool_call",
                        "name": call.name,
                        "input": call.input,
                        "result": output,
                        "is_error": is_error,
                    }
                )
                results.append(ToolResult(call, output, is_error))
            messages.extend(llm.continuation(turn, results))
        else:
            run["error"] = f"No final answer after {MAX_TURNS} turns"

        if run["answer"] and score:
            result, input_tokens, output_tokens = score_answer(llm, run["answer"], question)
            run["score"] = result.model_dump()
            run["untraced_numbers"] = untraced_numbers(result, run["steps"])
            run["input_tokens"] += input_tokens
            run["output_tokens"] += output_tokens
    except LLMError as error:
        run["error"] = str(error)
    return run


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [run["score"] for run in runs if run["score"]]
    headlines = Counter(
        "no single number" if score["headline_number"] is None else str(score["headline_number"])
        for score in scored
    )
    return {
        "runs": len(runs),
        "answered": len(scored),
        "failed": len(runs) - len(scored),
        "headline_numbers": dict(headlines.most_common()),
        "gave_a_count": sum(bool(s["headline_number"] or s["all_numbers"]) for s in scored),
        "stated_definition": sum(score["states_definition"] for score in scored),
        "flagged_ambiguity": sum(score["flags_ambiguity"] for score in scored),
        "invented_numbers": sum(bool(run["untraced_numbers"]) for run in runs),
        "mean_tool_calls": round(sum(run["tool_calls"] for run in runs) / len(runs), 1),
        "input_tokens": sum(run["input_tokens"] for run in runs),
        "output_tokens": sum(run["output_tokens"] for run in runs),
    }


def first_answered(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the example transcript by a fixed rule, so it can't be chosen for how it looks."""
    return next((run for run in sorted(runs, key=lambda r: r["run"]) if run["score"]), None)


def transcript_markdown(run: dict[str, Any]) -> str:
    lines = [
        f"# {run['agent'].title()} agent, run {run['run']}",
        "",
        f"**Question:** {QUESTION}",
        "",
    ]
    for step in run["steps"]:
        if step["type"] == "text":
            lines += [step["text"], ""]
            continue
        lines += [
            f"**Tool call: `{step['name']}`**",
            "",
            "```json",
            json.dumps(step["input"], indent=2),
            "```",
            "",
            "Result:",
            "",
            "```",
            step["result"],
            "```",
            "",
        ]
    return "\n".join(lines)


def comparison_markdown(results: dict[str, Any]) -> str:
    agents = results["summary"]
    rows = [
        ("Runs", "runs"),
        ("Answered", "answered"),
        ("Failed", "failed"),
        ("Gave a count", "gave_a_count"),
        ("Stated a definition (phrase rule)", "stated_definition"),
        ("Flagged ambiguity (phrase rule)", "flagged_ambiguity"),
        ("Reported numbers no tool returned", "invented_numbers"),
        ("Mean tool calls", "mean_tool_calls"),
        ("Input tokens", "input_tokens"),
        ("Output tokens", "output_tokens"),
    ]
    lines = [
        "# Agent comparison",
        "",
        f'Question: "{results["question"]}"',
        "",
        f"Backend: {results['backend']}. Model: `{results['model']}`. "
        f"Generated {results['generated_at']}.",
        "",
        "| | Naive | Context-aware |",
        "|---|---|---|",
    ]
    lines += [f"| {label} | {agents['naive'][k]} | {agents['context'][k]} |" for label, k in rows]
    lines += ["", "## Numbers returned", ""]
    for name, label in (("naive", "Naive"), ("context", "Context-aware")):
        counts = agents[name]["headline_numbers"]
        text = ", ".join(f"{number} (x{count})" for number, count in counts.items()) or "none"
        lines.append(f"- {label}: {text}")
    return "\n".join(lines) + "\n"


def open_read_only() -> duckdb.DuckDBPyConnection:
    """Load the full data, then block file access so model SQL reaches only these tables.

    This never falls back to the extract. It holds only diabetes rows, so an agent exploring it
    would be handed the answer's shape, which would rig the comparison.
    """
    con = connect(DEFAULT_CSV_DIR)
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


def save(results: dict[str, Any], results_path: Path, assets_dir: Path) -> None:
    results_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, indent=2) + "\n")
    (assets_dir / "comparison.md").write_text(comparison_markdown(results))
    for name, run in results["examples"].items():
        if run:
            (assets_dir / f"transcript_{name}.md").write_text(transcript_markdown(run))


def build_agents(con: duckdb.DuckDBPyConnection) -> list[Agent]:
    return [
        Agent("naive", naive_system(con), NAIVE_TOOLS, run_naive_tool),
        Agent("context", CONTEXT_SYSTEM, CONTEXT_TOOLS, run_context_tool),
    ]


def compare(llm: LLM, con: duckdb.DuckDBPyConnection, runs_per_agent: int) -> dict[str, Any]:
    agents = build_agents(con)
    jobs = [(agent, index) for agent in agents for index in range(1, runs_per_agent + 1)]
    with ThreadPoolExecutor(max_workers=llm.concurrency) as pool:
        runs = list(pool.map(lambda job: run_once(llm, con, *job), jobs))

    by_agent = {agent.name: [r for r in runs if r["agent"] == agent.name] for agent in agents}
    return {
        "question": QUESTION,
        "backend": llm.backend,
        "model": llm.model,
        "effort": llm.effort,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "prompts": {agent.name: agent.system for agent in agents},
        "summary": {name: summarize(group) for name, group in by_agent.items()},
        "examples": {name: first_answered(group) for name, group in by_agent.items()},
        "runs": runs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10, help="runs per agent")
    args = parser.parse_args(argv)

    try:
        llm = select_llm(os.environ)
        if llm is None:
            print(NOT_CONFIGURED)
            return 0
        print(f"Running {args.runs} runs per agent on {llm.backend} ({llm.model}).")
        results = compare(llm, open_read_only(), args.runs)
    except FileNotFoundError as error:
        print(f"Regenerating the results needs the full Synthea CSVs. {error}", file=sys.stderr)
        return 1
    except LLMFatalError as error:
        print(f"Stopped, and kept any saved results: {error}", file=sys.stderr)
        return 1

    if not any(summary["answered"] for summary in results["summary"].values()):
        errors = {run["error"] for run in results["runs"]}
        print(f"No run answered, so the saved results were kept: {errors}", file=sys.stderr)
        return 1

    save(results, RESULTS_PATH, ASSETS_DIR)
    print(comparison_markdown(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
