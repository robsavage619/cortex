from __future__ import annotations

import base64
import logging
import os
import re
import secrets
import subprocess
import sys
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

import cortex.calibration as cal
import cortex.cases as cases
import cortex.discovery as discovery
import cortex.review as rev
import cortex.thesis as th
from cortex.config import load_settings
from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema

log = logging.getLogger(__name__)

_WEB_DIST = Path(__file__).parents[2] / "web" / "dist"


def _apply_schema_on_startup() -> None:
    try:
        with connect(load_settings().duckdb_path) as conn:
            apply_schema(conn)
    except Exception as exc:
        log.warning("startup: schema apply failed — %s", exc)


_apply_schema_on_startup()

_is_production = bool(
    os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("CORTEX_PRODUCTION")
)

app = FastAPI(
    title="CORTEX — factor research platform",
    version="0.1.0",
    # Disable interactive API docs in production — no reason to expose the schema map.
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

# ── HTTP Basic Auth ───────────────────────────────────────────────────────────
# Supports multiple users via CORTEX_AUTH_USERS="user1:pass1,user2:pass2"
# Falls back to legacy CORTEX_AUTH_USER / CORTEX_AUTH_PASS for single-user.


def _load_credentials() -> dict[str, str]:
    """Return {username: base64(user:pass)} for every authorised user."""
    creds: dict[str, str] = {}
    raw = os.environ.get("CORTEX_AUTH_USERS", "")
    for pair in (p.strip() for p in raw.split(",") if p.strip()):
        if ":" not in pair:
            log.warning(
                "startup: skipping malformed CORTEX_AUTH_USERS entry (no colon)"
            )
            continue
        user, pw = pair.split(":", 1)
        if not pw:
            raise RuntimeError(
                f"CORTEX_AUTH_USERS: password for {user!r} is empty — refusing to start."
            )
        creds[user] = base64.b64encode(f"{user}:{pw}".encode()).decode()
    # Legacy single-user vars
    legacy_user = os.environ.get("CORTEX_AUTH_USER")
    legacy_pass = os.environ.get("CORTEX_AUTH_PASS", "")
    if legacy_user and legacy_user not in creds:
        if not legacy_pass:
            raise RuntimeError(
                "CORTEX_AUTH_USER is set but CORTEX_AUTH_PASS is empty — "
                "refusing to start with a blank password."
            )
        creds[legacy_user] = base64.b64encode(
            f"{legacy_user}:{legacy_pass}".encode()
        ).decode()
    return creds


class _BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, credentials: dict[str, str]) -> None:
        super().__init__(app)
        # Store as a list of encoded tokens for constant-time comparison
        self._tokens: list[str] = list(credentials.values())

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Railway's healthcheck sends no credentials — exempt it, or the probe
        # 401s and Railway marks every deploy unhealthy and won't route traffic.
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        token = auth[6:] if auth.startswith("Basic ") else ""
        if not any(secrets.compare_digest(token, t) for t in self._tokens):
            return Response(
                "Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="CORTEX"'},
            )
        return await call_next(request)


_credentials = _load_credentials()
if _credentials:
    app.add_middleware(_BasicAuthMiddleware, credentials=_credentials)
    log.info("startup: HTTP Basic Auth enabled for users: %s", list(_credentials))
