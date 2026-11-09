"""The loader must reproduce the published counts exactly."""

from itertools import islice
from pathlib import Path

import duckdb
import pytest

from conftest import needs_full_csvs
from phenoctx.db import DEFAULT_CSV_DIR, connect

T2DM_CODE = "SELECT DISTINCT PATIENT FROM conditions WHERE CODE = '44054006'"
T2DM_TEXT = "SELECT DISTINCT PATIENT FROM conditions WHERE DESCRIPTION ILIKE '%type 2 diabetes%'"
DIABET_TEXT = "SELECT DISTINCT PATIENT FROM conditions WHERE DESCRIPTION ILIKE '%diabet%'"
HIGH_HBA1C = (
    "SELECT DISTINCT PATIENT FROM observations "
    "WHERE CODE = '4548-4' AND TRY_CAST(VALUE AS DOUBLE) >= 6.5"
)


def count(con: duckdb.DuckDBPyConnection, query: str) -> int:
    return con.execute(f"SELECT count(*) FROM ({query})").fetchone()[0]


def test_population_size(con: duckdb.DuckDBPyConnection) -> None:
    assert count(con, "SELECT Id FROM patients") == 1153
    assert count(con, "SELECT DISTINCT Id FROM patients") == 1153


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        pytest.param(T2DM_CODE, 74, id="1-exact-code"),
        pytest.param(T2DM_TEXT, 115, id="2-type-2-text"),
        pytest.param(DIABET_TEXT, 474, id="3-diabet-text"),
        pytest.param(HIGH_HBA1C, 41, id="4-hba1c"),
        pytest.param(f"{T2DM_TEXT} UNION {HIGH_HBA1C}", 142, id="5-text-or-hba1c"),
    ],
)
def test_published_definition_counts(
    con: duckdb.DuckDBPyConnection, query: str, expected: int
) -> None:
    assert count(con, query) == expected


def test_definitions_2_and_4_overlap_on_14(con: duckdb.DuckDBPyConnection) -> None:
    assert count(con, f"{T2DM_TEXT} INTERSECT {HIGH_HBA1C}") == 14


def test_every_row_belongs_to_a_known_patient(con: duckdb.DuckDBPyConnection) -> None:
    for table in ("conditions", "observations"):
        orphans = f"SELECT 1 FROM {table} WHERE PATIENT NOT IN (SELECT Id FROM patients)"
        assert count(con, orphans) == 0


def test_codes_and_values_stay_text(con: duckdb.DuckDBPyConnection) -> None:
    types = {row[0]: row[1] for row in con.execute("DESCRIBE observations").fetchall()}
    assert types["CODE"] == "VARCHAR"
    assert types["VALUE"] == "VARCHAR"
    assert types["DATE"] == "TIMESTAMP"


@needs_full_csvs
@pytest.mark.parametrize("line", [2, 500, 30_000])
def test_source_line_points_at_the_csv_row(con: duckdb.DuckDBPyConnection, line: int) -> None:
    with Path(DEFAULT_CSV_DIR / "conditions.csv").open() as f:
        raw = next(islice(f, line - 1, None)).rstrip("\n")

    patient, code, description = con.execute(
        "SELECT PATIENT, CODE, DESCRIPTION FROM conditions WHERE source_line = ?", [line]
    ).fetchone()

    assert patient in raw
    assert f",{code}," in raw
    assert description in raw


def test_missing_csv_names_the_problem(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="data/README.md"):
        connect(tmp_path)
