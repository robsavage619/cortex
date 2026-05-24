# Savage Wall Street Tracker (WST)

> A factor-model research platform that treats investing as a **calibrated decision
> process**, not a signal feed. Every number on screen is evidence for a decision —
> never a recommendation.

WST is a single-operator quantitative research platform built end-to-end: a
point-in-time factor engine, an alt-data ingestion layer sourced entirely from free
public filings, a decision-quality system that scores the operator's own forecasting
calibration, and a glass-premium React portal — all served from one Python process.

It is deliberately **honest about what it has and hasn't found**: the backtest harness
holds every candidate factor to a pre-registered, multiple-testing-corrected
significance bar, and the platform refuses to dress up noise as alpha. No factor has
cleared the bar yet, so nothing trades live. That restraint is the point.

---

## Why this project exists

Most retail "stock tools" optimise for action — buy buttons, green arrows, dopamine.
WST optimises for the opposite: slower, better-calibrated decisions, and intellectual
honesty about edge. It was built to demonstrate, in one codebase:

- **Research engineering** — point-in-time data discipline, survivorship-bias
  accounting, pre-registration, and honest negative results.
- **Data engineering** — robust ingestion from messy, undocumented public filing
  systems (SEC EDGAR, Senate disclosures) with rate-limit etiquette and idempotent
  writes, using **zero paid APIs**.
- **Full-stack product** — a typed FastAPI service, a vector-search research layer,
  and a polished React/TypeScript portal, shipped as a single deployable.
- **Product integrity** — an anti-action-bias design system and a persistent
  "decision tool — not financial advice" contract surfaced everywhere.

---

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │  React + Vite + TS portal  (web/)            │
                    │  glass-premium UI · TanStack Query · charts  │
                    └───────────────────────┬─────────────────────┘
                                            │  one origin, port 8000
                    ┌───────────────────────┴─────────────────────┐
                    │  FastAPI service  (src/wst/api.py)           │
                    │  serves the built SPA + a typed JSON API     │
                    └───────────────────────┬─────────────────────┘
          ┌─────────────────┬───────────────┼───────────────┬─────────────────┐
          │                 │               │               │                 │
   ┌──────┴──────┐  ┌───────┴──────┐ ┌──────┴──────┐ ┌──────┴──────┐ ┌────────┴───────┐
   │ CORTEX      │  │ Decision     │ │ RAG /        │ │ Alt-data     │ │ Backtest /     │
   │ factor      │  │ quality      │ │ research     │ │ ingestion    │ │ pre-registered │
   │ engine      │  │ (theses,     │ │ (fastembed + │ │ (EDGAR,      │ │ OOS harness    │
   │             │  │  calibration)│ │  DuckDB VSS) │ │  Senate eFD) │ │                │
   └──────┬──────┘  └───────┬──────┘ └──────┬──────┘ └──────┬──────┘ └────────┬───────┘
          └─────────────────┴───────────────┴───────────────┴─────────────────┘
                                            │
                              ┌─────────────┴─────────────┐
                              │  DuckDB  (columnar store  │
                              │  + VSS HNSW vector index) │
                              └───────────────────────────┘
```

**Stack:** Python 3.12 · FastAPI · DuckDB (analytics + native vector search) ·
fastembed (local embeddings) · scikit-learn · React 18 · Vite · TypeScript ·
TanStack Query · lightweight-charts · Recharts. Tooling: `uv`, `ruff`, `pyright`.

The whole thing runs as one command (`wst serve`) on `127.0.0.1` — the API and the
compiled SPA share a single origin and process.

---

## What's inside

### CORTEX — point-in-time multi-factor engine

A composite equity-ranking engine over the S&P universe. Factors are computed from
**point-in-time** inputs (no lookahead) and standardised cross-sectionally each period:

| Factor   | Intuition                              | Source              |
|----------|----------------------------------------|---------------------|
| Momentum | 12-1 trailing return                   | Market prices       |
| Low-vol  | Inverse realised volatility            | Market prices       |
| Sharpe   | Risk-adjusted trailing return          | Market prices       |
| Value    | Earnings yield                         | EDGAR XBRL (PIT)    |
| Quality  | Return on equity / capital efficiency  | EDGAR XBRL (PIT)    |

Plus **alternative-data factors** ingested from public disclosures: congressional
trading flow, Form 4 insider open-market buys, 13F institutional fund flow, and 13D
activist stakes. The exact composite weighting is intentionally not documented here.

### Pre-registered backtest harness

The differentiator. `wst backtest` and `wst congress-oos` evaluate factors against a
**pre-registered hypothesis and an out-of-sample window**, and apply a
multiple-testing-corrected significance gate. A factor is only called "real" when its
information-coefficient t-statistic clears the bar — anything below is treated as noise.

The harness explicitly reports its own caveats (survivorship bias from a
current-membership universe, sparse coverage on alt-data factors, transaction-cost
assumptions) **in the output itself**. As of the latest run no candidate factor clears
the bar, so the platform does no live trading. Honest negative results, surfaced rather
than buried.

### Decision-quality system

Investing decisions are logged as **theses** with a required, explicit *falsifier* and a
*review date* — you must state in advance what would prove you wrong. A calibration
engine then scores the operator's forecasting using **Brier scores** and per-conviction
hit-rate buckets, flagging systematic over-confidence. Dissents can be attached to any
thesis to capture the bear case. A review queue surfaces theses whose review date has
passed.

### Research RAG

Markdown research notes are chunked, embedded locally with `fastembed`, and indexed in
DuckDB's native vector-search extension (HNSW). Context retrieval grounds the
per-ticker analysis without any external embedding API.

### Glass-premium portal

A dark-only, anti-action-bias React portal (see [`DESIGN.md`](DESIGN.md) for the locked
design system): a CORTEX command-center dashboard with live factor z-score meters,
congressional-flow analytics, a volatility/dollar-swing screen, the calibration
reliability diagram, and thesis management. Gains and losses are rendered in *muted*
green/red on purpose — the UI signals direction, never excitement.

---

## Data engineering notes (hard-won)

Free public filing systems are gloriously undocumented. A few things this codebase gets
right that most tutorials get wrong:

- **SEC Form 4 filenames are not standardised.** `form4.xml` only resolves for ~half of
  filers; filing agents use custom names. The canonical resolution path is each filer's
  `submissions/CIK……json` → `primaryDocument`, stripping the XSLT rendering subdirectory
  to reach the actual data file.
- **Bulk index over per-company queries.** Insider/activism backfills parse SEC's
  quarterly `form.idx` bulk indexes rather than issuing hundreds of thousands of
  per-filing guesses — orders of magnitude fewer requests.
- **Rate-limit etiquette.** Bounded worker pools, exponential back-off on HTTP 429, and a
  compliant, configurable `User-Agent` keep ingestion within SEC fair-access limits.
- **Idempotent writes.** Every sync is safe to re-run: rows carry deterministic SHA-256
  dedup keys with `ON CONFLICT DO NOTHING`, so partial runs never duplicate or corrupt.
- **Fail visibly.** Skipped or degraded records are surfaced, never silently dropped.

---

## Quickstart

```bash
# 1. Install (Python 3.12, uv)
uv sync

