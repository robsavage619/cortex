"""Point-in-time backtest for the CORTEX composite buy-signal.

Designed to a strict methodology (no look-ahead, zero tunable parameters):

- Composite = three equal blocks, each the nanmean of its factors
  (see ``_build_signals``): price (momentum 12-1, trend = continuous
  distance to 200d SMA), fundamental (earnings yield, ROE — point-in-time
  EDGAR filings gated on filing_date), flow (congressional net-buy,
  13F institutional net-buy).
- Low-vol is pre-registered OUT of the price block (2026-05-23); insider
  Form 4 is pre-registered OUT of the flow block (2026-05-28, NW t=-0.43).
  Both are still computed for the per-factor ablation.
- Monthly rebalance, long-only top decile, equal-weighted, vs an equal-weight
  S&P-500 benchmark, net of transaction costs (10 bps/side).
- PRICE-ONLY and PRICE+FUND composites run as null models: flow factors only
  earn credit if the full composite beats them.

KNOWN BIASES (disclosed, not hidden):
- Universe = point-in-time S&P 500 membership (vendored snapshot history in
  data/reference/sp500_history.csv); each monthly cross-section keeps only
  that month's true members. Residual delisting bias remains where neither
  yfinance nor the Stooq fallback can price a dead ticker — the per-month
  coverage ratio in the report measures exactly that gap. (Stooq is
  currently gated by a JS challenge, so in practice the gap ≈ all names
  yfinance can no longer price.)
- Flow factors are sparse and momentum-correlated; treat as a tilt.
"""

from __future__ import annotations

import logging
import math
import re
import warnings
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from cortex.composite import (
    ACTIVISM_HALFLIFE as _ACTIVISM_HALFLIFE,
)
from cortex.composite import (
    ACTIVISM_WINDOW as _ACTIVISM_WINDOW,
)
from cortex.composite import (
    CONGRESS_HALFLIFE as _CONGRESS_HALFLIFE,
)
from cortex.composite import (
    CONGRESS_WINDOW as _CONGRESS_WINDOW,
)
from cortex.composite import (
    FUND_HALFLIFE as _FUND_HALFLIFE,
)
from cortex.composite import (
    FUND_SELL_WEIGHT,
    build_blocks,
)
from cortex.composite import (
    FUND_WINDOW as _FUND_WINDOW,
)
from cortex.composite import (
    INSIDER_HALFLIFE as _INSIDER_HALFLIFE,
)
from cortex.composite import (
    INSIDER_WINDOW as _INSIDER_WINDOW,
)
from cortex.composite import (
    Z_CLIP as _Z_CLIP,
)

log = logging.getLogger(__name__)

_COST_PER_SIDE = 0.0010  # 10 bps
_SHORT_COST_EXTRA = 0.0015  # extra 15 bps/side on the short leg (borrow/locate)
_TRADING_DAYS = 252


# ── amount parsing ───────────────────────────────────────────────────────────


def _amount_midpoint(amount: str) -> float:
    """Map a Senate dollar-range string to a midpoint notional (USD)."""
    nums = [
        float(x.replace(",", ""))
        for x in re.findall(r"\$?\s*([\d,]+)", amount or "")
        if x.replace(",", "").isdigit()
    ]
    if not nums:
        return 0.0
    if len(nums) == 1:
        return nums[0]
    return (nums[0] + nums[1]) / 2.0


def _congress_sign(transaction_type: str) -> int:
    """Map a disclosure's transaction type to a buy/sell/ignore sign.

    The two chambers do not speak the same language. Senate eFD writes English
    ("Purchase", "Sale (Full)"); House PTRs carry SEC single-letter codes
    ("P", "S", "S (partial)"). Handling only the Senate form silently zeroed
    roughly 14,300 of 14,551 House rows.

    The code form is tested first and on the leading token only: a bare "s"
    must not fall through to the substring test, and "p" must not match the
    "partial" in "S (partial)".
    """
    t = (transaction_type or "").strip().lower()
    if not t:
        return 0
    code = t.split()[0].rstrip(".")
    if code == "p":
        return 1
    if code == "s":
        return -1
    if code == "e":  # exchange — neither a buy nor a sell
        return 0
    if "purchase" in t:
        return 1
    if "sale" in t:
        return -1
    return 0


# ── event loading (point-in-time) ────────────────────────────────────────────


@dataclass
class _Event:
    ticker: str
    when: date
    signed_weight: float


def _load_congress_events(db_path: Path) -> list[_Event]:
    from cortex.storage.db import connect

    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT ticker, disclosure_date, transaction_date,
                   transaction_type, amount
            FROM congress_trades
            WHERE amended IS NOT TRUE
              AND ticker_ok IS NOT FALSE
            """
        ).fetchall()
    events: list[_Event] = []
    for ticker, disc, txn, ttype, amount in rows:
        when = disc or txn  # gate on disclosure (public knowledge) date
        sign = _congress_sign(ttype)
        if when is None or sign == 0:
            continue
        notional = _amount_midpoint(amount)
        if notional <= 0:
            continue
        events.append(_Event(ticker.upper(), when, sign * notional))
    return events


@dataclass
class _Fundamental:
    ticker: str
    filing_date: date
    eps_diluted: float | None
    roe: float | None


def _load_fundamentals(db_path: Path) -> list[_Fundamental]:
    """Point-in-time annual fundamentals, oldest filing first.

    A single 10-K carries several comparative periods, so many rows share one
    filing_date; period_end breaks the tie so the last-wins scan in
    :func:`_fundamental_asof` lands on the newest period the filing disclosed
    rather than an arbitrary storage-order row.

    EPS is restated onto the split basis of the cached price series, which
    yfinance back-adjusts to the present. Only the cached ``splits`` table is
    consulted — never the network — so a backtest re-run stays reproducible;
    warm it via :func:`cortex.sources.splits.load_splits` before relying on the
    value factor. ROE is a ratio and needs no adjustment.
    """
    from cortex.sources.splits import load_splits, split_factor_since
    from cortex.storage.db import connect

    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT ticker, filing_date, eps_diluted, net_income, equity
                FROM fundamentals
                ORDER BY filing_date, period_end
                """
            ).fetchall()
    except Exception:  # noqa: BLE001 - table may be empty/absent
        return []

    today = date.today()
    splits = load_splits(db_path, [r[0].upper() for r in rows], fetch_missing=False)
    out: list[_Fundamental] = []
    for ticker, fd, eps, ni, eq in rows:
        tk = ticker.upper()
        roe = (ni / eq) if (ni is not None and eq not in (None, 0)) else None
        if eps is not None and fd is not None:
            factor = split_factor_since(splits.get(tk, []), fd, today)
            if factor != 1.0:
                eps = eps / factor
        out.append(_Fundamental(tk, fd, eps, roe))
    return out


