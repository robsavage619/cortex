from __future__ import annotations

import datetime as dt

import numpy as np

from cortex.backtest import (
    _amount_midpoint,
    _congress_sign,
    _Fundamental,
    _fundamental_asof,
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
