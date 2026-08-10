from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pytest

from cortex.backtest import (
    _amount_midpoint,
    _congress_sign,
    _factor_corr,
    _Fundamental,
    _fundamental_asof,
    _nw_tstat,
    _series_stats,
    _spearman_ic,
    _zscore,
)


def test_amount_midpoint_parses_ranges():
    assert _amount_midpoint("$1,001 - $15,000") == 8000.5
    assert _amount_midpoint("$15,001 - $50,000") == 32500.5
    assert _amount_midpoint("$1,000,001 - $5,000,000") == 3000000.5
    # single value
    assert _amount_midpoint("$50,000,000") == 50000000.0
    # junk
    assert _amount_midpoint("--") == 0.0
    assert _amount_midpoint("") == 0.0


def test_congress_sign():
    assert _congress_sign("Purchase") == 1
    assert _congress_sign("Sale (Full)") == -1
    assert _congress_sign("Sale (Partial)") == -1
    assert _congress_sign("Exchange") == 0


def test_fundamental_asof_is_point_in_time():
    """Only filings disclosed on/before as_of count; latest per ticker wins."""
    funds = [
        _Fundamental("AAPL", dt.date(2023, 11, 1), eps_diluted=6.0, roe=1.5),
        _Fundamental("AAPL", dt.date(2024, 11, 1), eps_diluted=6.1, roe=1.6),
        _Fundamental("MSFT", dt.date(2024, 7, 30), eps_diluted=11.0, roe=0.4),
    ]
    # As of mid-2024: AAPL's 2024 10-K not yet filed → use 2023; MSFT not yet filed.
    asof_mid = _fundamental_asof(funds, dt.date(2024, 6, 1))
    assert asof_mid["AAPL"].eps_diluted == 6.0
    assert "MSFT" not in asof_mid

    # As of end-2024: both companies' latest filings are public.
    asof_end = _fundamental_asof(funds, dt.date(2024, 12, 1))
    assert asof_end["AAPL"].eps_diluted == 6.1  # latest ≤ as_of
    assert asof_end["MSFT"].eps_diluted == 11.0


def test_load_fundamentals_breaks_filing_date_ties_by_period(tmp_path):
    """One 10-K discloses several comparative periods under a single filing_date.

    The rows are inserted newest-period-first so storage order alone would hand
    _fundamental_asof the *oldest* period — the defect that priced WDC off a
    2023 quarter and left SNDK with a NULL EPS.
    """
    from cortex.backtest import _load_fundamentals
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    db = tmp_path / "f.db"
    with connect(db) as conn:
        apply_schema(conn)
        conn.executemany(
            "INSERT INTO fundamentals "
            "(ticker, period_end, filing_date, eps_diluted, net_income, equity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("WDC", dt.date(2025, 6, 27), dt.date(2025, 8, 14), 9.9, 200.0, 1000.0),
                (
                    "WDC",
                    dt.date(2023, 9, 29),
                    dt.date(2025, 8, 14),
                    -2.17,
                    -50.0,
                    1000.0,
                ),
            ],
        )

    asof = _fundamental_asof(_load_fundamentals(db), dt.date(2026, 8, 10))
    assert asof["WDC"].eps_diluted == 9.9


