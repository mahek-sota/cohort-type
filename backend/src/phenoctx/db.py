"""Load the Synthea CSVs into an in-memory DuckDB database."""

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CSV_DIR = REPO_ROOT / "data" / "synthea" / "csv"
EXTRACT_DIR = REPO_ROOT / "data" / "extract"

# Every column is read as text, then only these are typed. That keeps CODE (mixed SNOMED and LOINC
# formats) and VALUE (numbers and free text in one column) exactly as they appear in the source.
TYPED_COLUMNS = {
    "patients": {"BIRTHDATE": "DATE", "DEATHDATE": "DATE", "source_line": "BIGINT"},
    "conditions": {"START": "DATE", "STOP": "DATE", "source_line": "BIGINT"},
    "observations": {"DATE": "TIMESTAMP", "source_line": "BIGINT"},
}


def _has_all_csvs(csv_dir: Path) -> bool:
    return all((csv_dir / f"{table}.csv").is_file() for table in TYPED_COLUMNS)


def _load_table(con: duckdb.DuckDBPyConnection, table: str, csv_dir: Path) -> None:
    path = str(csv_dir / f"{table}.csv").replace("'", "''")
    source = f"read_csv('{path}', header = true, all_varchar = true)"
    columns = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]

    casts = ", ".join(
        f'CAST("{column}" AS {sql_type}) AS "{column}"'
        for column, sql_type in TYPED_COLUMNS[table].items()
        if column in columns
    )
    replace = f" REPLACE ({casts})" if casts else ""
    # The extract already has source_line, pointing at the row's line in the full CSV.
    line = "" if "source_line" in columns else ", row_number() OVER () + 1 AS source_line"
    con.execute(f"CREATE TABLE {table} AS SELECT *{replace}{line} FROM {source}")


def connect(csv_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Return a new connection with patients, conditions, and observations loaded.

    With no argument this uses the full CSVs if present, otherwise the committed extract. Passing
    `csv_dir` means exactly that folder, with no fallback, for callers that need the full data.

    Each table has `source_line`, the row's 1-based line in its full CSV (the header is line 1),
    so any row can be traced back to the file.
    """
    if csv_dir is None:
        csv_dir = DEFAULT_CSV_DIR if _has_all_csvs(DEFAULT_CSV_DIR) else EXTRACT_DIR

    missing = [t for t in TYPED_COLUMNS if not (csv_dir / f"{t}.csv").is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing {', '.join(missing)} CSV in {csv_dir}. See data/README.md for setup."
        )

    con = duckdb.connect(":memory:")
    for table in TYPED_COLUMNS:
        _load_table(con, table, csv_dir)
    return con
