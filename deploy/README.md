# Railway deployment & scheduled data freshness

CORTEX runs as **one web service** (FastAPI + DuckDB on a persistent volume).
Data freshness is driven by **separate Railway cron services** that share the
same repo image but **no volume** — they trigger work over HTTP against the web
service, which owns the DB.

## Why cron triggers over HTTP instead of running the sync directly

A Railway volume can only attach to **one service**. The DuckDB file lives on
the web service's volume, so a cron service cannot open it. Each cron service
therefore runs a tiny `cortex trigger-*` command that makes an authenticated
request to the web app; the web app runs the actual work as an isolated
subprocess on its own volume (the same OOM-safe path the "Sync" button uses).

```
┌─────────────┐   POST /refresh?only=…   ┌────────────────────────┐
│ cron service │ ───────────────────────▶ │ web service (has volume)│
│ (no volume)  │   POST /admin/backup     │  spawns cortex sync-all │
│ exits at end │   POST /admin/snapshot…  │  → DuckDB on volume     │
└─────────────┘                          └────────────────────────┘
```

## One-time setup

### 1. Web service (already deployed)
Uses the root `railway.json`. Required env vars:

| Var | Purpose |
|-----|---------|
| `CORTEX_DUCKDB_PATH` | **Must** point at the mounted volume, e.g. `/data/cortex.db` — otherwise the DB is wiped on every deploy |
| `CORTEX_AUTH_USER` / `CORTEX_AUTH_PASS` | HTTP Basic Auth (also used by cron services to authenticate) |
| `CORTEX_SEC_USER_AGENT` | `"Name email"` — SEC returns 403 without it |
| `CORTEX_ALERT_WEBHOOK` | *(optional)* Discord/Slack webhook; sync failures post here |
| `CORTEX_BACKUP_S3_URI` | *(optional)* off-box backup target, e.g. `s3://bucket/cortex` |
| `ANTHROPIC_API_KEY` | Claude key for House-PDF OCR + executive-mention significance analysis |

> **Token spend is gated to Railway.** Anthropic API calls (House OCR, Haiku
> mention analysis) only fire when `RAILWAY_ENVIRONMENT` or `CORTEX_PRODUCTION`
> is set — so local dev/testing never bills the key. For an intentional one-off
> local LLM run, set `CORTEX_ALLOW_LLM=1`. See `cortex.config.llm_calls_enabled`.

### 2. Cron services (one per file in this directory)
For each `railway.cron.*.json`, add a new service in the **same Railway project**
from the **same repo**, then:

1. **Settings → Config-as-code → Railway Config File** → set the path, e.g.
   `deploy/railway.cron.daily.json`.
2. Set env vars on the cron service:
   - `CORTEX_REFRESH_URL` → the web service URL. Prefer the private network URL
     (`http://${{web.RAILWAY_PRIVATE_DOMAIN}}:8000`) to avoid public egress.
   - `CORTEX_AUTH_USER` / `CORTEX_AUTH_PASS` → same credentials as the web app.
3. Confirm **Settings → Cron Schedule** shows the schedule from the config file.

> The cron service needs **no volume**. It builds the same image, runs the
> trigger command, and exits. Railway skips a run if the previous one is still
> going, and enforces a 5-minute minimum interval. Schedules are UTC.

## Schedules (UTC)

| Config file | Command | Schedule | What it refreshes |
|-------------|---------|----------|-------------------|
| `railway.cron.daily.json` | `trigger-refresh --only congress,discover,volatility,executive` | `0 6 * * *` daily | Congress disclosures, price screens + White House company mentions |
| `railway.cron.funds.json` | `trigger-refresh --only funds` | `0 7 * * 1` Mondays | 13F institutional moves (quarterly data) |
| `railway.cron.factors.json` | `trigger-snapshot` | `0 8 * * *` daily | Factor t-stat history snapshot |
| `railway.cron.backup.json` | `trigger-backup --keep 7` | `0 9 * * 0` Sundays | DuckDB snapshot to the volume |

Adjust cadences to taste — congress/house filings update daily; 13F is quarterly
so weekly is generous; the factor snapshot is cheap signal to watch over time.

## Verifying

- `GET /freshness` → per-source last-success + staleness (also shown in the UI).
- `GET /factor-history` → the accumulating t-stat time series.
- A failed step posts to `CORTEX_ALERT_WEBHOOK` (if set) and is recorded in the
  `sync_runs` table regardless.
- Backups land under `<volume>/duckdb/backups/<timestamp>/` (Parquet + `load.sql`).

## Manual / local equivalents

```bash
uv run cortex sync-all --only congress      # run a subset in-process
uv run cortex snapshot-factors              # record today's factor t-stats
uv run cortex backup --keep 7               # snapshot the local DB
```
