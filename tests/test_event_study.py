from __future__ import annotations

import numpy as np
import pytest

from cortex.backtest import _car_window


def _make_ar(n_days: int, n_names: int) -> np.ndarray:
    """Return a zero abnormal-return array."""
    return np.zeros((n_days, n_names))


def test_car_window_positive_planted_event():
    # 30 days, 2 names. Ticker 0 earns +1% daily on days 5-15; ticker 1 flat.
    n_days, n_names = 30, 2
    price = np.ones((n_days, n_names))
    for d in range(5, 16):
        price[d, 0] = price[d - 1, 0] * 1.01

    ret = np.full((n_days, n_names), np.nan)
    ret[1:] = price[1:] / price[:-1] - 1.0

    bench = np.nanmean(ret, axis=1)
    ar = ret - bench[:, np.newaxis]

    # Event at day 5, ticker 0, window (0, 5) = days 5..10 (6 days).
    # ret[5..10, 0] = 0.01; ret[5..10, 1] = 0.0
    # bench[5..10] = 0.005 (mean of 0.01 and 0.0)
    # ar[5..10, 0] = 0.005 each → CAR = 0.005 * 6 = 0.03
    car = _car_window(ar, 5, 0, 0, 5)
    assert car is not None
    assert car == pytest.approx(0.03, abs=1e-10)


def test_car_window_negative_planted_event():
    # Symmetric: ticker 0 loses 2% daily on days 3-8, ticker 1 flat.
    n_days, n_names = 20, 2
    price = np.ones((n_days, n_names))
    for d in range(3, 9):
        price[d, 0] = price[d - 1, 0] * 0.98

    ret = np.full((n_days, n_names), np.nan)
    ret[1:] = price[1:] / price[:-1] - 1.0

    bench = np.nanmean(ret, axis=1)
    ar = ret - bench[:, np.newaxis]

    # Window (0, 4): days 3..7 (5 days)
    # ar[3..7, 0] = -0.02 - (-0.01) = -0.01 each → CAR = -0.05
    car = _car_window(ar, 3, 0, 0, 4)
    assert car is not None
    assert car == pytest.approx(-0.05, abs=1e-10)


def test_car_window_placebo_is_zero_for_flat_series():
    # Flat prices → all returns and abnormal returns are 0 or NaN.
    ar = _make_ar(30, 2)
    # Day 0 ret is NaN in typical construction; set row 0 to 0 for simplicity.
    car = _car_window(ar, 10, 0, -5, -1)
    assert car == pytest.approx(0.0)


def test_car_window_returns_none_when_window_exceeds_end():
    ar = _make_ar(30, 2)
    # Event at day 28, window (0, 5) needs rows 28..33 — out of bounds.
    assert _car_window(ar, 28, 0, 0, 5) is None


def test_car_window_returns_none_when_window_exceeds_start():
    ar = _make_ar(30, 2)
    # Event at day 2, window (-5, -1) needs rows -3..-1 — out of bounds.
    assert _car_window(ar, 2, 0, -5, -1) is None


def test_car_window_returns_none_with_nan_in_window():
    ar = _make_ar(30, 2)
    ar[7, 0] = float("nan")
    # Window (0, 5) at event day 5 spans rows 5..10, which includes row 7.
    assert _car_window(ar, 5, 0, 0, 5) is None


def test_car_window_exact_boundary_is_valid():
    # Window that ends exactly at the last row should succeed.
    ar = _make_ar(30, 2)
    # Event at 29, window (0, 0) = just row 29 → valid.
    car = _car_window(ar, 29, 0, 0, 0)
    assert car == pytest.approx(0.0)
    # Window (0, 1) at 29 needs rows 29..30 — out of bounds.
    assert _car_window(ar, 29, 0, 0, 1) is None
