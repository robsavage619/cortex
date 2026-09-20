# Data model

Last verified 2026-09-19 against `src/cortex/storage/schemas.py` (schema v22).

One DuckDB file, 188 MB, 23 tables. No second store, no cache layer, no ORM.

## Migrations are idempotent DDL, not numbered files

`apply_schema()` runs every `CREATE TABLE IF NOT EXISTS` in `DDL_STATEMENTS`, then
every `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in `MIGRATION_STATEMENTS` (30 of
them), then records `SCHEMA_VERSION` in the `schema_version` table. Running it
against an up-to-date database is a no-op. There are no down migrations.

**A migration must never carry a `DEFAULT` on `ADD COLUMN`.** DuckDB (through
1.5.3) re-applies the default to every row on re-run, which silently overwrites
backfilled values. This is written as a comment in the migration list and it is
the single most dangerous footgun in the schema.

One rename is handled imperatively rather than by DDL, guarded on an
`information_schema` check, because DuckDB has no `RENAME COLUMN IF EXISTS`.

## Tables

### Market and reference

| Table | Rows | Notes |
|---|---:|---|
| `prices` | 1,555,751 | OHLCV cache, yfinance `auto_adjust=True`, back-adjusted to today |
| `price_coverage` | 744 | Per-ticker `cover_start` / `cover_end` / `fetched_at`. Distinguishes "never fetched" from "nothing there" |
| `splits` | | Split factors, used to restate as-reported EPS onto the adjusted price basis |
| `split_coverage` | | Per-ticker, because "no splits ever" and "never fetched" are otherwise the same empty result |

### Alt-data

| Table | Rows | Notes |
|---|---:|---|
| `congress_trades` | 26,227 | House 14,551, Senate 11,676. Carries `amended` and `ticker_ok` flags rather than deleting rows |
| `fund_holdings` | 432,922 | Quarter-over-quarter 13F diffs for 14 curated managers |
| `insider_buys` | 13,008 | Form 4 P-coded non-derivative |
| `activist_stakes` | 1,546 | SC 13D initial stakes |
| `short_volume` | 1,136,046 | FINRA Reg SHO daily, 2018-08-01 to present |
| `short_volume_coverage` | | Per-date coverage tracking |
| `fundamentals` | 21,538 | EDGAR XBRL, point-in-time by filing date |
| `executive_mentions` | 30 | White House transcript mentions, with abnormal-return columns |

### Research and decisions

| Table | Rows | Notes |
|---|---:|---|
| `theses` | 9 | Hand-authored positions with a required falsifier and review date |
| `reviews` | | Outcome plus a separate `decision_quality` field |
| `dissents` | | Recorded counter-arguments against a thesis |
| `candidates` | | Current discovery output, with per-factor z-scores and the composite rank |
| `volatility_screen` | | Dollar-swing screen output |
| `factor_history` | 18 | Nightly snapshot of every factor's t-statistic |
| `research_trials` | 7 | Cumulative trial count for the multiple-testing haircut |
| `research_chunks` | 239 | Embedded vault notes, HNSW index via the DuckDB VSS extension |
| `factor_evidence` | 38 | Vault note to factor links, synced by `cortex rag-index` |
| `sync_runs` | | Per-step sync outcome, recorded whether or not the webhook fires |
| `schema_version` | | Append-only version log |

## Three keys that were wrong, and what they cost

### `insider_buys.id`

A 16-character SHA256 over `(issuer_cik, filer_cik, tx_date, shares, accession)`.
The original key used the first three fields only. Same-filer same-day lots share
all three, so 34% of Form 4 purchase rows were collapsed at ingest. Rebuilding on
the 5-field key recovered 4,417 rows, a 51% increase.

### `fund_holdings.period` is misnamed

It holds the 13F **filing date**, not the quarter end. Only 10 of 432,922 rows
fall on a quarter end; the modes are the mid-February, May, August and November
statutory deadlines. There is no 45-day lookahead hiding in the column, but the
name says otherwise and it should be renamed `filing_date`.

An EXIT row has `value = 0` and `shares = 0` by construction; its magnitude lives
in `prev_shares`. Sizing a fund event off `value` alone drops every exit. It did,
for 71,958 rows. See [factor-journal.md](factor-journal.md).

### `fundamentals` needs a two-column as-of order

A 10-K carries comparative prior periods that all share one `filing_date`. Any
as-of query must order by `(filing_date, period_end)` or the tie-break is
arbitrary storage order. Ordering by `filing_date` alone priced WDC off a 2023
quarter and left SNDK with a NULL EPS.

## Vector search

`research_chunks` holds fastembed embeddings with an HNSW index created through
the DuckDB VSS extension, cosine metric. Index creation is wrapped in a
`try/except duckdb.Error` and passes on failure, because the extension is
optional and its absence should degrade retrieval rather than break startup.

Re-indexing deletes every chunk under the indexed tree rather than only the notes
it kept, so renamed, deleted and newly-excluded notes cannot survive as orphans
that retrieval can still return.

## Backups

`cortex backup --keep N` exports every table to Parquet under
`<volume>/duckdb/backups/<timestamp>/` with a generated `load.sql`, prunes to the
last N, and optionally pushes to S3. The whole store is small enough that this is
a complete backup rather than an incremental one.
