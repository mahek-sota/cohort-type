import csv
from typing import Any

import duckdb
import pytest
from pydantic import ValidationError

from conftest import needs_full_csvs
from phenoctx.cohort import (
    CODE_GROUPS,
    PRESETS,
    Judgments,
    build_cohort,
    patient_evidence,
)
from phenoctx.db import DEFAULT_CSV_DIR

ALL_T2DM = Judgments(
    evidence="codes",
    include_diagnosis=True,
    include_complications=True,
    include_other_complications=True,
)


def patients(con: duckdb.DuckDBPyConnection, judgments: Judgments) -> set[str]:
    return set(build_cohort(con, judgments).evidence_by_patient)


def preset_patients(con: duckdb.DuckDBPyConnection, preset_id: str) -> set[str]:
    return patients(con, PRESETS[preset_id].judgments)


@pytest.mark.parametrize(
    ("preset_id", "expected", "percent"),
    [
        ("exact-code", 74, 6.4),
        ("type-2-text", 115, 10.0),
        ("diabet-text", 474, 41.1),
        ("hba1c", 41, 3.6),
        ("text-or-hba1c", 142, 12.3),
    ],
)
def test_presets_reproduce_the_published_counts(
    con: duckdb.DuckDBPyConnection, preset_id: str, expected: int, percent: float
) -> None:
    cohort = build_cohort(con, PRESETS[preset_id].judgments)

    assert cohort.count == expected
    assert cohort.population == 1153
    assert cohort.percent == percent


def test_definitions_2_and_4_overlap_on_14(con: duckdb.DuckDBPyConnection) -> None:
    assert len(preset_patients(con, "type-2-text") & preset_patients(con, "hba1c")) == 14


def test_text_preset_leaves_out_half_the_diagnosis_code(con: duckdb.DuckDBPyConnection) -> None:
    diagnosed = preset_patients(con, "exact-code")

    assert len(diagnosed - preset_patients(con, "type-2-text")) == 37
    assert len(diagnosed - preset_patients(con, "text-or-hba1c")) == 10


def test_every_high_hba1c_patient_has_a_type_2_code(con: duckdb.DuckDBPyConnection) -> None:
    coded = patients(con, ALL_T2DM)

    assert len(coded) == 169
    assert preset_patients(con, "hba1c") <= coded


def test_prediabetes_only_patients_match_the_rationale(con: duckdb.DuckDBPyConnection) -> None:
    assert len(preset_patients(con, "diabet-text") - patients(con, ALL_T2DM)) == 305


@pytest.mark.parametrize(
    ("preset_id", "text"), [("type-2-text", "type 2 diabetes"), ("diabet-text", "diabet")]
)
def test_text_presets_use_the_codes_the_text_search_finds(
    con: duckdb.DuckDBPyConnection, preset_id: str, text: str
) -> None:
    rows = con.execute(
        "SELECT DISTINCT CODE FROM conditions WHERE DESCRIPTION ILIKE ?", [f"%{text}%"]
    ).fetchall()

    assert set(PRESETS[preset_id].judgments.condition_codes()) == {row[0] for row in rows}


def test_code_groups_list_every_diabetes_code_in_the_data(con: duckdb.DuckDBPyConnection) -> None:
    listed = {code: text for group in CODE_GROUPS.values() for code, text in group.items()}
    in_data = dict(
        con.execute(
            "SELECT DISTINCT CODE, DESCRIPTION FROM conditions WHERE DESCRIPTION ILIKE '%diabet%'"
        ).fetchall()
    )

    assert listed == in_data


def test_lowering_the_threshold_never_removes_patients(con: duckdb.DuckDBPyConnection) -> None:
    counts = [
        build_cohort(con, Judgments(evidence="labs", hba1c_threshold=t)).count
        for t in (8.0, 7.0, 6.5, 6.0, 5.7)
    ]

    assert counts == sorted(counts)
    assert counts[0] < counts[-1]


