from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

import wst.calibration as cal
import wst.review as rev
import wst.thesis as th
from wst.config import load_settings

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

@app.get("/")
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
    from wst.sources.congress import (
        CongressSourceError,
        fetch_senate_trades,
        filter_trades,
        recent_window,
    )
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
        }
    except MarketSourceError as exc:
        result["market_error"] = str(exc)

    try:
        all_trades = fetch_senate_trades()
        trades = filter_trades(all_trades, [ticker], since=recent_window(180))
        result["senate_trades"] = [
            {
                "senator": t.senator,
                "transaction_type": t.transaction_type,
                "amount": t.amount,
                "transaction_date": (
                    t.transaction_date.isoformat() if t.transaction_date else None
                ),
            }
            for t in trades[:10]
        ]
    except CongressSourceError as exc:
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


def _maybe_mirror() -> None:
    try:
        from wst.mirror import generate
        settings = load_settings()
        generate(settings.vault_dir, db_path=settings.duckdb_path)
    except Exception:
        pass
