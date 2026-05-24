from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# A "2-week" window in trading days; enforced as the floor so the screen always
# reflects at least two weeks of price action as Ari specified.
MIN_LOOKBACK_DAYS = 10
DEFAULT_LOOKBACK_DAYS = 15


# ── Domain model ──────────────────────────────────────────────────────────────

@dataclass
class VolStock:
    """A row of the Ari Special volatility screen.

    The Ari Special surfaces stocks that swing a large *and repeatable* dollar
    amount between their daily highs and lows. ``avg_dollar_range`` is the
    Average Daily Range (ADR, a dollar cousin of ATR); ``range_consistency``
    rewards swings of a stable size; ``ari_special_score`` is their product.
    """

    ticker: str
    as_of_date: date
    computed_at: datetime
    lookback_days: int
    avg_dollar_range: float | None
    range_consistency: float | None
    avg_range_pct: float | None
    avg_close: float | None
    ari_special_score: float
    rank: int


# ── Metric computation ─────────────────────────────────────────────────────────

def _compute_metrics(
    tickers: list[str], lookback_days: int
) -> dict[str, dict[str, Any]]:
    """Download recent OHLC data and compute Ari Special metrics per ticker.

    Returns a dict keyed by ticker with keys: avg_dollar_range,
    range_consistency, avg_range_pct, avg_close, ari_special_score.
    """
    import numpy as np
    import yfinance as yf

    log.info("Downloading 3mo OHLC for %d tickers…", len(tickers))
    raw = yf.download(
        tickers,
        period="3mo",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    # yf.download gives MultiIndex columns (field, ticker) for >1 ticker.
    def _frame_for(ticker: str) -> Any | None:
        try:
            if len(tickers) == 1:
                highs = raw["High"]
                lows = raw["Low"]
                closes = raw["Close"]
            else:
                highs = raw["High"][ticker]
                lows = raw["Low"][ticker]
                closes = raw["Close"][ticker]
        except (KeyError, TypeError):
            return None
        return highs, lows, closes

    results: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        frame = _frame_for(ticker)
        empty = {
            "avg_dollar_range": None,
            "range_consistency": None,
            "avg_range_pct": None,
            "avg_close": None,
            "ari_special_score": 0.0,
        }
        if frame is None:
            results[ticker] = empty
            continue

        highs, lows, closes = frame
        ranges = (highs - lows).dropna()
        closes = closes.dropna()
        if len(ranges) < lookback_days or len(closes) < lookback_days:
            results[ticker] = empty
            continue

        window = ranges.iloc[-lookback_days:]
        close_window = closes.iloc[-lookback_days:]

        avg_range = float(window.mean())
        std_range = float(window.std())
        avg_close = float(close_window.mean())

        if avg_range <= 0 or avg_close <= 0:
            results[ticker] = empty
            continue

        # Coefficient of variation → consistency in (0, 1]; lower CV = steadier
        # swing size = closer to 1.
        cv = std_range / avg_range
        consistency = 1.0 / (1.0 + cv)
        avg_range_pct = avg_range / avg_close
        score = avg_range * consistency

        results[ticker] = {
            "avg_dollar_range": round(avg_range, 4),
            "range_consistency": round(consistency, 4),
            "avg_range_pct": round(avg_range_pct, 6),
            "avg_close": round(avg_close, 4),
            "ari_special_score": round(score, 4),
        }

    return results


# ── Storage ───────────────────────────────────────────────────────────────────

def _store(stocks: list[VolStock], db_path: Path) -> None:
    """Atomically replace the volatility_screen table contents."""
    from wst.storage.db import connect

    with connect(db_path) as conn:
        conn.execute("DELETE FROM volatility_screen")
        if not stocks:
            return
        conn.executemany(
            """
            INSERT INTO volatility_screen (
                ticker, as_of_date, computed_at, lookback_days,
                avg_dollar_range, range_consistency, avg_range_pct,
                avg_close, ari_special_score, rank
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    s.ticker,
                    s.as_of_date,
                    s.computed_at,
                    s.lookback_days,
                    s.avg_dollar_range,
                    s.range_consistency,
                    s.avg_range_pct,
                    s.avg_close,
                    s.ari_special_score,
                    s.rank,
                )
                for s in stocks
            ],
        )


def list_volatility_screen(db_path: Path) -> list[VolStock]:
    """Load the Ari Special screen ordered by score, newest run first.

    Returns an empty list if the table does not exist yet (pre-migration DB).
    """
    import duckdb

    from wst.storage.db import connect

    with connect(db_path, read_only=True) as conn:
        try:
            rows = conn.execute(
                """
                SELECT
                    ticker, as_of_date, computed_at, lookback_days,
                    avg_dollar_range, range_consistency, avg_range_pct,
                    avg_close, ari_special_score, rank
                FROM volatility_screen
                ORDER BY rank
                """
            ).fetchall()
        except duckdb.CatalogException:
            return []

    return [
        VolStock(
            ticker=r[0],
            as_of_date=r[1],
            computed_at=r[2],
            lookback_days=r[3],
            avg_dollar_range=r[4],
            range_consistency=r[5],
            avg_range_pct=r[6],
            avg_close=r[7],
            ari_special_score=r[8],
            rank=r[9],
        )
        for r in rows
    ]


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_volatility_screen(
    db_path: Path,
    top_n: int = 40,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[VolStock]:
    """Run the Ari Special volatility screen over the S&P 500 universe.

    Ranks stocks by the product of their Average Daily Range (in dollars) and a
    consistency factor, so the top names swing a large *and steady* dollar
    amount over the lookback window.

    Args:
        db_path: DuckDB path to persist results to.
        top_n: Number of stocks to keep.
        lookback_days: Trading-day window; floored at ``MIN_LOOKBACK_DAYS``
            (two weeks) per the feature spec.
    """
    from wst.sources.universe import sp500_tickers

    lookback = max(MIN_LOOKBACK_DAYS, lookback_days)
    as_of = date.today()
    now = datetime.now(tz=UTC)

    tickers = sp500_tickers()
    log.info("Ari Special: scanning %d tickers (%d-day window)", len(tickers), lookback)

    metrics = _compute_metrics(tickers, lookback)

    ranked = sorted(
        tickers,
        key=lambda t: metrics.get(t, {}).get("ari_special_score") or 0.0,
        reverse=True,
    )

    stocks: list[VolStock] = []
    for rank, ticker in enumerate(ranked[:top_n], start=1):
        m = metrics[ticker]
        stocks.append(
            VolStock(
                ticker=ticker,
                as_of_date=as_of,
                computed_at=now,
                lookback_days=lookback,
                avg_dollar_range=m["avg_dollar_range"],
                range_consistency=m["range_consistency"],
                avg_range_pct=m["avg_range_pct"],
                avg_close=m["avg_close"],
                ari_special_score=m["ari_special_score"],
                rank=rank,
            )
        )

    log.info("Ari Special: storing %d stocks", len(stocks))
    _store(stocks, db_path)
    return stocks
