# CORTEX Project Context

## What this is
CORTEX — a personal factor-model research platform.
Single user (Rob). Not a product. Optimise for research iteration speed.

## Stack
- Backend: FastAPI (`src/cortex/`), DuckDB via `cortex.storage.db.connect()`
- Frontend: React + Vite (`web/`), built to `web/dist/`, served by FastAPI on port 8000
- CLI: `uv run cortex <command>` — see `src/cortex/cli.py` for all commands
- Run server: `uv run cortex serve` (serves React SPA + API on same port 8000)

## EDGAR integration lessons (hard-won)

### Form 4 XML filenames are NOT standardised
- `form4.xml` only works for ~half of filers
- Filing agents (Edgar Online → `rdgdoc.xml`, Workiva → `wf-form4-*.xml`, etc.) use custom names
- **Canonical source**: `data.sec.gov/submissions/CIK{cik10}.json` → `filings.recent.primaryDocument`
- `primaryDocument` may be `xslF345X06/filename.xml` — that's an XSLT rendering path; strip the
  subdirectory to get the actual data file
- Paginate older filings via `filings.files[]` → fetch each page from `data.sec.gov/submissions/{name}`

### EDGAR rate limits
- Hard cap: ~10 req/s. Use `_MAX_WORKERS = 3` with `_RETRY_SLEEP = 12.0`s back-off on 429
- After multiple failed runs, the whole IP gets rate-limited. Wait until
  `curl -s -o /dev/null -w "%{http_code}" https://www.sec.gov/files/company_tickers.json` → `200`
- `User-Agent` comes from `CORTEX_SEC_USER_AGENT` (see `cortex.config.sec_user_agent`) and MUST
  be `"Name email"` format; SEC returns 403 for anything else. Never hardcode a contact.

### Bulk-index approach (use this, not per-company queries)
- `https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{N}/form.idx` — ~10 MB/quarter
- Parse right-to-left: `parts[-1]` = filename, `parts[-2]` = date, `parts[-3]` = CIK
- Pre-load primary doc map (503 CIKs × 0.15s ≈ 75s) — pays for itself vs 282K filename guesses

## Factor model decisions

### Start year: 2017 (not earlier)
- Extending to 2000 destroys fund factor signal (t: 2.58 → 0.34)
- Pre-2017 dominated by Renaissance regime; structural break ~2015-2017
- Default `from_year=2017` everywhere. Do not change without backtesting first.

### Pre-registration threshold: t ≥ 3.0 (Bonferroni-corrected)
- Congress NW t=1.72, fund t=2.62, composite t=1.83 as of last backtest (2026-08-10d, first run with real House data). Bars are DERIVED PER RUN in `significance.py`, not hardcoded: own-family BHY 3.21, zoo-draw BHY 4.21
- None clear the bar yet — no live trading until at least one factor does
- **Journal 2026-07-06 (post-remediation):** old → new: congress 2.40→2.59 (+0.19, amendment exclusion removed ~1,978 double-counted rows), fund 2.58→2.29 (-0.29, EXIT preservation changed the event set), composite 1.89→2.40 (+0.51, brain alignment fixed: discovery now computes the same 3-block equal-weight signal as the backtest). Long-short spread NW t=2.98 (was not tracked). No factor clears t≥3.0.
- **Journal 2026-07-16 (methodology hardening, same data vintage):** old → new: congress 2.59→2.36, fund 2.29→2.64, composite 2.40→2.32, L/S 2.98→2.55 gross / 2.08 net. Drivers: point-in-time S&P 500 universe (742-name union vs 503 current members; monthly priced-member coverage mean 91%, worst 81% — residual delisting bias measured, not hidden), L/S costed (10bps long / 25bps short per side), OOS verdict re-keyed to NW t (OOS NW t=2.33 → "interesting, unconfirmed"). The t≥3.0 bar did not move. Event-study CARs (now market-model, overlap-collapsed) are flat-to-negative for congress at long horizons — the monthly IC framing carries the signal, not event CARs.

- **Journal 2026-08-10 (value-factor data integrity, schema v19):** old → new: congress 2.36→2.24, fund 2.64→2.48, composite 2.32→**1.78**, L/S 2.55→1.39 gross / 2.08→0.96 net. The composite fell because two defects had been feeding the fundamental block spurious signal: (a) `_load_fundamentals` ordered only by `filing_date`, so a 10-K's comparative periods tied and last-wins kept an arbitrary row (WDC priced off a 2023 quarter, SNDK left with NULL EPS); (b) as-reported EDGAR EPS was divided by back-adjusted prices, inflating earnings yield by the cumulative split factor (BKNG implied P/E 1.3 on a 25:1 split, KLAC 6.4 on 10:1). Standalone value is now NW t=**0.13** — the value leg carries nothing. Part of the delta is confounded with same-day congress/house refresh. **A fix that lowers a t-stat is the credible kind** (Grinold's sensibleness guard). No factor clears t≥3.0.

