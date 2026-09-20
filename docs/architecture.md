# Architecture

Last verified 2026-09-19.

## Shape

One Python process serves everything. There is no queue, no scheduler daemon, no
second database, and no service boundary inside the application.

```
                +----------------------------------------------+
                |  React 19 + Vite + TS portal   (web/)         |
                |  terminal UI, TanStack Query, charts          |
                +-----------------------+----------------------+
                                        |  one origin, port 8000
                +-----------------------+----------------------+
                |  FastAPI service   (src/cortex/api.py)        |
                |  36 routes: typed JSON API + the built SPA    |
                +-----------------------+----------------------+
                                        |
      +--------------+--------------+---+----------+--------------+
      |              |              |              |              |
+-----+-----+  +-----+-----+  +-----+-----+  +-----+-----+  +-----+------+
| composite |  | decision  |  | RAG /     |  | ingestion |  | backtest / |
| + scoring |  | quality   |  | evidence  |  | 14 source |  | pre-reg    |
| discovery |  | theses,   |  | fastembed |  | modules   |  | harness    |
|           |  | calibrat. |  | DuckDB VSS|  |           |  |            |
+-----+-----+  +-----+-----+  +-----+-----+  +-----+-----+  +-----+------+
      |              |              |              |              |
      +--------------+--------------+--------------+--------------+
                                        |
                       +----------------+----------------+
                       |  DuckDB, single file            |
                       |  23 tables, schema v22          |
                       |  + VSS HNSW index on embeddings |
                       +---------------------------------+
```

`cortex serve` mounts the compiled SPA under the same FastAPI app that serves the
API, with a catch-all `GET /{full_path:path}` returning `index.html` for client
routes. On Railway the SPA is rebuilt from source on every deploy, so the served
frontend cannot drift behind the Python API.

## Why one process

The binding constraint is that this is a research tool for one person. There is no
concurrency requirement to design around and no latency budget to hit. The
throughput that matters is how quickly one operator gets from a hypothesis to a
measured t-statistic. Every layer that would exist to serve many users at once is
a layer between the operator and that number, so none of them are here.

The corollary is that the database is embedded. DuckDB runs in the same process,
so the backtest reads 1.56M price rows and 433k 13F rows with no network hop and
no serialisation. The whole store is 188 MB and snapshots to Parquet in one
command. A warehouse would add operational surface and buy nothing at this size.

## Module layout

```
src/cortex/
  api.py               FastAPI app, 36 routes, SPA mount, subprocess job control
  cli.py               argparse entry point, 28 subcommands
  backtest.py          the point-in-time harness: ablation, L/S, deciles, gate
  composite.py         the one composite definition, shared by backtest+discovery
  discovery.py         live ranking over the current universe
  significance.py      BHY / Yekutieli / Bonferroni bar derivation, trial log
  thesis.py            thesis CRUD, falsifiers, review dates
  calibration.py       Brier scores, reliability curve, conviction buckets
  cases.py             auto-built per-ticker bull/risk argument
  evidence.py          vault note to factor links, caveat surfacing
  rag.py               fastembed embeddings, DuckDB VSS retrieval
  audit.py             data-integrity audit, event yield per source
  sync_job.py          orchestrates a full refresh across sources
  volatility_screen.py dollar-swing screen
  mirror.py            regenerates the vault markdown mirror
  backup.py            Parquet snapshot + load.sql
  alerts.py            webhook on sync failure
  config.py            settings, LLM spend gate
  sources/             14 ingestion modules, one per feed
  storage/             db.py (connection), schemas.py (DDL + migrations)
```

`composite.py` is the load-bearing one. Both the backtest and live discovery
import `build_blocks` from it, because a live ranking that diverges from the
tested signal is a bug rather than a feature. The one accepted divergence is
documented in its module docstring: discovery applies a hard 200d-SMA gate before
scoring, so it ranks the 300 to 500 above-trend names rather than the full
eligible cross-section.

## Frontend

React 19, Vite 8, TypeScript, Tailwind 4, TanStack Query for server state,
lightweight-charts for price, Recharts for the calibration diagram, framer-motion
for transitions, lucide-react for icons. Seven routes behind one `Layout`:
dashboard, review queue, swing screen, congress, whales, calibration, new thesis.
Per-ticker detail opens as a modal rather than a route.

The visual language is a terminal instrument panel, not a trading app. See
[design-system.md](design-system.md).

## Deployment

One Railway web service owns the volume and therefore the database. Four cron
services build the same image, own no volume, and call `cortex trigger-*`, which
makes an authenticated HTTP request to the web service. The web service spawns the
real work as a detached subprocess on its own volume.

This is not a preference. A Railway volume attaches to exactly one service, so a
cron service physically cannot open the DuckDB file. The HTTP trigger is the
consequence. Details in [../deploy/README.md](../deploy/README.md) and
[operations.md](operations.md).
