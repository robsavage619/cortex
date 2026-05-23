from __future__ import annotations

import duckdb

SCHEMA_VERSION = 2

DDL_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version   INTEGER   NOT NULL,
        applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS theses (
        id               VARCHAR   PRIMARY KEY,
        tickers          VARCHAR[] NOT NULL,
        author           VARCHAR   NOT NULL,
        opened           DATE      NOT NULL,
        conviction       INTEGER   NOT NULL,
        claim            VARCHAR   NOT NULL,
        falsifier        VARCHAR   NOT NULL,
        reasoning        VARCHAR,
        evidence         VARCHAR[],
        review_date      DATE      NOT NULL,
        status           VARCHAR   NOT NULL DEFAULT 'open',
        entry_price      DOUBLE,
        entry_date       DATE,
        base_rate        VARCHAR,
        pre_mortem       VARCHAR,
        change_my_mind   VARCHAR,
        sizing_rationale VARCHAR,
        why_now          VARCHAR,
        activate_at      TIMESTAMP,
        created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reviews (
        thesis_id        VARCHAR   NOT NULL,
        reviewed_on      DATE      NOT NULL,
        outcome          VARCHAR   NOT NULL,
        decision_quality VARCHAR,
        note             VARCHAR,
        PRIMARY KEY (thesis_id, reviewed_on)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dissents (
        id          VARCHAR   PRIMARY KEY,
        thesis_id   VARCHAR   NOT NULL,
        author      VARCHAR   NOT NULL,
        stance      VARCHAR   NOT NULL,
        conviction  INTEGER,
        note        VARCHAR,
        created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS research_chunks (
        id         VARCHAR   PRIMARY KEY,
        note_path  VARCHAR   NOT NULL,
        wikilink   VARCHAR   NOT NULL,
        tier       INTEGER,
        text       VARCHAR   NOT NULL,
        embedding  FLOAT[384],
        indexed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
)

# Idempotent column additions so pre-v2 databases upgrade in place.
MIGRATION_STATEMENTS = (
    "ALTER TABLE theses ADD COLUMN IF NOT EXISTS base_rate VARCHAR",
    "ALTER TABLE theses ADD COLUMN IF NOT EXISTS pre_mortem VARCHAR",
    "ALTER TABLE theses ADD COLUMN IF NOT EXISTS change_my_mind VARCHAR",
    "ALTER TABLE theses ADD COLUMN IF NOT EXISTS sizing_rationale VARCHAR",
    "ALTER TABLE theses ADD COLUMN IF NOT EXISTS why_now VARCHAR",
    "ALTER TABLE theses ADD COLUMN IF NOT EXISTS activate_at TIMESTAMP",
    "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS decision_quality VARCHAR",
)


def apply_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all tables, run migrations, and record the schema version."""
    for ddl in DDL_STATEMENTS:
        conn.execute(ddl)
    for ddl in MIGRATION_STATEMENTS:
        conn.execute(ddl)

    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = row[0] if row and row[0] is not None else 0
    if current < SCHEMA_VERSION:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", [SCHEMA_VERSION]
        )


def _load_vss(conn: duckdb.DuckDBPyConnection) -> None:
    """Install and load the VSS extension, then create the HNSW index."""
    try:
        conn.execute("INSTALL vss")
        conn.execute("LOAD vss")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS research_chunks_embedding_idx
            ON research_chunks USING HNSW (embedding)
            WITH (metric = 'cosine')
            """
        )
    except duckdb.Error:
        pass
