from __future__ import annotations

from datetime import date

import pytest

from cortex.sources.universe import sp500_members_asof, sp500_union


def test_members_asof_known_index_changes():
    # TSLA joined the index 2020-12-21.
    assert "TSLA" not in sp500_members_asof(date(2020, 12, 18))
    assert "TSLA" in sp500_members_asof(date(2020, 12, 21))
    # FRC (First Republic) was removed after its 2023 collapse.
    assert "FRC" in sp500_members_asof(date(2023, 3, 1))
    assert "FRC" not in sp500_members_asof(date(2023, 6, 1))
    # BBBY was a member in 2017 and is long gone today.
    assert "BBBY" in sp500_members_asof(date(2017, 6, 1))
    assert "BBBY" not in sp500_members_asof(date.today())


def test_members_asof_ticker_normalisation():
    # Dataset uses BF.B; everything else in universe.py uses yfinance BF-B.
    members = sp500_members_asof(date(2024, 1, 2))
    assert "BF-B" in members
    assert not any("." in t for t in members)


def test_members_asof_prehistory_raises():
    with pytest.raises(ValueError):
        sp500_members_asof(date(1990, 1, 1))


def test_union_is_superset_of_endpoints():
    start = date(2017, 1, 3)
    union = set(sp500_union(start))
    assert sp500_members_asof(start) <= union
    assert sp500_members_asof(date.today()) <= union
    # Delisted names inside the window must appear in the union.
    assert "FRC" in union