- **Journal 2026-08-10b (fund EXIT restoration):** old → new: fund 2.48→2.42, composite 1.78→**1.65**, L/S 1.39→1.23 gross / 0.96→0.78 net. Congress (2.24) and value (0.13) unchanged to the decimal, which pins the deltas to this fix alone. `_load_fund_events` sized every event off `value`; an EXIT closes the position so `value` is 0, `log1p(0)=0` tripped the `weight <= 0` guard, and **all 71,958 EXIT rows were dropped** — the negative leg was TRIM only. Now sized as `prev_shares × last close ≤ filing_date` (10-day lookback) from the local price cache; restores 7,309 of 8,100 in-universe EXITs, ~21% more event flow, all sell-side. Full re-measure this run: congress 2.24, fund 2.42, quality 1.10, trend 0.71, mom 0.38, value 0.13, insider -0.35, vol -0.47, activism -1.71. Third defect in a row that lived in what the pipeline discarded rather than in the scorer.

- **Journal 2026-08-10c (derived bar + three pre-registered construction changes):** fund 2.42→**2.62**, composite 1.65→**1.90**, L/S 1.23→1.61 gross / 0.78→1.21 net, insider -0.35→-0.19, congress 2.24 unchanged. (a) 13F sells damped to 0.5 of buy weight — Agarwal's acquisition/disposal ratio, pre-registered at two fixed values and NOT swept; 1.0→2.42, 0.5→2.62, 0.0→1.73, an interior optimum being the shape theory predicts. (b) Insider now weights distinct-filer count and ranks dollars within-month instead of raw log1p — moved toward zero as predicted and still dead, because Lakonishok & Lee find the effect is entirely small-cap and our universe is not. (c) Congress log-scale **tested and reverted**: it collapsed congress to 1.52, firing the pre-registered falsifier — the signal lives in a handful of very large disclosures, so the factor is far more fragile than 2.24 suggests. Hypotheses were written to the vault before any run.

- **Journal 2026-08-10d (House backfill + the transaction-code defect):** congress 2.24→**1.72**, coverage 33%→**61%**, composite 1.90→1.83, L/S 1.61→1.41 gross / 1.21→1.02 net. Two changes, both data-completeness: (a) the House PTR backfill had never been run, so all 967 House rows were dated 2026 and the congress factor was **Senate-only for 2017-2025**; backfilling added 13,584 trades (house now 14,551 vs senate 11,676). (b) That alone changed *nothing* — `_congress_sign` only understood the Senate's English words ("Purchase"/"Sale (Full)") while House PTRs carry SEC letter codes ("P"/"S"/"S (partial)"), so ~14,300 of 14,551 House rows returned 0 and were dropped. Fixed; congress events 12.6k→23.2k. The halving of the signal is what Ziobrowski 2011 predicts — the House effect is weaker than the Senate's (55 vs 85 bps/month, power dilution) — so pooling dilutes. **The old 2.24 was a Senate-only number.** Congress log-scale retested on the complete two-chamber data and reverted again: 1.72→1.13, so the "signal lives in a handful of large disclosures" finding holds across both chambers.

### Price data (post-2026-07-16)
- All research prices go through `cortex.sources.prices` (DuckDB `prices` + `price_coverage`, schema v18) — never call `yf.download` directly in research code
- yfinance quirks: dead tickers come back as all-NaN COLUMNS in mixed batches but as an EMPTY frame when the whole batch is dead — the cache uses a SPY canary probe to distinguish "all dead" from "yfinance down" before recording names as unpriceable
- Stooq CSV endpoint is blocked by a JS proof-of-work challenge (2026-07-16) — delisted-price fallback prices 0 names; the gap surfaces in the backtest's universe-coverage ratio
- EPS vs prices are on different split bases: the price cache is yfinance `auto_adjust=True` (back-adjusted to today), EDGAR EPS is as-reported at the filing's share count. `cortex.sources.splits` restates EPS inside `_load_fundamentals`; never compute earnings yield from raw `eps_diluted / close`
- Point-in-time S&P membership: `sp500_members_asof()` / `sp500_union()` backed by vendored `data/reference/sp500_history.csv` (fja05680/sp500; refresh by re-downloading, provenance in the file header)

### Factor signals in scope
- `congress_trades` — EDGAR bulk EFTS JSON
- `fund_flow` — 13F via edgartools
- `insider_buys` — Form 4 P-coded non-derivative transactions (bulk-index approach)
- `fundamentals` — EDGAR XBRL `EarningsPerShareDiluted` concept (PEAD, planned)
- `quality` — ROE + gross-profits-to-assets (Novy-Marx 2013, planned)