elif _is_production:
    log.warning(
        "startup: no auth credentials set — app is running without authentication. "
        "Set CORTEX_AUTH_USERS or CORTEX_AUTH_USER + CORTEX_AUTH_PASS."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

_BANNER = "Decision tool — not financial advice."


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for Railway. Auth-exempt; no DB or network I/O so it
    stays fast and green even while a sync is hammering the volume."""
    return {"status": "ok"}


# In-memory cache for the expensive CAR daily series (yfinance download).
# {signal: (unix_ts, serialised_list)}
_car_series_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CAR_CACHE_TTL = 86400.0  # 24 hours


def _db() -> Path:
    return load_settings().duckdb_path


# ── "Sync all data" job (out-of-process) ─────────────────────────────────────
# The refresh is memory-heavy (yfinance/pandas over ~500 tickers). Running it
# in the web process means an OOM there kills the live site. So we spawn it as
# an isolated subprocess (`cortex sync-all`); the OS OOM-killer targets that
# process and the server keeps serving. Status crosses the process boundary via
# a JSON file on the volume (see cortex.sync_job).

_refresh_lock = threading.Lock()


def _status_path() -> Path:
    from cortex.sync_job import default_status_path

    return default_status_path(_db())


_SYNC_STEPS = ("congress", "funds", "discover", "volatility")


@app.post("/refresh")
def refresh(only: str | None = None) -> dict[str, Any]:
    """Spawn the data refresh as an isolated subprocess.

    ``only`` is an optional comma-separated subset of sync steps, used by the
    per-source Railway cron services (e.g. ``?only=congress``). Values are
    validated against the known step names before reaching the subprocess argv.
    """
    from cortex.sync_job import initial_state, read_status, write_status

    requested = [s.strip() for s in only.split(",")] if only else []
    invalid = [s for s in requested if s not in _SYNC_STEPS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"unknown sync steps: {invalid}")

    status_path = _status_path()
    with _refresh_lock:
        current = read_status(status_path)
        if current.get("running"):
            return {"banner": _BANNER, "status": "already_running", **current}
        # Seed a running status before returning so the next status poll
        # reflects the in-flight run immediately (no stale "done" flicker).
        state = initial_state()
        if requested:
            state["steps"] = {s: "queued" for s in _SYNC_STEPS if s in requested}
        write_status(status_path, state)
        argv = [sys.executable, "-m", "cortex.cli", "sync-all"]
        if requested:
            argv += ["--only", ",".join(requested)]
        try:
            # start_new_session detaches the child so a uvicorn worker reload
            # doesn't kill an in-flight sync. It runs to completion independently
            # and reports progress through the status file.
            subprocess.Popen(  # noqa: S603 - argv validated against _SYNC_STEPS
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:  # noqa: BLE001 - surface spawn failure visibly
            state["running"] = False
            state["error"] = f"failed to start sync: {exc}"
            write_status(status_path, state)
            return {"banner": _BANNER, "status": "error", **state}
    return {"banner": _BANNER, "status": "started", **state}


@app.get("/refresh/status")
def refresh_status() -> dict[str, Any]:
    from cortex.sync_job import read_status

    return {"banner": _BANNER, **read_status(_status_path())}


@app.get("/freshness")
def freshness() -> dict[str, Any]:
    """Per-source data freshness: when each source last synced and whether it's
    stale. Powers the freshness indicator and surfaces silent cron failures."""
    from cortex.sync_job import read_freshness

    return {"banner": _BANNER, "sources": read_freshness(_db())}


@app.get("/factor-history")
def factor_history(factor: str | None = None) -> dict[str, Any]:
    """Time series of factor t-stats from nightly snapshots — watch the congress
    and fund factors drift toward the t≥3.0 pre-registration bar."""
    from cortex.storage.db import connect

    clause = "WHERE factor = ?" if factor else ""
    params = [factor] if factor else []
    try:
        with connect(_db(), read_only=True) as conn:
            rows = conn.execute(
                f"""
                SELECT snapshot_date, factor, ic_mean, ic_tstat, ic_tstat_nw,
                       coverage, n_months
                FROM factor_history {clause}
                ORDER BY snapshot_date ASC, factor ASC
                """,
                params,
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - degrade visibly, never 500
        return {"banner": _BANNER, "points": [], "error": str(exc)}
    return {
        "banner": _BANNER,
        "points": [
            {
                "snapshot_date": d.isoformat(),
                "factor": f,
                "ic_mean": im,
                "ic_tstat": it,
                "ic_tstat_nw": itn,
                "coverage": cov,
                "n_months": n,
            }
            for d, f, im, it, itn, cov, n in rows
        ],
    }


@app.post("/admin/snapshot-factors")
def admin_snapshot_factors() -> dict[str, Any]:
    """Spawn `cortex snapshot-factors` as an isolated subprocess.

    The backtest pulls S&P 500 prices through yfinance/numpy and is memory-heavy
    — same OOM hazard as a sync — so it runs detached like /refresh rather than
    in the web worker. Triggered nightly by a Railway cron service."""
    argv = [sys.executable, "-m", "cortex.cli", "snapshot-factors"]
    try:
        subprocess.Popen(  # noqa: S603 - fixed argv, no shell, no user input
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001 - surface spawn failure visibly
        raise HTTPException(
            status_code=500, detail=f"failed to start snapshot: {exc}"
        ) from exc
    return {"banner": _BANNER, "status": "started"}


@app.post("/admin/backup")
def admin_backup(keep: int = 7) -> dict[str, Any]:
    """Snapshot the DuckDB to the volume. Triggered by the weekly backup cron
    service (the volume-owning web process must do this, not the cron box)."""
    from cortex.backup import prune_backups, run_backup

    try:
        dest = run_backup(_db(), keep=keep)
        removed = prune_backups(_db(), keep=keep)
    except Exception as exc:  # noqa: BLE001 - surface failure to the caller
        raise HTTPException(status_code=500, detail=f"backup failed: {exc}") from exc
    return {"banner": _BANNER, "snapshot": str(dest), "pruned": removed}


# ── request / response models ────────────────────────────────────────────────


class ThesisIn(BaseModel):
    tickers: list[str]
    author: str
    conviction: int
    claim: str
    falsifier: str
    review_date: date
    reasoning: str | None = None
    evidence: list[str] = []
    entry_price: float | None = None
    entry_date: date | None = None
    base_rate: str | None = None
    pre_mortem: str | None = None
    change_my_mind: str | None = None
    sizing_rationale: str | None = None
    why_now: str | None = None
    cooling_off_hours: int | None = None

    @field_validator("conviction")
    @classmethod
    def _check_conviction(cls, v: int) -> int:
        if v not in range(1, 6):
            raise ValueError("conviction must be 1–5")
        return v


class ThesisPatch(BaseModel):
    status: str | None = None
    reasoning: str | None = None
    evidence: list[str] | None = None
    entry_price: float | None = None
    entry_date: date | None = None


class ReviewIn(BaseModel):
    outcome: str
    decision_quality: str | None = None
    note: str | None = None
    reviewed_on: date | None = None


class DissentIn(BaseModel):
    author: str
    stance: str
    conviction: int | None = None
    note: str | None = None


class PriorsIn(BaseModel):
    query: str
    k: int = 3


def _thesis_out(t: th.Thesis) -> dict[str, Any]:
    return {
        "id": t.id,
        "tickers": t.tickers,
        "author": t.author,
        "opened": t.opened.isoformat(),
        "conviction": t.conviction,
        "claim": t.claim,
        "falsifier": t.falsifier,
        "reasoning": t.reasoning,
        "evidence": t.evidence,
        "review_date": t.review_date.isoformat(),
        "status": t.status,
        "entry_price": t.entry_price,
        "entry_date": t.entry_date.isoformat() if t.entry_date else None,
        "base_rate": t.base_rate,
        "pre_mortem": t.pre_mortem,
        "change_my_mind": t.change_my_mind,
        "sizing_rationale": t.sizing_rationale,
        "why_now": t.why_now,
        "activate_at": t.activate_at.isoformat() if t.activate_at else None,
        "created_at": t.created_at.isoformat(),
    }


def _candidate_out(c: discovery.Candidate) -> dict[str, Any]:
    return {
        "ticker": c.ticker,
        "as_of_date": c.as_of_date.isoformat(),
        "discovered_at": c.discovered_at.isoformat(),
        "momentum_12_1": c.momentum_12_1,
        "vol_252d": c.vol_252d,
        "sharpe_12m": c.sharpe_12m,
        "above_200d_sma": c.above_200d_sma,
        "earnings_yield": c.earnings_yield,
        "roe": c.roe,
        "z_momentum": c.z_momentum,
        "z_low_vol": c.z_low_vol,
        "z_sharpe": c.z_sharpe,
        "z_value": c.z_value,
        "z_quality": c.z_quality,
        "composite_score": c.composite_score,
        "composite_rank": c.composite_rank,
    }


def _volstock_out(s: Any) -> dict[str, Any]:
    return {
        "ticker": s.ticker,
        "as_of_date": s.as_of_date.isoformat(),
        "computed_at": s.computed_at.isoformat(),
        "lookback_days": s.lookback_days,
        "avg_dollar_range": s.avg_dollar_range,
        "range_consistency": s.range_consistency,
        "avg_range_pct": s.avg_range_pct,
        "avg_close": s.avg_close,
        "oscillation_score": s.oscillation_score,
        "net_drift_pct": s.net_drift_pct,
        "range_position": s.range_position,
        "direction_changes": s.direction_changes,
        "avg_volume": s.avg_volume,
        "swing_score": s.swing_score,
        "rank": s.rank,
        "company_name": s.company_name,
        "max_range_pct": s.max_range_pct,
        "max_dollar_range": s.max_dollar_range,
    }


def _dissent_out(d: th.Dissent) -> dict[str, Any]:
    return {
        "id": d.id,
        "thesis_id": d.thesis_id,
        "author": d.author,
        "stance": d.stance,
        "conviction": d.conviction,
        "note": d.note,
        "created_at": d.created_at.isoformat(),
    }


# ── routes ───────────────────────────────────────────────────────────────────


@app.get("/api")
def root() -> dict[str, str]:
    return {"banner": _BANNER}


@app.get("/theses")
def get_theses(author: str | None = None, status: str | None = None) -> dict[str, Any]:
    theses = th.list_theses(author=author, status=status, db_path=_db())
    return {"banner": _BANNER, "theses": [_thesis_out(t) for t in theses]}


@app.get("/theses/{thesis_id}")
def get_thesis(thesis_id: str) -> dict[str, Any]:
    try:
        t = th.get(thesis_id, db_path=_db())
        dissents = th.list_dissents(thesis_id, db_path=_db())
    except th.ThesisError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "banner": _BANNER,
        "thesis": _thesis_out(t),
        "dissents": [_dissent_out(d) for d in dissents],
    }


@app.post("/theses", status_code=201)
def post_thesis(body: ThesisIn) -> dict[str, Any]:
    activate_at: datetime | None = None
    if body.cooling_off_hours:
        activate_at = datetime.now(tz=UTC) + timedelta(hours=body.cooling_off_hours)
    try:
        t = th.create(
            tickers=body.tickers,
            author=body.author,
            conviction=body.conviction,
            claim=body.claim,
            falsifier=body.falsifier,
            review_date=body.review_date,
            reasoning=body.reasoning,
            evidence=body.evidence,
            entry_price=body.entry_price,
            entry_date=body.entry_date,
            base_rate=body.base_rate,
            pre_mortem=body.pre_mortem,
            change_my_mind=body.change_my_mind,
            sizing_rationale=body.sizing_rationale,
            why_now=body.why_now,
            activate_at=activate_at,
            db_path=_db(),
        )
    except th.ThesisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _maybe_mirror()
    return {"banner": _BANNER, "thesis": _thesis_out(t)}


@app.patch("/theses/{thesis_id}")
def patch_thesis(thesis_id: str, body: ThesisPatch) -> dict[str, Any]:
    try:
        t = th.update(
            thesis_id,
            status=body.status,
            reasoning=body.reasoning,
            evidence=body.evidence,
            entry_price=body.entry_price,
            entry_date=body.entry_date,
            db_path=_db(),
        )
    except th.ThesisError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _maybe_mirror()
    return {"banner": _BANNER, "thesis": _thesis_out(t)}


@app.post("/theses/{thesis_id}/review", status_code=201)
def post_review(thesis_id: str, body: ReviewIn) -> dict[str, str]:
    try:
        th.record_review(
            thesis_id,
            outcome=body.outcome,
            decision_quality=body.decision_quality,
            note=body.note,
            reviewed_on=body.reviewed_on,
            db_path=_db(),
        )
    except th.ThesisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _maybe_mirror()
    return {"status": "recorded"}


@app.post("/theses/{thesis_id}/activate", status_code=200)
def activate_thesis(thesis_id: str) -> dict[str, Any]:
    try:
        t = th.activate(thesis_id, db_path=_db())
    except th.ThesisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _maybe_mirror()
    return {"banner": _BANNER, "thesis": _thesis_out(t)}


@app.post("/theses/{thesis_id}/dissents", status_code=201)
def post_dissent(thesis_id: str, body: DissentIn) -> dict[str, Any]:
    try:
        d = th.add_dissent(
            thesis_id,
            author=body.author,
            stance=body.stance,
            conviction=body.conviction,
            note=body.note,
            db_path=_db(),
        )
    except th.ThesisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"banner": _BANNER, "dissent": _dissent_out(d)}


@app.get("/review-queue")
def review_queue() -> dict[str, Any]:
    theses = rev.due_for_review(db_path=_db())
    return {"banner": _BANNER, "due": [_thesis_out(t) for t in theses]}


@app.get("/calibration")
def calibration() -> dict[str, Any]:
    report = cal.compute(db_path=_db())
    return {
        "banner": _BANNER,
        "brier_score": report.brier_score,
        "overconfident": report.overconfident,
        "process_score": report.process_score,
        "decision_counts": report.decision_counts,
        "trend": [{"date": p.date, "brier": p.brier} for p in report.trend],
        "buckets": [
            {
                "conviction": b.conviction,
                "total": b.total,
                "correct": b.correct,
                "hit_rate": b.hit_rate,
            }
            for b in report.buckets
        ],
        "per_author": report.per_author,
    }


@app.get("/digest")
def digest() -> dict[str, Any]:
    """Weekly-ritual digest: what's due, calibration drift, oldest unreviewed."""
    db = _db()
    due = rev.due_for_review(db_path=db)
    open_theses = th.list_theses(status="open", db_path=db)
    pending = th.list_theses(status="pending", db_path=db)
    oldest = sorted(open_theses, key=lambda t: t.opened)[:3]
    report = cal.compute(db_path=db)
    return {
        "banner": _BANNER,
        "due": [_thesis_out(t) for t in due],
        "pending": [_thesis_out(t) for t in pending],
        "oldest_open": [_thesis_out(t) for t in oldest],
        "open_count": len(open_theses),
        "brier_score": report.brier_score,
        "process_score": report.process_score,
        "overconfident": report.overconfident,
    }


@app.post("/research/priors")
def research_priors(body: PriorsIn) -> dict[str, Any]:
    """Surface relevant research chunks for a claim at decision time."""
    from cortex.rag import retrieve

    try:
        chunks = retrieve(body.query, k=body.k, db_path=_db())
    except Exception as exc:  # noqa: BLE001 - degrade visibly, never block writing
        return {"banner": _BANNER, "priors": [], "error": str(exc)}
    return {
        "banner": _BANNER,
        "priors": [
            {
                "wikilink": c.wikilink,
                "tier": c.tier,
                "text": c.text,
            }
            for c in chunks
        ],
    }


@app.get("/context/{ticker}")
def context(ticker: str, response: Response) -> dict[str, Any]:
    from cortex.sources.congress import list_trades, recent_window
    from cortex.sources.market import MarketSourceError
    from cortex.sources.market import context_for as market_ctx

    response.headers["Cache-Control"] = "private, max-age=900"
    result: dict[str, Any] = {"banner": _BANNER, "ticker": ticker.upper()}

    try:
        mkt = market_ctx(ticker)
        result["market"] = {
            "price": mkt.price,
            "day_change_percent": mkt.day_change_percent,
            "week_52_high": mkt.week_52_high,
            "week_52_low": mkt.week_52_low,
            "market_cap": mkt.market_cap,
            "pe_ratio": mkt.pe_ratio,
            "news_headlines": mkt.news_headlines,
            "news_urls": mkt.news_urls,
            "company_name": mkt.company_name,
            "website": mkt.website,
        }
    except MarketSourceError as exc:
        result["market_error"] = str(exc)

    try:
        trades = list_trades(_db(), ticker=ticker, since=recent_window(365), limit=10)
        result["congress_trades"] = [
            {
                "senator": t.senator,
                "chamber": t.chamber,
                "transaction_type": t.transaction_type,
                "amount": t.amount,
                "transaction_date": (
                    t.transaction_date.isoformat() if t.transaction_date else None
                ),
            }
            for t in trades
        ]
    except Exception as exc:  # noqa: BLE001 - degrade visibly, never block context
        result["congress_trades_error"] = str(exc)

    try:
        from cortex.sources.insiders import list_insider_buys

        buys = list_insider_buys(_db(), ticker=ticker, limit=10)
        result["insider_buys"] = [
            {
                "filer_name": b.filer_name,
                "filer_role": b.filer_role,
                "transaction_date": (
                    b.transaction_date.isoformat() if b.transaction_date else None
                ),
                "shares": b.shares,
                "value_usd": b.value_usd,
            }
            for b in buys
        ]
    except Exception as exc:  # noqa: BLE001
        result["insider_buys_error"] = str(exc)

    try:
        from cortex.sources.activism import list_activism_events

        stakes = list_activism_events(_db(), ticker=ticker, limit=10)
        result["activist_stakes"] = [
            {
                "filer": s.filer,
                "filing_date": (s.filing_date.isoformat() if s.filing_date else None),
            }
            for s in stakes
        ]
    except Exception as exc:  # noqa: BLE001
        result["activist_stakes_error"] = str(exc)

    try:
        from cortex.sources.executive import list_mentions

        mentions = list_mentions(_db(), ticker=ticker, limit=10)
        result["executive_mentions"] = [
            {
                "speaker": m.speaker,
                "mention_date": m.mention_date.isoformat(),
                "source_type": m.source_type,
                "source_url": m.source_url,
                "quote": m.quote,
                "stance": m.stance,
            }
            for m in mentions
        ]
    except Exception as exc:  # noqa: BLE001
        result["executive_mentions_error"] = str(exc)

    return result


@app.get("/context/{ticker}/history")
def price_history(
    ticker: str, response: Response, period: str = "6mo"
) -> dict[str, Any]:
    from cortex.sources.market import MarketSourceError, history_for

    response.headers["Cache-Control"] = "private, max-age=900"
    try:
        bars = history_for(ticker, period=period)
    except MarketSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "banner": _BANNER,
        "ticker": ticker.upper(),
        "period": period,
        "bars": [
            {
                "date": b.date,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ],
    }


@app.get("/congress/stats")
def get_congress_stats(days: int = 365) -> dict[str, Any]:
    """Aggregated Congress-trade analytics (Senate + House) over a trailing window."""
    from cortex.sources.congress import congress_stats
    from cortex.sources.legislators import photo_url_for

    stats = congress_stats(_db(), days=days)
    for m in stats.get("top_members", []):
        m["photo_url"] = photo_url_for(m["senator"])
    return {"banner": _BANNER, "days": days, **stats}


@app.get("/congress")
def get_congress(
    ticker: str | None = None, days: int = 120, limit: int = 100
) -> dict[str, Any]:
    """Recent Congress trades (Senate + House) from the local mirror."""
    from cortex.sources.congress import list_trades, recent_window
    from cortex.sources.legislators import photo_url_for

    trades = list_trades(_db(), ticker=ticker, since=recent_window(days), limit=limit)
    return {
        "banner": _BANNER,
        "ticker": ticker.upper() if ticker else None,
        "count": len(trades),
        "trades": [
            {
                "senator": t.senator,
                "chamber": t.chamber,
                "photo_url": photo_url_for(t.senator),
                "ticker": t.ticker,
                "transaction_type": t.transaction_type,
                "amount": t.amount,
                "transaction_date": (
                    t.transaction_date.isoformat() if t.transaction_date else None
                ),
                "disclosure_date": (
                    t.disclosure_date.isoformat() if t.disclosure_date else None
                ),
                "asset_description": t.asset_description,
                "report_url": t.report_url,
            }
            for t in trades
        ],
    }


@app.get("/congress/member")
def get_congress_member(name: str, days: int = 730) -> dict[str, Any]:
    """Full trade profile for a single Congress member."""
    from collections import defaultdict

    from cortex.sources.legislators import member_info_for
    from cortex.storage.db import connect

    info = member_info_for(name) or {}
    since = __import__("datetime").date.today() - __import__("datetime").timedelta(
        days=days
    )

    # The DB may store names with an "Hon." prefix (House filings) or without.
    # Try the canonical name from legislators first, then the raw query name,
    # then a LIKE fallback on last name so we always get the right rows.
    canonical = info.get("name", name)
    last_name = (info.get("last") or name.split()[-1]).replace("'", "''")

    with connect(_db(), read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT ticker, transaction_type, amount, transaction_date,
                   disclosure_date, asset_description, report_url
            FROM congress_trades
            WHERE (senator = ? OR senator = ? OR senator ILIKE ?)
              AND COALESCE(disclosure_date, transaction_date) >= ?
            ORDER BY COALESCE(disclosure_date, transaction_date) DESC NULLS LAST
            """,
            [canonical, name, f"%{last_name}%", since],
        ).fetchall()

    # ── amount midpoint (reuse congress.py logic inline) ──────────────────────
    _num_re = re.compile(r"\$?\s*([\d,]+)")

    def midpoint(amount: str | None) -> float:
        nums = [
            float(x.replace(",", ""))
            for x in _num_re.findall(amount or "")
            if x.replace(",", "").isdigit()
        ]
        if not nums:
            return 0.0
        return nums[0] if len(nums) == 1 else (nums[0] + nums[1]) / 2.0

    def sign(tx: str) -> int:
        t = (tx or "").lower().strip()
        if "purchase" in t or t == "p" or t.startswith("p "):
            return 1
        if (
            "sale" in t
            or "sell" in t
            or t == "s"
            or t.startswith("s ")
            or t.startswith("s (")
        ):
            return -1
        return 0

    trades_out = []
    timeline: dict[str, dict[str, float]] = defaultdict(
        lambda: {"buys": 0, "sells": 0, "buy_notional": 0.0, "sell_notional": 0.0}
    )
    by_ticker: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "buys": 0,
            "sells": 0,
            "buy_notional": 0.0,
            "sell_notional": 0.0,
            "last_date": None,
        }
    )
    total_buys = total_sells = 0
    buy_notional = sell_notional = 0.0
    lags: list[int] = []

    for ticker, tx_type, amount, tx_date, disc_date, asset_desc, report_url in rows:
        s = sign(tx_type)
        n = midpoint(amount)
        when = disc_date or tx_date
        month = when.strftime("%Y-%m") if when else "unknown"

        if s > 0:
            total_buys += 1
            buy_notional += n
            timeline[month]["buys"] += 1
            timeline[month]["buy_notional"] += n
            by_ticker[ticker]["buys"] += 1
            by_ticker[ticker]["buy_notional"] += n
        elif s < 0:
            total_sells += 1
            sell_notional += n
            timeline[month]["sells"] += 1
            timeline[month]["sell_notional"] += n
            by_ticker[ticker]["sells"] += 1
            by_ticker[ticker]["sell_notional"] += n

        if by_ticker[ticker]["last_date"] is None or (
            when and when > by_ticker[ticker]["last_date"]
        ):
            by_ticker[ticker]["last_date"] = when

        if tx_date and disc_date:
            lag = (disc_date - tx_date).days
            if 0 <= lag <= 365:
                lags.append(lag)

        trades_out.append(
            {
                "ticker": ticker,
                "transaction_type": tx_type,
                "amount": amount,
                "transaction_date": tx_date.isoformat() if tx_date else None,
                "disclosure_date": disc_date.isoformat() if disc_date else None,
                "lag_days": (disc_date - tx_date).days
                if tx_date and disc_date
                else None,
                "asset_description": asset_desc,
                "report_url": report_url or "",
            }
        )

    top_tickers = sorted(
        [
            {
                "ticker": t,
                "buys": int(v["buys"]),
                "sells": int(v["sells"]),
                "buy_notional": round(v["buy_notional"], 2),
                "sell_notional": round(v["sell_notional"], 2),
                "net_notional": round(v["buy_notional"] - v["sell_notional"], 2),
                "last_date": v["last_date"].isoformat() if v["last_date"] else None,
            }
            for t, v in by_ticker.items()
        ],
        key=lambda r: abs(r["net_notional"]),
        reverse=True,
    )[:20]

    timeline_out = [
        {
            "month": m,
            **{k: round(v, 2) if isinstance(v, float) else v for k, v in vals.items()},
        }
        for m, vals in sorted(timeline.items())
        if m != "unknown"
    ]

    median_lag = int(sorted(lags)[len(lags) // 2]) if lags else None

    return {
        "banner": _BANNER,
        "member": {
            "name": info.get("name", name),
            "photo_url": info.get("photo_url"),
            "party": info.get("party", ""),
            "state": info.get("state", ""),
            "district": info.get("district"),
            "chamber": info.get("chamber", ""),
            "gender": info.get("gender", ""),
        },
        "totals": {
            "trades": total_buys + total_sells,
            "buys": total_buys,
            "sells": total_sells,
            "buy_notional": round(buy_notional, 2),
            "sell_notional": round(sell_notional, 2),
            "tickers": len(by_ticker),
            "median_lag_days": median_lag,
        },
        "timeline": timeline_out,
        "top_tickers": top_tickers,
        "trades": trades_out,
    }


@app.get("/funds")
def get_funds(
    ticker: str | None = None, actions: str = "NEW,ADD", limit: int = 100
) -> dict[str, Any]:
    """Institutional 13F moves from the local mirror (`cortex funds-sync`)."""
    from cortex.sources.funds import list_fund_moves

    action_tuple = tuple(a.strip().upper() for a in actions.split(",") if a.strip())
    moves = list_fund_moves(_db(), ticker=ticker, actions=action_tuple, limit=limit)
    return {
        "banner": _BANNER,
        "ticker": ticker.upper() if ticker else None,
        "count": len(moves),
        "moves": [
            {
                "manager": m.manager,
                "ticker": m.ticker,
                "issuer": m.issuer,
                "action": m.action,
                "shares": m.shares,
                "prev_shares": m.prev_shares,
                "value": m.value,
                "pct_change": m.pct_change,
                "period": m.period.isoformat() if m.period else None,
            }
            for m in moves
        ],
    }


@app.get("/executive")
def get_executive(ticker: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Executive-branch company mentions — market-moving public statements."""
    from cortex.sources.executive import list_mentions

    mentions = list_mentions(_db(), ticker=ticker, limit=limit)
    return {
        "banner": _BANNER,
        "ticker": ticker.upper() if ticker else None,
        "count": len(mentions),
        "mentions": [
            {
                "ticker": m.ticker,
                "speaker": m.speaker,
                "mention_date": m.mention_date.isoformat(),
                "source_type": m.source_type,
                "source_url": m.source_url,
                "quote": m.quote,
                "stance": m.stance,
                "meaningful": m.meaningful,
                "significance": m.significance,
                "analysis": m.analysis,
                "abn_1d": m.abn_1d,
                "abn_5d": m.abn_5d,
                "abn_20d": m.abn_20d,
            }
            for m in mentions
        ],
    }


@app.get("/candidates")
def get_candidates() -> dict[str, Any]:
    candidates = discovery.list_candidates(_db())
    return {
        "banner": _BANNER,
        "candidates": [_candidate_out(c) for c in candidates],
        "last_run": candidates[0].discovered_at.isoformat() if candidates else None,
        "count": len(candidates),
    }


@app.get("/screen/volatility")
def get_volatility_screen() -> dict[str, Any]:
    """The swing screen — stocks with large, consistent daily dollar swings."""
    from cortex.volatility_screen import list_volatility_screen

    stocks = list_volatility_screen(_db())
    return {
        "banner": _BANNER,
        "stocks": [_volstock_out(s) for s in stocks],
        "last_run": stocks[0].computed_at.isoformat() if stocks else None,
        "lookback_days": stocks[0].lookback_days if stocks else None,
        "count": len(stocks),
    }


@app.get("/candidates/{ticker}")
def get_candidate(ticker: str) -> dict[str, Any]:
    """Return the CORTEX factor breakdown for a single ticker, if discovered."""
    tk = ticker.upper()
    match = next((c for c in discovery.list_candidates(_db()) if c.ticker == tk), None)
    return {
        "banner": _BANNER,
        "ticker": tk,
        "candidate": _candidate_out(match) if match else None,
    }


# Plain-English framework backing for each CORTEX factor, grounded in the vault.
_FACTOR_QUERIES: dict[str, str] = {
    "momentum": (
        "12-1 month price momentum factor cross-sectional returns Jegadeesh Titman"
    ),
    "low_vol": "low volatility anomaly betting against beta low risk high return",
    "sharpe": "risk-adjusted return Sharpe ratio trend following time-series momentum",
    "value": (
        "value factor earnings yield cheap stocks book-to-market EBIT enterprise value"
    ),
    "quality": (
        "quality factor profitability ROE gross profitability quality-minus-junk Piotroski"  # noqa: E501
    ),
}


def _case_point_out(p: cases.CasePoint) -> dict[str, Any]:
    return {
        "factor": p.factor,
        "label": p.label,
        "z": p.z,
        "stat": p.stat,
        "argument": p.argument,
        "citation": p.citation,
        "citation_text": p.citation_text,
    }


@app.get("/candidates/{ticker}/case")
def get_case(ticker: str) -> dict[str, Any]:
    """Return the auto-built investment case for a discovered ticker."""
    case = cases.build_case(ticker, db_path=_db())
    if case is None:
        return {"banner": _BANNER, "ticker": ticker.upper(), "case": None}
    return {
        "banner": _BANNER,
        "ticker": case.ticker,
        "case": {
            "ticker": case.ticker,
            "composite_score": case.composite_score,
            "composite_rank": case.composite_rank,
            "suggested_conviction": case.suggested_conviction,
            "trend_ok": case.trend_ok,
            "headline": case.headline,
            "summary": case.summary,
            "bull_points": [_case_point_out(p) for p in case.bull_points],
            "risk_points": [_case_point_out(p) for p in case.risk_points],
            "falsifier": case.falsifier,
        },
    }


@app.get("/research/ticker/{ticker}")
def research_ticker(ticker: str, k: int = 2) -> dict[str, Any]:
    """Surface vault research that explains why each CORTEX factor matters.

    Returns one short research snippet per factor (momentum, low-vol, sharpe,
    value, quality) drawn from the indexed wiki via semantic retrieval.
    """
    from cortex.rag import retrieve

    by_factor: dict[str, list[dict[str, Any]]] = {}
    error: str | None = None
    for factor, query in _FACTOR_QUERIES.items():
        try:
            chunks = retrieve(query, k=k, db_path=_db())
        except Exception as exc:  # noqa: BLE001 - degrade visibly
            error = str(exc)
            chunks = []
        by_factor[factor] = [
            {"wikilink": c.wikilink, "tier": c.tier, "text": c.text} for c in chunks
        ]
    return {
        "banner": _BANNER,
        "ticker": ticker.upper(),
        "by_factor": by_factor,
        "error": error,
    }


def _reason_trend(price: float | None, change: float | None) -> str | None:
    if price is None:
        return None
    chg = change or 0.0
    direction = "gaining" if chg > 0 else "sliding"
    mag = abs(chg)
    if mag > 3:
        strength = "sharply"
    elif mag > 1:
        strength = "meaningfully"
    else:
        strength = "modestly"
    return (
        f"Trading at ${price:,.2f}, {direction} {strength} at {chg:+.2f}% today. "
        f"{'Buyers are in control intraday.' if chg >= 0 else 'Sellers have the upper hand intraday.'}"
    )


def _reason_rsi(rsi: float | None) -> str | None:
    if rsi is None:
        return None
    if rsi >= 70:
        return (
            f"RSI at {rsi:.0f} — firmly overbought. The move has been fast; "
            f"short-term mean-reversion risk is elevated. Not a sell signal, but chasing here carries a poor risk/reward."
        )
    if rsi >= 60:
        return (
            f"RSI at {rsi:.0f} — strong momentum without being stretched. "
            f"Buyers are pressing but the reading is not yet a caution flag."
        )
    if rsi >= 40:
        return (
            f"RSI at {rsi:.0f} — neutral. Neither side has clear momentum dominance. "
            f"Wait for a decisive move in either direction before adding conviction."
        )
    if rsi >= 30:
        return (
            f"RSI at {rsi:.0f} — weak momentum. Selling has outpaced buying recently. "
            f"Worth watching for stabilization before building a position."
        )
    return (
        f"RSI at {rsi:.0f} — oversold. The stock has been aggressively sold. "
        f"Bounces are possible but verify the catalyst before acting — oversold can stay oversold."
    )


def _reason_pe(pe: float | None) -> str | None:
    if pe is None or pe <= 0:
        return None
    if pe > 60:
        return (
            f"At {pe:.1f}×, the market is pricing in exceptional, sustained growth. "
            f"Any disappointment on earnings or guidance tends to compress multiples fast — execution risk is high."
        )
    if pe > 35:
        return (
            f"At {pe:.1f}×, this is a premium multiple — meaningful above the ~21× S&P average. "
            f"Justified only if growth is durable; re-rates quickly if momentum stalls."
        )
    if pe > 20:
        return (
            f"At {pe:.1f}×, a modest premium to the market. "
            f"Reasonable for a quality business growing above-average — not stretched, not cheap."
        )
    if pe > 12:
        return (
            f"At {pe:.1f}×, at or below the S&P average. "
            f"The market expects limited growth or is pricing in risk. Either a value opportunity or a value trap — context matters."
        )
    return (
        f"At {pe:.1f}×, deeply cheap by market standards. "
        f"The discount is either a genuine opportunity or reflects real fundamental risk. Investigate the reason before assuming upside."
    )


def _reason_range(
    price: float | None, low: float | None, high: float | None
) -> str | None:
    if price is None or low is None or high is None:
        return None
    rng = high - low
    if rng <= 0:
        return None
    pct = ((price - low) / rng) * 100
    if pct >= 85:
        return (
            f"Near its 52-week high (${high:,.2f}), with {pct:.0f}% of the range behind it. "
            f"The run has been strong — understand the catalyst and whether it's priced in before adding."
        )
    if pct >= 60:
        return (
            f"In the upper portion of its 52-week range (${low:,.2f}–${high:,.2f}). "
            f"Momentum is constructive; not at extremes."
        )
    if pct >= 40:
        return (
            f"Mid-range over the past year (${low:,.2f}–${high:,.2f}). "
            f"Balanced price action — neither a breakout nor a breakdown story right now."
        )
    if pct >= 15:
        return (
            f"In the lower half of its 52-week range (${low:,.2f}–${high:,.2f}). "
            f"Either building a base or in persistent weakness — the reason for the discount matters."
        )
    return (
        f"Near its 52-week low (${low:,.2f}), with only {pct:.0f}% of the range recovered. "
        f"Heavy selling has occurred. Know exactly why before buying into it."
    )


def _reason_market_cap(cap: float | None) -> str | None:
    if cap is None:
        return None
    if cap >= 1e12:
        t = f"${cap / 1e12:.1f}T mega-cap"
        liq = "among the most liquid equities globally — institutional flows dominate price action"
    elif cap >= 2e11:
        t = f"${cap / 1e9:.0f}B large-cap"
        liq = (
            "deep institutional coverage and high liquidity — bid-ask spreads are tight"
        )
    elif cap >= 1e10:
        t = f"${cap / 1e9:.0f}B mid-large cap"
        liq = "solid liquidity for most position sizes"
    elif cap >= 2e9:
        t = f"${cap / 1e9:.1f}B mid-cap"
        liq = "adequate liquidity but more sensitive to large order flows"
    else:
        t = f"${cap / 1e6:.0f}M small-cap"
        liq = "lower liquidity — wider spreads and thinner order books"
    return f"{t} — {liq}."


def _reason_z(label: str, z: float | None, raw_fmt: str) -> str | None:
    if z is None:
        return None
    if z >= 1.5:
        tier = f"top-tier ({z:+.2f}σ)"
        impl = "a standout relative to the S&P 500 universe"
    elif z >= 0.5:
        tier = f"above-average ({z:+.2f}σ)"
        impl = "clearly above the cross-sectional median"
    elif z >= -0.5:
        tier = f"average ({z:+.2f}σ)"
        impl = "in line with the broad universe — not a differentiating factor"
    elif z >= -1.5:
        tier = f"below-average ({z:+.2f}σ)"
        impl = "a headwind relative to peers"
    else:
        tier = f"poor ({z:+.2f}σ)"
        impl = "a meaningful drag — well below the cross-sectional median"
    return f"{label} is {tier} — {raw_fmt}, {impl}."


def _reason_cortex(
    score: float | None, rank: int | None, above_sma: bool | None, ticker: str = ""
) -> str | None:
    if score is None:
        return None
    trend_gate = (
        "passes the 200-day trend gate"
        if above_sma
        else "currently below the 200-day trend gate"
    )
    if score >= 1.0:
        stance = "a high-conviction systematic long"
    elif score >= 0.5:
        stance = "scoring well on the multi-factor composite"
    elif score >= 0.0:
        stance = "modestly positive — no strong factor tailwinds or headwinds"
    elif score >= -0.5:
        stance = "slightly below average on the composite — factor mix is mixed"
    else:
        stance = "weak on the composite — multiple factors are below-average"
    rank_str = f"ranked #{rank} in the discovery universe" if rank else ""
    name = ticker or "This name"
    return f"CORTEX composite {score:+.2f}σ — {stance}{', ' + rank_str if rank_str else ''}. {name} {trend_gate}."


@app.post("/context/{ticker}/reason")
def generate_reasoning(ticker: str) -> dict[str, Any]:
    """Generate data-driven reasoning for a stock's key metrics (no external calls)."""
    import contextlib

    from cortex.sources.market import MarketSourceError
    from cortex.sources.market import context_for as market_ctx

    tk = ticker.upper()

    mkt: Any = None
    with contextlib.suppress(MarketSourceError):
        mkt = market_ctx(ticker)

    cand: Any = None
    try:
        candidates = discovery.list_candidates(_db())
        cand = next((c for c in candidates if c.ticker == tk), None)
    except Exception:
        pass

    price = mkt.price if mkt else None
    change = mkt.day_change_percent if mkt else None
    pe = mkt.pe_ratio if mkt else None
    low52 = mkt.week_52_low if mkt else None
    high52 = mkt.week_52_high if mkt else None
    cap = mkt.market_cap if mkt else None

    def _pct(v: float | None) -> str:
        return f"{v * 100:.1f}%" if v is not None else "—"

    reasoning = {
        "trend": _reason_trend(price, change),
        "rsi": None,
        "volume": None,
        "pe": _reason_pe(pe),
        "range": _reason_range(price, low52, high52),
        "market_cap": _reason_market_cap(cap),
        "cortex_summary": _reason_cortex(
            cand.composite_score if cand else None,
            cand.composite_rank if cand else None,
            cand.above_200d_sma if cand else None,
            tk,
        )
        if cand
        else None,
        "momentum_factor": _reason_z(
            "12-month momentum",
            cand.z_momentum if cand else None,
            _pct(cand.momentum_12_1) + " trailing return" if cand else "—",
        ),
        "low_vol_factor": _reason_z(
            "Volatility",
            cand.z_low_vol if cand else None,
            _pct(cand.vol_252d) + " annualised vol" if cand else "—",
        ),
        "sharpe_factor": _reason_z(
            "Risk-adjusted return",
            cand.z_sharpe if cand else None,
            f"{cand.sharpe_12m:.2f} Sharpe"
            if cand and cand.sharpe_12m is not None
            else "—",
        ),
        "value_factor": _reason_z(
            "Earnings yield",
            cand.z_value if cand else None,
            _pct(cand.earnings_yield) + " yield" if cand else "—",
        ),
        "quality_factor": _reason_z(
            "Return on equity",
            cand.z_quality if cand else None,
            _pct(cand.roe) + " ROE" if cand else "—",
        ),
    }

    return {"banner": _BANNER, "ticker": tk, "reasoning": reasoning}


@app.get("/context/{ticker}/prompt")
def generate_prompt(ticker: str) -> dict[str, Any]:
    """Assemble a structured research brief prompt for pasting into Claude."""
    import contextlib
    from datetime import date

    from cortex.sources.congress import list_trades, recent_window
    from cortex.sources.market import MarketSourceError
    from cortex.sources.market import context_for as market_ctx
    from cortex.thesis import list_theses

    tk = ticker.upper()
    today = date.today().isoformat()

    # ── Market data ───────────────────────────────────────────────────────────
    mkt: Any = None
    with contextlib.suppress(MarketSourceError):
        mkt = market_ctx(ticker)

    # ── CORTEX candidate ──────────────────────────────────────────────────────
    cand: Any = None
    with contextlib.suppress(Exception):
        candidates = discovery.list_candidates(_db())
        cand = next((c for c in candidates if c.ticker == tk), None)

    # ── Senate trades ─────────────────────────────────────────────────────────
    senate_rows: list[str] = []
    with contextlib.suppress(Exception):
        trades = list_trades(_db(), ticker=ticker, since=recent_window(365), limit=10)
        for t in trades:
            senate_rows.append(
                f"  • {t.senator} — {t.transaction_type} — {t.amount}"
                + (f" ({t.transaction_date.isoformat()})" if t.transaction_date else "")
            )

    # ── Insider buys ──────────────────────────────────────────────────────────
    insider_rows: list[str] = []
    with contextlib.suppress(Exception):
        from cortex.sources.insiders import list_insider_buys

        for b in list_insider_buys(_db(), ticker=ticker, limit=10):
            val = f"${b.value_usd:,.0f}" if b.value_usd else "—"
            shares = f"{b.shares:,.0f} shares" if b.shares else "—"
            insider_rows.append(
                f"  • {b.filer_name} ({b.filer_role}) — {shares} / {val}"
                + (f" ({b.transaction_date.isoformat()})" if b.transaction_date else "")
            )

    # ── Activist stakes ───────────────────────────────────────────────────────
    activist_rows: list[str] = []
    with contextlib.suppress(Exception):
        from cortex.sources.activism import list_activism_events

        for s in list_activism_events(_db(), ticker=ticker, limit=10):
            activist_rows.append(
                f"  • {s.filer}"
                + (f" (filed {s.filing_date.isoformat()})" if s.filing_date else "")
            )

    # ── Active thesis ─────────────────────────────────────────────────────────
    thesis_rows: list[str] = []
    with contextlib.suppress(Exception):
        for status in ("open", "pending"):
            for th in list_theses(status=status, db_path=_db()):
                if tk in [t.upper() for t in th.tickers]:
                    thesis_rows.append(f"  Conviction: {th.conviction}/5  ({status})")
                    thesis_rows.append(f"  Claim: {th.claim}")
                    thesis_rows.append(f"  Falsifier: {th.falsifier}")
                    if th.reasoning:
                        thesis_rows.append(f"  Reasoning: {th.reasoning}")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _pct(v: float | None, scale: float = 1.0) -> str:
        return f"{v * scale * 100:.1f}%" if v is not None else "—"

    def _fmt(v: float | None, fmt: str = ".2f") -> str:
        return format(v, fmt) if v is not None else "—"

    def _section(rows: list[str], empty: str = "  None on record") -> str:
        return "\n".join(rows) if rows else empty

    # ── Price range position ──────────────────────────────────────────────────
    range_pct = ""
    if mkt and mkt.week_52_high and mkt.week_52_low and mkt.price:
        span = mkt.week_52_high - mkt.week_52_low
        if span > 0:
            pct = (mkt.price - mkt.week_52_low) / span * 100
            range_pct = f"  ({pct:.0f}% of 52-week range)"

    # ── Assemble prompt ───────────────────────────────────────────────────────
    name = mkt.company_name if mkt and mkt.company_name else tk
    cap_str = f"${mkt.market_cap / 1e9:,.0f}B" if mkt and mkt.market_cap else "—"
    lines: list[str] = [
        f"CORTEX RESEARCH BRIEF — {tk} ({name})",
        f"Generated: {today}",
        "",
        "═" * 60,
        "MARKET DATA",
        "═" * 60,
        f"Price:        ${_fmt(mkt.price if mkt else None, ',.2f') if mkt else '—'}"
        + (
            f"  ({_fmt(mkt.day_change_percent if mkt and mkt.day_change_percent else None, '+.2f')}% today)"
            if mkt
            else ""
        ),
        f"52-week:      ${_fmt(mkt.week_52_low if mkt else None, ',.2f')} – ${_fmt(mkt.week_52_high if mkt else None, ',.2f')}{range_pct}",
        f"Market cap:   {cap_str}",
        f"P/E ratio:    {_fmt(mkt.pe_ratio if mkt else None, '.1f')}×",
        "",
        "═" * 60,
        "CORTEX FACTOR SCORES  (cross-sectional z-scores, S&P 500 universe)",
        "═" * 60,
    ]
    if cand:
        lines += [
            f"Composite:      {cand.composite_score:+.2f}σ  (rank #{cand.composite_rank} of discovery universe)",
            f"Momentum 12-1:  z={_fmt(cand.z_momentum)}  raw={_pct(cand.momentum_12_1)} trailing return",
            f"Low-vol:        z={_fmt(cand.z_low_vol)}  raw={_pct(cand.vol_252d)} annualised vol",
            f"Sharpe 12m:     z={_fmt(cand.z_sharpe)}  raw={_fmt(cand.sharpe_12m)} Sharpe",
            f"Value (EY):     z={_fmt(cand.z_value)}  raw={_pct(cand.earnings_yield)} earnings yield",
            f"Quality (ROE):  z={_fmt(cand.z_quality)}  raw={_pct(cand.roe)} ROE",
            f"Above 200d SMA: {'Yes' if cand.above_200d_sma else 'No' if cand.above_200d_sma is not None else '—'}",
        ]
    else:
        lines.append(
            "  Not in CORTEX discovery universe (run cortex discover to populate)"
        )

    lines += [
        "",
        "═" * 60,
        "SENATE TRADES (last 365 days)",
        "═" * 60,
        _section(senate_rows),
        "",
        "═" * 60,
        "INSIDER BUYS",
        "═" * 60,
        _section(insider_rows),
        "",
        "═" * 60,
        "ACTIVIST STAKES",
        "═" * 60,
        _section(activist_rows),
    ]

    if mkt and mkt.news_headlines:
        lines += [
            "",
            "═" * 60,
            "NEWS HEADLINES",
            "═" * 60,
        ]
        for h in mkt.news_headlines[:8]:
            lines.append(f"  • {h}")

    if thesis_rows:
        lines += [
            "",
            "═" * 60,
            "ACTIVE THESIS",
            "═" * 60,
            *thesis_rows,
        ]

    lines += [
        "",
        "═" * 60,
        "REQUEST",
        "═" * 60,
        f"Based on the above data context for {tk}, provide a structured investment analysis covering:",
        "",
        "1. Thesis quality — does the data support a long position? What are the key risks?",
        "2. Factor interpretation — how should the CORTEX composite be weighted vs individual z-scores?",
        "3. Valuation — is the current P/E justifiable given the momentum and quality signals?",
        "4. Catalysts — from news, insider, and senate data, what are the most significant near-term drivers?",
        "5. Conviction and sizing — recommended conviction level (1–5) and position sizing rationale.",
        "",
        "Flag anything that would cause you to reverse or reduce the thesis.",
        "Be specific and cite the data where possible.",
    ]

    return {"banner": _BANNER, "ticker": tk, "prompt": "\n".join(lines)}


@app.get("/event-study/{signal}/car-series")
def car_series_endpoint(signal: str) -> dict[str, Any]:
    """Day-by-day mean CAR (days 0–120) for a filing-gated signal. Cached 24 h.

    First call downloads S&P 500 prices via yfinance (~30–60 s). Subsequent
    calls within the TTL window return immediately from the in-memory cache.
    """
    import time

    from cortex.backtest import run_event_study_daily

    if signal not in ("insider", "activism", "congress", "executive"):
        raise HTTPException(status_code=400, detail=f"Unknown signal {signal!r}")

    now = time.time()
    if signal in _car_series_cache:
        ts, cached = _car_series_cache[signal]
        if now - ts < _CAR_CACHE_TTL:
            return {"banner": _BANNER, "signal": signal, "series": cached}

    points = run_event_study_daily(_db(), signal=signal)
    data = [
        {"day": p.day, "mean_car": p.mean_car, "se": p.se, "n": p.n} for p in points
    ]
    _car_series_cache[signal] = (now, data)
    return {"banner": _BANNER, "signal": signal, "series": data}


def _maybe_mirror() -> None:
    try:
        from cortex.mirror import generate

        settings = load_settings()
        generate(settings.vault_dir, db_path=settings.duckdb_path)
    except Exception as exc:
        log.warning("mirror: failed — %s", exc)


# ── static frontend (must come last so API routes take precedence) ────────────

if _WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=_WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        """Serve static files from dist root when they exist, otherwise index.html."""
        candidate = (_WEB_DIST / full_path).resolve()
        if candidate.is_relative_to(_WEB_DIST.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_WEB_DIST / "index.html")
