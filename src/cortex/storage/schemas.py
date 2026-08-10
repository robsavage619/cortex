from __future__ import annotations

import duckdb

SCHEMA_VERSION = 20

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
        swing_score        DOUBLE    NOT NULL,
        rank               INTEGER   NOT NULL,
        company_name       VARCHAR,
        max_range_pct      DOUBLE,
        max_dollar_range   DOUBLE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_runs (
        source       VARCHAR   NOT NULL,
        ran_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ok           BOOLEAN   NOT NULL,
        rows_new     INTEGER,
        detail       VARCHAR,
        PRIMARY KEY (source, ran_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS executive_mentions (
        id           VARCHAR   PRIMARY KEY,
        ticker       VARCHAR   NOT NULL,
        speaker      VARCHAR   NOT NULL DEFAULT 'President',
        mention_date DATE      NOT NULL,
        source_type  VARCHAR   NOT NULL DEFAULT 'press_conference',
        source_url   VARCHAR,
        quote        VARCHAR,
        stance       VARCHAR   NOT NULL DEFAULT 'positive',
        meaningful   BOOLEAN,
        significance VARCHAR,
        analysis     VARCHAR,
        abn_1d       DOUBLE,
        abn_5d       DOUBLE,
        abn_20d      DOUBLE,
        synced_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prices (
        ticker     VARCHAR   NOT NULL,
        date       DATE      NOT NULL,
        close      DOUBLE,
        high       DOUBLE,
        low        DOUBLE,
        volume     DOUBLE,
        source     VARCHAR   NOT NULL DEFAULT 'yfinance',
        fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ticker, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS price_coverage (
        ticker      VARCHAR   PRIMARY KEY,
        cover_start DATE      NOT NULL,
        cover_end   DATE      NOT NULL,
        fetched_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS splits (
        ticker     VARCHAR   NOT NULL,
        date       DATE      NOT NULL,
        ratio      DOUBLE    NOT NULL,
        fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ticker, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS split_coverage (
        ticker     VARCHAR   PRIMARY KEY,
        fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS short_volume (
        ticker        VARCHAR   NOT NULL,
        date          DATE      NOT NULL,
        short_volume  BIGINT    NOT NULL,
        total_volume  BIGINT    NOT NULL,
        fetched_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ticker, date)
    )
    """,
    """
    -- Coverage is per SESSION DATE, not per ticker: a day FINRA never
    -- published and a day we never fetched are otherwise indistinguishable,
    -- and the difference decides whether a gap in the series is real.
    CREATE TABLE IF NOT EXISTS short_volume_coverage (
        date       DATE      PRIMARY KEY,
        rows       INTEGER   NOT NULL,
        fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS factor_history (
        snapshot_date DATE     NOT NULL,
        factor        VARCHAR  NOT NULL,
        ic_mean       DOUBLE,
        ic_tstat      DOUBLE,
        ic_tstat_nw   DOUBLE,
        coverage      DOUBLE,
        n_months      INTEGER,
        recorded_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (snapshot_date, factor)
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
    "ALTER TABLE executive_mentions ADD COLUMN IF NOT EXISTS meaningful BOOLEAN",
    "ALTER TABLE executive_mentions ADD COLUMN IF NOT EXISTS significance VARCHAR",
    "ALTER TABLE executive_mentions ADD COLUMN IF NOT EXISTS analysis VARCHAR",
    "ALTER TABLE executive_mentions ADD COLUMN IF NOT EXISTS abn_1d DOUBLE",
    "ALTER TABLE executive_mentions ADD COLUMN IF NOT EXISTS abn_5d DOUBLE",
    "ALTER TABLE executive_mentions ADD COLUMN IF NOT EXISTS abn_20d DOUBLE",
    # v16 — congress integrity: amendment marking + ticker quarantine;
    # executive tri-state (NULL meaningful + NULL analyzed_at = never analyzed).
    # NEVER put a DEFAULT on these ADD COLUMNs: in DuckDB (≤ v1.5.3),
    # re-running ADD COLUMN IF NOT EXISTS with a DEFAULT re-applies the
    # default to EVERY row even when the column already exists — it wiped
    # 1,978 amendment marks before this was caught. NULL means false here.
    "ALTER TABLE congress_trades ADD COLUMN IF NOT EXISTS amended BOOLEAN",
    "ALTER TABLE congress_trades ADD COLUMN IF NOT EXISTS ticker_ok BOOLEAN",
    "ALTER TABLE executive_mentions ADD COLUMN IF NOT EXISTS analyzed_at TIMESTAMP",
    # v17 — brain alignment: discovery computes the backtested composite;
    # candidates carry the canonical factor z-scores + honest forced flag.
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS forced BOOLEAN",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS z_trend DOUBLE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS z_congress DOUBLE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS z_fund_flow DOUBLE",
    # v18 — survivorship correction: mean fraction of true point-in-time S&P
    # members priced per month (NULL for pre-v18 snapshots).
    "ALTER TABLE factor_history ADD COLUMN IF NOT EXISTS universe_coverage DOUBLE",
)


def apply_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all tables, run migrations, and record the schema version."""
    for ddl in DDL_STATEMENTS:
        conn.execute(ddl)
    for ddl in MIGRATION_STATEMENTS:
        conn.execute(ddl)

    # Rename the swing-screen score column for databases created before v12.
    vol_cols = {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'volatility_screen'"
        ).fetchall()
    }
    if "ari_special_score" in vol_cols and "swing_score" not in vol_cols:
        conn.execute(
            "ALTER TABLE volatility_screen "
            "RENAME COLUMN ari_special_score TO swing_score"
        )

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
