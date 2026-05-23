from __future__ import annotations

import sys
import types

import pytest

from wst.sources.market import MarketSourceError, history_for


def test_history_rejects_invalid_period():
    with pytest.raises(MarketSourceError, match="Invalid period"):
        history_for("AAPL", period="13mo")


def test_history_parses_bars(monkeypatch):
    import datetime as dt

    rows = [
        (
            dt.datetime(2026, 1, 2),
            {"Open": 10.0, "High": 11.0, "Low": 9.5, "Close": 10.5, "Volume": 100},
        ),
        (
            dt.datetime(2026, 1, 3),
            {"Open": 10.5, "High": 12.0, "Low": 10.0, "Close": 11.8, "Volume": 200},
        ),
    ]

    class FakeFrame:
        def iterrows(self):
            return iter(rows)

    class FakeTicker:
        def __init__(self, _symbol: str) -> None:
            pass

        def history(self, *, period: str, interval: str) -> FakeFrame:
            assert period == "6mo"
            assert interval == "1d"
            return FakeFrame()

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    bars = history_for("AAPL", period="6mo")
    assert [b.date for b in bars] == ["2026-01-02", "2026-01-03"]
    assert bars[1].close == 11.8
    assert bars[0].volume == 100.0
