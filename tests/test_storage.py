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
        "id", "tickers", "author", "opened", "conviction", "claim",
        "falsifier", "review_date", "status", "created_at",
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