def _fund_db(tmp_path, rows, prices=()):
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    db = tmp_path / "fund.db"
    with connect(db) as conn:
        apply_schema(conn)
        conn.executemany(
            "INSERT INTO fund_holdings "
            "(id, manager, manager_cik, ticker, action, shares, prev_shares, "
            "value, period) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        if prices:
            conn.executemany(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", prices
            )
    return db


def test_load_fund_events_sizes_exit_from_prior_position(tmp_path):
    """An EXIT closes the position, so its `value` is 0.

    Sizing off `value` made log1p(0) == 0 trip the `weight <= 0` guard and
    dropped every EXIT row in the table — the fund factor's negative leg was
    carrying TRIM alone. Magnitude has to come from prev_shares × last close.
    """
    from cortex.backtest import _load_fund_events

    db = _fund_db(
        tmp_path,
        [
            ("a", "M", "1", "AAPL", "EXIT", 0, 1000, 0, dt.date(2025, 5, 15)),
            ("b", "M", "1", "MSFT", "ADD", 500, 100, 50_000, dt.date(2025, 5, 15)),
        ],
        prices=[("AAPL", dt.date(2025, 5, 13), 200.0)],
    )

    from cortex.composite import FUND_SELL_WEIGHT

    events = {e.ticker: e.signed_weight for e in _load_fund_events(db)}
    assert set(events) == {"AAPL", "MSFT"}
    # 1000 shares * $200 = $200k of sell pressure, signed negative and damped
    # by the pre-registered sell weight (Agarwal 2013: sells carry less
    # information than buys, so they are not mirror images).
    assert events["AAPL"] == pytest.approx(-FUND_SELL_WEIGHT * math.log1p(200_000.0))
    assert events["MSFT"] > 0


def test_fund_sells_are_damped_relative_to_buys(tmp_path):
    """Buys and sells are not mirror images — the sell weight must bite."""
    from cortex.backtest import _load_fund_events
    from cortex.composite import FUND_SELL_WEIGHT

    assert 0.0 <= FUND_SELL_WEIGHT <= 1.0
    db = _fund_db(
        tmp_path,
        [
            ("a", "M", "1", "AAPL", "ADD", 500, 100, 100_000, dt.date(2025, 5, 15)),
            ("b", "M", "1", "MSFT", "TRIM", 100, 500, 100_000, dt.date(2025, 5, 15)),
        ],
    )
    ev = {e.ticker: e.signed_weight for e in _load_fund_events(db)}
    # same notional on both sides, so the ratio is exactly the sell weight
    assert abs(ev["MSFT"]) == pytest.approx(FUND_SELL_WEIGHT * ev["AAPL"])


def test_load_fund_events_drops_unpriceable_exit_visibly(tmp_path, caplog):
    """No cached price near the filing date means the EXIT cannot be sized.

    It is dropped — but loudly, because that is missing sell pressure.
    """
    import logging

    from cortex.backtest import _load_fund_events

    db = _fund_db(
        tmp_path,
        [("a", "M", "1", "DELISTED", "EXIT", 0, 1000, 0, dt.date(2025, 5, 15))],
        # only a stale price, outside the 10-day lookback
        prices=[("DELISTED", dt.date(2025, 1, 2), 50.0)],
    )

    with caplog.at_level(logging.WARNING):
        assert _load_fund_events(db) == []
    assert "dropped 1 EXIT" in caplog.text


def test_load_fund_events_treats_period_as_filing_date(tmp_path):
    """`period` stores the 13F filing date, not the quarter-end.

    A price on the filing date is in-window; the quarter-end 45 days earlier is
    not what the event is dated by.
    """
    from cortex.backtest import _load_fund_events

    db = _fund_db(
        tmp_path,
        [("a", "M", "1", "AAPL", "EXIT", 0, 10, 0, dt.date(2025, 5, 15))],
        prices=[("AAPL", dt.date(2025, 3, 31), 100.0)],
    )
    # the quarter-end price is >10 days before the filing date, so no sizing
    assert _load_fund_events(db) == []


def test_split_factor_since_only_counts_events_in_window():
    from cortex.sources.splits import split_factor_since

    events = [
        (dt.date(2020, 8, 31), 4.0),
        (dt.date(2024, 6, 10), 10.0),
    ]
    # Filed after both splits — nothing to restate.
    assert split_factor_since(events, dt.date(2025, 1, 1), dt.date(2026, 8, 10)) == 1.0
    # Filed between them — only the 2024 split applies.
    assert split_factor_since(events, dt.date(2022, 1, 1), dt.date(2026, 8, 10)) == 10.0
    # Filed before both — compounding.
    assert split_factor_since(events, dt.date(2019, 1, 1), dt.date(2026, 8, 10)) == 40.0
    # A split on the filing date itself is already in the reported share count.
    assert split_factor_since(events, dt.date(2024, 6, 10), dt.date(2026, 8, 10)) == 1.0


def test_load_fundamentals_restates_eps_onto_adjusted_split_basis(tmp_path):
    """As-reported EPS vs back-adjusted prices is the BKNG implied-P/E-1.3 bug.

    A 20:1 split after the filing means one reported share is now 20, so EPS
    must be divided by 20 to sit on the same basis as the adjusted close.
    """
    from cortex.backtest import _load_fundamentals
    from cortex.sources.splits import store_splits
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    db = tmp_path / "s.db"
    with connect(db) as conn:
        apply_schema(conn)
        conn.execute(
            "INSERT INTO fundamentals "
            "(ticker, period_end, filing_date, eps_diluted, net_income, equity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                "BKNG",
                dt.date(2025, 12, 31),
                dt.date(2026, 2, 18),
                165.57,
                200.0,
                1000.0,
            ],
        )
    store_splits(db, {"BKNG": [(dt.date(2026, 5, 1), 20.0)]})

    asof = _fundamental_asof(_load_fundamentals(db), dt.date(2026, 8, 10))
    assert asof["BKNG"].eps_diluted == pytest.approx(165.57 / 20.0)
    # ROE is a ratio of aggregates — split-invariant, must be untouched.
    assert asof["BKNG"].roe == pytest.approx(0.2)