# 2. Provide an SEC contact identity (required by SEC fair-access policy)
#    Set WST_SEC_USER_AGENT to "Your Name your-email@example.com" in a .env file.

# 3. Initialise the columnar store
uv run wst db-init

# 4. (optional) Ingest public data — all free sources
uv run wst congress-sync          # Senate disclosures
uv run wst insiders-sync          # Form 4 open-market buys
uv run wst funds-sync             # 13F institutional flow
uv run wst fundamentals-sync      # point-in-time EDGAR fundamentals

# 5. Rank the universe and check the evidence
uv run wst discover               # CORTEX multi-factor ranking
uv run wst backtest               # pre-registered factor evaluation

# 6. Build the portal and serve everything from one process
(cd web && npm install && npm run build)
uv run wst serve                  # http://127.0.0.1:8000
```

### CLI surface

`db-init` · `new` · `review` · `calibration` · `mirror` · `rag-index` · `discover` ·
`vol-screen` · `congress-sync` · `funds-sync` · `funds-backfill` · `insiders-sync` ·
`activism-sync` · `fundamentals-sync` · `congress-oos` · `backtest` · `serve`

Run `uv run wst <command> --help` for arguments.

### Configuration

All runtime config comes from the environment (or a local, git-ignored `.env`). Nothing
sensitive is committed.

| Variable              | Purpose                                              |
|-----------------------|------------------------------------------------------|
| `WST_SEC_USER_AGENT`  | SEC EDGAR contact identity (`Name email`) — required |
| `WST_DUCKDB_PATH`     | Override the DuckDB path (must end in `.db`)         |
| `WST_VAULT_DIR`       | Markdown mirror output directory                     |
| `WST_RESEARCH_DIR`    | Research-note source for the RAG index               |
| `WST_CLAUDE_BIN`      | Explicit path to the `claude` CLI (LLM analysis)     |
| `VITE_LOGODEV_TOKEN`  | Optional logo enhancement; UI falls back to monograms|

---

## Engineering quality

- **69 tests** across the suite, covering storage, thesis CRUD, calibration, RAG, the
  backtest math, and HTTP-mocked data sources (`respx`).
- **Strict tooling:** `ruff` (format + lint + isort), `pyright` (basic), `uv` lockfile.
- **Typed throughout:** `from __future__ import annotations`, `X | None` unions,
  dataclasses, Pydantic request models.
- **Idempotent, schema-versioned storage** with a migration table.

```bash
uv run pytest        # tests + coverage
uv run ruff check src/
uv run pyright src/
```

---

## Security & privacy posture

This repository is published as a portfolio piece and is hardened accordingly:

- **No secrets, no PII in source.** Contact identities, tokens, and machine-specific
  paths are read from the environment — never hardcoded. `.env*` files are both
  git-ignored and on a filesystem deny-list.
- **No data committed.** The DuckDB store, coverage artefacts, and caches are
  git-ignored; the repo ships code, not anyone's positions or research.
- **Local-only by default.** The server binds `127.0.0.1`; CORS is restricted to the
  local dev origin; the API is read-mostly with a small typed write surface.
- **Safe subprocess + DB access.** The LLM analysis path invokes the `claude` CLI with
  argument vectors (no shell string interpolation); all SQL uses parameterised queries.
- **Public data only.** Every external source is a free public disclosure feed (SEC
  EDGAR, Senate eFD) accessed within published rate-limit and fair-access policies.

---

## Disclaimer

WST is a personal research and decision-support tool. It is **not financial advice**, it
does not execute trades, and it makes no recommendations. Nothing here is an offer or
solicitation. Markets are risky; past performance does not predict future results.

---

© Rob Savage. Source provided for portfolio review. All rights reserved.
