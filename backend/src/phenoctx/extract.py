"""Build the committed extract: only the rows the app reads, from the full CSVs.

Run with `make extract`. It keeps a fresh clone runnable, since the full CSVs are too large to
commit. The agents never use it, see `phenoctx.agents.open_read_only`.
"""

from pathlib import Path

import duckdb

from phenoctx.cohort import CODE_GROUPS, HBA1C_LOINC
from phenoctx.db import DEFAULT_CSV_DIR, EXTRACT_DIR, connect


def build_extract(con: duckdb.DuckDBPyConnection, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    codes = sorted(code for group in CODE_GROUPS.values() for code in group)
    code_list = ", ".join(f"'{code}'" for code in codes)
    queries = {
        "patients": "SELECT Id, source_line FROM patients",
        "conditions": (
            "SELECT START, STOP, PATIENT, CODE, DESCRIPTION, source_line "
            f"FROM conditions WHERE CODE IN ({code_list})"
        ),
        "observations": (
            "SELECT DATE, PATIENT, CODE, DESCRIPTION, VALUE, UNITS, source_line "
            f"FROM observations WHERE CODE = '{HBA1C_LOINC}'"
        ),
    }
    for table, query in queries.items():
        path = out_dir / f"{table}.csv"
        con.execute(f"COPY ({query} ORDER BY source_line) TO '{path}' (HEADER)")


def main() -> None:
    build_extract(connect(DEFAULT_CSV_DIR), EXTRACT_DIR)
    for path in sorted(EXTRACT_DIR.glob("*.csv")):
        print(f"{path.name}: {path.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
