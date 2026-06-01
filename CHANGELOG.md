# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

### Added
- **Executive-mentions signal** — organic discovery of companies named by the
  administration. Scans whitehouse.gov category RSS feeds (statements / fact-sheets /
  releases) for S&P 500 companies via a precision-first entity matcher (full-phrase
  multi-word names, distinctive single tokens, common-word/ticker stoplists), then
  enriches each hit with a market-reaction gate (abnormal return vs SPY at +1/+5/+20
  trading days) and a Claude Haiku significance verdict that doubles as a precision
  backstop. New `executive_mentions` table (schema v15), `event-study --signal
  executive`, and a dashboard "White House Buzz" reaction timeline (scrollable, with
  per-mention source links). CLI: `exec-mention add|list|sync`.
- **Plain-English mode** — an app-wide toggle that translates the quant surface (factor
  codes, z-scores, composite percentiles, section labels) into plain language so the app
  reads clearly for non-quants.
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