def test_load_fundamentals_leaves_eps_alone_without_cached_splits(tmp_path):
    """No split coverage must degrade to a no-op, never to a silent guess."""
    from cortex.backtest import _load_fundamentals
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    db = tmp_path / "n.db"
    with connect(db) as conn:
        apply_schema(conn)
        conn.execute(
            "INSERT INTO fundamentals "
            "(ticker, period_end, filing_date, eps_diluted, net_income, equity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ["AAPL", dt.date(2025, 9, 27), dt.date(2025, 10, 30), 6.5, 100.0, 500.0],
        )

    asof = _fundamental_asof(_load_fundamentals(db), dt.date(2026, 8, 10))
    assert asof["AAPL"].eps_diluted == 6.5


def test_zscore_winsorizes_and_preserves_nan():
    vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0, np.nan, 100.0])
    z = _zscore(vals)
    assert np.isnan(z[5])  # NaN preserved
    assert np.nanmax(z) <= 3.0 + 1e-9  # clipped at +3
    assert np.nanmin(z) >= -3.0 - 1e-9


def test_spearman_ic_perfect_and_inverse():
    sig = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    same = sig.copy()
    inv = sig[::-1].copy()
    assert _spearman_ic(sig, same) == 1.0
    assert _spearman_ic(sig, inv) == -1.0


def test_nw_tstat_shrinks_under_positive_autocorrelation():
    """A persistent (autocorrelated) series should get a smaller HAC t-stat
    than the naive IID t-stat, because effective sample size is lower."""
    rng = np.random.default_rng(0)
    n = 240
    # AR(1) with positive phi around a positive mean.
    phi, mean = 0.6, 0.02
    x = np.zeros(n)
    x[0] = mean
    for t in range(1, n):
        x[t] = mean + phi * (x[t - 1] - mean) + rng.normal(0, 0.01)
    series = list(x)
    _, naive_t, nw_t = _series_stats(series)
    assert nw_t < naive_t  # HAC correction penalizes the persistence
    assert nw_t > 0  # still detects the positive mean


def test_nw_tstat_matches_naive_for_white_noise():
    """With no autocorrelation, HAC and naive t-stats should be close."""
    rng = np.random.default_rng(1)
    series = list(0.01 + rng.normal(0, 0.005, size=400))
    _, naive_t, nw_t = _series_stats(series)
    assert abs(nw_t - naive_t) / naive_t < 0.35


def test_nw_tstat_degenerate_inputs():
    assert _nw_tstat([]) == 0.0
    assert _nw_tstat([0.1, 0.2]) == 0.0  # n < 3
    assert _nw_tstat([0.05, 0.05, 0.05, 0.05]) == 0.0  # zero variance


def test_factor_corr_recovers_correlation_and_gates_overlap():
    base = [0.1, -0.2, 0.05, 0.3, -0.1, 0.2, 0.15]
    series = {
        "a": list(base),
        "b": list(base),  # identical → corr +1
        "c": [-v for v in base],  # negated → corr -1
        "d": [float("nan")] * len(base),  # no overlap → None
    }
    fc = _factor_corr(series, ("a", "b", "c", "d"))
    idx = {k: i for i, k in enumerate(fc.factors)}
    assert fc.matrix[idx["a"]][idx["b"]] == pytest.approx(1.0)
    assert fc.matrix[idx["a"]][idx["c"]] == pytest.approx(-1.0)
    assert fc.matrix[idx["a"]][idx["d"]] is None
