# Remediation Audit Baseline — 2026-07-06

Output of `uv run cortex audit-integrity` against the live DuckDB
(`data/duckdb/cortex.db`, 74 MB, schema v15) BEFORE any remediation phase
touched data. Re-run and appended after each data-touching phase.

## Baseline (pre-remediation)

```
[congress_amendment_duplicates]
  total_rows: 11738
  by_chamber:
    senate: {'dup_groups': 1636, 'excess_rows': 1978}
  dup_groups: 1636
  excess_rows: 1978

[suspicious_tickers]
  distinct_tickers: 1661
  pattern_fail_tickers: 82
  pattern_fail_rows: 180
  pattern_fail_top20: -- AM, -- DIS, -- DWDP, -- ENB, -- HR, -- IRT, -- LGI,
    -- OKE, -- PTEN, -- RTN, -- RTX, -- TAC, -- TFC, -- VIAC, -- WBD, -- WGP,
    0QZI.IL, 3V64.TI, AET CVS, AHL-C
  universe: S&P 500 ∪ 400 (903 tickers)
  outside_universe_tickers: 1005 (informational — members trade non-index names)

[collapse_baselines]
  insider_buys_rows: 8591
  activist_stakes_rows: 1626
  note: collisions were collapsed at ingest and are unrecoverable here;
    measure damage as the Phase 1 --rebuild re-sync delta

[fund_actions]
  by_action: ADD 153226 | TRIM 131136 | NEW 76602 | EXIT 71958
  exit_rows: 71958

[executive_analysis]
  total_rows: 30
  meaningful_null: 30
  analyzed: 0

[candidate_rank_fakes]
  rows_over_rank_30: 0
```

## Read

- **~17% of the senate congress table is amendment double-counts** (1,978
  excess rows / 11,738 total). Every congress factor stat computed to date
  included these duplicates. Phase 2 marks them `amended` and excludes them
  from the backtest loader.
- 180 rows carry parse-corrupted tickers (`-- AM`, `AET CVS`, `0QZI.IL`).
  Phase 2 quarantines them via `ticker_ok = FALSE`.
- Insider (8,591) and activist (1,626) row counts are the before-numbers for
  the Phase 1 dedupe-key rebuild; the re-sync delta measures ingest-time
  collapse loss.
- All 30 executive mentions have `meaningful IS NULL` — none were ever
  LLM-analyzed (local syncs run with LLM gated off). Phase 2 adds
  `analyzed_at` to disambiguate.
- No fabricated candidate ranks at this snapshot (no force-included tickers
  in the current candidates table).

## Phase 1 re-sync delta (2026-07-06)

Dedupe keys fixed (insider: + shares + accession; activist: + filer; funds:
EXIT preserved as terminal), affected tables wiped and re-ingested from SEC:

| table | before | after | delta | read |
|---|---|---|---|---|
| insider_buys | 8,591 | 13,008 | **+4,417 (+51%)** | the old key silently collapsed 34% of all Form 4 P-buys (same-filer same-day lots) |
| activist_stakes | 1,626 | 1,546 | −80 | not a clean damage measure: old rows accumulated across years of S&P-500 universe drift; the new count is one consistent fetch (2014→now, today's universe) with the finer key |

## Phase 2 backfill (2026-07-06, schema v15 → 16)

- `ticker_ok` backfill: **180 rows quarantined** (matches baseline
  pattern-fail count exactly).
- `mark_amended_duplicates` backfill: **1,978 rows marked `amended`**
  (matches baseline excess-rows count exactly).
- Post-backfill audit: `excess_rows_unmarked: 0` — every natural-key
  duplicate group now has exactly one live row (newest disclosure kept).
- Serving paths (`list_trades`, `congress_stats`, member profile) and the
  backtest congress loader now exclude amended + quarantined rows.

## Post-remediation audit + re-validation (2026-07-06, schema v17)

All phases complete. Re-run of `uv run cortex audit-integrity` on cleaned DB:

```
[congress_amendment_duplicates]
  total_rows: 11738
  rows_marked_amended: 1978
  excess_rows_unmarked: 0  ← all duplicate groups resolved

[suspicious_tickers]
  distinct_tickers: 1661
  pattern_fail_tickers: 82
  pattern_fail_rows: 180   ← quarantined (ticker_ok=FALSE), excluded from backtest + API

[collapse_baselines]
  insider_buys_rows: 13008  (was 8591 pre-Phase-1, +51%)
  activist_stakes_rows: 1546

[fund_actions]
  by_action: ADD 153226 | TRIM 131136 | NEW 76602 | EXIT 71958
  exit_rows: 71958  ← EXIT rows preserved (terminal action guard in store_fund_moves)

[executive_analysis]
  total_rows: 30
  meaningful_null: 30
  analyzed: 0  ← LLM gated off in local env; analyzed_at disambiguates NULL

[candidate_rank_fakes]
  rows_over_rank_30: 9
  tickers: GOOGL#51, AMZN#70, GOOG#86, NVDA#93, AAPL#133, JPM#137, META#142, MSFT#284, TSLA#311
  note: these 9 are force-included thesis tickers with forced=TRUE and TRUE ordinal ranks
        (Phase 3 fix); no fabricated rank positions remain
```

### Backtest re-validation — `uv run cortex backtest` on cleaned data

| factor | pre-remediation NW t | post-remediation NW t | delta | attribution |
|---|---|---|---|---|
| congress | 2.40 | 2.59 | +0.19 | amendment exclusion removed 1,978 double-counted rows |
| fund | 2.58 | 2.29 | −0.29 | EXIT preservation changed the 13F event set |
| composite | 1.89 | 2.40 | +0.51 | brain alignment: discovery now computes the same 3-block equal-weight signal as backtest |
| L/S spread | (not tracked) | 2.98 | — | first measurement |

**None clear t≥3.0 gate.** No live trading until at least one factor does.
Long-short spread at NW t=2.98 is the closest signal to the bar.
`uv run cortex snapshot-factors` persisted all 9 factor rows to `factor_history` (2026-07-06).
