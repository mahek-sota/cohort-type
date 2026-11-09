from collections.abc import Iterator

import duckdb
import pytest

from phenoctx.db import DEFAULT_CSV_DIR, connect

needs_full_csvs = pytest.mark.skipif(
    not (DEFAULT_CSV_DIR / "patients.csv").is_file(),
    reason="Full Synthea CSVs not present; see data/README.md",
)


@pytest.fixture(scope="session")
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = connect()
    yield connection
    connection.close()
