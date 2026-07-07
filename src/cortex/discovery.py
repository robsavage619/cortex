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
    z_low_vol: float | None  # display-only: pre-registered OUT of the composite
    z_sharpe: float | None  # display-only: never in any tested composite
    z_value: float | None
    z_quality: float | None
    composite_score: float
    composite_rank: int
    z_trend: float | None = None
    z_congress: float | None = None
    z_fund_flow: float | None = None
    # True when persisted only because it was force-included (open thesis)
    # despite ranking outside top_n — the rank is still its true position.
    forced: bool = False


# ── Math helpers ──────────────────────────────────────────────────────────────


def _zscore_series(values: dict[str, float | None]) -> dict[str, float | None]:
    """Cross-sectional z-score, winsorized at ±Z_CLIP for parity with the
    backtest's ``_zscore``. Returns None for tickers that had None input."""
    from cortex.composite import Z_CLIP

    valid = {k: v for k, v in values.items() if v is not None}
    if len(valid) < 2:
        return {k: None for k in values}
    nums = list(valid.values())
    mean = sum(nums) / len(nums)
    variance = sum((x - mean) ** 2 for x in nums) / len(nums)
    std = variance**0.5
    if std == 0:
        return {k: (0.0 if k in valid else None) for k in values}
    out: dict[str, float | None] = {}
    for k in values:
        if k in valid:
            out[k] = max(-Z_CLIP, min(Z_CLIP, (valid[k] - mean) / std))
        else:
            out[k] = None
    return out


# ── Price-based factor computation ────────────────────────────────────────────


# Batch size for yfinance bulk downloads. Downloading the whole S&P 500 in one
# call builds a ~500-column float64 DataFrame whose concat peak OOM-kills a small
# instance; 50-ticker batches keep peak memory flat and are released between batches.
_PRICE_BATCH = 50


def _compute_price_factors(
    tickers: list[str],
) -> dict[str, dict[str, Any]]:
    """Download 13 months of daily close prices and compute price-based factors.

    Downloads in :data:`_PRICE_BATCH`-sized batches so peak memory stays flat
    regardless of universe size. Returns a dict keyed by ticker with keys:
        momentum_12_1, vol_252d, sharpe_12m, above_200d_sma
    """
    import gc

    log.info("Downloading price data for %d tickers (13mo, batched)…", len(tickers))
    results: dict[str, dict[str, Any]] = {}
    for start in range(0, len(tickers), _PRICE_BATCH):
        results.update(_price_factors_batch(tickers[start : start + _PRICE_BATCH]))
        gc.collect()
    return results


