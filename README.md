<p align="center">
  <img src="docs/banner.png" alt="CORTEX — a point-in-time, multi-factor research engine" width="100%"/>
</p>

<p align="center">
  <b>A factor-model research platform that treats investing as a calibrated decision process — not a signal feed.</b><br/>
  <i>Every number on screen is evidence for a decision. Never a recommendation.</i>
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="python 3.12"/></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/api-FastAPI-009688" alt="FastAPI"/></a>
  <a href="https://duckdb.org/"><img src="https://img.shields.io/badge/store-DuckDB%20%2B%20VSS-fff100" alt="DuckDB"/></a>
  <a href="web/"><img src="https://img.shields.io/badge/frontend-React%2018%20%2B%20Vite-61dafb" alt="React 18"/></a>
  <img src="https://img.shields.io/badge/tests-198%20passing-34D399" alt="tests"/>
  <img src="https://img.shields.io/badge/paid%20APIs-zero-8B5CF6" alt="zero paid APIs"/>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-source--available-lightgrey" alt="license"/></a>
</p>

---

## What this is

CORTEX is a personal quantitative research platform I built end-to-end. It's a point-in-time multi-factor equity engine over the S&P universe, with an alt-data ingestion layer sourced entirely from free public filings, a decision-quality system that scores my own forecasting calibration, and a glass-premium React portal — all served from one Python process.

It is deliberately **honest about what it has and hasn't found.** The backtest harness holds every candidate factor to a pre-registered significance bar that is *derived per run* from the actual number of tests, and refuses to dress up noise as alpha. As of the latest run, **no factor clears the bar — so nothing trades live.** That restraint is the point.

The most useful thing this repo demonstrates is not a signal. It is a research apparatus that keeps producing "no" and makes it hard to lie to yourself: every factor carries its own known caveats in the output, corrections that *lower* a t-statistic are kept, and the bar rises automatically each time another idea is tested.

This repository is published as a portfolio piece. The source code is available for review; it is not intended to be deployed or extended by others. See the [license](LICENSE).

---

## Skills demonstrated

| Domain | Specifics |
|--------|-----------|
| **Data engineering** | Public-filing ingestion from SEC EDGAR (Form 4, 13F, XBRL), Senate eFD, House Clerk PTR PDFs and FINRA Reg SHO; bulk-index strategies; idempotent dedup-keyed writes; per-source coverage tracking that distinguishes "never fetched" from "nothing there"; rate-limit etiquette |
| **Quantitative finance** | Point-in-time factor construction; Newey–West HAC-adjusted IC t-statistics; pre-registered hypotheses with written falsifiers; Benjamini–Hochberg–Yekutieli multiple-testing control derived per run; long–short spread attribution; size and tail decomposition |
| **Backend** | FastAPI service with typed Pydantic models; DuckDB for columnar analytics + native vector search (HNSW via VSS extension); schema-versioned migrations |
| **Frontend** | React 18 + TypeScript + Vite SPA; TanStack Query; lightweight-charts + Recharts; custom glass-premium design system |
| **LLM integration** | fastembed local embeddings for RAG; Claude Haiku for significance classification, gated to production so local runs never bill |
| **Deployment** | Railway (FastAPI + DuckDB on a persistent volume); nixpacks custom build (Python + Node in one image); cron-over-HTTP architecture for volume-owning service; automated freshness monitoring |
| **Engineering process** | Conventional commits; 198 tests covering the scoring core (discovery composite, swing screen, calibration math, dedupe keys, thesis CRUD, storage, RAG, evidence links, significance maths, backtest helpers); `ruff` clean; `pyright` tracked (legacy type debt being paid down) |

---

## The command center

> *A dark-only, anti-action-bias dashboard. Gains and losses render in muted green/red on purpose — the UI signals direction, never excitement.*

<p align="center">
  <img src="docs/screenshots/dashboard.png" alt="CORTEX dashboard — discovered candidates with live factor z-score meters" width="100%"/>
</p>

The dashboard opens on the **CORTEX-ranked universe**: every candidate carries a composite z-score and a per-factor breakdown — momentum, low-vol, Sharpe, value, quality — rendered as live meters. **DISCOVERED** is the raw screen; **ALGO BUYS** are the engine's multi-factor picks, built from the model, not hand-selected; **STRONG BUY** holds hand-authored theses at conviction ≥ 4. The top strip carries calibration KPIs (Brier score, hit rate, review count) so decision quality is always in view.

---

## Congressional trade flow

> *Every U.S. senator is legally required to disclose their trades. CORTEX aggregates the whole feed into buy/sell pressure.*

<p align="center">
  <img src="docs/screenshots/congress.png" alt="Congressional trade flow — monthly buy/sell flow, per-ticker pressure, and most active members" width="100%"/>
