from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ── Domain model ──────────────────────────────────────────────────────────────

@dataclass
class Candidate:
    ticker: str
    as_of_date: date
    discovered_at: datetime
    momentum_12_1: float | None
    vol_252d: float | None
    sharpe_12m: float | None
    above_200d_sma: bool | None
    earnings_yield: float | None
    roe: float | None
    z_momentum: float | None
    z_low_vol: float | None
    z_sharpe: float | None
    z_value: float | None
    z_quality: float | None
    composite_score: float
    composite_rank: int


# ── Math helpers ──────────────────────────────────────────────────────────────

def _zscore_series(values: dict[str, float | None]) -> dict[str, float | None]:
    """Cross-sectional z-score.  Returns None for tickers that had None input."""
    valid = {k: v for k, v in values.items() if v is not None}
    if len(valid) < 2:
        return {k: None for k in values}
    nums = list(valid.values())
    mean = sum(nums) / len(nums)
    variance = sum((x - mean) ** 2 for x in nums) / len(nums)
    std = variance ** 0.5
    if std == 0:
        return {k: (0.0 if k in valid else None) for k in values}
    out: dict[str, float | None] = {}
    for k in values:
        if k in valid:
            out[k] = (valid[k] - mean) / std
        else:
            out[k] = None
    return out


# ── Price-based factor computation ────────────────────────────────────────────

def _compute_price_factors(
    tickers: list[str],
) -> dict[str, dict[str, Any]]:
    """Download 13 months of daily close prices and compute price-based factors.

    Returns a dict keyed by ticker with keys:
        momentum_12_1, vol_252d, sharpe_12m, above_200d_sma
    """
    import numpy as np
    import yfinance as yf

    log.info("Downloading price data for %d tickers (13mo)…", len(tickers))
    raw = yf.download(
        tickers,
        period="13mo",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    # yf.download returns MultiIndex columns when >1 ticker, single-level when 1
    if len(tickers) == 1:
        closes = raw[["Close"]].rename(columns={"Close": tickers[0]})
    else:
        closes = raw["Close"]

    results: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        if ticker not in closes.columns:
            results[ticker] = {
                "momentum_12_1": None,
                "vol_252d": None,
                "sharpe_12m": None,
                "above_200d_sma": None,
            }
            continue

        series = closes[ticker].dropna()
        if len(series) < 60:
            results[ticker] = {
                "momentum_12_1": None,
                "vol_252d": None,
                "sharpe_12m": None,
                "above_200d_sma": None,
            }
            continue

        # Momentum 12-1: skip most recent month (t-2 to t-13)
        # t-2 ≈ 21 trading days ago; t-13 ≈ 252 trading days ago
        idx_t2 = max(0, len(series) - 21)
        idx_t13 = max(0, len(series) - 252)
        price_t2 = float(series.iloc[idx_t2])
        price_t13 = float(series.iloc[idx_t13]) if idx_t13 < idx_t2 else None
        momentum_12_1 = (
            price_t2 / price_t13 - 1.0 if price_t13 and price_t13 > 0 else None
        )

        # Vol 252d: annualised realised vol
        if len(series) >= 30:
            log_rets = np.log(series / series.shift(1)).dropna()
            recent = log_rets.iloc[-252:]
            vol_252d = (
                float(recent.std() * np.sqrt(252)) if len(recent) >= 20 else None
            )
        else:
            vol_252d = None

        # Sharpe-like: 12m return / 12m vol
        idx_12m = max(0, len(series) - 252)
        price_12m_ago = (
            float(series.iloc[idx_12m]) if idx_12m < len(series) - 1 else None
        )
        price_now = float(series.iloc[-1])
        ret_12m = (
            price_now / price_12m_ago - 1.0
            if price_12m_ago and price_12m_ago > 0
            else None
        )
        sharpe_12m = (
            ret_12m / vol_252d
            if ret_12m is not None and vol_252d and vol_252d > 0
            else None
        )

        # Trend regime: above 200-day SMA?
        if len(series) >= 200:
            sma_200 = float(series.iloc[-200:].mean())
            above_200d_sma = price_now > sma_200
        else:
            above_200d_sma = None

        results[ticker] = {
            "momentum_12_1": momentum_12_1,
            "vol_252d": vol_252d,
            "sharpe_12m": sharpe_12m,
            "above_200d_sma": above_200d_sma,
        }

    return results


# ── Fundamental factor fetch ──────────────────────────────────────────────────

def _fetch_fundamentals(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch earnings yield and ROE for the given ticker list via yf.Ticker.info."""
    import yfinance as yf

    log.info("Fetching fundamentals for %d tickers…", len(tickers))
    out: dict[str, dict[str, Any]] = {}
    for i, ticker in enumerate(tickers):
        if i % 25 == 0:
            log.info("  fundamentals %d/%d", i, len(tickers))
        try:
            info = yf.Ticker(ticker).info
            pe = info.get("trailingPE")
            roe = info.get("returnOnEquity")
            earnings_yield = (1.0 / pe) if pe and pe > 0 else None
            out[ticker] = {
                "earnings_yield": earnings_yield,
                "roe": float(roe) if roe is not None else None,
            }
        except Exception as exc:
            log.debug("fundamentals failed for %s: %s", ticker, exc)
            out[ticker] = {"earnings_yield": None, "roe": None}
    return out


# ── Storage ───────────────────────────────────────────────────────────────────

def _store_candidates(candidates: list[Candidate], db_path: Path) -> None:
    """Atomically replace the candidates table contents."""
    from cortex.storage.db import connect

    with connect(db_path) as conn:
        conn.execute("DELETE FROM candidates")
        if not candidates:
            return
        conn.executemany(
            """
            INSERT INTO candidates (
                ticker, as_of_date, discovered_at,
                momentum_12_1, vol_252d, sharpe_12m, above_200d_sma,
                earnings_yield, roe,
                z_momentum, z_low_vol, z_sharpe, z_value, z_quality,
                composite_score, composite_rank
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    c.ticker,
                    c.as_of_date,
                    c.discovered_at,
                    c.momentum_12_1,
                    c.vol_252d,
                    c.sharpe_12m,
                    c.above_200d_sma,
                    c.earnings_yield,
                    c.roe,
                    c.z_momentum,
                    c.z_low_vol,
                    c.z_sharpe,
                    c.z_value,
                    c.z_quality,
                    c.composite_score,
                    c.composite_rank,
                )
                for c in candidates
            ],
        )


