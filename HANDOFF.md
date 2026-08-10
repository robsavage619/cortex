# CORTEX — Handoff Document
**Updated:** 2026-07-16

---

## What Is This

CORTEX — Rob's personal factor-model research platform. FastAPI backend + React/Vite frontend + DuckDB.
Users: Rob + wife Ari.

**Live URL:** https://cortex-production-0783.up.railway.app
**GitHub:** https://github.com/robsavage619/cortex (branch: `main`)

For project context, stack, and hard-won EDGAR lessons see `.claude/CLAUDE.md` and `AGENTS.md`.
For deployment and cron architecture see `deploy/README.md`.

---

## Current Deployment Architecture (do not "fix" this)

- **`nixpacks.toml` at repo root is live and required.** It extends the auto-detected
  Python/uv plan, downloads Node 22.15.0, and builds the SPA (`npm --prefix web run build`)
  on every deploy. `web/dist/` is **NOT** committed to git — do not commit it, do not
  delete `nixpacks.toml`. (An older version of this document said the opposite; that
  approach was abandoned. Following it breaks every build.)
- Web service starts via `railway.json`: `uv run cortex serve --host 0.0.0.0 --port $PORT`,
  healthcheck `/health`.
- Persistent volume `cortex-volume` at `/data` — DuckDB survives redeploys.
- Four Railway cron services hit the web app over HTTP (`cortex trigger-*`); see
  `deploy/railway.cron.*.json` and `deploy/README.md`.

## Credentials

All credentials live in **Railway Variables** (`CORTEX_AUTH_USERS`, `CORTEX_DUCKDB_PATH`,
`ANTHROPIC_API_KEY`, `CORTEX_SEC_USER_AGENT`, …). Never write passwords, tokens, or
project IDs into this repo — this file previously contained a plaintext production
password (removed 2026-07-16; the credential was rotated rather than rewriting git
history, since the repo is private). **If this repo ever goes public, a full
`git filter-repo` history purge is mandatory first.**

---

## Local Dev

```bash
uv run cortex serve          # backend + built SPA on :8000
cd web && npm run dev        # frontend dev server on :5173 (proxies API to :8000)
```

Local auth bypass for browser testing: run from `data/` cwd, or set `CORTEX_AUTH_USERS=dev:dev`.
