from __future__ import annotations

import logging
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

import wst.calibration as cal
import wst.cases as cases
import wst.discovery as discovery
import wst.review as rev
import wst.thesis as th
from wst.config import load_settings
from wst.storage.db import connect
from wst.storage.schemas import apply_schema

log = logging.getLogger(__name__)

_WEB_DIST = Path(__file__).parents[2] / "web" / "dist"


def _apply_schema_on_startup() -> None:
    from contextlib import suppress
    with suppress(Exception):
        with connect(load_settings().duckdb_path) as conn:
            apply_schema(conn)


_apply_schema_on_startup()

app = FastAPI(title="WST — Wall Street Tracker", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

_BANNER = "Decision tool — not financial advice."


def _db() -> Path:
    return load_settings().duckdb_path


# ── "Sync all data" background job ───────────────────────────────────────────
# A single in-process worker refreshes congress filings + the CORTEX discovery
# scan. Heavy work (yfinance, scraping) runs without holding a DB connection;
# only the brief store steps open read-write, so concurrent reads stay healthy.

_refresh_lock = threading.Lock()
_refresh_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "steps": {},
    "error": None,
}


def _run_refresh() -> None:
    from wst.discovery import run_discovery
    from wst.sources.congress import fetch_senate_trades, recent_window, store_trades

    try:
        db = _db()

        try:
            _refresh_state["steps"]["congress"] = "running"
            trades = fetch_senate_trades(since=recent_window(120), max_reports=400)
            new = store_trades(trades, db)
            _refresh_state["steps"]["congress"] = f"done — {len(trades)} trades ({new} new)"
        except Exception as exc:  # noqa: BLE001 - record and continue to discovery
            log.warning("refresh: congress sync failed: %s", exc)
            _refresh_state["steps"]["congress"] = f"failed — {exc}"

        try:
            _refresh_state["steps"]["funds"] = "running"
            from wst.sources.funds import sync_all_managers

            new_funds = sync_all_managers(db)
            _refresh_state["steps"]["funds"] = f"done — {new_funds} new moves"
        except Exception as exc:  # noqa: BLE001 - record and continue
            log.warning("refresh: funds sync failed: %s", exc)
            _refresh_state["steps"]["funds"] = f"failed — {exc}"

        try:
            _refresh_state["steps"]["discover"] = "running"
            candidates = run_discovery(db, top_n=30)
            _refresh_state["steps"]["discover"] = f"done — {len(candidates)} candidates"
        except Exception as exc:  # noqa: BLE001 - record visibly
            log.warning("refresh: discovery failed: %s", exc)
            _refresh_state["steps"]["discover"] = f"failed — {exc}"
            _refresh_state["error"] = str(exc)

        try:
            _refresh_state["steps"]["volatility"] = "running"
            from wst.volatility_screen import run_volatility_screen

            vol = run_volatility_screen(db)
            _refresh_state["steps"]["volatility"] = f"done — {len(vol)} stocks"
        except Exception as exc:  # noqa: BLE001 - record and continue
            log.warning("refresh: volatility screen failed: %s", exc)
            _refresh_state["steps"]["volatility"] = f"failed — {exc}"

    except Exception as exc:  # noqa: BLE001 - db init or import failure
        log.exception("refresh: fatal error: %s", exc)
        _refresh_state["error"] = str(exc)
        for step, val in _refresh_state["steps"].items():
            if val in ("queued", "running"):
                _refresh_state["steps"][step] = f"failed — {exc}"
    finally:
        _refresh_state["running"] = False
        _refresh_state["finished_at"] = datetime.now(tz=UTC).isoformat()


@app.post("/refresh")
def refresh() -> dict[str, Any]:
    """Kick off a background refresh of congress filings + CORTEX discovery."""
    with _refresh_lock:
        if _refresh_state["running"]:
            return {"banner": _BANNER, "status": "already_running", **_refresh_state}
        _refresh_state.update(
            running=True,
            started_at=datetime.now(tz=UTC).isoformat(),
            finished_at=None,
            error=None,
            steps={
                "congress": "queued",
                "funds": "queued",
                "discover": "queued",
                "volatility": "queued",
            },
        )
    threading.Thread(target=_run_refresh, daemon=True).start()
    return {"banner": _BANNER, "status": "started", **_refresh_state}


