"""Offline price fixtures: seed the DuckDB price cache with synthetic series.

Because every research price read goes through ``cortex.sources.prices``,
pre-populating the ``prices`` table (with coverage records through today)
makes backtests, OOS tests, and event studies run end-to-end with zero
network access.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cortex.sources.prices import store_frames
from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema


def seed_price_history(db_path: Path, closes: pd.DataFrame) -> None:
    """Write a wide close frame into the cache with coverage through today.

    Coverage is recorded from before the first bar through today so
    ``load_ohlcv`` treats every ticker as fully cached and never fetches.
    """
    with connect(db_path) as conn:
        apply_schema(conn)
    frames = {
        "close": closes,
        "high": closes * 1.01,
        "low": closes * 0.99,
        "volume": closes * 0.0 + 1_000_000.0,
    }
    # Coverage from 1996 = "nothing exists before the first bar" (the same
    # semantics as a real pre-IPO gap), so any requested start is a cache hit.
    store_frames(
        db_path,
        frames,
        cover_start=date(1996, 1, 1),
        cover_end=date.today(),
    )


def drift_universe(
    n_names: int,
    start: str,
    days: int,
    *,
    base: float = 100.0,
    drift_spread: float = 0.002,
    wobble: float = 0.004,
    jitter: float = 0.0,
    prefix: str = "T",
) -> pd.DataFrame:
    """Deterministic universe where ticker index ranks daily drift.

    Ticker ``{prefix}000`` has the most negative drift, the last ticker the
    most positive, so momentum/trend factor ranks are fully determined. A
    small alternating wobble keeps realised vol positive (the backtest
    excludes zero-vol names) without disturbing the ranking. ``jitter`` adds
    a ticker-phased sinusoid so monthly ICs vary below 1.0 (a constant IC
    series has zero variance and a degenerate t-stat).
    """
    idx = pd.bdate_range(start, periods=days)
    t = np.arange(days, dtype=float)
    wob = wobble * np.where(t % 2 == 0, 1.0, -1.0)
    data = {}
    for i in range(n_names):
        mu = -drift_spread / 2 + drift_spread * i / max(n_names - 1, 1)
        logp = np.log(base) + mu * t + wob
        if jitter:
            logp = logp + jitter * np.sin(2 * np.pi * (t / 40 + i / n_names))
        data[f"{prefix}{i:03d}"] = np.exp(logp)
    return pd.DataFrame(data, index=idx)


def block_network(monkeypatch: Any) -> None:
    """Make any yfinance/Stooq access fail loudly — the tests must be offline."""
    import httpx
    import yfinance

    def _no_network(*_a: Any, **_k: Any) -> None:
        raise AssertionError("network access attempted in an offline test")

    monkeypatch.setattr(yfinance, "download", _no_network)
    monkeypatch.setattr(httpx.Client, "get", _no_network)


def patch_membership(
    monkeypatch: Any,
    members_by_date: Callable[[date], Iterable[str]] | Iterable[str],
    universe: list[str],
) -> None:
    """Point the backtest's PIT membership lookups at a synthetic universe.

    ``members_by_date`` is either a static iterable of tickers or a callable
    ``date -> iterable`` for time-varying membership.
    """
    if callable(members_by_date):
        fn = members_by_date
        asof = lambda d: frozenset(fn(d))  # noqa: E731
    else:
        static = frozenset(members_by_date)
        asof = lambda d: static  # noqa: E731
    monkeypatch.setattr("cortex.sources.universe.sp500_members_asof", asof)
    monkeypatch.setattr(
        "cortex.sources.universe.sp500_union",
        lambda start, end=None: list(universe),
    )
