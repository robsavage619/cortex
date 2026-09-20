# Running and operating CORTEX

Last verified 2026-09-19.

CORTEX runs as one FastAPI process that serves both the JSON API and the compiled
React SPA on a single origin. Locally that is `127.0.0.1:8000`. In production it is
one Railway service with a persistent volume, plus four cron services that own no
data and only trigger work over HTTP.

For the Railway cron topology, the per-service env vars, and the schedules, see
[../deploy/README.md](../deploy/README.md). This file covers local development and
the deployment decisions that are easy to undo by accident.

## Local development

```bash
uv run cortex serve          # API + built SPA on :8000
cd web && npm run dev        # Vite dev server on :5173, proxies the API to :8000
```

`uv run cortex serve` binds `127.0.0.1` by default. CORS allows only the two local
Vite origins.

HTTP Basic auth is on when `CORTEX_AUTH_USERS` is set. To bypass it for local
browser work, either run from the `data/` working directory or set
`CORTEX_AUTH_USERS=dev:dev`.

The full CLI is argparse-based with 28 subcommands. `uv run cortex --help` lists
them; `src/cortex/cli.py` is the registry.

## Build topology, do not "fix" this

`nixpacks.toml` at the repo root is live and required. It extends the auto-detected
Python/uv plan, installs Node, and runs `npm --prefix web run build` on every
deploy. `web/dist/` is deliberately not committed. Deleting `nixpacks.toml` or
committing `web/dist/` breaks every build. An older version of the handoff note
said the opposite; following it does not work.

The web service starts from `railway.json`:
`uv run cortex serve --host 0.0.0.0 --port $PORT`, healthcheck `/health`.

The persistent volume `cortex-volume` mounts at `/data`, so DuckDB survives
redeploys. `CORTEX_DUCKDB_PATH` must point inside it. If it does not, the database
is recreated empty on every deploy and nothing says so.

## A refresh runs as a detached subprocess

`POST /refresh` does not do the work in the request handler. It validates the
requested step names against `_SYNC_STEPS`, builds an argv
(`sys.executable -m cortex.cli sync-all --only ...`), and spawns it with
`start_new_session=True`. Two reasons: a sync is memory-heavy enough that the OOM
killer should take the child rather than the web server, and a uvicorn worker
reload should not kill an in-flight sync. Progress is reported through a status
file, read back by `GET /refresh/status`.

## Backfill is a separate path from incremental sync

`congress-sync`, `house-sync` and `short-sync` each take an explicit
`--backfill-from-year` or `--start`. An incremental window silently leaves history
missing, and there is no error when it does. That exact gap left the congress
factor Senate-only for eight years without a single failing check. See
[factor-journal.md](factor-journal.md).

## Credentials

Every credential lives in Railway Variables: `CORTEX_AUTH_USERS`,
`CORTEX_DUCKDB_PATH`, `ANTHROPIC_API_KEY`, `CORTEX_SEC_USER_AGENT` and the optional
`CORTEX_ALERT_WEBHOOK` / `CORTEX_BACKUP_S3_URI`. Nothing is read from a file in the
repo.

**The "because the repo is private" justification has expired.** The predecessor
of this file (`HANDOFF.md`) once contained a plaintext production password. It
was removed on 2026-07-16 and the credential was rotated rather than rewriting
git history, on the stated grounds that the repository was private. As of
2026-09-19 `gh repo view` reports `robsavage619/cortex` as **PUBLIC**, so that
condition no longer holds and the deferred `git filter-repo` purge is now
outstanding rather than conditional.

Scope check run 2026-09-19, for whoever picks this up:

- A pattern scan for secret-shaped assignments across every reachable commit in
  `*.md`, `*.py`, `*.json`, `*.toml`, `*.ts` and `*.tsx` returned only
  `os.environ.get("ANTHROPIC_API_KEY")` and variable references such as
  `password=_auth_pass`. No literal value was found.
- The `HANDOFF.md` blob at `b97afa1` names a Railway variable, not its value.
- `.env` has never been committed and is matched by `.gitignore:151`. The DuckDB
  store and `.coverage` are untracked.

That scan only matches the shapes it was given, so it is evidence rather than a
clearance. The rotated credential is dead either way; the open question is
whether to purge history now that the premise for deferring it is gone.

## Token spend is gated to production

Anthropic API calls (House PTR PDF extraction, executive-mention significance
classification) fire only when `RAILWAY_ENVIRONMENT` or `CORTEX_PRODUCTION` is
present in the environment. Local runs and the test suite never bill the key. For a
deliberate one-off local run, set `CORTEX_ALLOW_LLM=1`. The gate is
`cortex.config.llm_calls_enabled`.

## Observability

- `GET /freshness` reports per-source last success and staleness, also rendered as
  a dashboard strip.
- `GET /factor-history` returns the accumulating factor t-statistic time series,
  written nightly by `cortex snapshot-factors`.
- Failed sync steps post to `CORTEX_ALERT_WEBHOOK` if it is set, and are recorded
  in the `sync_runs` table whether or not it is.
- `cortex backup --keep 7` writes a Parquet snapshot plus a `load.sql` under
  `<volume>/duckdb/backups/<timestamp>/`, pruned to the last N.