</p>

Disclosed trades are ingested from public Senate eFD filings and rolled into **monthly net buy/sell flow**, **per-ticker pressure**, and a **most-active-members** leaderboard with a buy/sell split. The median disclosure lag is surfaced directly — because alt-data that arrives 26 days late is a different signal than one that arrives same-day, and the platform refuses to hide that.

---

## Institutional positioning — WHALES

> *Every quarter, hedge funds and asset managers file their holdings with the SEC. CORTEX aggregates the picture: who owns what, how much, and whether the bet paid off.*

The WHALES tab is a dedicated workspace for 13F institutional positioning. A **conviction-map bubble scatter** plots each name by position size and holder count — names in the top-right corner are big bets held by many. Below it: **most-crowded names**, **biggest single bets**, and a **clickable manager leaderboard** with a buy/sell action filter.

Every filing row in both the Congress and WHALES tabs expands a **TradeImpactChart**: the stock's closing price on the exact trade date, its price today, and a plain-language verdict — "up 12.6% since the buy." The chart makes it immediate whether a disclosed position has worked.

---

## The volatility / dollar-swing screen

> *Rank the universe by how much it actually moves — average daily swing, peak swing, consistency, and range position.*

<p align="center">
  <img src="docs/screenshots/swing.png" alt="Swing screen — universe ranked by dollar swing, consistency, and range position" width="100%"/>
</p>

A trading-oriented screen that scores each name on **dollar-swing magnitude, consistency, and where it sits in its range** — for sizing and timing decisions rather than long-horizon conviction. Sortable, filterable, and wired into the same per-ticker analysis as everything else.

---

## The CORTEX case — per ticker

> *Click any candidate. The auto-built case shows the factor evidence, the trend snapshot, performance, and a falsifier — before you ever form an opinion.*

<p align="center">
  <img src="docs/screenshots/stock-modal.png" alt="Per-ticker CORTEX case — overview, factor breakdown, performance, and vault-grounded research" width="100%"/>
</p>

Each ticker opens a four-tab workspace: **Overview** (trend, momentum, trading activity, recent news), **Case** (the auto-built bull/risk argument with per-point z-scores), **CORTEX** (the 5-factor decomposition plus retrieved vault research), and **Charts** (price, volume, RSI). The *AI Reasoning* path grounds its analysis in locally-embedded research notes — no external embedding API.

---

## Decision quality & calibration

> *You must state in advance what would prove you wrong. Then the platform scores how well-calibrated you actually are.*

<p align="center">
  <img src="docs/screenshots/calibration.png" alt="Calibration — reliability diagram, hit rate by conviction bucket, and per-author Brier score" width="100%"/>
</p>

Investing decisions are logged as **theses** with a required, explicit *falsifier* and a *review date*. A calibration engine then scores forecasting using **Brier scores** and per-conviction hit-rate buckets, plotting a reliability diagram that flags systematic over-confidence. A **process score** separates decision *quality* from outcome — a good decision with a bad result is still a good decision.

---

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │  React + Vite + TS portal  (web/)            │
                    │  glass-premium UI · TanStack Query · charts  │
                    └───────────────────────┬─────────────────────┘
                                            │  one origin, port 8000
                    ┌───────────────────────┴─────────────────────┐
                    │  FastAPI service  (src/cortex/api.py)        │
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

The whole thing runs as one command on `127.0.0.1` — the API and the compiled SPA share a single origin and process. On Railway the SPA is compiled from source on every deploy, so the served frontend can never fall behind the Python API.

---

## Factor model

A composite equity-ranking engine over a **point-in-time S&P 500 universe** — a 742-name
historical union, of which 621 (83.7%) can still be priced; each monthly cross-section
keeps only that month's true members, and the residual delisting gap is reported rather
than hidden.
Every factor is built from point-in-time inputs — no lookahead — and standardised
cross-sectionally each period.

| Factor | Intuition | Source | Grounding |
|---|---|---|---|
| `mom` | 12-1 trailing return | Market prices | Jegadeesh & Titman 1993 |
| `trend` | Distance to the 200-day SMA | Market prices | Faber 2007 |
| `vol` | Inverse realised volatility | Market prices | Baker 2011, Frazzini & Pedersen 2014 |
| `value` | Earnings yield, split-basis corrected | EDGAR XBRL (PIT) | Fama & French 1992/93 |
| `quality` | Return on equity | EDGAR XBRL (PIT) | Novy-Marx 2013, Asness 2019 |
| `congress` | Congressional buy/sell pressure | Senate eFD + House Clerk PTR | Ziobrowski 2004/2011, Eggers & Hainmueller 2013 |
| `fund` | 13F institutional flow, sells damped | SEC EDGAR 13F | Cohen/Polk/Silli, Agarwal 2013 |
| `insider` | Form 4 buys, distinct-filer weighted | SEC EDGAR Form 4 | Lakonishok & Lee 2001, Cohen/Malloy/Pomorski 2012 |
| `activism` | 13D initial stakes | SEC EDGAR 13D | *ungrounded — no vault source* |
| `short` | Reg SHO short-volume share | FINRA (free, daily) | Boehmer/Jones/Zhang 2008 |

