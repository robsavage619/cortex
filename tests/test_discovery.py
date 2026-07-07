from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from cortex.composite import Z_CLIP, build_blocks
from cortex.discovery import _zscore_series, list_candidates, run_discovery
from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema

# ── z-score math ──────────────────────────────────────────────────────────────


def test_zscore_series_basic():
    z = _zscore_series({"A": 1.0, "B": 2.0, "C": 3.0})
    assert z["B"] == pytest.approx(0.0)
    assert z["A"] is not None and z["C"] is not None
    assert z["A"] == pytest.approx(-z["C"])


def test_zscore_series_preserves_none():
    z = _zscore_series({"A": 1.0, "B": None, "C": 3.0})
    assert z["B"] is None
    assert z["A"] is not None


def test_zscore_series_winsorizes_at_clip():
    values: dict[str, float | None] = {f"T{i}": 0.0 for i in range(50)}
    values["OUTLIER"] = 1000.0
    z = _zscore_series(values)
    assert z["OUTLIER"] == pytest.approx(Z_CLIP)


def test_zscore_series_zero_std():
    z = _zscore_series({"A": 5.0, "B": 5.0, "C": None})
    assert z["A"] == 0.0
    assert z["C"] is None


def test_zscore_series_too_few_valid():
    z = _zscore_series({"A": 1.0, "B": None})
    assert z == {"A": None, "B": None}


# ── composite parity: discovery's dict math == composite.build_blocks ────────


def test_composite_block_math_matches_build_blocks():
    zmom = np.array([1.0, np.nan, -0.5])
    ztrend = np.array([0.5, 2.0, np.nan])
    zval = np.array([np.nan, np.nan, 1.0])
    zqual = np.array([0.2, np.nan, np.nan])
    zcong = np.array([np.nan, 1.0, np.nan])
    zfund = np.array([0.4, np.nan, np.nan])

    expected = build_blocks(zmom, ztrend, zval, zqual, zcong, zfund)["cortex"]

    def dict_composite(i: int) -> float:
        blocks = []
        for pair in (
            (zmom[i], ztrend[i]),
            (zval[i], zqual[i]),
            (zcong[i], zfund[i]),
        ):
            valid = [v for v in pair if not np.isnan(v)]
            if valid:
                blocks.append(sum(valid) / len(valid))
        return sum(blocks) / len(blocks) if blocks else float("nan")

    for i in range(3):
        assert dict_composite(i) == pytest.approx(expected[i])


# ── pipeline semantics with synthetic data (no network) ──────────────────────


def _synthetic_price_data(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """Monotone factor values so the expected ranking is fully determined."""
    out: dict[str, dict[str, Any]] = {}
    for i, t in enumerate(tickers):
        strength = 1.0 - i / len(tickers)  # earlier tickers are stronger
        out[t] = {
            "momentum_12_1": strength,
            "vol_252d": 0.2,
            "sharpe_12m": strength,
            "above_200d_sma": t != "BELOWTREND",
            "trend_200d": strength if t != "BELOWTREND" else -0.1,
            "last_close": 100.0,
        }
    return out


@pytest.fixture
def discovery_env(tmp_path, monkeypatch):
    tickers = [f"TK{i:02d}" for i in range(20)] + ["BELOWTREND"]
    monkeypatch.setattr(
        "cortex.sources.universe.sp500_tickers", lambda: list(tickers)
    )
    monkeypatch.setattr(
        "cortex.discovery._compute_price_factors",
        lambda ts: _synthetic_price_data(ts),
    )
    monkeypatch.setattr(
        "cortex.discovery._pit_fundamentals",
        lambda db, ts, pd_, as_of: {
            t: {"earnings_yield": 0.05, "roe": 0.15} for t in ts
        },
    )
    flow_names = {"TK03": 2.0, "TK05": 1.0, "TK07": -1.0}
    monkeypatch.setattr(
        "cortex.discovery._flow_scores",
        lambda db, ts, as_of: (
            {t: flow_names.get(t) for t in ts},
            {t: None for t in ts},
        ),
    )
    db = tmp_path / "disc.db"
    with connect(db) as conn:
        apply_schema(conn)
    return db, tickers


def test_run_discovery_ranks_are_contiguous_true_positions(discovery_env):
    db, _ = discovery_env
    out = run_discovery(db, top_n=5)
    unforced = [c for c in out if not c.forced]
    assert [c.composite_rank for c in unforced] == [1, 2, 3, 4, 5]
    assert all(not c.forced for c in out)


def test_run_discovery_trend_gate_excludes_below_trend(discovery_env):
    db, _ = discovery_env
    out = run_discovery(db, top_n=30)
    assert all(c.ticker != "BELOWTREND" for c in out)


def test_run_discovery_forced_gets_true_rank_and_flag(discovery_env):
    db, _ = discovery_env
    out = run_discovery(db, top_n=3, force_include=["TK15", "TK00"])
    by_ticker = {c.ticker: c for c in out}
    # TK00 is the strongest name — inside top_n, so not flagged forced.
    assert by_ticker["TK00"].composite_rank == 1
    assert by_ticker["TK00"].forced is False
    # TK15 ranks far outside top 3 — persisted with its TRUE rank + flag.
    weak = by_ticker["TK15"]
    assert weak.forced is True
    assert weak.composite_rank > 3
    ranks = [c.composite_rank for c in out]
    assert len(set(ranks)) == len(ranks)  # no duplicated/fabricated ranks


def test_run_discovery_forced_below_trend_still_scored(discovery_env):
    db, _ = discovery_env
    out = run_discovery(db, top_n=3, force_include=["BELOWTREND"])
    below = next(c for c in out if c.ticker == "BELOWTREND")
    assert below.forced is True
    assert below.composite_rank > 3


def test_run_discovery_flow_z_populated_for_event_names(discovery_env):
    db, _ = discovery_env
    out = run_discovery(db, top_n=30)
    by_ticker = {c.ticker: c for c in out}
    # Names with congress events get a z over the event-having cross-section;
    # everyone else stays None (sparse coverage — matches backtest NaN
    # semantics; no zero-imputation).
    z03 = by_ticker["TK03"].z_congress
    z07 = by_ticker["TK07"].z_congress
    assert z03 is not None and z07 is not None
    assert by_ticker["TK05"].z_congress is not None
    assert z03 > z07
    others = [c for c in out if c.ticker not in ("TK03", "TK05", "TK07")]
    assert all(c.z_congress is None for c in others)
    assert all(c.z_fund_flow is None for c in out)


def test_store_load_round_trip(discovery_env):
    db, _ = discovery_env
    stored = run_discovery(db, top_n=5, force_include=["TK18"])
    loaded = list_candidates(db)
    assert [c.ticker for c in loaded] == [c.ticker for c in stored]
    assert [c.forced for c in loaded] == [c.forced for c in stored]
    assert [c.composite_rank for c in loaded] == [
        c.composite_rank for c in stored
    ]


def test_rank_stability_across_reruns(discovery_env):
    db, _ = discovery_env
    first = run_discovery(db, top_n=10)
    second = run_discovery(db, top_n=10)
    assert [(c.ticker, c.composite_rank) for c in first] == [
        (c.ticker, c.composite_rank) for c in second
    ]
