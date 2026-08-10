# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Vault retrieval actually reaches the vault (2026-08-10)

The research retriever had been serving a stale, diluted index that no shipped
command could refresh. Three independent faults:

- **`rag-index` was a silent no-op.** `settings.research_dir` defaulted to
  `vault_dir / "research"` — `~/Vault/savage_vault/investing/research`, a
  directory that has never existed. `index_vault` logged a warning, returned 0,
  and the CLI printed "Indexed 0 chunks", which reads like success. Meanwhile
  the live index was a 2026-05-23 snapshot of 529 notes built by some one-off
  override. New `DEFAULT_RESEARCH_DIR` points at `savage_vault/wiki/`, and the
  command now exits non-zero when it matches no notes.
- **The corpus was the whole knowledge base.** All 1,278 wiki notes were
  eligible, so exercise science, sabermetrics and frontend notes crowded the
  finance corpus at query time — a query about the CORTEX composite returned
  HRV standards and a McElreath covariance chapter. `index_vault` now parses
  YAML frontmatter and keeps only notes whose `tags`/`domains` intersect
  `rag.RESEARCH_TAGS`. 39 notes, 109 chunks. The same queries now return
  `cortex-signal-register` and `cortex-research-promotion-policy`.
- **Chunk text was half punctuation.** The YAML block was embedded verbatim
  into each note's first chunk, and later chunks carried no indication of which
  paper they came from. Frontmatter is now stripped, `title` and `summary` are
  lifted into the body, and every chunk is prefixed with the note title.

Also: `tier` is populated from the vault's own `retrieval_priority` instead of
a path regex that never matched (all 1,783 old rows had `tier IS NULL`);
re-indexing clears the whole tree so renamed/deleted/newly-excluded notes cannot
survive as orphan chunks; and `retrieve()` returns at most one chunk per note,
so a `k=2` factor panel no longer spends both slots on the same paper.

### Value-factor data integrity (2026-08-10, schema v19)

Two independent defects were corrupting the fundamental block. Both are fixed;
**the pre-registered t-stats below were computed on the corrupted inputs and
must be re-measured before they are quoted again.**

- **Comparative-period tie-break.** `_load_fundamentals` ordered only by
  `filing_date`. One 10-K discloses several comparative periods under a single
  filing date, so tied rows fell in arbitrary storage order and the last-wins
  scan in `_fundamental_asof` kept whichever landed last. WDC was priced off a
  2023 quarter (EPS −2.17); SNDK resolved to a 2022 row with a NULL EPS. Now
  ordered by `(filing_date, period_end)`. Live effect: SNDK #1→#3, WDC #8→#5.
- **As-reported EPS vs back-adjusted prices.** The price cache is yfinance
  `auto_adjust=True` (re-based retroactively by every split); EDGAR EPS is on
  the share count in force at filing. Their ratio inflates earnings yield by the
  cumulative split factor — BKNG showed an implied P/E of 1.3, KLAC 6.4, EIX
  5.9. New `splits` + `split_coverage` tables (`cortex.sources.splits`) restate
  EPS onto the adjusted basis inside `_load_fundamentals`. ROE is a ratio of
  aggregates and is left untouched.

`_load_fundamentals` reads only the cached `splits` table and never the network,
so backtests stay reproducible; the cache is warmed by the new `fundamentals`
sync step. Coverage is tracked per ticker because "no splits ever" and "never
fetched" are otherwise indistinguishable, and uncovered names are reported
rather than silently treated as unsplit.

- **`sync-all` now runs `fundamentals`.** `_STEPS` was
  `congress, funds, discover, volatility, executive` — `sync_runs` confirms a
  fundamentals sync had never once run from the refresh path, so the value and
  quality legs were computed against whatever EDGAR data was last pulled by
  hand. The step runs before `discover` and also warms the split cache.

### Methodology hardening + re-baseline (2026-07-16)

The pre-registered suite was re-measured on a hardened pipeline (same data
vintage as the 2026-07-06 journal; only methodology changed — the t≥3.0 bar
itself did not move):

| metric (NW t) | old (2026-07-06) | new (2026-07-16) | why it moved |
|---|---|---|---|
| congress ablation | 2.59 | 2.36 | point-in-time universe |
| fund ablation | 2.29 | 2.64 | point-in-time universe |
| composite | 2.40 | 2.32 | point-in-time universe |
| L/S spread (gross) | 2.98 | 2.55 | point-in-time universe |
| L/S spread (net) | — | 2.08 | now costed (10bps long / 25bps short per side) |
| congress OOS verdict | naive t | NW t 2.33 | verdict re-keyed to NW |

Still no factor clears the t≥3.0 gate. **No live trading.**

What changed:

- **Survivorship bias corrected.** Universe is now point-in-time S&P 500
  membership (vendored snapshot history at `data/reference/sp500_history.csv`,
  1996→present, validated against known adds/removes). Monthly cross-sections
  keep only that month's true members: 742-name union since 2016 vs the 503
  current members the old backtest saw. Residual delisting bias is *measured*
  per month (priced members / true members: mean 91%, worst month 81%) and
  printed with every run; 123 dead tickers are unpriceable by any free source
  (yfinance dropped them; Stooq now fronts a JS challenge that blocks headless
  CSV fetches — fallback code kept, degrades gracefully).
