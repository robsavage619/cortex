from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from wst.config import DEFAULT_DUCKDB_PATH


@contextmanager
def connect(
    path: Path | None = None,
    *,
    read_only: bool = False,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open a DuckDB connection, yielding it and closing on exit.

    Args:
        path: DB file path; defaults to DEFAULT_DUCKDB_PATH.
        read_only: Open in read-only mode (safe for concurrent API reads).
    """
    target = path or DEFAULT_DUCKDB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(target), read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()
