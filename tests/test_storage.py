from __future__ import annotations

import duckdb
import pytest

from cortex.storage.db import connect
from cortex.storage.schemas import SCHEMA_VERSION, apply_schema


def test_connect_creates_db(tmp_path):
    db = tmp_path / "test.db"
    with connect(db) as conn:
        result = conn.execute("SELECT 1").fetchone()
    assert result == (1,)


def test_apply_schema_creates_tables(tmp_path):
    db = tmp_path / "test.db"
    with connect(db) as conn:
        apply_schema(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = 'main'"
            ).fetchall()
        }
    assert {"schema_version", "theses", "reviews", "research_chunks"} <= tables


def test_apply_schema_records_version(tmp_path):
    db = tmp_path / "test.db"
    with connect(db) as conn:
        apply_schema(conn)
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    assert row is not None and row[0] == SCHEMA_VERSION


def test_apply_schema_idempotent(tmp_path):
    db = tmp_path / "test.db"
    with connect(db) as conn:
        apply_schema(conn)
        apply_schema(conn)
        count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert count == 1


def test_theses_table_columns(tmp_path):
    db = tmp_path / "test.db"
    with connect(db) as conn:
        apply_schema(conn)
        cols = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'theses'"
            ).fetchall()
        }
    required = {
        "id",
        "tickers",
        "author",
        "opened",
        "conviction",
        "claim",
        "falsifier",
        "review_date",
        "status",
        "created_at",
    }
    assert required <= cols


def test_research_chunks_embedding_column(tmp_path):
    db = tmp_path / "test.db"
    with connect(db) as conn:
        apply_schema(conn)
        cols = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'research_chunks'"
            ).fetchall()
        }
    assert "embedding" in cols


def test_connect_read_only_raises_on_write(tmp_path):
    db = tmp_path / "test.db"
    with connect(db) as conn:
        apply_schema(conn)
    with (
        connect(db, read_only=True) as ro,
        pytest.raises(duckdb.Error),
    ):
        ro.execute("INSERT INTO theses VALUES (NULL)")


def test_reapplying_schema_preserves_migrated_column_values(tmp_path):
    """DuckDB ≤1.5.3: ADD COLUMN IF NOT EXISTS with a DEFAULT re-applies the
    default to every row on re-run. Migrations must never carry DEFAULTs —
    this guards against the regression that wiped 1,978 amendment marks."""
    db = tmp_path / "test.db"
    with connect(db) as conn:
        apply_schema(conn)
        conn.execute(
            "INSERT INTO congress_trades (id, senator, ticker, amended, ticker_ok)"
            " VALUES ('x1', 'Doe', 'AAPL', TRUE, FALSE)"
        )
        conn.execute(
            "INSERT INTO candidates (ticker, as_of_date, composite_score,"
            " composite_rank, forced) VALUES ('AAPL', DATE '2026-01-01', 1.0,"
            " 45, TRUE)"
        )
        apply_schema(conn)  # must be a true no-op on existing columns
        amended, ticker_ok = conn.execute(
            "SELECT amended, ticker_ok FROM congress_trades"
        ).fetchone()
        forced = conn.execute("SELECT forced FROM candidates").fetchone()[0]
    assert amended is True
    assert ticker_ok is False
    assert forced is True
