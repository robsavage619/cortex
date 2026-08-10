"""End-to-end, network-free tests of the backtest / OOS / event-study harnesses.

The price cache is seeded with deterministic synthetic series (see
tests/fixtures/prices.py); yfinance and httpx are patched to fail loudly, so
any network access is a test failure.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from cortex.backtest import run_backtest, run_congress_oos, run_event_study
from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema
from tests.fixtures.prices import (
    block_network,
    drift_universe,
    patch_membership,
    seed_price_history,
)

N_NAMES = 120  # ≥100 so the decile split (and the L/S spread) engages


def _d(idx, i: int) -> date:
    """Calendar date of the i-th index entry (via ISO string, stub-safe)."""
    return date.fromisoformat(str(idx[i])[:10])


@pytest.fixture
def offline(monkeypatch):
    block_network(monkeypatch)
    return monkeypatch


def _seeded_db(tmp_path, closes):
    db = tmp_path / "bt.db"
    with connect(db) as conn:
        apply_schema(conn)
    # The backtest loads SPY as its cap-weighted reality check; seed a
    # deterministic proxy so offline runs never reach for the network.
    seed_price_history(db, closes.assign(SPY=closes.mean(axis=1)))
    return db


def test_backtest_recovers_planted_momentum_factor(tmp_path, offline):
    # ~2016 → ~2020, with rank jitter so monthly ICs vary below 1.0
    closes = drift_universe(N_NAMES, "2016-01-04", 1250, jitter=0.005)
    db = _seeded_db(tmp_path, closes)
    patch_membership(offline, list(closes.columns), list(closes.columns))

    rep = run_backtest(db, start_year=2017)

    mom = next(f for f in rep.factor_ics if f.factor == "mom")
    assert mom.mean_ic > 0.8  # drift dominates next-month ranks
    assert mom.ic_tstat_nw > 3.0
    trend = next(f for f in rep.factor_ics if f.factor == "trend")
    assert trend.mean_ic > 0.5
    cortex = next(v for v in rep.variants if v.label.startswith("CORTEX"))
    assert cortex.mean_ic > 0.8
    # Every synthetic member is priced every month — no residual gap.
    assert rep.universe_coverage_mean == pytest.approx(1.0)
    assert rep.universe_coverage_min == pytest.approx(1.0)
    # The seeded SPY proxy shows up as the cap-weighted reality check.
    assert rep.spy_cagr is not None and rep.spy_sharpe is not None


def test_backtest_is_reproducible_offline(tmp_path, offline):
    closes = drift_universe(N_NAMES, "2016-01-04", 1000)
    db = _seeded_db(tmp_path, closes)
    patch_membership(offline, list(closes.columns), list(closes.columns))

    r1 = run_backtest(db, start_year=2017)
    r2 = run_backtest(db, start_year=2017)
    assert [v.mean_ic for v in r1.variants] == [v.mean_ic for v in r2.variants]
    assert [f.ic_tstat_nw for f in r1.factor_ics] == [
        f.ic_tstat_nw for f in r2.factor_ics
    ]


def test_long_short_net_charges_only_turnover(tmp_path, offline):
    closes = drift_universe(N_NAMES, "2016-01-04", 1250)
    db = _seeded_db(tmp_path, closes)
    patch_membership(offline, list(closes.columns), list(closes.columns))

    ls = run_backtest(db, start_year=2017).long_short
    assert ls is not None
    assert ls.tstat_nw_net <= ls.tstat_nw
    # Static drift ranking → deciles never change after month 1: the only
    # cost is the first month's full build (10bps long + 25bps short).
    expected_drag = (0.0010 + 0.0025) / ls.n_months
    assert ls.mean_monthly - ls.mean_monthly_net == pytest.approx(
        expected_drag, rel=1e-6
    )


def test_pit_membership_drives_universe_coverage(tmp_path, offline):
    closes = drift_universe(N_NAMES, "2016-01-04", 1250)
    # DEADX delists: no prices after mid-2018.
    dead = closes["T000"].copy()
    dead.iloc[650:] = float("nan")
    closes = closes.assign(DEADX=dead)
    db = _seeded_db(tmp_path, closes)

    all_names = list(closes.columns)
    drop_date = _d(closes.index, 650)

    # Membership never drops DEADX → months after delisting can't price a
    # true member → coverage dips below 1.
    patch_membership(offline, all_names, all_names)
    stale = run_backtest(db, start_year=2017)
    assert stale.universe_coverage_min < 1.0

    # Point-in-time membership removes DEADX at its delisting → clean.
    def members(d: date):
        return all_names if d < drop_date else [t for t in all_names if t != "DEADX"]

    patch_membership(offline, members, all_names)
    pit = run_backtest(db, start_year=2017)
    assert pit.universe_coverage_min == pytest.approx(1.0)


def test_congress_oos_verdict_keys_off_nw_tstat(tmp_path, offline):
    closes = drift_universe(N_NAMES, "2016-01-04", 2000)  # ~2016 → ~2023
    db = _seeded_db(tmp_path, closes)
    names = list(closes.columns)
    patch_membership(offline, names, names)

    # Congress buys the strongest-drift names, sells the weakest, disclosed
    # quarterly across the whole sample — the factor ranks next-month returns.
    rows = []
    disclosure_dates = [d for d in closes.index[::63]]
    for k, when in enumerate(disclosure_dates):
        for j, t in enumerate(names[-30:]):
            rows.append(
                (
                    f"buy-{k}-{j}",
                    "Sen. Alpha",
                    t,
                    "Purchase",
                    "$50,001 - $100,000",
                    when.date(),
                    when.date(),
                )
            )
        for j, t in enumerate(names[:30]):
            rows.append(
                (
                    f"sell-{k}-{j}",
                    "Sen. Alpha",
                    t,
                    "Sale (Full)",
                    "$50,001 - $100,000",
                    when.date(),
                    when.date(),
                )
            )
    with connect(db) as conn:
        conn.executemany(
            "INSERT INTO congress_trades "
            "(id, senator, ticker, transaction_type, amount, transaction_date,"
            " disclosure_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    rep = run_congress_oos(db, start_year=2017, insample_end_year=2019)
    assert rep.oos_n_months > 12
    assert rep.oos_mean_ic > 0.5
    # The verdict must key off the NW t-stat, not the naive IID t.
    if rep.oos_ic_tstat_nw >= 3.0:
        assert rep.verdict.startswith("EDGE CONFIRMED")
    elif rep.oos_ic_tstat_nw >= 2.0:
        assert rep.verdict.startswith("INTERESTING")
    else:
        assert rep.verdict.startswith("NO EDGE")
    assert "NW" in rep.verdict


def _flat_market_with_event_name(days: int, abnormal_days: range):
    """50 identical background names + EVENT with +2% total abnormal drift."""
    import numpy as np

    idx = pd.bdate_range("2017-06-01", periods=days)
    t = np.arange(days, dtype=float)
    base = np.exp(np.log(100.0) + 0.0002 * t + 0.004 * np.where(t % 2 == 0, 1, -1))
    data = {f"B{i:03d}": base for i in range(50)}
    ev = base.copy()
    bump = np.ones(days)
    for d in abnormal_days:
        bump[d:] *= 1.02 ** (1 / len(abnormal_days))
    data["EVENT"] = ev * bump
    return pd.DataFrame(data, index=idx)


def test_event_study_recovers_planted_drift_and_collapses(tmp_path, offline):
    days = 500
    event_day = 320
    closes = _flat_market_with_event_name(days, range(event_day, event_day + 6))
    db = _seeded_db(tmp_path, closes)
    names = list(closes.columns)
    patch_membership(offline, names, names)

    when = _d(closes.index, event_day)
    soon = _d(closes.index, event_day + 2)  # overlaps → collapse
    with connect(db) as conn:
        conn.executemany(
            "INSERT INTO activist_stakes (id, ticker, subject_cik, filer,"
            " filing_date) VALUES (?, ?, ?, ?, ?)",
            [
                ("ev1", "EVENT", "0001", "Fund", when),
                ("ev2", "EVENT", "0001", "Fund", soon),
            ],
        )

    rep = run_event_study(db, signal="activism", from_year=2018)
    h5 = next(h for h in rep.horizons if h.w_end == 5)
    assert h5.n == 1
    assert h5.n_collapsed == 1  # the 2-days-later duplicate was dropped
    assert h5.mean_car == pytest.approx(0.02, abs=0.004)
    assert abs(rep.placebo.mean_car) < 0.005
    assert rep.market_model is True


def test_market_model_kills_spurious_beta_car(tmp_path, offline):
    """A beta-2 name in a trending market shows CAR under market-adjustment
    but ~0 under the market model."""
    import numpy as np

    days = 500
    idx = pd.bdate_range("2017-06-01", periods=days)
    t = np.arange(days, dtype=float)
    m = 0.001 + 0.004 * np.where(t % 2 == 0, 1.0, -1.0)  # market daily return
    base = 100.0 * np.cumprod(1 + m)
    beta2 = 100.0 * np.cumprod(1 + 2 * m)
    data = {f"B{i:03d}": base for i in range(50)}
    data["BETA2"] = beta2
    closes = pd.DataFrame(data, index=idx)

    db = _seeded_db(tmp_path, closes)
    names = list(closes.columns)
    patch_membership(offline, names, names)
    when = _d(idx, 320)
    with connect(db) as conn:
        conn.execute(
            "INSERT INTO activist_stakes (id, ticker, subject_cik, filer,"
            " filing_date) VALUES (?, ?, ?, ?, ?)",
            ["b2", "BETA2", "0002", "Fund", when],
        )

    ma = run_event_study(db, signal="activism", from_year=2018, market_model=False)
    mm = run_event_study(db, signal="activism", from_year=2018, market_model=True)
    car_ma = next(h for h in ma.horizons if h.w_end == 60).mean_car
    car_mm = next(h for h in mm.horizons if h.w_end == 60).mean_car
    assert car_ma > 0.02  # spurious: beta exposure read as abnormal return
    assert abs(car_mm) < 0.25 * car_ma