- **Prices persisted in DuckDB** (`prices` + `price_coverage`, schema v18).
  All research price access goes through `cortex.sources.prices` with
  fetch-missing-then-cache semantics, adjustment-drift self-healing on
  dividend re-basing, and a canary probe that distinguishes dead tickers from
  yfinance outages. A backtest re-run is now network-free, ~2s, and
  bit-identical. Live screens (discovery, swing) top up only the missing tail.
- **OOS verdict keys off the Newey-West t-stat** (monthly ICs are
  autocorrelated; the naive IID t overstated significance). Both stats still
  printed.
- **Event study upgraded to a market model** — per-name (α, β) estimated on a
  252d pre-event window (30d gap, min 120 obs), market-adjusted fallback
  disclosed. Overlapping same-ticker events are collapsed per horizon
  (collapsed counts printed). CARs explicitly labeled GROSS. Post-upgrade the
  congress CAR is flat-to-negative at long horizons with a small negative
  pre-event placebo — the monthly-IC framing, not the event CAR, carries the
  congress signal.
- **L/S spread now reported net of costs** (turnover-based, +15bps/side
  short-leg borrow assumption) alongside gross; SPY added as a cap-weighted
  reality-check benchmark next to the EW null.
- **Offline test harness** — `tests/fixtures/prices.py` seeds the price cache
  with deterministic synthetic universes; `tests/test_backtest_integration.py`
  runs the full backtest/OOS/event-study stack network-free (planted-factor
  recovery, PIT-coverage semantics, NW verdict keying, market-model
  beta-stripping, overlap collapse, cost accounting).

### Security
- Removed all hardcoded personal contact details from source. The SEC EDGAR
  `User-Agent` / identity is now read from `CORTEX_SEC_USER_AGENT` via a single helper,
  with a generic placeholder default.
- Removed a hardcoded, machine-specific absolute path from the LLM-analysis code path;
  the `claude` binary is now resolved from `PATH` with an optional `CORTEX_CLAUDE_BIN`
  override.
- **Anthropic token spend gated to the deployment.** All Claude API calls (House-PDF
  OCR and the new executive-mention significance analysis) run only when
  `RAILWAY_ENVIRONMENT` / `CORTEX_PRODUCTION` is set, via `config.llm_calls_enabled()`,
  so local development and testing never bill the API key. `CORTEX_ALLOW_LLM=1`
  overrides for a deliberate local run.

### Changed
- **Frontend is now built during the Railway deploy** instead of committing `web/dist`.
  The NIXPACKS plan (`nixpacks.toml`) extends the Python toolchain with Node and runs
  `npm install && npm run build`, so the served SPA can never go stale relative to source.
  `web/dist` is no longer tracked in git. Getting this to work required three rounds of
  fixes against nixpkgs version pinning constraints:
  - Railway's nixpkgs snapshot resolves `nodejs_22` to 22.10.0, which is below Vite 8's
    minimum (20.19+ or 22.12+), causing the rolldown native binding to install the wrong
    linux variant.
  - `npm ci` strictly follows `package-lock.json` (generated on macOS), so
    `@rolldown/binding-linux-x64-gnu` is absent and the build fails on the Railway host.
    Switched to `npm install` so the linux binding is resolved at build time.
  - Railway does not expand `[variables]` from `nixpacks.toml` as build-time env vars,
    so `pip install uv==$NIXPACKS_UV_VERSION` expands to `pip install uv==` and fails.
    The uv version is now hardcoded in `[phases.install]`.
  - The nixpkgs snapshot contains no `nodejs_24` and caps `nodejs_22` at 22.10.0. The
    final fix sidesteps nixpkgs entirely: the build phase downloads the official Node
    22.15.0 tarball and prepends `/usr/local/bin` to `PATH`.

### Added
- **WHALES tab** — dedicated institutional 13F view for hedge-fund and asset-manager
  positioning. Surfaces a conviction-map bubble scatter (position size vs. number of
  holders), most-crowded names, biggest single bets, and a clickable manager leaderboard
  with action filters. 13F institutional buys were previously embedded in the main
  dashboard; they now live here with their own full-page workspace.
- **TradeImpactChart** — reusable price-at-trade visualization added to both the Congress
  and Whales tabs. Every filing row expands to show the stock's price on the trade date
  and how it has moved since, with a plain-language verdict ("up 12.6% since the buy").
- **`/admin/sync/executive` endpoint** — `railway run` cannot write to Railway's `/data`
  volume, so a POST endpoint was added that spawns the exec-mention sync as a subprocess
  on the live container, enabling manual seeding of the executive-mentions table on a
  fresh deployment.
- **Per-row significance glow** on White House Buzz entries — left border accent and
  subtle background tint (cyan = high significance, amber = medium) applied to each row
  so significance is visible at a glance, not just in the badge chip.