def _fundamental_asof(
    funds: list[_Fundamental], as_of: date
) -> dict[str, _Fundamental]:
    """Latest fundamental per ticker filed on or before as_of (point-in-time)."""
    latest: dict[str, _Fundamental] = {}
    for f in funds:  # sorted ascending by filing_date
        if f.filing_date <= as_of:
            latest[f.ticker] = f
        else:
            break
    return latest


def _load_activism_events(db_path: Path) -> list[_Event]:
    """Load 13D initial filings as unit buy events, gated on filing_date."""
    from cortex.storage.db import connect

    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                "SELECT ticker, filing_date FROM activist_stakes"
            ).fetchall()
    except Exception:  # noqa: BLE001 - table may not exist yet
        return []
    return [
        _Event(ticker.upper(), filing_date, 1.0)
        for ticker, filing_date in rows
        if filing_date is not None
    ]


def _load_executive_events(db_path: Path) -> list[_Event]:
    """Load executive-branch company mentions, gated on the mention date.

    A positive mention is a unit buy event; negative is a unit sell. Neutral
    mentions carry no directional weight and are dropped by the >0 filter.
    """
    from cortex.storage.db import connect

    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                "SELECT ticker, mention_date, stance FROM executive_mentions"
            ).fetchall()
    except Exception:  # noqa: BLE001 - table may not exist yet
        return []
    sign = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
    return [
        _Event(ticker.upper(), mention_date, sign.get(stance, 0.0))
        for ticker, mention_date, stance in rows
        if mention_date is not None
    ]


def _load_insider_events(db_path: Path) -> list[_Event]:
    """Load Form 4 open-market purchase events (point-in-time via filing_date).

    Two departures from a plain dollar-weighted sum, both from Lakonishok & Lee
    (2001), whose strongest screen is built on distinct-insider count rather
    than volume:

    * **Distinct filers matter more than repeat trades.** Three officers buying
      is a stronger signal than one officer buying three times, so each event
      is scaled by the count of distinct filers on that issuer in the month.
    * **Dollars are ranked, not logged.** A raw ``log1p(value_usd)`` weight
      mechanically favours mega-caps — a $2M buy is a rounding error at a $3T
      company and a statement at a $5B one, and the log scale scores them
      almost identically. LL use dollars only as a size-relative rank, so the
      weight is the trade's percentile within its own month.
    """
    from cortex.storage.db import connect

    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                """
                WITH scored AS (
                    SELECT
                        ticker,
                        filing_date,
                        value_usd,
                        date_trunc('month', filing_date) AS mo,
                        COUNT(DISTINCT filer_cik) OVER (
                            PARTITION BY issuer_cik, date_trunc('month', filing_date)
                        ) AS distinct_filers
                    FROM insider_buys
                    WHERE filing_date IS NOT NULL
                      AND value_usd > 0
                )
                SELECT
                    ticker,
                    filing_date,
                    distinct_filers,
                    PERCENT_RANK() OVER (PARTITION BY mo ORDER BY value_usd)
                        AS size_rank
                FROM scored
                """
            ).fetchall()
    except Exception:  # noqa: BLE001 - table may not exist yet
        return []

    events: list[_Event] = []
    for ticker, filing_date, distinct_filers, size_rank in rows:
        # percent_rank is 0 for the smallest trade in a month; floor it so a
        # genuine buy never contributes exactly nothing.
        rank = max(float(size_rank or 0.0), 0.01)
        weight = rank * math.log1p(float(distinct_filers or 1))
        if weight <= 0:
            continue
        events.append(_Event(ticker.upper(), filing_date, weight))
    return events