def list_candidates(db_path: Path) -> list[Candidate]:
    """Load all candidates from the DB ordered by composite_rank."""
    from cortex.storage.db import connect

    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT
                ticker, as_of_date, discovered_at,
                momentum_12_1, vol_252d, sharpe_12m, above_200d_sma,
                earnings_yield, roe,
                z_momentum, z_low_vol, z_sharpe, z_value, z_quality,
                composite_score, composite_rank
            FROM candidates
            ORDER BY composite_rank
            """
        ).fetchall()

    return [
        Candidate(
            ticker=r[0],
            as_of_date=r[1],
            discovered_at=r[2],
            momentum_12_1=r[3],
            vol_252d=r[4],
            sharpe_12m=r[5],
            above_200d_sma=bool(r[6]) if r[6] is not None else None,
            earnings_yield=r[7],
            roe=r[8],
            z_momentum=r[9],
            z_low_vol=r[10],
            z_sharpe=r[11],
            z_value=r[12],
            z_quality=r[13],
            composite_score=r[14],
            composite_rank=r[15],
        )
        for r in rows
    ]


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_discovery(
    db_path: Path,
    top_n: int = 30,
    prefilter_n: int = 150,
) -> list[Candidate]:
    """Run the 6-factor CORTEX discovery pipeline.

    Pipeline:
        1. Load S&P 500 universe (~500 tickers)
        2. Bulk-download 13 months of price data (fast, yf.download)
        3. Compute price-based factors: momentum 12-1, vol 252d, Sharpe 12m,
           trend regime (200d SMA gate)
        4. Cross-sectional z-score price factors; compute price composite
        5. Pre-filter to top `prefilter_n` by price composite
        6. Fetch fundamentals (earnings yield, ROE) for the shortlist only
        7. Compute full 6-factor composite; rank; keep top `top_n`
        8. Persist results to DB (DELETE + re-INSERT)
    """
    from cortex.sources.universe import sp500_tickers

    as_of = date.today()
    now = datetime.now(tz=UTC)

    tickers = sp500_tickers()
    log.info("Universe: %d tickers", len(tickers))

    # ── Stage 1: price factors ────────────────────────────────────────────────
    price_data = _compute_price_factors(tickers)

    # ── Stage 2: trend gate + price composite pre-filter ─────────────────────
    # Exclude stocks below 200d SMA (Faber regime filter — hard gate)
    trend_ok = [
        t for t in tickers
        if price_data.get(t, {}).get("above_200d_sma") is not False
    ]
    log.info("After trend gate: %d tickers remain", len(trend_ok))

    # Price composite: z-score momentum, neg-z vol, z Sharpe → equal-weight avg
    mom_raw = {t: price_data[t]["momentum_12_1"] for t in trend_ok}
    vol_raw = {t: price_data[t]["vol_252d"] for t in trend_ok}
    shr_raw = {t: price_data[t]["sharpe_12m"] for t in trend_ok}

    z_mom = _zscore_series(mom_raw)
    # Low-vol: negate so lower vol → higher z-score
    z_vol_inv = _zscore_series(
        {t: (-v if v is not None else None) for t, v in vol_raw.items()}
    )
    z_shr = _zscore_series(shr_raw)

    def _price_composite(t: str) -> float:
        scores = [z_mom[t], z_vol_inv[t], z_shr[t]]
        valid = [s for s in scores if s is not None]
        return sum(valid) / len(valid) if valid else -999.0

    price_ranked = sorted(trend_ok, key=_price_composite, reverse=True)
    shortlist = price_ranked[:prefilter_n]
    log.info("Shortlist: top %d by price composite", len(shortlist))

    # ── Stage 3: fundamentals ─────────────────────────────────────────────────
    fund_data = _fetch_fundamentals(shortlist)

    # ── Stage 4: full 6-factor composite ─────────────────────────────────────
    ey_raw = {t: fund_data[t]["earnings_yield"] for t in shortlist}
    roe_raw = {t: fund_data[t]["roe"] for t in shortlist}

    z_ey = _zscore_series(ey_raw)
    z_roe = _zscore_series(roe_raw)

    # Recompute price z-scores over shortlist only (tighter cross-section)
    z_mom2 = _zscore_series({t: price_data[t]["momentum_12_1"] for t in shortlist})
    z_vol2 = _zscore_series(
        {
            t: (-v if (v := price_data[t]["vol_252d"]) is not None else None)
            for t in shortlist
        }
    )
    z_shr2 = _zscore_series({t: price_data[t]["sharpe_12m"] for t in shortlist})

    def _composite(t: str) -> float:
        scores = [z_mom2[t], z_vol2[t], z_shr2[t], z_ey[t], z_roe[t]]
        valid = [s for s in scores if s is not None]
        return sum(valid) / len(valid) if valid else -999.0

    ranked = sorted(shortlist, key=_composite, reverse=True)
    top = ranked[:top_n]

    candidates: list[Candidate] = []
    for rank, ticker in enumerate(top, start=1):
        pd_ = price_data[ticker]
        z_lv = z_vol2[ticker]
        comp = _composite(ticker)
        candidates.append(
            Candidate(
                ticker=ticker,
                as_of_date=as_of,
                discovered_at=now,
                momentum_12_1=pd_["momentum_12_1"],
                vol_252d=pd_["vol_252d"],
                sharpe_12m=pd_["sharpe_12m"],
                above_200d_sma=pd_["above_200d_sma"],
                earnings_yield=fund_data[ticker]["earnings_yield"],
                roe=fund_data[ticker]["roe"],
                z_momentum=z_mom2[ticker],
                z_low_vol=z_lv,
                z_sharpe=z_shr2[ticker],
                z_value=z_ey[ticker],
                z_quality=z_roe[ticker],
                composite_score=round(comp, 4),
                composite_rank=rank,
            )
        )

    log.info("Storing %d candidates", len(candidates))
    _store_candidates(candidates, db_path)
    return candidates
