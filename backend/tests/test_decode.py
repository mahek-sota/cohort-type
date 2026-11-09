import json
from typing import Any

import duckdb
import pytest

from phenoctx.cohort import PRESETS, Judgments
from phenoctx.decode import Candidate, build_candidates, decode_query, decode_run, patients_behind

LOWERCASE = "SELECT COUNT(DISTINCT PATIENT) FROM conditions WHERE DESCRIPTION LIKE '%diabetes%'"
ANY_CASE = LOWERCASE.replace("LIKE", "ILIKE")
ALL_ROWS = "SELECT COUNT(*) FROM conditions WHERE DESCRIPTION LIKE '%diabetes%'"


@pytest.fixture(scope="module")
def candidates(con: duckdb.DuckDBPyConnection) -> list[Candidate]:
    return build_candidates(con)


def step(name: str, tool_input: dict[str, Any], result: Any, is_error: bool = False) -> dict:
    return {
        "type": "tool_call",
        "name": name,
        "input": tool_input,
        "result": json.dumps(result),
        "is_error": is_error,
    }


def sql_step(query: str, value: int) -> dict:
    return step("run_sql", {"query": query}, {"columns": ["n"], "rows": [[value]]})


def test_candidates_cover_every_builder_definition(candidates: list[Candidate]) -> None:
    assert len(candidates) == 15 + 51 + 15 * 51


@pytest.mark.parametrize("preset_id", ["exact-code", "type-2-text", "diabet-text", "hba1c"])
def test_every_simple_preset_is_a_candidate(candidates: list[Candidate], preset_id: str) -> None:
    assert PRESETS[preset_id].judgments in [c.judgments for c in candidates]


def test_a_case_sensitive_search_decodes_to_everything_but_the_diagnosis(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate]
) -> None:
    decoding = decode_query(con, LOWERCASE, 465, candidates)

    assert decoding.status == "match"
    assert decoding.judgments == Judgments(
        evidence="codes",
        include_complications=True,
        include_other_complications=True,
        include_prediabetes=True,
    )


def test_an_any_case_search_decodes_to_all_codes(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate]
) -> None:
    decoding = decode_query(con, ANY_CASE, 474, candidates)

    assert decoding.status == "match"
    assert decoding.judgments == PRESETS["diabet-text"].judgments


def test_counting_rows_is_called_out(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate]
) -> None:
    decoding = decode_query(con, ALL_ROWS, 748, candidates)

    assert decoding.status == "rows_not_patients"
    assert (decoding.reported, decoding.patients) == (748, 465)


def test_an_alias_and_join_still_decode(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate]
) -> None:
    query = (
        "SELECT COUNT(DISTINCT t1.PATIENT) FROM conditions AS t1 JOIN patients AS t2 "
        "ON t1.PATIENT = t2.Id WHERE t1.DESCRIPTION ILIKE '%diabetes%';"
    )

    assert decode_query(con, query, 474, candidates).status == "match"


def test_a_lab_query_decodes_to_the_threshold(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate]
) -> None:
    query = (
        "SELECT COUNT(DISTINCT PATIENT) FROM observations "
        "WHERE CODE = '4548-4' AND TRY_CAST(VALUE AS DOUBLE) >= 6.5"
    )

    decoding = decode_query(con, query, 41, candidates)

    assert decoding.status == "match"
    assert decoding.judgments is not None
    assert decoding.judgments.hba1c_threshold == 6.5


def test_a_cohort_the_builder_cannot_express_does_not_match(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate]
) -> None:
    query = "SELECT COUNT(DISTINCT PATIENT) FROM conditions WHERE DESCRIPTION LIKE 'Neuropathy%'"

    decoding = decode_query(con, query, 19, candidates)

    assert decoding.status == "no_match"
    assert decoding.judgments is None


@pytest.mark.parametrize(
    "query",
    [
        "WITH x AS (SELECT 1) SELECT count(*) FROM x",
        "SELECT count(*) FROM (SELECT 1)",
        "not sql at all",
    ],
)
def test_unsupported_queries_are_not_guessed_at(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate], query: str
) -> None:
    assert decode_query(con, query, 1, candidates).status == "no_match"


def test_from_inside_a_function_is_not_the_outer_from(con: duckdb.DuckDBPyConnection) -> None:
    query = (
        "SELECT COUNT(DISTINCT (SELECT PATIENT FROM conditions LIMIT 1)) "
        "FROM conditions WHERE CODE = '44054006'"
    )

    assert patients_behind(con, query) is not None


def test_a_run_decodes_its_last_successful_count(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate]
) -> None:
    steps = [
        sql_step(ALL_ROWS, 748),
        sql_step(LOWERCASE, 465),
        step("run_sql", {"query": "bad"}, "Error", is_error=True),
    ]

    decoding = decode_run(con, steps, "There are 465 patients.", candidates)

    assert (decoding.status, decoding.reported) == ("match", 465)


def test_a_definition_tool_call_decodes_to_its_own_judgments(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate]
) -> None:
    judgments = {"evidence": "codes", "include_diagnosis": True}
    steps = [step("get_cohort", {"judgments": judgments}, {"count": 74})]

    decoding = decode_run(con, steps, "There are 74 diabetics.", candidates)

    assert decoding.status == "match"
    assert decoding.judgments == PRESETS["exact-code"].judgments


def test_an_answer_that_ignores_the_tool_result_is_not_decoded(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate]
) -> None:
    decoding = decode_run(con, [sql_step(LOWERCASE, 465)], "There are 500 patients.", candidates)

    assert decoding.status == "no_count"


def test_an_answer_of_no_patients_reports_a_zero_count(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate]
) -> None:
    query = "SELECT COUNT(DISTINCT PATIENT) FROM conditions WHERE DESCRIPTION = 'Type 2 diabetes'"

    decoding = decode_run(con, [sql_step(query, 0)], "There are no such patients.", candidates)

    assert decoding.status == "no_match"
    assert (decoding.reported, decoding.patients) == (0, 0)


def test_a_run_with_no_tools_has_nothing_to_decode(
    con: duckdb.DuckDBPyConnection, candidates: list[Candidate]
) -> None:
    assert decode_run(con, [], "There are 74 patients.", candidates).status == "no_count"
