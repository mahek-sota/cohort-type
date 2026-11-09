"""Build a diabetes cohort from explicit judgments, keeping the rows behind every patient."""

from typing import Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field, model_validator

HBA1C_LOINC = "4548-4"

# Every condition code in the data whose description mentions "diabet", grouped by the judgment
# that controls it. Descriptions are copied from conditions.csv.
CODE_GROUPS: dict[str, dict[str, str]] = {
    "diagnosis": {
        "44054006": "Diabetes mellitus type 2 (disorder)",
    },
    "complications": {
        "90781000119102": "Microalbuminuria due to type 2 diabetes mellitus (disorder)",
        "157141000119108": "Proteinuria due to type 2 diabetes mellitus (disorder)",
        "368581000119106": "Neuropathy due to type 2 diabetes mellitus (disorder)",
        "97331000119101": (
            "Macular edema and retinopathy due to type 2 diabetes mellitus (disorder)"
        ),
    },
    # Diabetic complications that a search for the phrase "type 2 diabetes" does not find.
    "other_complications": {
        "127013003": "Disorder of kidney due to diabetes mellitus (disorder)",
        "1551000119108": "Nonproliferative diabetic retinopathy due to type II diabetes mellitus",
    },
    "prediabetes": {
        "714628002": "Prediabetes (finding)",
    },
}


class Judgments(BaseModel):
    """The choices that decide who counts. Each include flag switches on one code group.

    `both` means either source qualifies a patient. A judgment that does not apply must be left
    unset, so a definition never appears to rely on evidence it ignores.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence: Literal["codes", "labs", "both"]
    include_diagnosis: bool = False
    include_complications: bool = False
    include_other_complications: bool = False
    include_prediabetes: bool = False
    hba1c_threshold: float | None = Field(default=None, gt=0, le=20)

    @model_validator(mode="after")
    def only_applicable_judgments(self) -> "Judgments":
        has_codes = bool(self.condition_codes())
        if self.evidence == "labs" and has_codes:
            raise ValueError("labs evidence cannot include code groups")
        if self.evidence != "labs" and not has_codes:
            raise ValueError(f"{self.evidence} evidence needs at least one code group")
        if self.evidence == "codes" and self.hba1c_threshold is not None:
            raise ValueError("codes evidence cannot set hba1c_threshold")
        if self.evidence != "codes" and self.hba1c_threshold is None:
            raise ValueError(f"{self.evidence} evidence needs hba1c_threshold")
        return self

    def condition_codes(self) -> list[str]:
        """Return the condition codes this definition counts."""
        included = {
            "diagnosis": self.include_diagnosis,
            "complications": self.include_complications,
            "other_complications": self.include_other_complications,
            "prediabetes": self.include_prediabetes,
        }
        return [code for group, on in included.items() if on for code in CODE_GROUPS[group]]


class Preset(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    judgments: Judgments
    rationale: str


PRESETS: dict[str, Preset] = {
    "exact-code": Preset(
        name="Exact SNOMED code",
        judgments=Judgments(evidence="codes", include_diagnosis=True),
        rationale=(
            "Counts only SNOMED 44054006, the diagnosis code itself. Precise and easy to explain, "
            "but it misses patients with a type 2 complication and no plain diagnosis code."
        ),
    ),
    "type-2-text": Preset(
        name='Mentions "type 2 diabetes"',
        judgments=Judgments(evidence="codes", include_complications=True),
        rationale=(
            'The first article\'s text search for "type 2 diabetes", restated as the codes it '
            "actually matches. It finds four complication codes but not the diagnosis, whose "
            'description reads "Diabetes mellitus type 2", so 37 of the 74 patients with SNOMED '
            "44054006 are left out. It also misses complications worded differently."
        ),
    ),
    "diabet-text": Preset(
        name='Mentions "diabet"',
        judgments=Judgments(
            evidence="codes",
            include_diagnosis=True,
            include_complications=True,
            include_other_complications=True,
            include_prediabetes=True,
        ),
        rationale=(
            'The first article\'s text search for "diabet", which matches all eight related '
            "codes. Nothing diabetic is missed, but prediabetes counts as diabetes, and 305 of "
            "the 474 patients have only that code."
        ),
    ),
    "hba1c": Preset(
        name="Any HbA1c at or above 6.5",
        judgments=Judgments(evidence="labs", hba1c_threshold=6.5),
        rationale=(
            "Counts any patient with at least one HbA1c at or above 6.5%, the usual diagnostic "
            "threshold. It ignores diagnosis codes, and one result is enough, although clinical "
            "diagnosis usually requires confirmation."
        ),
    ),
    "text-or-hba1c": Preset(
        name='Mentions "type 2 diabetes" or high HbA1c',
        judgments=Judgments(evidence="both", include_complications=True, hba1c_threshold=6.5),
        rationale=(
            "Combines the text search and the HbA1c rule, so either source qualifies a patient. "
            "It keeps the text search's gaps: 10 patients with SNOMED 44054006 are still left out."
        ),
    ),
}


class Evidence(BaseModel):
    """One source row that qualified a patient. `row` is the line number in `table`'s CSV."""

    table: Literal["conditions", "observations"]
    row: int
    code: str
    description: str
    value: str | None
    units: str | None
    date: str