def test_threshold_is_inclusive(con: duckdb.DuckDBPyConnection) -> None:
    value = con.execute(
        "SELECT min(TRY_CAST(VALUE AS DOUBLE)) FROM observations "
        "WHERE CODE = '4548-4' AND TRY_CAST(VALUE AS DOUBLE) >= 6.5"
    ).fetchone()[0]

    cohort = build_cohort(con, Judgments(evidence="labs", hba1c_threshold=value))

    values = [
        float(e.value) for rows in cohort.evidence_by_patient.values() for e in rows if e.value
    ]
    assert min(values) == value


@needs_full_csvs
@pytest.mark.parametrize("preset_id", list(PRESETS))
def test_evidence_rows_exist_in_the_source_csv(
    con: duckdb.DuckDBPyConnection, preset_id: str
) -> None:
    cohort = build_cohort(con, PRESETS[preset_id].judgments)
    lines: dict[str, dict[int, dict[str, str]]] = {}
    for table in ("conditions", "observations"):
        with (DEFAULT_CSV_DIR / f"{table}.csv").open(newline="") as f:
            lines[table] = dict(enumerate(csv.DictReader(f), start=2))

    for patient_id, evidence in cohort.evidence_by_patient.items():
        assert evidence
        for item in evidence:
            source = lines[item.table][item.row]
            assert source["PATIENT"] == patient_id
            assert source["CODE"] == item.code
            assert source["DESCRIPTION"] == item.description


def test_lab_evidence_shows_only_qualifying_results(con: duckdb.DuckDBPyConnection) -> None:
    judgments = PRESETS["hba1c"].judgments
    cohort = build_cohort(con, judgments)

    for evidence in cohort.evidence_by_patient.values():
        for item in evidence:
            assert item.table == "observations"
            assert item.units == "%"
            assert float(item.value) >= judgments.hba1c_threshold


def test_union_evidence_comes_from_both_tables(con: duckdb.DuckDBPyConnection) -> None:
    judgments = PRESETS["text-or-hba1c"].judgments
    overlap = sorted(preset_patients(con, "type-2-text") & preset_patients(con, "hba1c"))

    evidence = patient_evidence(con, judgments, overlap[0])

    assert {item.table for item in evidence} == {"conditions", "observations"}


def test_patient_evidence_matches_the_cohort(con: duckdb.DuckDBPyConnection) -> None:
    judgments = PRESETS["text-or-hba1c"].judgments
    cohort = build_cohort(con, judgments)
    patient_id = sorted(cohort.evidence_by_patient)[0]

    assert patient_evidence(con, judgments, patient_id) == cohort.evidence_by_patient[patient_id]


def test_patient_outside_the_cohort_has_no_evidence(con: duckdb.DuckDBPyConnection) -> None:
    outside = sorted(preset_patients(con, "diabet-text") - preset_patients(con, "exact-code"))[0]

    assert patient_evidence(con, PRESETS["exact-code"].judgments, outside) == []


@pytest.mark.parametrize(
    "judgments",
    [
        pytest.param({"evidence": "codes"}, id="codes-without-code-group"),
        pytest.param({"evidence": "labs"}, id="labs-without-threshold"),
        pytest.param({"evidence": "both", "hba1c_threshold": 6.5}, id="both-without-code-group"),
        pytest.param({"evidence": "both", "include_diagnosis": True}, id="both-without-threshold"),
        pytest.param(
            {"evidence": "codes", "include_diagnosis": True, "hba1c_threshold": 6.5},
            id="codes-with-threshold",
        ),
        pytest.param(
            {"evidence": "labs", "include_diagnosis": True, "hba1c_threshold": 6.5},
            id="labs-with-code-group",
        ),
        pytest.param({"evidence": "labs", "hba1c_threshold": 0}, id="threshold-too-low"),
        pytest.param({"evidence": "labs", "hba1c_threshold": 21}, id="threshold-too-high"),
        pytest.param({"evidence": "meds"}, id="unknown-evidence"),
        pytest.param(
            {"evidence": "codes", "include_diagnosis": True, "active_only": True},
            id="unknown-judgment",
        ),
    ],
)
def test_invalid_judgments_are_rejected(judgments: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Judgments.model_validate(judgments)