## DB schema touch-points
- `insider_buys` table — `id` is a 16-char SHA256 dedup key on `(issuer_cik, filer_cik, tx_date, shares, accession)` (2026-07-06: old 3-field key collapsed 34% of rows — same-filer same-day lots)
- Migration `ADD COLUMN IF NOT EXISTS` statements must NEVER carry a DEFAULT — DuckDB (≤1.5.3) re-applies the default to every row on re-run, silently wiping backfilled values
- `fundamentals` — several comparative periods share one `filing_date` (a 10-K's prior years); any as-of query MUST order by `(filing_date, period_end)` or the tie-break is arbitrary storage order
- `splits` / `split_coverage` (schema v19) — coverage is tracked per ticker because "no splits ever" and "never fetched" are otherwise indistinguishable; `_load_fundamentals` reads the cache only, never the network, so backtests stay reproducible
- All sync commands are idempotent via `ON CONFLICT (id) DO NOTHING`

## Vault RAG (post-2026-08-10)
- Two separate trees: `settings.vault_dir` (`savage_vault/investing/`) is where CORTEX **writes** its mirror; `settings.research_dir` (`savage_vault/wiki/`) is where it **reads** notes to embed. They are not the same directory and never were — the old default pointed research at `investing/research`, which has never existed, so `rag-index` was a silent no-op for months while the retriever served a 2026-05-23 index
- `index_vault` filters on `rag.RESEARCH_TAGS` against each note's frontmatter `tags`/`domains`. The vault is a general knowledge base; without the filter the finance corpus (~39 notes) is buried under exercise science and sabermetrics. **A new finance note must be tagged `quantitative-finance` (or another allowlist tag) or the retriever will never see it**
- Re-indexing deletes every chunk under the indexed tree, not just the notes it kept — renamed, deleted, and newly-excluded notes must not survive as orphans that retrieval can still return
- YAML frontmatter is stripped before embedding and each chunk is prefixed with the note title, so a mid-note chunk still identifies its source
- `retrieve()` returns at most one chunk per note; fewer than `k` results means fewer than `k` distinct notes were relevant
- After ingesting anything into the vault, run `uv run cortex rag-index` — it exits non-zero if it matches no notes

## 13F / fund factor semantics
- `fund_holdings.period` is the 13F **filing date**, NOT the quarter-end — only 10 of 432,922 rows fall on a quarter-end; the modes are the mid-Feb/May/Aug/Nov statutory deadlines. There is no 45-day lookahead. The column name is wrong and should be renamed `filing_date`
- An EXIT row has `value = 0` and `shares = 0` by construction; its magnitude lives in `prev_shares`. Never size a fund event off `value` alone
- The table holds quarter-over-quarter **diffs for 14 curated managers**, not full portfolios — there are no HOLD rows. Cohen/Polk/Silli conviction weighting (position weight vs a passive benchmark) is therefore NOT computable from it
- Buys and sells are not mirror images: Agarwal 2013 finds 13F acquisitions +7.06% DGTW at 12m (t=3.95) vs disposals +2.94% (t=1.42); CORTEX signs them symmetrically ±1, which is unsupported and now testable

## Congress factor semantics
- The two chambers speak different languages: Senate eFD writes English ("Purchase", "Sale (Full)"); House PTRs carry SEC letter codes ("P", "S", "S (partial)", "E"). Any parser touching `transaction_type` must handle both — test the leading token as a code FIRST, or a bare "s" falls through and "p" matches the "partial" in "S (partial)"
- Congress notional is weighted RAW, not log1p, unlike the fund and insider loaders. This is deliberate as of 2026-08-10: log1p collapses the factor (1.72→1.13 on two-chamber data, 2.24→1.52 on Senate-only). The signal genuinely lives in a handful of very large disclosures, which makes the factor fragile — do not "fix" the inconsistency without re-reading that result
- Standing tension, unresolved: log-scaled congress is worse standalone but BETTER in the composite (1.98 vs 1.83). Replicated on both data vintages, so it is not noise

## Promotion bar (post-2026-08-10)
- **Never hardcode a t threshold.** `cortex.significance.build_gate(n_tests)` derives it from the run's actual test count; adding signals raises it for everyone
- Two bars, assigned by family in code AHEAD of the run so the choice can't be made after seeing a result: zoo draws (mom/trend/vol/value/quality/pead) carry HLZ's N=316 burden, CORTEX's own alt-data signals are scored against CORTEX's own family
- BHY + Yekutieli is STRICTER than Bonferroni for a lone discovery (3.21 vs 2.87 at N=12) — the rank-1 critical value carries a factor of c(N). BHY is only more lenient once several tests are already significant
- If you test k configurations of a factor, the honest N includes them. Two extra fund configs moved the bar 3.21→3.26

## Factor literature (vault, 16 papers as of 2026-08-10)
- The promotion bar traces to Harvey/Liu/Zhu 2016. Note both Harvey papers recommend **BHY (false discovery rate)**, while CORTEX's docs say "Bonferroni-corrected" — the label and the arithmetic disagree
- Newey & West 1987 does **not** specify lag selection; the `4(T/100)^(2/9)` plug-in rule is from later literature. At T=114 it gives lag 4, which is at the edge of the paper's own `m(T)/T^(1/4) → 0` growth condition
- The insider factor's -0.35 is likely a **universe mismatch**: Lakonishok & Lee find the effect is entirely small-cap (large-cap NPR coefficient -0.30, t=-0.65) and CORTEX's universe is the S&P 500
- Before building PEAD: Bernard & Thomas report SUE-return correlation 1.00 at decile level but **0.09 at firm level**. CORTEX's monthly cross-sectional IC is structurally the firm-level statistic, so expect IC ≈ 0.05-0.10, not the decile spread
