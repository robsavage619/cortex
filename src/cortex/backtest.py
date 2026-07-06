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
- Universe = *current* S&P 500 members → survivorship bias inflates everything.
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

log = logging.getLogger(__name__)

# Half-lives (days) chosen a priori from the literature — NOT fitted.
_CONGRESS_HALFLIFE = 180.0
_FUND_HALFLIFE = 270.0
# Insider (Form 4) signal decays faster — information advantage is short-lived
# post-disclosure. Cohen et al. (2012) show drift over ~6 months. 90-day
# halflife with 180-day window chosen a priori.
_INSIDER_HALFLIFE = 90.0
_INSIDER_WINDOW = 180
# Activism (SC 13D) drifts slowly: Brav & Jiang (2008) document 10-30% drift
# over 12-18 months in large caps. 365-day halflife / 730-day window a priori.
_ACTIVISM_HALFLIFE = 365.0
_ACTIVISM_WINDOW = 730
_CONGRESS_WINDOW = 365  # trailing days of filings to consider
_FUND_WINDOW = 540
_Z_CLIP = 3.0
_COST_PER_SIDE = 0.0010  # 10 bps
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
    t = (transaction_type or "").lower()
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
    """Point-in-time annual fundamentals, oldest filing first."""
    from cortex.storage.db import connect

    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT ticker, filing_date, eps_diluted, net_income, equity
                FROM fundamentals
                ORDER BY filing_date
                """
            ).fetchall()
    except Exception:  # noqa: BLE001 - table may be empty/absent
        return []
    out: list[_Fundamental] = []
    for ticker, fd, eps, ni, eq in rows:
        roe = (ni / eq) if (ni is not None and eq not in (None, 0)) else None
        out.append(_Fundamental(ticker.upper(), fd, eps, roe))
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
    """Load Form 4 open-market purchase events (point-in-time via filing_date)."""
    from cortex.storage.db import connect

    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT ticker, filing_date, value_usd
                FROM insider_buys
                """
            ).fetchall()
    except Exception:  # noqa: BLE001 - table may not exist yet
        return []
    events: list[_Event] = []
    for ticker, filing_date, value_usd in rows:
        if filing_date is None:
            continue
        weight = math.log1p(float(value_usd or 0))
        if weight <= 0:
            continue
        events.append(_Event(ticker.upper(), filing_date, weight))
    return events