@app.get("/refresh/status")
def refresh_status() -> dict[str, Any]:
    return {"banner": _BANNER, **_refresh_state}


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
        "ari_special_score": s.ari_special_score,
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
        activate_at = datetime.now() + timedelta(hours=body.cooling_off_hours)
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
    from wst.rag import retrieve

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
def context(ticker: str) -> dict[str, Any]:
    from wst.sources.congress import list_trades, recent_window
    from wst.sources.market import MarketSourceError
    from wst.sources.market import context_for as market_ctx

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
        trades = list_trades(
            _db(), ticker=ticker, since=recent_window(365), limit=10
        )
        result["senate_trades"] = [
            {
                "senator": t.senator,
                "transaction_type": t.transaction_type,
                "amount": t.amount,
                "transaction_date": (
                    t.transaction_date.isoformat() if t.transaction_date else None
                ),
            }
            for t in trades
        ]
    except Exception as exc:  # noqa: BLE001 - degrade visibly, never block context
        result["senate_trades_error"] = str(exc)

    return result


@app.get("/context/{ticker}/history")
def price_history(ticker: str, period: str = "6mo") -> dict[str, Any]:
    from wst.sources.market import MarketSourceError, history_for

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
    """Aggregated Senate-trade analytics over a trailing window."""
    from wst.sources.congress import congress_stats

    return {"banner": _BANNER, "days": days, **congress_stats(_db(), days=days)}