- **Executive-mentions signal** — organic discovery of companies named by the
  administration. Scans whitehouse.gov category RSS feeds (statements / fact-sheets /
  releases) for S&P 500 companies via a precision-first entity matcher (full-phrase
  multi-word names, distinctive single tokens, common-word/ticker stoplists), then
  enriches each hit with a market-reaction gate (abnormal return vs SPY at +1/+5/+20
  trading days) and a Claude Haiku significance verdict that doubles as a precision
  backstop. New `executive_mentions` table (schema v15), `event-study --signal
  executive`, and a dashboard "White House Buzz" reaction timeline (scrollable, with
  per-mention source links). CLI: `exec-mention add|list|sync`.
  - First iteration used GDELT for organic discovery but was rejected as too noisy
    (global news co-occurrence, common-word company-name collisions). Replaced with
    direct whitehouse.gov RSS ingestion, which carries full transcript text, exact dates,
    and a guaranteed administration speaker.
  - Entity matcher is precision-first: multi-word names match only as the full phrase;
    single tokens only if distinctive (len ≥ 4, not in the common-word stoplist); no
    bare-ticker matching (ICE / IP / WM acronym collisions); known generic-phrase names
    skipped; nav-boilerplate guard.
  - Verified on live data: 30 mentions / 22 tickers (Nvidia $500B commitment, Boeing,
    Intel, DoorDash, Pfizer, Freeport…); price-reaction gate correctly signs pharma
    price-cap deals as negative.
- **Plain-English mode** — an app-wide toggle (persisted) that translates the quant
  surface (factor codes, z-scores, composite percentiles, section labels) into plain
  language so the app reads clearly for non-quants. `MOM/LVOL/SHR/VAL/QUAL` →
  `Price trend / Steadiness / Efficiency / Value / Quality`; `+2.88z` → `top 0.2%`;
  `DISCOVERED / ALGO BUYS` → `TOP PICKS / STRONG BUYS`. `lib/plain.ts` is the single
  source of truth for term translations, reused across all views.
- **Operations & deployment layer** — per-source refresh (`sync-all --only …`),
  per-source freshness telemetry (`/freshness` + a dashboard strip), failure alerting to
  a webhook, DuckDB snapshot/backups (`cortex backup`, pruning, optional S3), a nightly
  factor-stat history snapshot (`snapshot-factors` → `/factor-history`), and Railway cron
  services that trigger work over HTTP against the volume-owning web process
  (`trigger-refresh` / `trigger-backup` / `trigger-snapshot`). The full refresh runs as
  an isolated subprocess and survives crashes (health check + restart policy).
- Root `README.md` (portfolio overview) and this changelog.

## [0.1.0] — 2026-05-24

The first complete build: factor engine, alt-data ingestion, decision-quality system,
and the React portal.

### Added
- **Decision-quality core** — thesis CRUD with mandatory falsifiers and review dates,
  Brier-score calibration with per-conviction hit-rate buckets, a review queue, and
  attachable dissents (schema v2). Markdown vault mirror of all theses.
- **CORTEX factor engine** — point-in-time multi-factor equity ranking (momentum,
  low-volatility, Sharpe, value, quality) over the S&P universe, with cross-sectional
  standardisation and a `discover` command.
- **Alternative-data factors & ingestion** — congressional trading flow (Senate eFD),
  Form 4 insider open-market buys via SEC bulk-index parsing, 13F institutional fund
  flow with historical backfill, 13D activist stakes, and point-in-time EDGAR XBRL
  fundamentals. All sources are free; all writes are idempotent (SHA-256 dedup).
- **Pre-registered backtest harness** — `backtest` and `congress-oos` evaluate factors
  against pre-registered hypotheses and an out-of-sample window, applying a
  multiple-testing-corrected t-statistic gate and reporting survivorship and
  coverage caveats inline.
- **Research RAG** — local `fastembed` embeddings indexed in DuckDB's native vector
  search (HNSW) for grounded per-ticker context.
- **FastAPI service** — typed JSON API (theses, reviews, calibration, congress, funds,
  candidates, screens, per-ticker context and history) that also serves the compiled
  SPA from a single origin. Optional LLM-backed factor commentary via the `claude` CLI.
- **React portal** — glass-premium, dark-only UI: CORTEX command-center dashboard with
  live factor z-score meters and price sparklines, congressional-flow analytics, a
  volatility / dollar-swing screen, the calibration reliability diagram, thesis
  management, and a stock detail modal. Built on TanStack Query, lightweight-charts,
  and Recharts.
- **Design system** — `DESIGN.md`, a locked anti-action-bias visual contract
  (tokens, components, motion) that all generated UI adheres to.
- **CLI** — `cortex` entrypoint covering database init, data syncs/backfills, discovery,
  screens, backtests, calibration, the RAG index, the vault mirror, and `serve`.
- **Storage** — DuckDB columnar store with a schema-version migration table and a
  context-managed connection helper.

### Engineering
- `src/` layout managed with `uv`; `ruff` + `pyright` configured.
- 69 tests covering storage, calibration, RAG, backtest math, and HTTP-mocked sources.

[Unreleased]: https://github.com/robsavage619/savage-wall-street-tracker/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/robsavage619/savage-wall-street-tracker/releases/tag/v0.1.0