def _load_fund_events(db_path: Path) -> list[_Event]:
    from cortex.storage.db import connect

    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT ticker, period, action, value
            FROM fund_holdings
            """
        ).fetchall()
    events: list[_Event] = []
    for ticker, period, action, value in rows:
        if period is None:
            continue
        sign = 1 if action in ("NEW", "ADD") else -1
        weight = math.log1p(float(value or 0))
        if weight <= 0:
            continue
        events.append(_Event(ticker.upper(), period, sign * weight))
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


@dataclass
class LongShortResult:
    """Top-decile-minus-bottom-decile spread of the CORTEX composite.

    The long-short return strips market beta from the long-only top decile,
    isolating the factor's directional content. A real factor produces a
    positive spread whose mean clears the HAC t-stat bar.
    """

    mean_monthly: float
    tstat_nw: float
    cagr: float
    sharpe: float
    n_months: int


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
    """Build composite variants from three equal blocks.

    Blocks: price (mom/trend), fundamental (value/quality), flow
    (congress/13F). Each block = nanmean of available factors;
    composite = nanmean of available block means (no z-imputation).

    Low-vol excluded from price block: the low-volatility anomaly
    underperforms in sustained bull-market regimes (Ang et al. 2006,
    Baker et al. 2011). Pre-registered removal 2026-05-23.

    Insider (Form 4 P-code) excluded from the flow block: pre-registered as
    "drop if t-stat < 1.0 after first sync." First full sync (2026-05-28,
    8.6k buys, 23% coverage) measured monthly IC NW t = -0.43 — insider buys
    are contrarian (corr -0.33 with momentum) and carry no monthly-horizon
    signal in large-cap names. Still computed and shown in the ablation; not
    in the composite. ``zinside`` is intentionally unused here.
    """
    _ = zinside  # retained for the ablation; pre-registered out of the composite
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        price = np.nanmean(np.vstack([zmom, ztrend]), axis=0)
        fund = np.nanmean(np.vstack([zval, zqual]), axis=0)
        flow = np.nanmean(np.vstack([zcong, zfund]), axis=0)
        cortex = np.nanmean(np.vstack([price, fund, flow]), axis=0)
        price_fund = np.nanmean(np.vstack([price, fund]), axis=0)
    return {
        "cortex": cortex,  # price + fundamental + flow (full)
        "price": price,  # null model (mom + trend, no low-vol)
        "price_fund": price_fund,  # price + fundamental (no flow)
    }


def run_backtest(
    db_path: Path,
    *,
    start_year: int = 2017,
    top_decile: float = 0.10,
) -> BacktestReport:
    """Run the point-in-time backtest. Downloads prices via yfinance."""
    import yfinance as yf

    from cortex.sources.universe import sp500_tickers

    tickers = sp500_tickers()
    log.info("Backtest universe: %d tickers (survivorship-biased)", len(tickers))

    start = f"{start_year - 1}-01-01"  # one extra year for 252d lookback warmup
    raw: Any = yf.download(
        tickers, start=start, auto_adjust=True, progress=False, threads=True
    )
    closes: Any = raw["Close"] if len(tickers) > 1 else raw[["Close"]]
    closes = closes.dropna(how="all")
    # yfinance silently omits tickers it fails to price — make the gap visible.
    closes = closes.dropna(axis=1, how="all")
    n_requested = len(tickers)
    n_priced = int(closes.shape[1])
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
    decile_acc: list[list[float]] = [[] for _ in range(10)]

    for k in range(len(rebal) - 1):
        i = rebal[k]
        j = rebal[k + 1]
        as_of = daily_idx[i].date()

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
            np.isfinite(p_now) & ~np.isnan(mom) & ~np.isnan(trend) & ~np.isnan(vol)
        )
        if eligible.sum() < 50:
            continue

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
            for d, ch in enumerate(np.array_split(order, 10)):
                if len(ch):
                    decile_acc[d].append(float(np.mean([fwd[m] for m in ch])))

    def _hit(strat: list[float]) -> float:
        wins = [1.0 if s > b else 0.0 for s, b in zip(strat, bench_rets, strict=False)]
        return float(np.mean(wins)) if wins else 0.0

    b_cagr, b_sharpe, _ = _annualize(bench_rets)
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
        factor_ics.append(FactorIC(fk, ic_m, ic_t, ic_t_nw, cov))

    # Long-short spread: CORTEX top decile (D10) minus bottom decile (D1),
    # aligned month-by-month (both deciles are appended under the same gate).
    long_short: LongShortResult | None = None
    if decile_acc[0] and decile_acc[9]:
        ls_monthly = [
            top - bot for top, bot in zip(decile_acc[9], decile_acc[0], strict=True)
        ]
        ls_mean, _, ls_t_nw = _series_stats(ls_monthly)
        ls_cagr, ls_sharpe, _ = _annualize(ls_monthly)
        long_short = LongShortResult(
            mean_monthly=ls_mean,
            tstat_nw=ls_t_nw,
            cagr=ls_cagr,
            sharpe=ls_sharpe,
            n_months=len(ls_monthly),
        )

    factor_corr = _factor_corr(fac_ic_series, factor_keys)

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
    )


# ── pre-registered OOS congress test ─────────────────────────────────────────


@dataclass
class CongressOOSReport:
    """Results of the pre-registered out-of-sample congress factor test.

    Pre-registration (2026-05-23): congress net-buy factor (180d half-life,
    365d window, gated on disclosure_date) must achieve OOS IC t-stat ≥ 3.0
    to claim an edge; t-stat ≥ 2.0 = "interesting, unconfirmed". No
    parameters were changed between in-sample and OOS.
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
    import yfinance as yf

    from cortex.sources.universe import sp500_tickers

    tickers = sp500_tickers()
    log.info("Congress OOS universe: %d tickers", len(tickers))

    raw: Any = yf.download(
        tickers,
        start=f"{start_year - 1}-01-01",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    closes: Any = raw["Close"] if len(tickers) > 1 else raw[["Close"]]
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

        p_now = price_arr[i]
        eligible = np.isfinite(p_now)
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

    if oos_tstat >= 3.0:
        verdict = (
            "EDGE CONFIRMED — OOS IC t-stat ≥ 3.0 passes pre-registered threshold."
        )
    elif oos_tstat >= 2.0:
        verdict = (
            "INTERESTING but UNCONFIRMED — OOS IC t-stat ≥ 2.0, below the 3.0 bar."
        )
    else:
        verdict = "NO EDGE — OOS IC t-stat < 2.0; congress factor does not survive OOS."

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


@dataclass
class EventStudyReport:
    """Results of the filing-gated event study.

    Method: market-adjusted model — daily return minus equal-weight S&P 500
    benchmark. No per-name beta estimation; CAPM-residual is a future upgrade.
    Each event is treated independently: multiple purchases by the same ticker
    in overlapping windows each contribute a separate observation (see Cohen
    et al. 2012 for a clustered alternative).
    """

    signal: str
    from_year: int
    n_events_total: int
    n_skipped: int  # ticker missing from price data, or event past data end
    horizons: list[HorizonResult]
    placebo: HorizonResult  # (-5, -1) pre-event leakage check


def run_event_study(
    db_path: Path,
    *,
    signal: str,
    from_year: int = 2017,
) -> EventStudyReport:
    """Compute cumulative abnormal return (CAR) around filing-gated events.

    Downloads daily adjusted closes via yfinance (no SEC credentials required).
    """
    import pandas as pd
    import yfinance as yf

    from cortex.sources.universe import sp500_tickers

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

    tickers = sp500_tickers()
    raw: Any = yf.download(
        tickers,
        start=f"{from_year - 1}-01-01",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    closes: Any = raw["Close"] if len(tickers) > 1 else raw[["Close"]]
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

    ar = ret - bench_ret[:, np.newaxis]  # [days, names]

    cars_by_horizon: dict[tuple[int, int], list[float]] = {h: [] for h in _HORIZONS}
    cars_placebo: list[float] = []
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

        pl = _car_window(ar, e, col, *_PLACEBO_WINDOW)
        if pl is not None:
            cars_placebo.append(pl)

        for h in _HORIZONS:
            car = _car_window(ar, e, col, *h)
            if car is not None:
                cars_by_horizon[h].append(car)

    def _to_horizon(h: tuple[int, int], cars: list[float]) -> HorizonResult:
        if not cars:
            return HorizonResult(h[0], h[1], 0.0, 0.0, 0.0, 0)
        arr = np.array(cars)
        return HorizonResult(
            w_start=h[0],
            w_end=h[1],
            mean_car=float(arr.mean()),
            nw_tstat=_nw_tstat(cars),
            hit_rate=float((arr > 0).mean()),
            n=len(cars),
        )

    placebo = _to_horizon(_PLACEBO_WINDOW, cars_placebo)
    horizons = [_to_horizon(h, cars_by_horizon[h]) for h in _HORIZONS]

    return EventStudyReport(
        signal=signal,
        from_year=from_year,
        n_events_total=len(events),
        n_skipped=n_skipped,
        horizons=horizons,
        placebo=placebo,
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
) -> list[DailyCARPoint]:
    """Day-by-day mean CAR trajectory for a filing-gated signal (days 0..max_day).

    Only events that have a complete max_day window (no NaN, not past data end)
    are included, so every day in the trajectory averages over the same event set.
    """
    import pandas as pd
    import yfinance as yf

    from cortex.sources.universe import sp500_tickers

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

    tickers = sp500_tickers()
    raw: Any = yf.download(
        tickers,
        start=f"{from_year - 1}-01-01",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    closes: Any = raw["Close"] if len(tickers) > 1 else raw[["Close"]]
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
    ar = ret - bench_ret[:, np.newaxis]

    cum_cars: list[np.ndarray] = []
    for ev in events:
        col = col_idx.get(ev.ticker)
        if col is None:
            continue
        e = int(daily_idx.searchsorted(pd.Timestamp(ev.when)))
        if e + max_day >= len(daily_idx):
            continue
        window = ar[e : e + max_day + 1, col]
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
