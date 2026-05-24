from __future__ import annotations

import duckdb

SCHEMA_VERSION = 11

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
    """
    CREATE TABLE IF NOT EXISTS congress_trades (
        id                VARCHAR   PRIMARY KEY,
        senator           VARCHAR   NOT NULL,
        ticker            VARCHAR   NOT NULL,
        transaction_type  VARCHAR,
        amount            VARCHAR,
        transaction_date  DATE,
        disclosure_date   DATE,
        asset_description  VARCHAR,
        report_url        VARCHAR,
        chamber           VARCHAR   NOT NULL DEFAULT 'senate',
        synced_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundamentals (
        ticker       VARCHAR NOT NULL,
        period_end   DATE    NOT NULL,
        filing_date  DATE    NOT NULL,
        eps_diluted  DOUBLE,
        net_income   DOUBLE,
        equity       DOUBLE,
        PRIMARY KEY (ticker, period_end)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fund_holdings (
        id            VARCHAR   PRIMARY KEY,
        manager       VARCHAR   NOT NULL,
        manager_cik   VARCHAR   NOT NULL,
        ticker        VARCHAR   NOT NULL,
        issuer        VARCHAR,
        action        VARCHAR   NOT NULL,
        shares        BIGINT,
        prev_shares   BIGINT,
        value         BIGINT,
        pct_change    DOUBLE,
        period        DATE,
        synced_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activist_stakes (
        id            VARCHAR   PRIMARY KEY,
        ticker        VARCHAR   NOT NULL,
        subject_cik   VARCHAR   NOT NULL,
        filer         VARCHAR,
        filing_date   DATE      NOT NULL,
        synced_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS insider_buys (
        id               VARCHAR   PRIMARY KEY,
        ticker           VARCHAR   NOT NULL,
        issuer_cik       VARCHAR   NOT NULL,
        filer_cik        VARCHAR   NOT NULL DEFAULT '',
        filer_name       VARCHAR,
        filer_role       VARCHAR   NOT NULL DEFAULT 'other',
        transaction_date DATE      NOT NULL,
        filing_date      DATE      NOT NULL,
        shares           DOUBLE,
        value_usd        DOUBLE,
        synced_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS candidates (
        ticker              VARCHAR   PRIMARY KEY,
        as_of_date          DATE      NOT NULL,
        discovered_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        momentum_12_1       DOUBLE,
        vol_252d            DOUBLE,
        sharpe_12m          DOUBLE,
        above_200d_sma      BOOLEAN,
        earnings_yield      DOUBLE,
        roe                 DOUBLE,
        z_momentum          DOUBLE,
        z_low_vol           DOUBLE,
        z_sharpe            DOUBLE,
        z_value             DOUBLE,
        z_quality           DOUBLE,
        composite_score     DOUBLE    NOT NULL,
        composite_rank      INTEGER   NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS volatility_screen (
        ticker             VARCHAR   PRIMARY KEY,
        as_of_date         DATE      NOT NULL,
        computed_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        lookback_days      INTEGER   NOT NULL,
        avg_dollar_range   DOUBLE,
        range_consistency  DOUBLE,
        avg_range_pct      DOUBLE,
        avg_close          DOUBLE,
        oscillation_score  DOUBLE,
        net_drift_pct      DOUBLE,
        range_position     DOUBLE,
        direction_changes  INTEGER,
        avg_volume         DOUBLE,
        ari_special_score  DOUBLE    NOT NULL,
        rank               INTEGER   NOT NULL,
        company_name       VARCHAR,
        max_range_pct      DOUBLE,
        max_dollar_range   DOUBLE
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
    "ALTER TABLE volatility_screen ADD COLUMN IF NOT EXISTS oscillation_score DOUBLE",
    "ALTER TABLE volatility_screen ADD COLUMN IF NOT EXISTS net_drift_pct DOUBLE",
    "ALTER TABLE volatility_screen ADD COLUMN IF NOT EXISTS range_position DOUBLE",
    "ALTER TABLE volatility_screen ADD COLUMN IF NOT EXISTS direction_changes INTEGER",
    "ALTER TABLE volatility_screen ADD COLUMN IF NOT EXISTS avg_volume DOUBLE",
    "ALTER TABLE volatility_screen ADD COLUMN IF NOT EXISTS company_name VARCHAR",
    "ALTER TABLE volatility_screen ADD COLUMN IF NOT EXISTS max_range_pct DOUBLE",
    "ALTER TABLE volatility_screen ADD COLUMN IF NOT EXISTS max_dollar_range DOUBLE",
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