Nine of the ten factors trace to a paper held in the research vault, and each paper's
own caveats are surfaced in the backtest output — see
[Evidence-linked research](#evidence-linked-research). `activism` is the exception: the
code cites Brav & Jiang (2008) in a comment but no source note exists, so it is scored
without grounding. It also reads −1.71 on 15% coverage, which is the weakest evidence
base on the board.

### Pre-registered backtest harness

The differentiator. A candidate factor is evaluated against a **hypothesis and a
falsifier written down before the run**, then held to a significance bar the harness
derives from the run's own test count rather than a constant someone chose.

**Two bars, assigned by family in code ahead of the run**, so the choice can never be
made after seeing a result:

| Family | Bar | Rationale |
|---|---:|---|
| Own-family BHY | **3.24** | congress, fund, insider, activism, short — a small private set CORTEX assembled |
| Zoo-draw BHY | **4.21** | mom, trend, vol, value, quality — lifted from the published literature, so they inherit its multiple-testing burden (Harvey/Liu/Zhu's N = 316) |

Benjamini–Hochberg–Yekutieli rather than Bonferroni, because both Harvey papers
recommend false-discovery-rate control when tests are correlated. Note the direction:
with the Yekutieli dependence correction, BHY is *stricter* than Bonferroni for a lone
discovery. **Adding a factor raises the bar for every other factor** — the honest cost
of testing another idea.

Every t-statistic is **Newey–West HAC-adjusted** (Bartlett kernel). Alongside the
per-factor ablation the harness reports:

- **Long–short spread**, gross and net of costs (10bps long / 25bps short per side)
- **Factor-IC correlation matrix**, plus the mean |ρ| the Sharpe-haircut procedure needs
- **Size split** — each factor's t within the larger and smaller half of the cross-section
- **Tail decomposition** — which *end* of a factor carries it, since an IC cannot say
- **Direction homogeneity** — share of months with positive IC
- **Cumulative trial count**, reported as a lower bound

### Current state — nothing clears

```
factor       mean IC       t    NW t    bar   cover    +mo   lgNWt   smNWt     topD     botD
fund         +0.0188    2.55    2.62   3.24    97%    61%    2.96    1.57   +0.41%   -0.37%
short        +0.0148    1.73    1.87   3.24    79%    58%    1.22    1.57   +0.24%   -0.22%
congress     +0.0104    1.68    1.72   3.24    61%    59%    1.71    0.74   +0.18%   -0.14%
quality      +0.0111    1.13    1.10   4.21    83%    54%    1.49    0.45   +0.21%   +0.31%
trend        +0.0089    0.44    0.71   4.21   100%    52%    0.48    0.99   +0.28%   -0.24%
mom          +0.0058    0.30    0.38   4.21   100%    54%    0.39    0.19   +0.31%   +0.07%
value        +0.0017    0.12    0.13   4.21    89%    50%   -0.27    0.53   +0.27%   +0.44%
insider      -0.0022   -0.20   -0.19   3.24    22%    56%    0.19   -0.17   -0.15%   +0.08%
vol          -0.0097   -0.41   -0.47   4.21   100%    50%   -0.69   -0.10   -0.21%   +0.59%
activism     -0.0195   -1.63   -1.71   3.24    15%    43%   -1.07   -1.45   -0.65%   -0.08%
```

Composite NW t **1.83**; price-only null model 0.51. Long–short **1.41 gross / 1.02 net**.

The harness reports its own caveats in the output — survivorship gaps, sparse alt-data
coverage, transaction-cost assumptions. **A correction that lowers a t-statistic is
kept.** That has happened repeatedly: fixing the value factor's split basis took the
composite from 2.32 to 1.78, and restoring 13F exit events took it to 1.65. Only one
change all year raised it, and that one was pre-registered from a paper before it ran.

### Evidence-linked research

The research vault is wired into the engine rather than sitting beside it. A note
declares which factors it bears on via `cortex_factors` frontmatter, and first-party
findings carrying a verdict are printed **next to the number they qualify**:

```
KNOWN CAVEATS (first-party findings from the vault):
 congress   fragile — 1.72 raw collapses to 1.13 on a log scale
 fund       structural concern; no change made, pre-registration candidate
 insider    blocked — needs S-coded Form 4 ingestion before the fix is testable
 short      evaluated 2026-08-10 — NW t 1.87, falsifier survived, not promoted
```

A citation rarely changes a decision; a caveat does. The link is synced into DuckDB by
`cortex rag-index`, so writing a note and re-indexing is the entire update path. A
separate local-embedding RAG index (fastembed + DuckDB VSS, no external API) serves
semantic retrieval over the same corpus.

### Executive-mentions signal

A signal the filing-based factors can't see: companies the administration **names in public** (a fact-sheet investment, a press-conference endorsement). The pipeline is precision-first: it sources from official White House transcripts, applies a multi-stage entity matcher to avoid false positives, gates each candidate on its abnormal return vs SPY, and uses Claude Haiku as a final significance classifier — gated to production so local runs never spend tokens. Surfaced in the portal as a "White House Buzz" reaction timeline with per-mention source links and per-row significance glow.

---

## Operations & deployment

Built to run unattended on a single Railway service with data staying fresh on its own:

- **Per-source refresh on independent cadences** — the full refresh runs as an isolated subprocess so a memory-heavy sync can't take down the live web server.
- **Scheduled freshness** — Railway cron services trigger work over HTTP against the volume-owning web process (Railway volumes can only attach to one service). Congress (both chambers) / prices / White House mentions refresh daily; 13F weekly; a factor-stat snapshot nightly; DuckDB backup weekly.
- **Backfill paths separate from incremental sync** — `congress-sync`, `house-sync` and `short-sync` each take a `--backfill-from-year` or `--start`, because an incremental window silently leaves history missing. That exact gap left the congress factor Senate-only for eight years.
- **Visible health** — a `/freshness` endpoint and dashboard strip show each source's staleness; failed sync steps post to a webhook and are recorded, never silently dropped. DuckDB snapshots (Parquet export, pruned, optional S3) guard against corruption.

---

## Engineering quality

- **198 tests** covering the scoring core — discovery composite and rank semantics, swing-screen math, calibration (including edge cases), dedupe-key integrity, thesis CRUD, storage, RAG indexing and retrieval, factor-evidence links, multiple-testing maths, and backtest helpers — plus HTTP-mocked data sources (`respx`). Sync pipelines are integration-tested against parsers, not live EDGAR; coverage is strongest in the decision-making code and thinner in fetch plumbing.
- **Regression tests for the failure modes that actually bit.** Several tests exist because a specific bug shipped and was found later: 13F exit events silently dropped, House transaction codes unparsed, an unquoted YAML wildcard removing notes from the index. Each carries the story in its docstring so the reason survives the fix.
- **A data-integrity audit that checks its own blind spot.** `cortex audit-integrity` reports event yield per source — rows stored versus events actually scored — because every other check was row-level and missed five defects of the shape \"well-formed data the loader cannot read\".
- **Static analysis:** `ruff check` and `ruff format` pass repo-wide. `pyright` (basic) is clean across the factor, storage, and decision core; 25 known errors remain, confined to two third-party-response parsers (`sources/house.py`, `sources/executive.py`) and tracked as type debt.
- **Strict tooling:** `ruff` (format + lint + isort), `pyright` (basic), `uv` lockfile.
- **Typed throughout:** `from __future__ import annotations`, `X | None` unions, dataclasses, Pydantic request models.
- **Idempotent, schema-versioned storage** with a migration table (currently v22). Migrations never carry a `DEFAULT` on `ADD COLUMN` — DuckDB re-applies it on re-run and silently wipes backfilled values.

---

## Security & privacy posture

- **No secrets, no PII in source.** Contact identities, tokens, and machine-specific paths are read from the environment — never hardcoded.
- **No data committed.** The DuckDB store, coverage artefacts, and caches are git-ignored; the repo ships code, not positions or research.
- **Local-only by default.** The server binds `127.0.0.1`; CORS is restricted to the local dev origin; the API is read-mostly with a small typed write surface.
- **Safe subprocess + DB access.** The LLM analysis path invokes the `claude` CLI with argument vectors (no shell string interpolation); all SQL uses parameterised queries.
- **Public data only.** Every external source is a free public disclosure feed (SEC EDGAR, Senate eFD, House Clerk, FINRA Reg SHO) accessed within published rate-limit and fair-access policies. **Zero paid data vendors.**

---

## Disclaimer

CORTEX is a personal research and decision-support tool. It is **not financial advice**, does not execute trades, and makes no recommendations. Nothing here is an offer or solicitation.

---

## License

**Source-available, all rights reserved.** This repository is published for portfolio review and evaluation only. You may read the code; you may **not** copy, modify, reuse, redistribute, or deploy it (in whole or in part) without prior written permission. See [`LICENSE`](LICENSE) for the full terms.

© Rob Savage. All rights reserved.
