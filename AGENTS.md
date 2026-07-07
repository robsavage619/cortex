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
- Congress factor t=2.59, fund t=2.29, CORTEX composite t=2.40 as of last backtest (2026-07-06)
- None clear the bar yet — no live trading until at least one factor does
- **Journal 2026-07-06 (post-remediation):** old → new: congress 2.40→2.59 (+0.19, amendment exclusion removed ~1,978 double-counted rows), fund 2.58→2.29 (-0.29, EXIT preservation changed the event set), composite 1.89→2.40 (+0.51, brain alignment fixed: discovery now computes the same 3-block equal-weight signal as the backtest). Long-short spread NW t=2.98 (was not tracked). No factor clears t≥3.0.

### Factor signals in scope
- `congress_trades` — EDGAR bulk EFTS JSON
- `fund_flow` — 13F via edgartools
- `insider_buys` — Form 4 P-coded non-derivative transactions (bulk-index approach)
- `fundamentals` — EDGAR XBRL `EarningsPerShareDiluted` concept (PEAD, planned)
- `quality` — ROE + gross-profits-to-assets (Novy-Marx 2013, planned)

## DB schema touch-points
- `insider_buys` table — `id` is a 16-char SHA256 dedup key on `(issuer_cik, filer_cik, tx_date, shares, accession)` (2026-07-06: old 3-field key collapsed 34% of rows — same-filer same-day lots)
- Migration `ADD COLUMN IF NOT EXISTS` statements must NEVER carry a DEFAULT — DuckDB (≤1.5.3) re-applies the default to every row on re-run, silently wiping backfilled values
- All sync commands are idempotent via `ON CONFLICT (id) DO NOTHING`