def _price_factors_batch(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """Compute price factors for one batch of tickers (see _compute_price_factors)."""
    import numpy as np
    import yfinance as yf

    raw: Any = yf.download(
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
    # float32 halves resident price memory; factor math tolerates it fine.
    closes = closes.astype("float32")
    del raw

    results: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        if ticker not in closes.columns:
            results[ticker] = {
                "momentum_12_1": None,
                "vol_252d": None,
                "sharpe_12m": None,
                "above_200d_sma": None,
                "trend_200d": None,
                "last_close": None,
            }
            continue

        series = closes[ticker].dropna()
        if len(series) < 60:
            results[ticker] = {
                "momentum_12_1": None,
                "vol_252d": None,
                "sharpe_12m": None,
                "above_200d_sma": None,
                "trend_200d": None,
                "last_close": None,
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
            vol_252d = float(recent.std() * np.sqrt(252)) if len(recent) >= 20 else None
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

        # Trend: continuous distance to the 200-day SMA (the backtest's
        # trend factor); the boolean gate derives from its sign.
        if len(series) >= 200:
            sma_200 = float(series.iloc[-200:].mean())
            above_200d_sma = price_now > sma_200
            trend_200d = price_now / sma_200 - 1.0 if sma_200 > 0 else None
        else:
            above_200d_sma = None
            trend_200d = None

        results[ticker] = {
            "momentum_12_1": momentum_12_1,
            "vol_252d": vol_252d,
            "sharpe_12m": sharpe_12m,
            "above_200d_sma": above_200d_sma,
            "trend_200d": trend_200d,
            "last_close": price_now,
        }

    return results


# ── Fundamental factor fetch ──────────────────────────────────────────────────


def _pit_fundamentals(
    db_path: Path,
    tickers: list[str],
    price_data: dict[str, dict[str, Any]],
    as_of: date,
) -> dict[str, dict[str, Any]]:
    """Point-in-time earnings yield and ROE from the ``fundamentals`` table.

    Same source and gating the backtest uses (latest filing with
    filing_date ≤ as_of) — replaces the old yf.Ticker.info shortcut, which
    served numbers the backtest never validated.
    """
    from cortex.backtest import _fundamental_asof, _load_fundamentals

    fmap = _fundamental_asof(_load_fundamentals(db_path), as_of)
    out: dict[str, dict[str, Any]] = {}
    covered = 0
    for ticker in tickers:
        fp = fmap.get(ticker)
        last_close = price_data.get(ticker, {}).get("last_close")
        earnings_yield = None
        roe = None
        if fp is not None:
            if fp.eps_diluted is not None and last_close and last_close > 0:
                earnings_yield = fp.eps_diluted / last_close
            roe = fp.roe
        if earnings_yield is not None or roe is not None:
            covered += 1
        out[ticker] = {"earnings_yield": earnings_yield, "roe": roe}
    log.info(
        "Fundamentals (point-in-time, filing_date ≤ %s): %d/%d tickers covered",
        as_of,
        covered,
        len(tickers),
    )
    if covered == 0:
        log.warning(
            "Fundamentals table empty or stale — fund block will be missing "
            "from every composite (run `cortex fundamentals-sync`)"
        )
    return out


def _flow_scores(
    db_path: Path, tickers: list[str], as_of: date
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    """Congress + 13F decayed net-flow scores, disclosure-gated at as_of.

    Reuses the backtest's event loaders and decay math with the canonical
    half-life constants. Tickers with no events in the window get None
    (sparse coverage — z-scored over event-having names only, matching the
    backtest's NaN semantics).
    """
    from cortex.backtest import (
        _flow_score,
        _load_congress_events,
        _load_fund_events,
    )
    from cortex.composite import (
        CONGRESS_HALFLIFE,
        CONGRESS_WINDOW,
        FUND_HALFLIFE,
        FUND_WINDOW,
    )

    cong_map = _flow_score(
        _load_congress_events(db_path), as_of, CONGRESS_HALFLIFE, CONGRESS_WINDOW
    )
    fund_map = _flow_score(
        _load_fund_events(db_path), as_of, FUND_HALFLIFE, FUND_WINDOW
    )
    cong = {t: cong_map.get(t) for t in tickers}
    fund = {t: fund_map.get(t) for t in tickers}
    log.info(
        "Flow coverage: congress %d, 13F %d of %d tickers",
        sum(1 for v in cong.values() if v is not None),
        sum(1 for v in fund.values() if v is not None),
        len(tickers),
    )
    return cong, fund


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
                composite_score, composite_rank,
                z_trend, z_congress, z_fund_flow, forced
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    c.z_trend,
                    c.z_congress,
                    c.z_fund_flow,
                    c.forced,
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
                composite_score, composite_rank,
                z_trend, z_congress, z_fund_flow, forced
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
            z_trend=r[16],
            z_congress=r[17],
            z_fund_flow=r[18],
            forced=bool(r[19]),
        )
        for r in rows
    ]


# ── Main pipeline ─────────────────────────────────────────────────────────────


def run_discovery(
    db_path: Path,
    top_n: int = 30,
    prefilter_n: int | None = None,
    force_include: list[str] | None = None,
) -> list[Candidate]:
    """Run CORTEX discovery — the live computation of the BACKTESTED composite.

    The composite definition lives in :mod:`cortex.composite` (three equal
    blocks: price = momentum/trend, fundamental = value/quality, flow =
    congress/13F). Low-vol and Sharpe are computed for display only — both
    are pre-registered OUT of the composite.

    Args:
        top_n: How many top-ranked candidates to persist.
        prefilter_n: Ignored — retained for call-site compatibility. The old
            150-ticker prefilter (and its shortlist z-score recompute) made
            live scores incomparable to the backtest and was removed.
        force_include: Tickers to always score and persist regardless of rank
            (e.g. active thesis tickers). They are scored truthfully — the
            composite and rank reflect their true cross-sectional position —
            and rows outside top_n carry ``forced = True``.

    Pipeline:
        1. Load S&P 500 universe (~500 tickers); bulk-download 13mo of prices
        2. Hard trend gate: drop stocks below the 200d SMA (Faber regime
           filter — the one documented, conservative-only divergence from
           the backtest, which scores below-trend names too)
        3. Point-in-time fundamentals from the ``fundamentals`` table and
           decayed congress/13F flow scores — the backtest's own loaders
        4. ONE cross-sectional z-pass over the full gated universe
           (winsorized ±3), canonical composite, rank ALL scored tickers
        5. Persist top_n plus force-included rows (DELETE + re-INSERT)
    """
    _ = prefilter_n  # removed: shortlist z-recompute broke backtest parity
    from cortex.sources.universe import sp500_tickers

    as_of = date.today()
    now = datetime.now(tz=UTC)

    tickers = sp500_tickers()
    log.info("Universe: %d tickers", len(tickers))

    # ── Stage 1: price factors ────────────────────────────────────────────────
    price_data = _compute_price_factors(tickers)

    # ── Stage 2: hard trend gate ──────────────────────────────────────────────
    # Below-200d-SMA stocks are excluded from the live list (conservatism);
    # force-included thesis tickers are scored and persisted regardless.
    trend_ok = [
        t for t in tickers if price_data.get(t, {}).get("above_200d_sma") is not False
    ]
    scored = list(trend_ok)
    for t in force_include or []:
        if t in price_data and t not in scored:
            scored.append(t)
            log.info("Force-including %s (below trend gate or outside universe)", t)
    log.info(
        "Scored cross-section: %d tickers (%d passed trend gate, %d forced in)",
        len(scored),
        len(trend_ok),
        len(scored) - len(trend_ok),
    )

    # ── Stage 3: point-in-time fundamentals + flow scores ────────────────────
    fund_data = _pit_fundamentals(db_path, scored, price_data, as_of)
    cong_raw, fundflow_raw = _flow_scores(db_path, scored, as_of)

    # ── Stage 4: single z-pass + canonical composite ─────────────────────────
    z_mom = _zscore_series({t: price_data[t]["momentum_12_1"] for t in scored})
    z_trend = _zscore_series({t: price_data[t]["trend_200d"] for t in scored})
    z_ey = _zscore_series({t: fund_data[t]["earnings_yield"] for t in scored})
    z_roe = _zscore_series({t: fund_data[t]["roe"] for t in scored})
    z_cong = _zscore_series(cong_raw)
    z_fund = _zscore_series(fundflow_raw)
    # Display-only (pre-registered out of the composite):
    z_vol_inv = _zscore_series(
        {
            t: (-v if (v := price_data[t]["vol_252d"]) is not None else None)
            for t in scored
        }
    )
    z_shr = _zscore_series({t: price_data[t]["sharpe_12m"] for t in scored})

    def _composite(t: str) -> float:
        # Mirror of composite.build_blocks for dict inputs: nanmean of the
        # available factors per block, nanmean of the available blocks.
        blocks = []
        for pair in (
            (z_mom[t], z_trend[t]),
            (z_ey[t], z_roe[t]),
            (z_cong[t], z_fund[t]),
        ):
            valid = [v for v in pair if v is not None]
            if valid:
                blocks.append(sum(valid) / len(valid))
        return sum(blocks) / len(blocks) if blocks else -999.0

    ranked = sorted(scored, key=_composite, reverse=True)
    rank_of = {t: i for i, t in enumerate(ranked, start=1)}
    top = set(ranked[:top_n])
    forced_set = {t for t in (force_include or []) if t in rank_of and t not in top}
    to_persist = sorted(top | forced_set, key=lambda t: rank_of[t])

    candidates: list[Candidate] = []
    for ticker in to_persist:
        pd_ = price_data[ticker]
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
                z_momentum=z_mom[ticker],
                z_low_vol=z_vol_inv[ticker],
                z_sharpe=z_shr[ticker],
                z_value=z_ey[ticker],
                z_quality=z_roe[ticker],
                composite_score=round(comp, 4),
                composite_rank=rank_of[ticker],
                z_trend=z_trend[ticker],
                z_congress=z_cong[ticker],
                z_fund_flow=z_fund[ticker],
                forced=ticker in forced_set,
            )
        )

    log.info("Storing %d candidates", len(candidates))
    _store_candidates(candidates, db_path)
    return candidates