def _load_fund_events(db_path: Path) -> list[_Event]:
    """Load 13F position changes as signed flow events.

    ``fund_holdings.period`` already stores the 13F *filing* date, not the
    quarter-end, so these events are point-in-time as loaded.

    An EXIT closes the position, so its ``value`` is 0 and its magnitude has to
    come from the prior holding: ``prev_shares`` priced at the last close on or
    before the filing date. Sizing it off ``value`` drops every EXIT and leaves
    the factor's negative leg carrying TRIM alone.
    """
    from cortex.storage.db import connect

    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT
                f.ticker,
                f.period,
                f.action,
                CASE
                    WHEN f.action = 'EXIT' THEN f.prev_shares * (
                        SELECT p.close
                        FROM prices p
                        WHERE p.ticker = f.ticker
                          AND p.date <= f.period
                          AND p.date >= f.period - 10
                        ORDER BY p.date DESC
                        LIMIT 1
                    )
                    ELSE f.value
                END AS magnitude
            FROM fund_holdings f
            """
        ).fetchall()

    events: list[_Event] = []
    unpriced_exits = 0
    for ticker, period, action, magnitude in rows:
        if period is None:
            continue
        if action == "EXIT" and magnitude is None:
            # No cached price within 10 days — cannot size the closed position.
            unpriced_exits += 1
            continue
        buy = action in ("NEW", "ADD")
        sign = 1.0 if buy else -FUND_SELL_WEIGHT
        weight = math.log1p(float(magnitude or 0))
        if weight <= 0:
            continue
        events.append(_Event(ticker.upper(), period, sign * weight))

    if unpriced_exits:
        log.warning(
            "fund events: dropped %d EXIT rows with no cached price within 10 "
            "days of the filing date; their sell pressure is missing from the "
            "factor",
            unpriced_exits,
        )
    return events


def _flow_score(
    events: list[_Event],
    as_of: date,
    halflife: float,
    window_days: int,
) -> dict[str, float]:
    """Decayed signed net flow per ticker, using only events disclosed by as_of."""
    floor = as_of - timedelta(days=window_days)
    out: dict[str, float] = {}
    for ev in events:
        if ev.when > as_of or ev.when < floor:
            continue
        age = (as_of - ev.when).days
        decay = 0.5 ** (age / halflife)
        out[ev.ticker] = out.get(ev.ticker, 0.0) + ev.signed_weight * decay
    return out


# ── cross-sectional helpers ──────────────────────────────────────────────────


def _zscore(values: np.ndarray) -> np.ndarray:
    """Winsorized cross-sectional z-score; NaNs preserved."""
    mask = ~np.isnan(values)
    if mask.sum() < 5:
        return np.full_like(values, np.nan)
    mu = values[mask].mean()
    sd = values[mask].std()
    if sd == 0:
        return np.where(mask, 0.0, np.nan)
    z = (values - mu) / sd
    return np.clip(z, -_Z_CLIP, _Z_CLIP)


def _spearman_ic(signal: np.ndarray, fwd: np.ndarray) -> float | None:
    mask = ~np.isnan(signal) & ~np.isnan(fwd)
    if mask.sum() < 10:
        return None
    s = signal[mask]
    f = fwd[mask]
    rs = np.argsort(np.argsort(s)).astype(float)
    rf = np.argsort(np.argsort(f)).astype(float)
    rs -= rs.mean()
    rf -= rf.mean()
    denom = math.sqrt((rs**2).sum() * (rf**2).sum())
    if denom == 0:
        return None
    return float((rs * rf).sum() / denom)


# ── result model ─────────────────────────────────────────────────────────────


@dataclass
class StrategyResult:
    label: str
    n_months: int
    mean_ic: float
    ic_tstat: float  # naive IID t-stat (mean·√n / std)
    ic_tstat_nw: float  # Newey-West HAC t-stat (autocorrelation-robust)
    cagr: float
    sharpe: float
    max_drawdown: float
    hit_rate: float
    avg_turnover: float
    decile_cagr: list[float] = field(default_factory=list)


@dataclass
class FactorIC:
    factor: str
    mean_ic: float
    ic_tstat: float  # naive IID t-stat
    ic_tstat_nw: float  # Newey-West HAC t-stat
    coverage: float  # avg fraction of universe with the factor present
    pct_months_positive: float = 0.0
    """Share of scored months with a positive IC.

    MacKinlay (1997) asks for the percent-positive alongside the mean, and Katz
    et al. (2018) note it is almost never reported — a mean IC says nothing
    about whether an effect is broad or a handful of outlier months carrying an
    otherwise-flat series. Near 50% means the sign is a coin flip regardless of
    what the mean looks like.
    """


@dataclass
class LongShortResult:
    """Top-decile-minus-bottom-decile spread of the CORTEX composite.

    The long-short return strips market beta from the long-only top decile,
    isolating the factor's directional content. A real factor produces a
    positive spread whose mean clears the HAC t-stat bar.

    Gross and net are both reported: net charges turnover-based costs of
    10 bps/side on the long leg and 25 bps/side on the short leg (the extra
    15 bps is a disclosed borrow/locate assumption).
    """

    mean_monthly: float
    tstat_nw: float
    cagr: float
    sharpe: float
    n_months: int
    mean_monthly_net: float = 0.0
    tstat_nw_net: float = 0.0
    cagr_net: float = 0.0
    sharpe_net: float = 0.0


@dataclass
class FactorCorrelation:
    """Pairwise correlation of the per-factor monthly IC time series.

    Answers whether the flow factors (congress/insider/13F) carry information
    beyond the price factors, or merely re-express momentum.
    """

    factors: list[str]
    matrix: list[list[float | None]]  # None where overlap < 6 months


@dataclass
class BacktestReport:
    start: date
    end: date
    n_names: int
    benchmark_cagr: float
    benchmark_sharpe: float
    variants: list[StrategyResult] = field(default_factory=list)
    factor_ics: list[FactorIC] = field(default_factory=list)
    long_short: LongShortResult | None = None
    factor_corr: FactorCorrelation | None = None
    n_tickers_requested: int = 0
    n_tickers_priced: int = 0
    # Point-in-time universe honesty: fraction of that month's actual S&P 500
    # members we could price. <1.0 means residual delisting bias remains.
    universe_coverage_mean: float = 0.0
    universe_coverage_min: float = 0.0
    # Cap-weighted reality check ("would I have just bought the index?").
    # The EW benchmark stays the fair null — the strategy itself is EW.
    spy_cagr: float | None = None
    spy_sharpe: float | None = None


def _annualize(monthly: list[float]) -> tuple[float, float, float]:
    """Return (CAGR, annualized Sharpe, max drawdown) from monthly returns."""
    if not monthly:
        return 0.0, 0.0, 0.0
    arr = np.array(monthly)
    growth = np.prod(1 + arr)
    years = len(arr) / 12.0
    cagr = growth ** (1 / years) - 1 if years > 0 and growth > 0 else -1.0
    sharpe = (arr.mean() / arr.std() * math.sqrt(12)) if arr.std() > 0 else 0.0
    curve = np.cumprod(1 + arr)
    peak = np.maximum.accumulate(curve)
    max_dd = float((curve / peak - 1).min())
    return float(cagr), float(sharpe), max_dd


def _nw_tstat(values: list[float], lag: int | None = None) -> float:
    """Newey-West HAC t-stat for the mean of a serially-correlated series.

    Monthly cross-sectional ICs from slow-decaying signals are autocorrelated,
    so the naive IID t-stat (mean·√n / std) overstates significance. This
    applies a Bartlett-kernel HAC correction; the lag defaults to the
    Newey-West (1994) plug-in rule ⌊4·(n/100)^(2/9)⌋.
    """
    a = np.asarray([v for v in values if not math.isnan(v)], dtype=float)
    n = a.size
    if n < 3:
        return 0.0
    mean = float(a.mean())
    dev = a - mean
    if lag is None:
        lag = int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    lag = max(1, min(lag, n - 1))
    lrv = float((dev * dev).mean())  # gamma_0
    for k in range(1, lag + 1):
        weight = 1.0 - k / (lag + 1.0)  # Bartlett kernel
        lrv += 2.0 * weight * float((dev[k:] * dev[:-k]).mean())
    if lrv <= 0:
        return 0.0
    se = math.sqrt(lrv / n)
    return float(mean / se) if se > 0 else 0.0


def _series_stats(values: list[float]) -> tuple[float, float, float]:
    """Return (mean, naive IID t-stat, Newey-West HAC t-stat) for a series."""
    a = np.asarray([v for v in values if not math.isnan(v)], dtype=float)
    if a.size == 0:
        return 0.0, 0.0, 0.0
    mean = float(a.mean())
    naive_t = float(mean / a.std() * math.sqrt(a.size)) if a.std() > 0 else 0.0
    return mean, naive_t, _nw_tstat(list(a))


def _factor_corr(
    series: dict[str, list[float]], keys: tuple[str, ...]
) -> FactorCorrelation:
    """Pairwise correlation of aligned per-factor monthly IC series.

    Series carry NaN for months a factor was unscored; each pair is correlated
    over its complete-overlap months only (None if fewer than 6).
    """
    arrs = {k: np.asarray(series[k], dtype=float) for k in keys}
    matrix: list[list[float | None]] = []
    for ki in keys:
        ai = arrs[ki]
        row: list[float | None] = []
        for kj in keys:
            aj = arrs[kj]
            mask = ~np.isnan(ai) & ~np.isnan(aj)
            if mask.sum() < 6 or ai[mask].std() == 0 or aj[mask].std() == 0:
                row.append(None)
            else:
                row.append(float(np.corrcoef(ai[mask], aj[mask])[0, 1]))
        matrix.append(row)
    return FactorCorrelation(list(keys), matrix)


def _top_decile_return(
    sig: np.ndarray,
    fwd: np.ndarray,
    prev: set[int],
    top_decile: float,
) -> tuple[float, float, set[int]]:
    """Net forward return of the equal-weight top-decile bucket + turnover."""
    valid = np.where(~np.isnan(sig) & np.isfinite(fwd))[0]
    if len(valid) < 20:
        return float("nan"), 0.0, prev
    order = valid[np.argsort(sig[valid])[::-1]]
    n_top = max(1, int(len(order) * top_decile))
    top = set(order[:n_top].tolist())
    gross = float(np.mean([fwd[m] for m in top]))
    turn = len(top.symmetric_difference(prev)) / max(len(top), 1) if prev else 1.0
    net = gross - turn * _COST_PER_SIDE
    return net, turn, top


def _build_signals(
    zmom: np.ndarray,
    ztrend: np.ndarray,
    zvol: np.ndarray,
    zval: np.ndarray,
    zqual: np.ndarray,
    zcong: np.ndarray,
    zfund: np.ndarray,
    zinside: np.ndarray,
) -> dict[str, np.ndarray]:
    """Build composite variants — thin wrapper over ``composite.build_blocks``.

    The definition, block structure and pre-registration history live in
    :mod:`cortex.composite` — the single source of truth shared with live
    discovery. ``zvol`` and ``zinside`` are accepted for the ablation but
    pre-registered OUT of every composite (low-vol 2026-05-23; insider
    2026-05-28, NW t = -0.43).
    """
    _ = zvol, zinside  # ablation-only; pre-registered out of the composite
    return build_blocks(zmom, ztrend, zval, zqual, zcong, zfund)


def run_backtest(
    db_path: Path,
    *,
    start_year: int = 2017,
    top_decile: float = 0.10,
) -> BacktestReport:
    """Run the point-in-time backtest. Prices come from the DuckDB cache."""
    from cortex.sources.prices import load_closes
    from cortex.sources.universe import sp500_members_asof, sp500_union

    # One extra year of history for the 252d lookback warmup.
    hist_start = date(start_year - 1, 1, 1)
    # Point-in-time universe: every name that was a member at any point in the
    # window; each monthly cross-section keeps only that month's true members.
    tickers = sp500_union(hist_start)
    log.info(
        "Backtest universe: %d point-in-time members (union since %s)",
        len(tickers),
        hist_start,
    )

    # SPY rides along as a cap-weighted reality check; the membership mask
    # keeps it out of every cross-section.
    closes: Any = load_closes(db_path, [*tickers, "SPY"], hist_start)
    closes = closes.dropna(how="all")
    # yfinance silently omits tickers it fails to price — make the gap visible.
    closes = closes.dropna(axis=1, how="all")
    n_requested = len(tickers)
    n_priced = int(closes.shape[1]) - (1 if "SPY" in closes.columns else 0)
    coverage = n_priced / n_requested if n_requested else 0.0
    missing = sorted(set(tickers) - set(closes.columns))
    if coverage < 0.95:
        log.warning(
            "Price coverage %d/%d (%.1f%%) — missing: %s",
            n_priced,
            n_requested,
            100 * coverage,
            missing[:20],
        )
    else:
        log.info("Price coverage %d/%d (%.1f%%)", n_priced, n_requested, 100 * coverage)
    cols = list(closes.columns)
    col_idx = {t: i for i, t in enumerate(cols)}
    price_arr = closes.to_numpy()  # [days, names]
    log_px = np.log(price_arr)
    daily_idx: Any = closes.index

    congress_events = _load_congress_events(db_path)
    fund_events = _load_fund_events(db_path)
    activism_events = _load_activism_events(db_path)
    insider_events = _load_insider_events(db_path)
    fundamentals = _load_fundamentals(db_path)
    log.info(
        "Loaded %d congress, %d fund, %d activism, %d insider, %d fundamental points",
        len(congress_events),
        len(fund_events),
        len(activism_events),
        len(insider_events),
        len(fundamentals),
    )

    # Month-end trading positions.
    me_marks = closes.resample("ME").last().index
    positions = daily_idx.searchsorted(me_marks, side="right") - 1
    positions = sorted({int(p) for p in positions if p >= _TRADING_DAYS})
    rebal: list[int] = [p for p in positions if p < len(daily_idx) - 1]

    n_names = price_arr.shape[1]
    variant_keys = ("cortex", "price", "price_fund")
    factor_keys = (
        "mom",
        "trend",
        "vol",
        "value",
        "quality",
        "congress",
        "fund",
        "activism",
        "insider",
    )

    rets: dict[str, list[float]] = {k: [] for k in variant_keys}
    turns: dict[str, list[float]] = {k: [] for k in variant_keys}
    prev: dict[str, set[int]] = {k: set() for k in variant_keys}
    var_ic: dict[str, list[float]] = {k: [] for k in variant_keys}
    fac_ic: dict[str, list[float]] = {k: [] for k in factor_keys}
    # Aligned per-month IC (NaN when unscored) for the factor-correlation matrix.
    fac_ic_series: dict[str, list[float]] = {k: [] for k in factor_keys}
    fac_cov: dict[str, list[float]] = {k: [] for k in factor_keys}
    bench_rets: list[float] = []
    spy_rets: list[float] = []
    decile_acc: list[list[float]] = [[] for _ in range(10)]
    ls_sets: list[tuple[set[int], set[int]]] = []
    universe_cov: list[float] = []
    spy_col = col_idx.get("SPY")

    for k in range(len(rebal) - 1):
        i = rebal[k]
        j = rebal[k + 1]
        as_of = daily_idx[i].date()

        members = sp500_members_asof(as_of)
        member_mask = np.fromiter(
            (t in members for t in cols), dtype=bool, count=n_names
        )

        p_now = price_arr[i]
        p_21 = price_arr[i - 21]
        p_252 = price_arr[i - 252]
        sma200 = price_arr[i - 199 : i + 1].mean(axis=0)
        win = log_px[i - 251 : i + 1]
        vol = np.diff(win, axis=0).std(axis=0) * math.sqrt(_TRADING_DAYS)

        with np.errstate(divide="ignore", invalid="ignore"):
            mom = np.log(p_21 / p_252)
            trend = p_now / sma200 - 1.0
        mom[~np.isfinite(mom)] = np.nan
        trend[~np.isfinite(trend)] = np.nan
        vol[vol == 0] = np.nan

        # Fundamental factors (point-in-time, gated on filing_date ≤ as_of).
        fmap = _fundamental_asof(fundamentals, as_of)
        value = np.full(n_names, np.nan)
        quality = np.full(n_names, np.nan)
        for tk, fp in fmap.items():
            idx = col_idx.get(tk)
            if idx is None:
                continue
            px = p_now[idx]
            if fp.eps_diluted is not None and np.isfinite(px) and px > 0:
                value[idx] = fp.eps_diluted / px  # earnings yield
            if fp.roe is not None:
                quality[idx] = fp.roe

        cong_map = _flow_score(
            congress_events, as_of, _CONGRESS_HALFLIFE, _CONGRESS_WINDOW
        )
        fundflow_map = _flow_score(fund_events, as_of, _FUND_HALFLIFE, _FUND_WINDOW)
        insider_map = _flow_score(
            insider_events, as_of, _INSIDER_HALFLIFE, _INSIDER_WINDOW
        )
        activ_map = _flow_score(
            activism_events, as_of, _ACTIVISM_HALFLIFE, _ACTIVISM_WINDOW
        )
        cong = np.full(n_names, np.nan)
        fundflow = np.full(n_names, np.nan)
        activ = np.full(n_names, np.nan)  # scored for ablation; not in composite
        insider = np.full(n_names, np.nan)
        for t, v in cong_map.items():
            if t in col_idx:
                cong[col_idx[t]] = v
        for t, v in fundflow_map.items():
            if t in col_idx:
                fundflow[col_idx[t]] = v
        for t, v in insider_map.items():
            if t in col_idx:
                insider[col_idx[t]] = v
        for t, v in activ_map.items():
            if t in col_idx:
                activ[col_idx[t]] = v

        eligible = (
            member_mask
            & np.isfinite(p_now)
            & ~np.isnan(mom)
            & ~np.isnan(trend)
            & ~np.isnan(vol)
        )
        if eligible.sum() < 50:
            continue
        # Priced members / true members (names absent from the price matrix
        # count against us): the honest residual-bias readout.
        cov_month = float(np.isfinite(p_now[member_mask]).sum() / max(len(members), 1))
        universe_cov.append(cov_month)
        log.debug("%s: universe coverage %.1f%%", as_of, 100 * cov_month)

        def _ze(x: np.ndarray, e: np.ndarray = eligible) -> np.ndarray:
            return _zscore(np.where(e, x, np.nan))

        zmom = _ze(mom)
        ztrend = _ze(trend)
        zvol = _ze(-vol)
        zval = _ze(value)
        zqual = _ze(quality)
        zcong = _ze(cong)
        zfund = _ze(fundflow)
        zactiv = _ze(activ)
        zinside = _ze(insider)

        # activism excluded from composite: monthly IC ≈ 0 (event timescale is days)
        # insider: evaluated in ablation; included in flow composite if positive
        sigs = _build_signals(zmom, ztrend, zvol, zval, zqual, zcong, zfund, zinside)

        fwd = price_arr[j] / p_now - 1.0
        fwd = np.where(eligible & np.isfinite(fwd), fwd, np.nan)
        bench_mask = eligible & np.isfinite(fwd)
        if bench_mask.sum() < 50:
            continue
        bench_rets.append(float(np.nanmean(fwd[bench_mask])))
        if spy_col is not None:
            spy_fwd = price_arr[j, spy_col] / p_now[spy_col] - 1.0
            if np.isfinite(spy_fwd):
                spy_rets.append(float(spy_fwd))

        # Per-factor IC + coverage (the ablation).
        n_elig = int(eligible.sum())
        for fk, z in zip(
            factor_keys,
            (zmom, ztrend, zvol, zval, zqual, zcong, zfund, zactiv, zinside),
            strict=True,
        ):
            ic = _spearman_ic(z, fwd)
            if ic is not None:
                fac_ic[fk].append(ic)
            fac_ic_series[fk].append(ic if ic is not None else math.nan)
            fac_cov[fk].append(float(np.sum(~np.isnan(z)) / max(n_elig, 1)))

        # Per-variant IC + top-decile returns.
        for vk in variant_keys:
            sig = sigs[vk]
            ic = _spearman_ic(sig, fwd)
            if ic is not None:
                var_ic[vk].append(ic)
            net, turn, top = _top_decile_return(sig, fwd, prev[vk], top_decile)
            if not math.isnan(net):
                rets[vk].append(net)
                turns[vk].append(turn)
                prev[vk] = top

        valid = np.where(~np.isnan(sigs["cortex"]) & np.isfinite(fwd))[0]
        if len(valid) >= 100:
            order = valid[np.argsort(sigs["cortex"][valid])]
            chunks = np.array_split(order, 10)
            for d, ch in enumerate(chunks):
                if len(ch):
                    decile_acc[d].append(float(np.mean([fwd[m] for m in ch])))
            # Extreme-decile membership for L/S turnover costs (with ≥100
            # valid names every chunk is non-empty, so this stays aligned
            # with the decile_acc appends).
            ls_sets.append((set(chunks[9].tolist()), set(chunks[0].tolist())))

    def _hit(strat: list[float]) -> float:
        wins = [1.0 if s > b else 0.0 for s, b in zip(strat, bench_rets, strict=False)]
        return float(np.mean(wins)) if wins else 0.0

    b_cagr, b_sharpe, _ = _annualize(bench_rets)
    spy_cagr: float | None = None
    spy_sharpe: float | None = None
    if spy_rets:
        spy_cagr, spy_sharpe, _ = _annualize(spy_rets)
    decile_cagr = [
        (np.prod([1 + r for r in d]) ** (12 / len(d)) - 1) if d else 0.0
        for d in decile_acc
    ]

    labels = {
        "cortex": "CORTEX (price+fund+flow)",
        "price": "Price-only (null model)",
        "price_fund": "Price+Fundamental (no flow)",
    }
    variants: list[StrategyResult] = []
    for vk in variant_keys:
        cagr, sharpe, dd = _annualize(rets[vk])
        ic_m, ic_t, ic_t_nw = _series_stats(var_ic[vk])
        variants.append(
            StrategyResult(
                labels[vk],
                len(rets[vk]),
                ic_m,
                ic_t,
                ic_t_nw,
                cagr,
                sharpe,
                dd,
                _hit(rets[vk]),
                float(np.mean(turns[vk])) if turns[vk] else 0.0,
                [float(x) for x in decile_cagr] if vk == "cortex" else [],
            )
        )

    factor_ics: list[FactorIC] = []
    for fk in factor_keys:
        ic_m, ic_t, ic_t_nw = _series_stats(fac_ic[fk])
        cov = float(np.mean(fac_cov[fk])) if fac_cov[fk] else 0.0
        series = fac_ic[fk]
        pct_pos = sum(1 for v in series if v > 0) / len(series) if series else 0.0
        factor_ics.append(FactorIC(fk, ic_m, ic_t, ic_t_nw, cov, pct_pos))

    # Long-short spread: CORTEX top decile (D10) minus bottom decile (D1),
    # aligned month-by-month (both deciles are appended under the same gate).
    long_short: LongShortResult | None = None
    if decile_acc[0] and decile_acc[9]:
        ls_monthly = [
            top - bot for top, bot in zip(decile_acc[9], decile_acc[0], strict=True)
        ]
        # Net of turnover costs: 10 bps/side long leg, 25 bps/side short leg
        # (extra 15 bps = disclosed borrow/locate assumption).
        ls_net: list[float] = []
        prev_top: set[int] = set()
        prev_bot: set[int] = set()
        for (top_set, bot_set), gross in zip(ls_sets, ls_monthly, strict=True):
            turn_top = (
                len(top_set ^ prev_top) / max(len(top_set), 1) if prev_top else 1.0
            )
            turn_bot = (
                len(bot_set ^ prev_bot) / max(len(bot_set), 1) if prev_bot else 1.0
            )
            cost = turn_top * _COST_PER_SIDE + turn_bot * (
                _COST_PER_SIDE + _SHORT_COST_EXTRA
            )
            ls_net.append(gross - cost)
            prev_top, prev_bot = top_set, bot_set
        ls_mean, _, ls_t_nw = _series_stats(ls_monthly)
        ls_cagr, ls_sharpe, _ = _annualize(ls_monthly)
        ls_mean_net, _, ls_t_nw_net = _series_stats(ls_net)
        ls_cagr_net, ls_sharpe_net, _ = _annualize(ls_net)
        long_short = LongShortResult(
            mean_monthly=ls_mean,
            tstat_nw=ls_t_nw,
            cagr=ls_cagr,
            sharpe=ls_sharpe,
            n_months=len(ls_monthly),
            mean_monthly_net=ls_mean_net,
            tstat_nw_net=ls_t_nw_net,
            cagr_net=ls_cagr_net,
            sharpe_net=ls_sharpe_net,
        )

    factor_corr = _factor_corr(fac_ic_series, factor_keys)

    cov_mean = float(np.mean(universe_cov)) if universe_cov else 0.0
    cov_min = float(np.min(universe_cov)) if universe_cov else 0.0
    log.info(
        "Point-in-time universe coverage: mean %.1f%%, worst month %.1f%%",
        100 * cov_mean,
        100 * cov_min,
    )

    return BacktestReport(
        start=daily_idx[rebal[0]].date(),
        end=daily_idx[rebal[-1]].date(),
        n_names=n_names,
        benchmark_cagr=b_cagr,
        benchmark_sharpe=b_sharpe,
        variants=variants,
        factor_ics=factor_ics,
        long_short=long_short,
        factor_corr=factor_corr,
        n_tickers_requested=n_requested,
        n_tickers_priced=n_priced,
        universe_coverage_mean=cov_mean,
        universe_coverage_min=cov_min,
        spy_cagr=spy_cagr,
        spy_sharpe=spy_sharpe,
    )


# ── pre-registered OOS congress test ─────────────────────────────────────────


@dataclass
class CongressOOSReport:
    """Results of the pre-registered out-of-sample congress factor test.

    Pre-registration (2026-05-23): congress net-buy factor (180d half-life,
    365d window, gated on disclosure_date) must achieve OOS IC t-stat ≥ 3.0
    to claim an edge; t-stat ≥ 2.0 = "interesting, unconfirmed". No
    parameters were changed between in-sample and OOS.

    Methodology corrections (2026-07-16, journaled in CHANGELOG): the verdict
    keys off the Newey-West t-stat (the naive IID t is still reported), and
    the universe is point-in-time S&P 500 membership. The 3.0/2.0 bars are
    unchanged — these tighten the test, they don't move the goalposts.
    """

    insample_start: date
    insample_end: date
    oos_start: date
    oos_end: date

    insample_mean_ic: float
    insample_ic_tstat: float
    insample_ic_tstat_nw: float
    insample_coverage: float
    insample_n_months: int

    oos_mean_ic: float
    oos_ic_tstat: float
    oos_ic_tstat_nw: float
    oos_coverage: float
    oos_n_months: int

    # Long-only portfolio vs benchmark (OOS only)
    oos_portfolio_cagr: float
    oos_benchmark_cagr: float
    oos_portfolio_sharpe: float
    oos_benchmark_sharpe: float

    verdict: str


def run_congress_oos(
    db_path: Path,
    *,
    insample_end_year: int = 2021,
    start_year: int = 2017,
) -> CongressOOSReport:
    """Pre-registered OOS test of the congressional-buy factor.

    In-sample: start_year-01 through insample_end_year-12.
    Out-of-sample: (insample_end_year+1)-01 through the available data end.

    Factor construction is identical to the main backtest — no tuning between
    periods.
    """
    from cortex.sources.prices import load_closes
    from cortex.sources.universe import sp500_members_asof, sp500_union

    hist_start = date(start_year - 1, 1, 1)
    tickers = sp500_union(hist_start)
    log.info("Congress OOS universe: %d point-in-time members", len(tickers))

    closes: Any = load_closes(db_path, tickers, hist_start)
    closes = closes.dropna(how="all")
    cols = list(closes.columns)
    col_idx = {t: i for i, t in enumerate(cols)}
    price_arr = closes.to_numpy()
    daily_idx: Any = closes.index

    congress_events = _load_congress_events(db_path)
    log.info("Loaded %d congress events", len(congress_events))

    me_marks = closes.resample("ME").last().index
    positions = daily_idx.searchsorted(me_marks, side="right") - 1
    positions = sorted({int(p) for p in positions if p >= _TRADING_DAYS})
    rebal = [p for p in positions if p < len(daily_idx) - 1]

    n_names = price_arr.shape[1]
    split_date = date(insample_end_year, 12, 31)

    # Accumulators split by period.
    is_ics: list[float] = []
    oos_ics: list[float] = []
    is_cov: list[float] = []
    oos_cov: list[float] = []

    oos_port_rets: list[float] = []
    oos_bench_rets: list[float] = []
    oos_prev: set[int] = set()

    for k in range(len(rebal) - 1):
        i = rebal[k]
        j = rebal[k + 1]
        as_of = daily_idx[i].date()
        if as_of.year < start_year:
            continue

        members = sp500_members_asof(as_of)
        member_mask = np.fromiter(
            (t in members for t in cols), dtype=bool, count=n_names
        )
        p_now = price_arr[i]
        eligible = member_mask & np.isfinite(p_now)
        if eligible.sum() < 50:
            continue

        cong_map = _flow_score(
            congress_events, as_of, _CONGRESS_HALFLIFE, _CONGRESS_WINDOW
        )
        cong = np.full(n_names, np.nan)
        for t, v in cong_map.items():
            if t in col_idx:
                cong[col_idx[t]] = v

        zcong = _zscore(np.where(eligible, cong, np.nan))

        fwd = price_arr[j] / p_now - 1.0
        fwd = np.where(eligible & np.isfinite(fwd), fwd, np.nan)
        if np.sum(~np.isnan(fwd) & eligible) < 50:
            continue

        n_elig = int(eligible.sum())
        n_scored = int(np.sum(~np.isnan(zcong)))
        cov = n_scored / max(n_elig, 1)

        ic = _spearman_ic(zcong, fwd)
        in_sample = as_of <= split_date

        if ic is not None:
            (is_ics if in_sample else oos_ics).append(ic)
        (is_cov if in_sample else oos_cov).append(cov)

        if not in_sample:
            bench_mask = eligible & np.isfinite(fwd)
            oos_bench_rets.append(float(np.nanmean(fwd[bench_mask])))
            net, _, oos_prev = _top_decile_return(zcong, fwd, oos_prev, 0.10)
            if not math.isnan(net):
                oos_port_rets.append(net)

    is_mean_ic, is_tstat, is_tstat_nw = _series_stats(is_ics)
    oos_mean_ic, oos_tstat, oos_tstat_nw = _series_stats(oos_ics)
    is_cov_avg = float(np.mean(is_cov)) if is_cov else 0.0
    oos_cov_avg = float(np.mean(oos_cov)) if oos_cov else 0.0

    port_cagr, port_sharpe, _ = _annualize(oos_port_rets)
    bench_cagr, bench_sharpe, _ = _annualize(oos_bench_rets)

    # Verdict keys off the Newey-West t-stat: monthly ICs are autocorrelated,
    # and the naive IID t overstates significance exactly when it matters.
    if oos_tstat_nw >= 3.0:
        verdict = (
            "EDGE CONFIRMED — OOS IC NW t-stat ≥ 3.0 passes pre-registered threshold."
        )
    elif oos_tstat_nw >= 2.0:
        verdict = (
            "INTERESTING but UNCONFIRMED — OOS IC NW t-stat ≥ 2.0, below the 3.0 bar."
        )
    else:
        verdict = (
            "NO EDGE — OOS IC NW t-stat < 2.0; congress factor does not survive OOS."
        )

    oos_start = date(insample_end_year + 1, 1, 1)
    is_start = date(start_year, 1, 1)

    return CongressOOSReport(
        insample_start=is_start,
        insample_end=split_date,
        oos_start=oos_start,
        oos_end=daily_idx[rebal[-1]].date(),
        insample_mean_ic=is_mean_ic,
        insample_ic_tstat=is_tstat,
        insample_ic_tstat_nw=is_tstat_nw,
        insample_coverage=is_cov_avg,
        insample_n_months=len(is_ics),
        oos_mean_ic=oos_mean_ic,
        oos_ic_tstat=oos_tstat,
        oos_ic_tstat_nw=oos_tstat_nw,
        oos_coverage=oos_cov_avg,
        oos_n_months=len(oos_ics),
        oos_portfolio_cagr=port_cagr,
        oos_benchmark_cagr=bench_cagr,
        oos_portfolio_sharpe=port_sharpe,
        oos_benchmark_sharpe=bench_sharpe,
        verdict=verdict,
    )


# ── event-study (CAR) harness ────────────────────────────────────────────────

_HORIZONS: list[tuple[int, int]] = [(0, 5), (0, 20), (0, 60), (0, 120)]
_PLACEBO_WINDOW: tuple[int, int] = (-5, -1)


def _car_window(
    ar: np.ndarray, event_idx: int, col: int, w_start: int, w_end: int
) -> float | None:
    """Sum of daily abnormal returns in [event_idx+w_start, event_idx+w_end] inclusive.

    Returns None if the window falls outside array bounds or contains any NaN/Inf.
    """
    start = event_idx + w_start
    end = event_idx + w_end + 1  # exclusive upper bound
    if start < 0 or end > ar.shape[0]:
        return None
    window = ar[start:end, col]
    if not np.all(np.isfinite(window)):
        return None
    return float(window.sum())


@dataclass
class HorizonResult:
    w_start: int
    w_end: int
    mean_car: float
    nw_tstat: float
    hit_rate: float  # fraction of events with positive CAR
    n: int
    n_collapsed: int = 0  # same-ticker events dropped for window overlap


# Market-model estimation: up to 252 trading days ending 30 days before the
# event (the gap keeps pre-event drift out of the beta), minimum 120 obs.
_BETA_WINDOW = 252
_BETA_GAP = 30
_BETA_MIN_OBS = 120


def _estimate_market_model(
    ret: np.ndarray, bench_ret: np.ndarray, event_idx: int, col: int
) -> tuple[float, float] | None:
    """OLS (alpha, beta) of a name on the benchmark over the pre-event window."""
    hi = max(0, event_idx - _BETA_GAP)
    lo = max(0, hi - _BETA_WINDOW)
    x = bench_ret[lo:hi]
    y = ret[lo:hi, col]
    mask = np.isfinite(x) & np.isfinite(y)
    if int(mask.sum()) < _BETA_MIN_OBS:
        return None
    xm = x[mask]
    ym = y[mask]
    var = float(np.var(xm))
    if var <= 0:
        return None
    beta = float(np.cov(xm, ym)[0, 1] / var)
    alpha = float(ym.mean() - beta * xm.mean())
    return alpha, beta


def _collapse_overlaps(event_idxs: list[int], span: int) -> tuple[list[int], int]:
    """Keep the first of any same-ticker events whose windows would overlap.

    ``span`` is the window length in trading days; two kept events are at
    least ``span`` days apart so their CAR windows are disjoint.
    """
    kept: list[int] = []
    dropped = 0
    last = None
    for e in sorted(event_idxs):
        if last is not None and e - last < span:
            dropped += 1
            continue
        kept.append(e)
        last = e
    return kept, dropped


@dataclass
class EventStudyReport:
    """Results of the filing-gated event study. CARs are GROSS of costs.

    Method: market model by default — per-name (alpha, beta) estimated on a
    pre-event window against the equal-weight benchmark; abnormal return =
    r − (α + β·r_mkt). Falls back to the market-adjusted model (r − r_mkt)
    for events without a sufficient estimation window (``n_no_beta`` counts
    them). Overlapping same-ticker events are collapsed per horizon — only
    the first of any events whose windows would overlap is kept (Cohen et
    al. 2012 clustering concern; ``n_collapsed`` per horizon discloses it).
    """

    signal: str
    from_year: int
    n_events_total: int
    n_skipped: int  # ticker missing from price data, or event past data end
    horizons: list[HorizonResult]
    placebo: HorizonResult  # (-5, -1) pre-event leakage check
    market_model: bool = True
    n_no_beta: int = 0  # events that fell back to market-adjusted


def run_event_study(
    db_path: Path,
    *,
    signal: str,
    from_year: int = 2017,
    market_model: bool = True,
) -> EventStudyReport:
    """Compute cumulative abnormal return (CAR) around filing-gated events.

    Daily adjusted closes come from the DuckDB price cache. See
    :class:`EventStudyReport` for the abnormal-return model and the
    overlapping-event collapse.
    """
    import pandas as pd

    from cortex.sources.prices import load_closes
    from cortex.sources.universe import sp500_union

    if signal == "insider":
        all_events = _load_insider_events(db_path)
    elif signal == "activism":
        all_events = _load_activism_events(db_path)
    elif signal == "congress":
        all_events = _load_congress_events(db_path)
    elif signal == "executive":
        all_events = _load_executive_events(db_path)
    else:
        raise ValueError(
            f"Unknown signal {signal!r}; choose insider, activism, congress, "
            "or executive"
        )

    events = [e for e in all_events if e.signed_weight > 0 and e.when.year >= from_year]
    log.info(
        "Event study: %d %s events (signed_weight > 0, year >= %d)",
        len(events),
        signal,
        from_year,
    )

    # Union of point-in-time members so events on later-delisted names are
    # not silently skipped when a source can price them.
    tickers = sp500_union(date(from_year - 1, 1, 1))
    closes: Any = load_closes(db_path, tickers, date(from_year - 1, 1, 1))
    closes = closes.dropna(how="all")
    cols = list(closes.columns)
    col_idx = {t: i for i, t in enumerate(cols)}
    price_arr = closes.to_numpy()  # [days, names]
    daily_idx: Any = closes.index

    # Daily simple returns; row 0 is NaN (no prior day).
    ret = np.full_like(price_arr, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret[1:] = price_arr[1:] / price_arr[:-1] - 1.0

    # Equal-weight benchmark: daily mean across all names.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        bench_ret = np.nanmean(ret, axis=1)  # [days]

    ar_ma = ret - bench_ret[:, np.newaxis]  # market-adjusted [days, names]

    # Group event day-indices by ticker so overlaps can be collapsed.
    by_ticker: dict[str, list[int]] = {}
    n_skipped = 0
    for ev in events:
        col = col_idx.get(ev.ticker)
        if col is None:
            n_skipped += 1
            continue
        e = int(daily_idx.searchsorted(pd.Timestamp(ev.when)))
        if e >= len(daily_idx):
            n_skipped += 1
            continue
        by_ticker.setdefault(ev.ticker, []).append(e)

    n_no_beta = 0
    windows = [_PLACEBO_WINDOW, *_HORIZONS]
    cars: dict[tuple[int, int], list[float]] = {w: [] for w in windows}
    collapsed: dict[tuple[int, int], int] = {w: 0 for w in windows}

    for ticker, idxs in by_ticker.items():
        col = col_idx[ticker]
        # One abnormal-return series per event (beta is event-specific).
        ar_by_event: dict[int, np.ndarray] = {}
        for e in dict.fromkeys(idxs):
            series = None
            if market_model:
                mm = _estimate_market_model(ret, bench_ret, e, col)
                if mm is not None:
                    a, b = mm
                    series = ret[:, col] - (a + b * bench_ret)
                else:
                    n_no_beta += 1
            if series is None:
                series = ar_ma[:, col]
            ar_by_event[e] = series
        for w in windows:
            span = w[1] - w[0] + 1
            kept, dropped = _collapse_overlaps(idxs, span)
            collapsed[w] += dropped
            for e in kept:
                car = _car_window(ar_by_event[e][:, np.newaxis], e, 0, *w)
                if car is not None:
                    cars[w].append(car)

    def _to_horizon(h: tuple[int, int]) -> HorizonResult:
        vals = cars[h]
        if not vals:
            return HorizonResult(h[0], h[1], 0.0, 0.0, 0.0, 0, collapsed[h])
        arr = np.array(vals)
        return HorizonResult(
            w_start=h[0],
            w_end=h[1],
            mean_car=float(arr.mean()),
            nw_tstat=_nw_tstat(vals),
            hit_rate=float((arr > 0).mean()),
            n=len(vals),
            n_collapsed=collapsed[h],
        )

    return EventStudyReport(
        signal=signal,
        from_year=from_year,
        n_events_total=len(events),
        n_skipped=n_skipped,
        horizons=[_to_horizon(h) for h in _HORIZONS],
        placebo=_to_horizon(_PLACEBO_WINDOW),
        market_model=market_model,
        n_no_beta=n_no_beta,
    )


@dataclass
class DailyCARPoint:
    """Mean cumulative abnormal return at a given day offset from the filing date."""

    day: int
    mean_car: float
    se: float  # standard error = std / sqrt(n)
    n: int


def run_event_study_daily(
    db_path: Path,
    *,
    signal: str,
    from_year: int = 2017,
    max_day: int = 120,
    market_model: bool = True,
) -> list[DailyCARPoint]:
    """Day-by-day mean CAR trajectory for a filing-gated signal (days 0..max_day).

    Only events that have a complete max_day window (no NaN, not past data end)
    are included, so every day in the trajectory averages over the same event
    set. Abnormal returns use the market model (market-adjusted fallback per
    event); overlapping same-ticker events are collapsed to the first.
    """
    import pandas as pd

    from cortex.sources.prices import load_closes
    from cortex.sources.universe import sp500_union

    if signal == "insider":
        all_events = _load_insider_events(db_path)
    elif signal == "activism":
        all_events = _load_activism_events(db_path)
    elif signal == "congress":
        all_events = _load_congress_events(db_path)
    elif signal == "executive":
        all_events = _load_executive_events(db_path)
    else:
        raise ValueError(
            f"Unknown signal {signal!r}; choose insider, activism, congress, "
            "or executive"
        )

    events = [e for e in all_events if e.signed_weight > 0 and e.when.year >= from_year]
    if not events:
        return []

    # Union of point-in-time members so events on later-delisted names are
    # not silently skipped when a source can price them.
    tickers = sp500_union(date(from_year - 1, 1, 1))
    closes: Any = load_closes(db_path, tickers, date(from_year - 1, 1, 1))
    closes = closes.dropna(how="all")
    col_idx = {t: i for i, t in enumerate(closes.columns)}
    price_arr = closes.to_numpy()
    daily_idx: Any = closes.index

    ret = np.full_like(price_arr, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret[1:] = price_arr[1:] / price_arr[:-1] - 1.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        bench_ret = np.nanmean(ret, axis=1)
    ar_ma = ret - bench_ret[:, np.newaxis]

    # Group by ticker and collapse events whose max_day windows overlap, so
    # one name's purchase cluster doesn't stack near-duplicate trajectories.
    by_ticker: dict[str, list[int]] = {}
    for ev in events:
        col = col_idx.get(ev.ticker)
        if col is None:
            continue
        e = int(daily_idx.searchsorted(pd.Timestamp(ev.when)))
        if e + max_day >= len(daily_idx):
            continue
        by_ticker.setdefault(ev.ticker, []).append(e)

    cum_cars: list[np.ndarray] = []
    for ticker, idxs in by_ticker.items():
        col = col_idx[ticker]
        kept, _ = _collapse_overlaps(idxs, max_day + 1)
        for e in kept:
            series = None
            if market_model:
                mm = _estimate_market_model(ret, bench_ret, e, col)
                if mm is not None:
                    a, b = mm
                    series = ret[:, col] - (a + b * bench_ret)
            if series is None:
                series = ar_ma[:, col]
            window = series[e : e + max_day + 1]
            if len(window) < max_day + 1 or not np.all(np.isfinite(window)):
                continue
            cum_cars.append(np.cumsum(window))

    if not cum_cars:
        return []

    matrix = np.vstack(cum_cars)  # [n_events, max_day+1]
    n = matrix.shape[0]
    means = matrix.mean(axis=0)
    ses = matrix.std(axis=0) / math.sqrt(n) if n > 1 else np.zeros(max_day + 1)

    log.info("CAR daily series: %d events contributed, signal=%s", n, signal)
    return [
        DailyCARPoint(day=d, mean_car=float(means[d]), se=float(ses[d]), n=n)
        for d in range(max_day + 1)
    ]
