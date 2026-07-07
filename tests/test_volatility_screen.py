from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema
from cortex.volatility_screen import (
    _metrics_batch,
    _sign,
    list_volatility_screen,
    run_volatility_screen,
)


def test_sign():
    assert _sign(2.0) == 1
    assert _sign(-0.1) == -1
    assert _sign(0.0) == 0


def _ohlc_frame(tickers: list[str], closes: dict[str, list[float]]) -> pd.DataFrame:
    """Build the MultiIndex (field, ticker) frame yf.download returns."""
    n = len(next(iter(closes.values())))
    idx = pd.bdate_range("2026-01-02", periods=n)
    data = {}
    for t in tickers:
        c = np.array(closes[t], dtype=float)
        data[("Close", t)] = c
        data[("High", t)] = c * 1.02
        data[("Low", t)] = c * 0.98
        data[("Volume", t)] = np.full(n, 1_000_000.0)
    return pd.DataFrame(data, index=idx)


@pytest.fixture
def fake_download(monkeypatch):
    def _install(frame: pd.DataFrame) -> None:
        import yfinance

        monkeypatch.setattr(yfinance, "download", lambda *a, **k: frame.copy())

    return _install


def test_metrics_batch_scores_swinger_above_trender(fake_download):
    n = 40
    # OSC oscillates hard around 100; TREND drifts smoothly upward.
    osc = [100.0 + (8.0 if i % 2 == 0 else -8.0) for i in range(n)]
    trend = [100.0 + i * 0.3 for i in range(n)]
    fake_download(_ohlc_frame(["OSC", "TREND"], {"OSC": osc, "TREND": trend}))

    m = _metrics_batch(["OSC", "TREND"], lookback_days=20)

    assert m["OSC"]["oscillation_score"] > m["TREND"]["oscillation_score"]
    assert m["OSC"]["direction_changes"] > m["TREND"]["direction_changes"]
    for t in ("OSC", "TREND"):
        assert m[t]["swing_score"] > 0
        assert 0 < m[t]["range_consistency"] <= 1
        assert m[t]["avg_close"] > 0


def test_metrics_batch_short_history_gets_empty_metrics(fake_download):
    fake_download(
        _ohlc_frame(["SHORT"], {"SHORT": [100.0, 101.0, 99.0, 100.5, 100.0]})
    )
    m = _metrics_batch(["SHORT"], lookback_days=20)
    assert m["SHORT"]["swing_score"] == 0.0
    assert m["SHORT"]["avg_dollar_range"] is None


def test_metrics_batch_missing_ticker_gets_empty_metrics(fake_download):
    n = 40
    fake_download(_ohlc_frame(["AAA"], {"AAA": [100.0 + i for i in range(n)]}))
    m = _metrics_batch(["AAA", "MISSING"], lookback_days=20)
    assert m["MISSING"]["swing_score"] == 0.0
    assert m["AAA"]["swing_score"] > 0


def _synthetic_metrics(tickers: list[str], _lookback: int) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i, t in enumerate(tickers):
        score = float(len(tickers) - i)  # earlier ticker = higher score
        out[t] = {
            "avg_dollar_range": 2.0,
            "range_consistency": 0.8,
            "avg_range_pct": 0.03,
            "max_range_pct": 0.05,
            "max_dollar_range": 4.0,
            "avg_close": 100.0,
            "oscillation_score": 0.7,
            "net_drift_pct": 0.01,
            "range_position": 0.5,
            "direction_changes": 12,
            "avg_volume": 1_000_000.0,
            "swing_score": score,
        }
    # A zero-score name must be excluded from the persisted screen.
    out[tickers[-1]]["swing_score"] = 0.0
    return out


def test_run_volatility_screen_ranking_and_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "cortex.volatility_screen._compute_metrics", _synthetic_metrics
    )
    monkeypatch.setattr(
        "cortex.volatility_screen._fetch_company_names",
        lambda ts: {t: f"{t} Corp" for t in ts},
    )
    db = tmp_path / "vol.db"
    with connect(db) as conn:
        apply_schema(conn)

    tickers = ["AL", "BE", "CE", "DE", "ZERO"]
    stocks = run_volatility_screen(db, top_n=3, lookback_days=20, tickers=tickers)

    assert [s.ticker for s in stocks] == ["AL", "BE", "CE"]
    assert [s.rank for s in stocks] == [1, 2, 3]
    assert all(s.swing_score > 0 for s in stocks)

    loaded = list_volatility_screen(db)
    assert [(s.ticker, s.rank) for s in loaded] == [
        (s.ticker, s.rank) for s in stocks
    ]
    assert loaded[0].company_name == "AL Corp"


def test_run_volatility_screen_empty_metrics_preserves_existing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "cortex.volatility_screen._compute_metrics", _synthetic_metrics
    )
    monkeypatch.setattr(
        "cortex.volatility_screen._fetch_company_names",
        lambda ts: dict.fromkeys(ts),
    )
    db = tmp_path / "vol.db"
    with connect(db) as conn:
        apply_schema(conn)
    run_volatility_screen(db, top_n=2, lookback_days=20, tickers=["AL", "BE", "Z"])
    assert len(list_volatility_screen(db)) == 2

    # A run where every name scores zero must NOT wipe the stored screen.
    def _all_zero(ts: list[str], lb: int) -> dict[str, dict[str, Any]]:
        return {
            t: {**_synthetic_metrics(ts, lb)[t], "swing_score": 0.0} for t in ts
        }

    monkeypatch.setattr("cortex.volatility_screen._compute_metrics", _all_zero)
    out = run_volatility_screen(db, top_n=2, lookback_days=20, tickers=["AL", "BE"])
    assert out == []
    assert len(list_volatility_screen(db)) == 2
