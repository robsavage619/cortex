# CORTEX — Handoff Document
**Updated:** 2026-05-30  
**Next agent:** Pick up Railway deployment — one file to delete and the app is live.

---

## The One Thing To Do First

**Delete `nixpacks.toml`** from the repo root. It was added to try building Node.js on Railway, but we pivoted to committing `web/dist` directly. It's still there and breaking every build.

```bash
cd /Users/robsavage/Projects/savage-wall-street-tracker
rm nixpacks.toml
git add nixpacks.toml
git commit -m "chore: remove nixpacks.toml — dist is committed to git"
git push origin main
```

After that push, Railway redeploys in ~30s and the app loads. Done.

---

## What Is This

CORTEX — Rob's personal factor-model research platform. FastAPI backend + React/Vite frontend.  
Users: Rob + wife Ari.

**Live URL:** https://cortex-production-0783.up.railway.app  
**GitHub:** https://github.com/robsavage619/cortex (branch: `main`)

---

## Current State (as of 2026-05-30)

### Working
- ✅ Railway service Online, healthy Python backend
- ✅ HTTP Basic Auth (rob + ari both have logins)
- ✅ Persistent volume at `/data` (cortex-volume) — DB survives redeploys
- ✅ `CORTEX_AUTH_USERS`, `CORTEX_AUTH_PASS`, `CORTEX_DUCKDB_PATH`, `ANTHROPIC_API_KEY` all set in Railway Variables
- ✅ `web/dist/` built and committed to git (commit `5789c34`) — Railway doesn't need Node.js

### Broken (blocked by `nixpacks.toml`)
- ❌ Every deploy since commit `5789c34` fails at build because `nixpacks.toml` conflicts with the Python-only Nixpacks build
- ❌ App serves `{"detail":"Not Found"}` at `/` because the ACTIVE deployment is an older commit (before `web/dist` was committed)

---

## Railway Project Details

| Field | Value |
|---|---|
| Project | pleasing-tranquility |
| Project ID | `206f3d3c-b0ff-4228-bb76-d8b9bcb9a43e` |
| Service ID | `122894d1-dfa3-4079-a5d3-57d2da39ca96` |
| Environment ID | `48dd1e4a-0d84-46c6-85b3-ac954b5d86f5` |
| Volume | cortex-volume, mounted at `/data` |

### Credentials
- **Rob:** username `rob`, password in Railway Variables (`CORTEX_AUTH_PASS`)
- **Ari:** username `ari`, password `<REDACTED — credential rotated>`
- Both are set via `CORTEX_AUTH_USERS` in Railway Variables

---

## Repo Structure

```
savage-wall-street-tracker/
├── src/cortex/
│   ├── api.py           # FastAPI app — auth, SPA fallback, all routes
│   └── cli.py           # serve subcommand: --host + --port flags
├── web/
│   ├── src/             # React + Vite source
│   └── dist/            # Built frontend — IN GIT (commit 5789c34)
├── railway.json         # NIXPACKS builder, start command
├── nixpacks.toml        # ← DELETE THIS
└── pyproject.toml
```

### How the SPA is served (`api.py` bottom)
```python
_WEB_DIST = Path(__file__).parents[2] / "web" / "dist"
# → /app/web/dist on Railway (exists because dist is in git)

if _WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=_WEB_DIST / "assets"))

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        candidate = (_WEB_DIST / full_path).resolve()
        if candidate.is_relative_to(_WEB_DIST.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_WEB_DIST / "index.html")
```

---

## Future: Keeping the Frontend in Sync

Whenever the React source changes, rebuild before pushing:
```bash
cd web && npm run build && cd ..
git add web/dist/
git commit -m "chore: rebuild frontend"
git push
```

---

## Local Dev

```bash
uv run cortex serve          # backend on :8000
cd web && npm run dev        # frontend on :5173 (proxies API to :8000)
```

## Original Handoff (2026-05-22)
See git history for the full original HANDOFF.md content (task list, stack decisions, etc.).
The React portal, ruff cleanup, and all core features were completed in that session.
