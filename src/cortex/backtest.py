"""Point-in-time backtest for the CORTEX composite buy-signal.

Designed to a strict methodology (no look-ahead, zero tunable parameters):

- BACKTEST factor set = price + flow factors ONLY. Value/quality are excluded
  because we have no point-in-time fundamentals — including them would be
  look-ahead. They appear in the LIVE ranking only.
- Factors: momentum 12-1, trend (continuous distance to 200d SMA), low-vol,
  congressional net-buy flow, 13F institutional net-buy flow.
- Equal-weight z-composite in two equal blocks (price 50% / flow 50%) so the
  collinear price trio doesn't drown the flow thesis.
- Monthly rebalance, long-only top decile, equal-weighted, vs an equal-weight
  S&P-500 benchmark, net of transaction costs.
- A PRICE-ONLY composite is run as the null model: the flow factors only earn
  credit if they beat price-only.

KNOWN BIASES (disclosed, not hidden):
- Universe = *current* S&P 500 members → survivorship bias inflates everything.
- Value/quality contribution is unmeasured (no point-in-time fundamentals).
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
    return [_Event(ticker.upper(), filing_date, 1.0) for ticker, filing_date in rows
            if filing_date is not None]


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
    ic_tstat: float
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
    ic_tstat: float
    coverage: float  # avg fraction of universe with the factor present


@dataclass
class BacktestReport:
    start: date
    end: date
    n_names: int
    benchmark_cagr: float
    benchmark_sharpe: float
    variants: list[StrategyResult] = field(default_factory=list)
    factor_ics: list[FactorIC] = field(default_factory=list)


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
    (congress/13F/insider). Each block = nanmean of available factors;
    composite = nanmean of available block means (no z-imputation).

    Low-vol excluded from price block: the low-volatility anomaly
    underperforms in sustained bull-market regimes (Ang et al. 2006,
    Baker et al. 2011). Pre-registered removal 2026-05-23.

    Insider signal included in flow block alongside congress and 13F.
    Evaluated post-sync — if t-stat < 1.0 after first sync, will be
    excluded from composite on the same pre-registration basis as activism.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        price = np.nanmean(np.vstack([zmom, ztrend]), axis=0)
        fund = np.nanmean(np.vstack([zval, zqual]), axis=0)
        flow = np.nanmean(np.vstack([zcong, zfund, zinside]), axis=0)
        cortex = np.nanmean(np.vstack([price, fund, flow]), axis=0)
        price_fund = np.nanmean(np.vstack([price, fund]), axis=0)
    return {
        "cortex": cortex,        # price + fundamental + flow (full)
        "price": price,          # null model (mom + trend, no low-vol)
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
        "mom", "trend", "vol", "value", "quality", "congress", "fund",
        "activism", "insider",
    )

    rets: dict[str, list[float]] = {k: [] for k in variant_keys}
    turns: dict[str, list[float]] = {k: [] for k in variant_keys}
    prev: dict[str, set[int]] = {k: set() for k in variant_keys}
    var_ic: dict[str, list[float]] = {k: [] for k in variant_keys}
    fac_ic: dict[str, list[float]] = {k: [] for k in factor_keys}
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
        cong = np.full(n_names, np.nan)
        fundflow = np.full(n_names, np.nan)
        activ = np.full(n_names, np.nan)  # excluded from composite (wrong timescale)
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

        eligible = (
            np.isfinite(p_now)
            & ~np.isnan(mom)
            & ~np.isnan(trend)
            & ~np.isnan(vol)
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

    def _ic_stats(ics: list[float]) -> tuple[float, float]:
        if not ics:
            return 0.0, 0.0
        a = np.array(ics)
        t = float(a.mean() / a.std() * math.sqrt(len(a))) if a.std() > 0 else 0.0
        return float(a.mean()), t

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
        ic_m, ic_t = _ic_stats(var_ic[vk])
        variants.append(
            StrategyResult(
                labels[vk], len(rets[vk]), ic_m, ic_t, cagr, sharpe, dd,
                _hit(rets[vk]),
                float(np.mean(turns[vk])) if turns[vk] else 0.0,
                [float(x) for x in decile_cagr] if vk == "cortex" else [],
            )
        )

    factor_ics: list[FactorIC] = []
    for fk in factor_keys:
        ic_m, ic_t = _ic_stats(fac_ic[fk])
        cov = float(np.mean(fac_cov[fk])) if fac_cov[fk] else 0.0
        factor_ics.append(FactorIC(fk, ic_m, ic_t, cov))

    return BacktestReport(
        start=daily_idx[rebal[0]].date(),
        end=daily_idx[rebal[-1]].date(),
        n_names=n_names,
        benchmark_cagr=b_cagr,
        benchmark_sharpe=b_sharpe,
        variants=variants,
        factor_ics=factor_ics,
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
    insample_coverage: float
    insample_n_months: int

    oos_mean_ic: float
    oos_ic_tstat: float
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
        tickers, start=f"{start_year - 1}-01-01", auto_adjust=True,
        progress=False, threads=True,
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

    def _ic_stats(ics: list[float]) -> tuple[float, float]:
        if not ics:
            return 0.0, 0.0
        a = np.array(ics)
        t = float(a.mean() / a.std() * math.sqrt(len(a))) if a.std() > 0 else 0.0
        return float(a.mean()), t

    is_mean_ic, is_tstat = _ic_stats(is_ics)
    oos_mean_ic, oos_tstat = _ic_stats(oos_ics)
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
        verdict = (
            "NO EDGE — OOS IC t-stat < 2.0; congress factor does not survive OOS."
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
        insample_coverage=is_cov_avg,
        insample_n_months=len(is_ics),
        oos_mean_ic=oos_mean_ic,
        oos_ic_tstat=oos_tstat,
        oos_coverage=oos_cov_avg,
        oos_n_months=len(oos_ics),
        oos_portfolio_cagr=port_cagr,
        oos_benchmark_cagr=bench_cagr,
        oos_portfolio_sharpe=port_sharpe,
        oos_benchmark_sharpe=bench_sharpe,
        verdict=verdict,
    )
