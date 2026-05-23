# WST Handoff — 2026-05-22

## What this project is
Savage Wall Street Tracker — a household investment **decision quality system** (not a signal feed).
DuckDB canonical store, FastAPI backend, React portal (glass-premium), vault markdown mirror.
**Hard rule: zero paid services.**

Plan file: `~/.claude/plans/i-m-hoping-that-you-curried-stream.md`

## Current state — all 42 tests passing

### Done this session
- `src/wst/storage/db.py` — `@contextmanager connect(path, read_only)`
- `src/wst/storage/schemas.py` — `apply_schema()`, DDL for `schema_version`, `theses`, `reviews`, `research_chunks`
- `src/wst/config.py` — refactored: `DUCKDB_PATH`, `WST_DUCKDB_PATH` env override, removed `financialdatasets_api_key`
- `src/wst/thesis.py` — CRUD (`create`, `get`, `list_theses`, `update`, `record_review`) + `ThesisError`
- `src/wst/calibration.py` — Brier score + hit-rate buckets via sklearn
- `src/wst/review.py` — `due_for_review(today)` returns open theses past review_date
- `src/wst/rag.py` — chunking, embedding (fastembed bge-small), DuckDB VSS HNSW index, `retrieve(query, k)`
- `src/wst/sources/market.py` — yfinance `context_for(ticker)` → `PriceContext`
- `src/wst/sources/filings.py` — edgartools `context_for(ticker)` → `FilingsContext`
- `src/wst/mirror.py` — `generate(vault_dir)` writes per-thesis notes + `dashboard.md`
- `src/wst/api.py` — FastAPI: `GET/POST /theses`, `PATCH /theses/{id}`, `POST /theses/{id}/review`, `GET /review-queue`, `GET /calibration`, `GET /context/{ticker}`
- `src/wst/cli.py` — `db-init`, `new`, `review`, `calibration`, `mirror`, `rag-index`, `serve`
- `tests/` — 42 tests, all passing
- `src/wst/signals.py`, `src/wst/watchlist.py`, `src/wst/sources/financialdatasets.py` — deleted
- `.claude/settings.json` — permission allowlist added

### NOT YET done
- **ruff clean** — 6 E501 (line too long) errors remain in:
  - `src/wst/cli.py` lines 54, 72
  - `src/wst/mirror.py` line 97
  - `src/wst/sources/congress.py` line 77
  - `src/wst/sources/filings.py` lines 52, 74
  Run `uv run ruff check src/` to see them. Fix by wrapping or shortening. Then run `uv run pyright src/`.
- **Git commit** — nothing committed yet this session (42 modified/new files)
- **React portal** (`web/`) — not started (Task #12)
- **DESIGN.md** — not written
- **wst-decisions skill + weekly scheduled job** — not started (Task #13)
- **Research backbone ingest** — not started (Task #13)

## Next steps in order

### 1. Fix ruff + commit (5 min)
```bash
uv run ruff check src/   # see the 6 E501s
# fix them (wrap long strings/raises)
uv run ruff check src/ && uv run pyright src/ && uv run pytest
git add -A
git commit -m "feat: decision system core — storage, thesis CRUD, calibration, RAG, API, CLI"
```

### 2. Smoke-test the API
```bash
uv run wst db-init
uv run wst new --ticker AAPL --author rob --conviction 3 \
  --claim "Services margin expands to 40%" \
  --falsifier "Two consecutive quarters below 35%" \
  --review-date 2026-12-01
uv run wst mirror    # check ~/Vault/savage_vault/investing/
uv run wst serve     # curl http://localhost:8000/theses
```

### 3. React portal (Task #12)
```bash
cd /Users/robsavage/Projects/savage-wall-street-tracker
npm create vite@latest web -- --template react-ts
cd web
npm install
npm install -D tailwindcss @tailwindcss/vite
npm install @tanstack/react-query axios lucide-react
npm install lightweight-charts @tremor/react
npm install framer-motion
npx shadcn@latest init
```
Glass-premium tokens (from plan):
- bg `#0A0E1A`
- card `rgba(255,255,255,0.04)` + `backdrop-blur`
- border `rgba(255,255,255,0.08)`
- accent gradient `#22D3EE → #8B5CF6`
- radius `16px`, Inter font, tabular-nums on all figures
- logo.dev free tier for real logos (`VITE_LOGODEV_TOKEN` in `web/.env`), gradient monogram fallback

Views needed: Dashboard, Thesis detail, New Thesis form, Calibration, Review queue.

### 4. wst-decisions skill + schedule (Task #13)
Use `skill-forge` to create `~/.claude/skills/wst-decisions.md` wrapping the CLI.
Use `schedule` skill to set up weekly review-queue nudge.

## Key file locations
```
src/wst/
├── api.py          FastAPI app
├── calibration.py  Brier score / hit-rate
├── cli.py          wst CLI entrypoint
├── config.py       Settings (DUCKDB_PATH, vault_dir)
├── mirror.py       Vault markdown generator
├── rag.py          fastembed + DuckDB VSS
├── review.py       Review queue
├── thesis.py       CRUD + ThesisError
├── sources/
│   ├── congress.py  Senate STOCK Act (free)
│   ├── filings.py   edgartools / SEC (free)
│   └── market.py    yfinance (free)
└── storage/
    ├── db.py        connect() context manager
    └── schemas.py   DDL + apply_schema()
tests/               42 tests, all passing
web/                 (not yet created)
data/duckdb/wst.db   (created by db-init, gitignored)
```

## Commands
```bash
uv run wst db-init
uv run wst new --ticker AAPL --author rob --conviction 3 --claim "..." --falsifier "..." --review-date 2026-12-01
uv run wst review
uv run wst calibration
uv run wst mirror
uv run wst rag-index
uv run wst serve [--port 8000] [--reload]
uv run pytest
uv run ruff check src/
uv run pyright src/
```
