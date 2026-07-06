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