@app.get("/congress")
def get_congress(
    ticker: str | None = None, days: int = 120, limit: int = 100
) -> dict[str, Any]:
    """Recent Senate trades from the local mirror (populated by `wst congress-sync`)."""
    from wst.sources.congress import list_trades, recent_window

    trades = list_trades(
        _db(), ticker=ticker, since=recent_window(days), limit=limit
    )
    return {
        "banner": _BANNER,
        "ticker": ticker.upper() if ticker else None,
        "count": len(trades),
        "trades": [
            {
                "senator": t.senator,
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


@app.get("/funds")
def get_funds(
    ticker: str | None = None, actions: str = "NEW,ADD", limit: int = 100
) -> dict[str, Any]:
    """Institutional 13F moves from the local mirror (`wst funds-sync`)."""
    from wst.sources.funds import list_fund_moves

    action_tuple = tuple(a.strip().upper() for a in actions.split(",") if a.strip())
    moves = list_fund_moves(
        _db(), ticker=ticker, actions=action_tuple, limit=limit
    )
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
    """The Ari Special — stocks with large, consistent daily dollar swings."""
    from wst.volatility_screen import list_volatility_screen

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
    match = next(
        (c for c in discovery.list_candidates(_db()) if c.ticker == tk), None
    )
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
    from wst.rag import retrieve

    by_factor: dict[str, list[dict[str, Any]]] = {}
    error: str | None = None
    for factor, query in _FACTOR_QUERIES.items():
        try:
            chunks = retrieve(query, k=k, db_path=_db())
        except Exception as exc:  # noqa: BLE001 - degrade visibly
            error = str(exc)
            chunks = []
        by_factor[factor] = [
            {"wikilink": c.wikilink, "tier": c.tier, "text": c.text}
            for c in chunks
        ]
    return {
        "banner": _BANNER,
        "ticker": ticker.upper(),
        "by_factor": by_factor,
        "error": error,
    }


@app.post("/context/{ticker}/reason")
def generate_reasoning(ticker: str) -> dict[str, Any]:
    """Shell to the local claude CLI to generate AI reasoning for a stock's key metrics."""
    import json
    import shutil
    import subprocess

    from wst.sources.market import MarketSourceError
    from wst.sources.market import context_for as market_ctx

    tk = ticker.upper()

    # Gather all available context
    mkt_data: dict[str, Any] = {}
    try:
        mkt = market_ctx(ticker)
        mkt_data = {
            "price": mkt.price,
            "day_change_percent": mkt.day_change_percent,
            "week_52_high": mkt.week_52_high,
            "week_52_low": mkt.week_52_low,
            "market_cap": mkt.market_cap,
            "pe_ratio": mkt.pe_ratio,
            "news_headlines": mkt.news_headlines[:5],
        }
    except MarketSourceError:
        pass

    cortex_data: dict[str, Any] = {}
    try:
        candidates = discovery.list_candidates(_db())
        match = next((c for c in candidates if c.ticker == tk), None)
        if match:
            cortex_data = {
                "composite_score": match.composite_score,
                "composite_rank": match.composite_rank,
                "above_200d_sma": match.above_200d_sma,
                "momentum_12_1": match.momentum_12_1,
                "vol_252d": match.vol_252d,
                "sharpe_12m": match.sharpe_12m,
                "earnings_yield": match.earnings_yield,
                "roe": match.roe,
                "z_momentum": match.z_momentum,
                "z_low_vol": match.z_low_vol,
                "z_sharpe": match.z_sharpe,
                "z_value": match.z_value,
                "z_quality": match.z_quality,
            }
    except Exception:
        pass

    prompt = f"""You are analyzing stock {tk} for an investment research dashboard.

Given the data below, write direct, intelligent reasoning for each section.
Be specific about the actual numbers. Avoid generic disclaimers.
Write as if explaining to a sophisticated investor who has already accepted the risk.

MARKET DATA:
{json.dumps(mkt_data, indent=2)}

CORTEX FACTOR SCORES (z-scores vs S&P 500 universe):
{json.dumps(cortex_data, indent=2) if cortex_data else "Not in current discovery run"}

Return ONLY a JSON object with exactly these keys. Each value is 1-2 sentences max:
{{
  "trend": "interpretation of price trend and what it means right now",
  "rsi": "what the current momentum reading implies for near-term action",
  "volume": "what current trading activity says about institutional conviction",
  "pe": "whether this valuation is justified given the growth profile",
  "range": "where in the 52-week range this sits and what that implies",
  "market_cap": "one sentence on the size and liquidity implications",
  "cortex_summary": "what the CORTEX composite score says about this name vs peers",
  "momentum_factor": "what the momentum z-score implies",
  "low_vol_factor": "what the volatility profile implies",
  "sharpe_factor": "what the risk-adjusted return says",
  "value_factor": "what earnings yield says about valuation",
  "quality_factor": "what ROE says about capital efficiency"
}}"""

    # Locate the claude binary: PATH first, then an explicit WST_CLAUDE_BIN override.
    claude_bin = shutil.which("claude")
    if claude_bin is None:
        import os

        override = os.environ.get("WST_CLAUDE_BIN", "")
        if override and Path(override).exists():
            claude_bin = override

    if claude_bin is None:
        raise HTTPException(
            status_code=503,
            detail="claude CLI not found — ensure Claude Code is installed",
        )

    try:
        result = subprocess.run(
            [claude_bin, "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=120,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="claude CLI timed out") from None
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"claude CLI error: {exc}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise HTTPException(
            status_code=502, detail=f"claude CLI failed: {stderr or result.stdout[:200]}"
        )

    # Parse the outer JSON envelope from claude --output-format json
    try:
        envelope = json.loads(result.stdout)
        raw_text: str = envelope.get("result", "")
    except json.JSONDecodeError:
        raw_text = result.stdout

    # Extract the JSON object from the model's response
    start = raw_text.find("{")
    end = raw_text.rfind("}") + 1
    if start == -1 or end == 0:
        raise HTTPException(
            status_code=502,
            detail=f"claude returned unexpected output: {raw_text[:200]}",
        )

    try:
        reasoning = json.loads(raw_text[start:end])
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502, detail=f"failed to parse claude JSON output: {exc}"
        ) from exc

    return {"banner": _BANNER, "ticker": tk, "reasoning": reasoning}


def _maybe_mirror() -> None:
    try:
        from wst.mirror import generate
        settings = load_settings()
        generate(settings.vault_dir, db_path=settings.duckdb_path)
    except Exception:
        pass


# ── static frontend (must come last so API routes take precedence) ────────────

if _WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=_WEB_DIST / "assets"), name="assets")

    @app.get("/favicon.svg")
    def favicon() -> FileResponse:
        return FileResponse(_WEB_DIST / "favicon.svg")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:  # noqa: ARG001
        """Serve index.html for all unmatched paths (React SPA routing)."""
        return FileResponse(_WEB_DIST / "index.html")
