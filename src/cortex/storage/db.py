from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from cortex.config import DEFAULT_DUCKDB_PATH

_OPEN_ATTEMPTS = 6
_OPEN_BACKOFF = 0.15  # seconds, multiplied by attempt number


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

    A background sync briefly holds a read-write connection while it stores
    results; an in-flight read-only request can collide with that window
    ("different configuration than existing connections"). We retry the open
    a few times with backoff so that transient clash self-heals instead of
    surfacing as a 500.
    """
    target = path or DEFAULT_DUCKDB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    conn: duckdb.DuckDBPyConnection | None = None
    last_err: duckdb.Error | None = None
    for attempt in range(1, _OPEN_ATTEMPTS + 1):
        try:
            conn = duckdb.connect(str(target), read_only=read_only)
            break
        except duckdb.Error as exc:
            last_err = exc
            if attempt < _OPEN_ATTEMPTS:
                time.sleep(_OPEN_BACKOFF * attempt)
    if conn is None:
        raise last_err if last_err else RuntimeError("DuckDB connect failed")

    try:
        yield conn
    finally:
        conn.close()
