from __future__ import annotations

import datetime as dt

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
