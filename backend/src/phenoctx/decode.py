"""Work out which builder settings an agent's answer really used.

A matching count proves little, since two definitions can share a number by chance. So this recovers
the patients behind the agent's own query and looks for a definition with exactly the same patients.
"""

import itertools
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

import duckdb
from pydantic import BaseModel

from phenoctx.cohort import CODE_GROUPS, HBA1C_LOINC, Judgments

THRESHOLDS = [round(5 + step * 0.1, 1) for step in range(51)]
FLAGS = {
    "diagnosis": "include_diagnosis",
    "complications": "include_complications",
    "other_complications": "include_other_complications",
    "prediabetes": "include_prediabetes",
}


class Decoding(BaseModel):
    """`rows_not_patients` means the query matches a definition but counted records instead."""

    status: Literal["match", "rows_not_patients", "no_match", "no_count"]
    reported: int | None = None
    patients: int | None = None
    judgments: Judgments | None = None


@dataclass(frozen=True)
class Candidate:
    judgments: Judgments
    patients: frozenset[str]


def _patients_by_group(con: duckdb.DuckDBPyConnection) -> dict[str, frozenset[str]]:
    groups = {}
    for group, codes in CODE_GROUPS.items():
        rows = con.execute(
            "SELECT DISTINCT PATIENT FROM conditions WHERE list_contains(?, CODE)", [list(codes)]
        ).fetchall()
        groups[group] = frozenset(row[0] for row in rows)
    return groups


def build_candidates(con: duckdb.DuckDBPyConnection) -> list[Candidate]:
    """List every definition the builder can express.

    Some settings select identical patients, because one group can sit inside another. The most
    inclusive come first, since that describes what a broad search really covered.
    """
    groups = _patients_by_group(con)
    highest_result = con.execute(
        "SELECT PATIENT, max(TRY_CAST(VALUE AS DOUBLE)) FROM observations "
        "WHERE CODE = ? GROUP BY PATIENT",
        [HBA1C_LOINC],
    ).fetchall()
    above = {
        threshold: frozenset(p for p, value in highest_result if value and value >= threshold)
        for threshold in THRESHOLDS
    }

    combinations = [
        combo
        for size in range(len(groups), 0, -1)
        for combo in itertools.combinations(groups, size)
    ]
    candidates = []
    for combo in combinations:
        flags = {FLAGS[group]: True for group in combo}
        coded = frozenset().union(*(groups[group] for group in combo))
        candidates.append(Candidate(Judgments(evidence="codes", **flags), coded))
    for threshold, patients in above.items():
        candidates.append(
            Candidate(Judgments(evidence="labs", hba1c_threshold=threshold), patients)
        )
    for combo in combinations:
        flags = {FLAGS[group]: True for group in combo}
        coded = frozenset().union(*(groups[group] for group in combo))
        for threshold, patients in above.items():
            judgments = Judgments(evidence="both", hba1c_threshold=threshold, **flags)
            candidates.append(Candidate(judgments, coded | patients))
    return candidates


def _select_list_end(query: str) -> tuple[int, int] | None:
    """Return where the outer SELECT list starts and ends, or None if the shape is unsupported."""
    match = re.match(r"\s*SELECT\s", query, re.IGNORECASE)
    if not match:
        return None
    depth = 0
    for index in range(match.end(), len(query)):
        character = query[index]
        depth += (character == "(") - (character == ")")
        if depth == 0 and re.match(r"\sFROM\s", query[index : index + 6], re.IGNORECASE):
            return match.end(), index
    return None


def patients_behind(con: duckdb.DuckDBPyConnection, query: str) -> frozenset[str] | None:
    """Rerun a counting query so it returns its patients. None means that isn't possible."""
    span = _select_list_end(query)
    if span is None:
        return None
    rewritten = f"SELECT DISTINCT PATIENT {query[span[1] :].strip().rstrip(';')}"
    cursor = con.cursor()
    try:
        return frozenset(row[0] for row in cursor.execute(rewritten).fetchall())
    except duckdb.Error:
        return None
    finally:
        cursor.close()


def _matching(patients: frozenset[str], candidates: list[Candidate]) -> Judgments | None:
    return next((c.judgments for c in candidates if c.patients == patients), None)


def _single_count(result: str) -> int | None:
    try:
        rows = json.loads(result).get("rows", [])
    except (json.JSONDecodeError, AttributeError):
        return None
    if len(rows) == 1 and len(rows[0]) == 1 and isinstance(rows[0][0], int):
        return rows[0][0]
    return None


def decode_query(
    con: duckdb.DuckDBPyConnection, query: str, reported: int, candidates: list[Candidate]
) -> Decoding:
    patients = patients_behind(con, query)
    if patients is None:
        return Decoding(status="no_match", reported=reported)
    # An empty search means nothing was found, not that a definition with no patients was chosen.
    judgments = _matching(patients, candidates) if patients else None
    status = "match" if judgments and len(patients) == reported else "no_match"
    if judgments and len(patients) != reported:
        status = "rows_not_patients"
    return Decoding(status=status, reported=reported, patients=len(patients), judgments=judgments)


def decode_run(
    con: duckdb.DuckDBPyConnection,
    steps: list[dict[str, Any]],
    answer: str | None,
    candidates: list[Candidate],
) -> Decoding:
    """Decode the last successful count in a run, if the answer actually reports it."""
    for step in reversed(steps):
        if step["type"] != "tool_call" or step["is_error"]:
            continue
        reported: int | None = None
        decoding: Decoding | None = None
        if step["name"] == "run_sql":
            reported = _single_count(step["result"])
            if reported is not None:
                decoding = decode_query(con, step["input"]["query"], reported, candidates)
        elif step["name"] == "get_cohort":
            reported = json.loads(step["result"])["count"]
            judgments = Judgments.model_validate(step["input"]["judgments"])
            decoding = Decoding(
                status="match", reported=reported, patients=reported, judgments=judgments
            )
        if decoding is None:
            continue
        digits = re.sub(r"(?<=\d),(?=\d)", "", answer or "")
        says_none = reported == 0 and re.search(r"\b(no|none|zero)\b", digits, re.IGNORECASE)
        if not says_none and not re.search(rf"\b{reported}\b", digits):
            return Decoding(status="no_count")
        return decoding
    return Decoding(status="no_count")