class Cohort(BaseModel):
    count: int
    population: int
    percent: float
    evidence_by_patient: dict[str, list[Evidence]]


_CONDITION_ROWS = """
    SELECT PATIENT, 'conditions' AS source, source_line, CODE, DESCRIPTION,
           NULL AS value, NULL AS units, CAST(START AS VARCHAR) AS event_date
    FROM conditions
    WHERE list_contains(?, CODE)
"""
_LAB_ROWS = """
    SELECT PATIENT, 'observations' AS source, source_line, CODE, DESCRIPTION,
           VALUE AS value, UNITS AS units, strftime(DATE, '%Y-%m-%d') AS event_date
    FROM observations
    WHERE CODE = ? AND TRY_CAST(VALUE AS DOUBLE) >= ?
"""


def _evidence_query(judgments: Judgments) -> tuple[str, list[object]]:
    parts: list[str] = []
    params: list[object] = []
    if judgments.evidence != "labs":
        parts.append(_CONDITION_ROWS)
        params.append(judgments.condition_codes())
    if judgments.evidence != "codes":
        parts.append(_LAB_ROWS)
        params.extend([HBA1C_LOINC, judgments.hba1c_threshold])
    return " UNION ALL ".join(parts), params


def _evidence_rows(
    con: duckdb.DuckDBPyConnection, judgments: Judgments, patient_id: str | None = None
) -> list[tuple]:
    query, params = _evidence_query(judgments)
    query = f"SELECT * FROM ({query})"
    if patient_id is not None:
        query += " WHERE PATIENT = ?"
        params = [*params, patient_id]
    return con.execute(
        f"{query} ORDER BY PATIENT, event_date, source, source_line", params
    ).fetchall()


def _to_evidence(row: tuple) -> Evidence:
    _, table, line, code, description, value, units, date = row
    return Evidence(
        table=table,
        row=line,
        code=code,
        description=description,
        value=value,
        units=units,
        date=date,
    )


def build_cohort(con: duckdb.DuckDBPyConnection, judgments: Judgments) -> Cohort:
    """Return every qualifying patient with the rows that qualified them."""
    by_patient: dict[str, list[Evidence]] = {}
    for row in _evidence_rows(con, judgments):
        by_patient.setdefault(row[0], []).append(_to_evidence(row))
    population = con.execute("SELECT count(*) FROM patients").fetchone()[0]
    return Cohort(
        count=len(by_patient),
        population=population,
        percent=round(100 * len(by_patient) / population, 1),
        evidence_by_patient=by_patient,
    )


def patient_evidence(
    con: duckdb.DuckDBPyConnection, judgments: Judgments, patient_id: str
) -> list[Evidence]:
    """Return the rows that qualify one patient. Empty means the patient is not in the cohort."""
    return [_to_evidence(row) for row in _evidence_rows(con, judgments, patient_id)]
