"""The committed extract must behave exactly like the full data for everything the app does."""

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from conftest import needs_full_csvs
from phenoctx.cohort import PRESETS, Judgments, build_cohort, patient_evidence
from phenoctx.db import DEFAULT_CSV_DIR, EXTRACT_DIR, connect
from phenoctx.extract import build_extract


@pytest.fixture(scope="module")
def extract() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = connect(EXTRACT_DIR)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def full() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = connect(DEFAULT_CSV_DIR)
    yield connection
    connection.close()


@pytest.mark.parametrize(
    ("preset_id", "expected"),
    [
        ("exact-code", 74),
        ("type-2-text", 115),
        ("diabet-text", 474),
        ("hba1c", 41),
        ("text-or-hba1c", 142),
    ],
)
def test_extract_reproduces_the_published_counts(
    extract: duckdb.DuckDBPyConnection, preset_id: str, expected: int
) -> None:
    cohort = build_cohort(extract, PRESETS[preset_id].judgments)

    assert cohort.count == expected
    assert cohort.population == 1153


def test_extract_holds_only_what_the_app_reads(extract: duckdb.DuckDBPyConnection) -> None:
    tables = {
        table: extract.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("patients", "conditions", "observations")
    }
    columns = [row[0] for row in extract.execute("DESCRIBE patients").fetchall()]

    assert tables == {"patients": 1153, "conditions": 822, "observations": 8804}
    assert columns == ["Id", "source_line"]


def test_connect_falls_back_to_the_extract_without_full_csvs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("phenoctx.db.DEFAULT_CSV_DIR", tmp_path)

    con = connect()

    assert con.execute("SELECT count(*) FROM conditions").fetchone()[0] == 822


def test_an_explicit_folder_never_falls_back(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        connect(tmp_path)


@needs_full_csvs
@pytest.mark.parametrize(
    "judgments",
    [
        *[preset.judgments for preset in PRESETS.values()],
        Judgments(evidence="labs", hba1c_threshold=5.0),
        Judgments(evidence="both", include_prediabetes=True, hba1c_threshold=9.0),
    ],
    ids=[*PRESETS, "low-threshold", "prediabetes-or-high-threshold"],
)
def test_extract_and_full_data_give_identical_evidence(
    extract: duckdb.DuckDBPyConnection, full: duckdb.DuckDBPyConnection, judgments: Judgments
) -> None:
    assert build_cohort(extract, judgments) == build_cohort(full, judgments)


@needs_full_csvs
def test_patient_evidence_matches_for_one_patient(
    extract: duckdb.DuckDBPyConnection, full: duckdb.DuckDBPyConnection
) -> None:
    judgments = PRESETS["text-or-hba1c"].judgments
    patient_id = sorted(build_cohort(full, judgments).evidence_by_patient)[0]

    assert patient_evidence(extract, judgments, patient_id) == patient_evidence(
        full, judgments, patient_id
    )


@needs_full_csvs
def test_committed_extract_is_what_the_builder_produces(
    full: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    build_extract(full, tmp_path)

    for table in ("patients", "conditions", "observations"):
        assert (tmp_path / f"{table}.csv").read_bytes() == (
            EXTRACT_DIR / f"{table}.csv"
        ).read_bytes()
