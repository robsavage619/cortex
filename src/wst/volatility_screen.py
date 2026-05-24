from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# A "2-week" window in trading days; enforced as the floor so the screen always
# reflects at least two weeks of price action.
MIN_LOOKBACK_DAYS = 10
DEFAULT_LOOKBACK_DAYS = 15


# ── Domain model ──────────────────────────────────────────────────────────────

@dataclass
class VolStock:
    """A row of the swing screen.

    The swing screen surfaces stocks that move a large *and repeatable* dollar
    amount between their daily highs and lows. ``avg_dollar_range`` is the
    Average Daily Range (ADR, a dollar cousin of ATR); ``range_consistency``
    rewards swings of a stable size; ``swing_score`` is their product.
    """

    ticker: str
    as_of_date: date
    computed_at: datetime
    lookback_days: int
    avg_dollar_range: float | None
    range_consistency: float | None
    avg_range_pct: float | None
    avg_close: float | None
    oscillation_score: float | None
    net_drift_pct: float | None
    range_position: float | None
    direction_changes: int | None
    avg_volume: float | None
    swing_score: float
    rank: int
    company_name: str | None = None
    max_range_pct: float | None = None
    max_dollar_range: float | None = None


# ── Metric computation ─────────────────────────────────────────────────────────

def _compute_metrics(
    tickers: list[str], lookback_days: int
) -> dict[str, dict[str, Any]]:
    """Download recent OHLC data and compute swing-screen metrics per ticker.

    Returns a dict keyed by ticker with the metric keys mirrored on
    :class:`VolStock` (avg_dollar_range, range_consistency, oscillation_score,
    net_drift_pct, range_position, direction_changes, avg_volume, …).
    """
    import yfinance as yf

    log.info("Downloading 3mo OHLC for %d tickers…", len(tickers))
    raw = yf.download(
        tickers,
        period="3mo",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    # yf.download gives MultiIndex columns (field, ticker) for >1 ticker and a
    # single-level frame for one ticker. Normalise each field to a frame keyed
    # by ticker so the per-ticker loop can index uniformly.
    if len(tickers) == 1:
        highs_df = raw[["High"]].rename(columns={"High": tickers[0]})
        lows_df = raw[["Low"]].rename(columns={"Low": tickers[0]})
        closes_df = raw[["Close"]].rename(columns={"Close": tickers[0]})
        volumes_df = raw[["Volume"]].rename(columns={"Volume": tickers[0]})
    else:
        highs_df = raw["High"]
        lows_df = raw["Low"]
        closes_df = raw["Close"]
        volumes_df = raw["Volume"]

    empty = {
        "avg_dollar_range": None,
        "range_consistency": None,
        "avg_range_pct": None,
        "max_range_pct": None,
        "max_dollar_range": None,
        "avg_close": None,
        "oscillation_score": None,
        "net_drift_pct": None,
        "range_position": None,
        "direction_changes": None,
        "avg_volume": None,
        "swing_score": 0.0,
    }

    results: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        if ticker not in closes_df.columns or ticker not in highs_df.columns:
            results[ticker] = dict(empty)
            continue

        ranges = (highs_df[ticker] - lows_df[ticker]).dropna()
        closes = closes_df[ticker].dropna()
        highs = highs_df[ticker].dropna()
        lows = lows_df[ticker].dropna()
        if len(ranges) < lookback_days or len(closes) < lookback_days:
            results[ticker] = dict(empty)
            continue

        window = ranges.iloc[-lookback_days:]
        close_window = closes.iloc[-lookback_days:]
        high_window = highs.iloc[-lookback_days:]
        low_window = lows.iloc[-lookback_days:]

        avg_range = float(window.mean())
        std_range = float(window.std())
        avg_close = float(close_window.mean())

        if avg_range <= 0 or avg_close <= 0:
            results[ticker] = dict(empty)
            continue

        # Coefficient of variation → consistency in (0, 1]; lower CV = steadier
        # swing size = closer to 1.
        cv = std_range / avg_range
        consistency = 1.0 / (1.0 + cv)
        avg_range_pct = avg_range / avg_close
        max_range_pct = float((window / close_window).max())
        max_dollar_range = float(window.max())
        # Score = % swing (in pct-points) × consistency so expensive
        # high-dollar stocks don't crowd out nimble smaller ones.
        score = avg_range_pct * 100 * consistency

        # Day-to-day close changes drive the oscillation metrics.
        deltas = close_window.diff().dropna()
        first_close = float(close_window.iloc[0])
        last_close = float(close_window.iloc[-1])
        net_change = last_close - first_close
        total_path = float(deltas.abs().sum())

        # Kaufman efficiency ratio: |net move| / total path travelled. A pure
        # trend ≈ 1; a stock that bounces and ends where it started ≈ 0. We
        # invert it so a *higher* oscillation score = more back-and-forth swing.
        efficiency = abs(net_change) / total_path if total_path > 0 else 0.0
        oscillation = max(0.0, min(1.0, 1.0 - efficiency))
        net_drift_pct = net_change / first_close if first_close > 0 else None
        direction_changes = int((deltas.apply(_sign).diff().fillna(0) != 0).sum())

        # Where the latest close sits inside the window's full low→high band.
        win_low = float(low_window.min())
        win_high = float(high_window.max())
        band = win_high - win_low
        range_position = (last_close - win_low) / band if band > 0 else None

        avg_volume = (
            float(volumes_df[ticker].dropna().iloc[-lookback_days:].mean())
            if ticker in volumes_df.columns
            else None
        )

        drift = round(net_drift_pct, 6) if net_drift_pct is not None else None
        pos = round(range_position, 4) if range_position is not None else None
        vol = round(avg_volume, 1) if avg_volume is not None else None

        results[ticker] = {
            "avg_dollar_range": round(avg_range, 4),
            "range_consistency": round(consistency, 4),
            "avg_range_pct": round(avg_range_pct, 6),
            "max_range_pct": round(max_range_pct, 6),
            "max_dollar_range": round(max_dollar_range, 4),
            "avg_close": round(avg_close, 4),
            "oscillation_score": round(oscillation, 4),
            "net_drift_pct": drift,
            "range_position": pos,
            "direction_changes": direction_changes,
            "avg_volume": vol,
            "swing_score": round(score, 4),
        }

    return results


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _fetch_company_names(tickers: list[str]) -> dict[str, str | None]:
    """Fetch display names for a small list of tickers via yfinance .info."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import yfinance as yf

    def _one(t: str) -> tuple[str, str | None]:
        try:
            info = yf.Ticker(t).info
            name = info.get("longName") or info.get("shortName") or None
            return t, name
        except Exception:
            return t, None

    out: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(_one, t): t for t in tickers}
        for t, name in (f.result() for f in as_completed(futs)):
            out[t] = name
    return out


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
                avg_dollar_range, range_consistency, avg_range_pct, max_range_pct,
                max_dollar_range, avg_close, oscillation_score, net_drift_pct,
                range_position, direction_changes, avg_volume, swing_score,
                rank, company_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    s.max_range_pct,
                    s.max_dollar_range,
                    s.avg_close,
                    s.oscillation_score,
                    s.net_drift_pct,
                    s.range_position,
                    s.direction_changes,
                    s.avg_volume,
                    s.swing_score,
                    s.rank,
                    s.company_name,
                )
                for s in stocks
            ],
        )


def list_volatility_screen(db_path: Path) -> list[VolStock]:
    """Load the swing screen ordered by score, newest run first.

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
                    avg_dollar_range, range_consistency, avg_range_pct, max_range_pct,
                    max_dollar_range, avg_close, oscillation_score, net_drift_pct,
                    range_position, direction_changes, avg_volume, swing_score,
                    rank, company_name
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
            max_range_pct=r[7],
            max_dollar_range=r[8],
            avg_close=r[9],
            oscillation_score=r[10],
            net_drift_pct=r[11],
            range_position=r[12],
            direction_changes=r[13],
            avg_volume=r[14],
            swing_score=r[15],
            rank=r[16],
            company_name=r[17],
        )
        for r in rows
    ]


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_volatility_screen(
    db_path: Path,
    top_n: int = 75,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[VolStock]:
    """Run the swing screen over the S&P 500 + S&P 400 universe.

    Ranks stocks by swing % × consistency so that nimble mid-caps compete
    fairly with expensive large-caps.

    Args:
        db_path: DuckDB path to persist results to.
        top_n: Number of stocks to keep.
        lookback_days: Trading-day window; floored at ``MIN_LOOKBACK_DAYS``
            (two weeks) per the feature spec.
    """
    from wst.sources.universe import composite_tickers

    lookback = max(MIN_LOOKBACK_DAYS, lookback_days)
    as_of = date.today()
    now = datetime.now(tz=UTC)

    tickers = composite_tickers()
    log.info("Swing screen: scanning %d tickers (%dd window)", len(tickers), lookback)

    metrics = _compute_metrics(tickers, lookback)

    ranked = sorted(
        tickers,
        key=lambda t: metrics.get(t, {}).get("swing_score") or 0.0,
        reverse=True,
    )

    top_tickers = [t for t in ranked[:top_n] if (metrics.get(t, {}).get("swing_score") or 0.0) > 0]
    log.info("Swing screen: fetching company names for %d tickers", len(top_tickers))
    names = _fetch_company_names(top_tickers)

    stocks: list[VolStock] = []
    for rank, ticker in enumerate(top_tickers, start=1):
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
                oscillation_score=m["oscillation_score"],
                net_drift_pct=m["net_drift_pct"],
                range_position=m["range_position"],
                direction_changes=m["direction_changes"],
                avg_volume=m["avg_volume"],
                swing_score=m["swing_score"],
                rank=rank,
                company_name=names.get(ticker),
                max_range_pct=m["max_range_pct"],
                max_dollar_range=m["max_dollar_range"],
            )
        )

    if not stocks:
        log.warning("Swing screen: no scored stocks — aborting store to preserve existing data")
        return stocks

    log.info("Swing screen: storing %d stocks", len(stocks))
    _store(stocks, db_path)
    return stocks
