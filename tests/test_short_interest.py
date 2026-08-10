from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from cortex.backtest import _load_short_volume, _short_interest_asof
from cortex.sources.short_interest import _parse, fetch_session, sync_short_volume
from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema

_FILE = """Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
20250815|AAPL|169646|0|439327|B,Q,N
20250815|MSFT|637122|1381|1903721|B,Q,N
20250815|ZEROVOL|0|0|0|Q
20250815|BAD|notanumber|0|100|Q
"""

_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20250815.txt"


def test_parse_extracts_rows_and_skips_junk():
    rows = _parse(_FILE, None)
    tickers = {r[0] for r in rows}
    assert tickers == {"AAPL", "MSFT"}
    # zero total volume would make sfrac 0/0
    assert "ZEROVOL" not in tickers
    # unparseable numbers are dropped, not crashed on
    assert "BAD" not in tickers
    aapl = next(r for r in rows if r[0] == "AAPL")
    assert aapl[1] == dt.date(2025, 8, 15)
    assert aapl[2] == 169646
    assert aapl[3] == 439327


def test_parse_filters_to_wanted_universe():
    rows = _parse(_FILE, {"AAPL"})
    assert {r[0] for r in rows} == {"AAPL"}


@respx.mock
def test_fetch_session_treats_403_as_no_file():
    """FINRA answers 403, not 404, for a file it is not serving.

    A Sunday and a pre-archive session look identical at the HTTP layer, so
    treating 403 as fatal aborted the entire backfill on its first weekend.
    """
    respx.get(_URL).mock(return_value=httpx.Response(403))
    assert fetch_session(dt.date(2025, 8, 15)) is None


@respx.mock
def test_fetch_session_treats_404_as_no_file():
    respx.get(_URL).mock(return_value=httpx.Response(404))
    assert fetch_session(dt.date(2025, 8, 15)) is None


@respx.mock
def test_fetch_session_returns_rows():
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_FILE))
    rows = fetch_session(dt.date(2025, 8, 15))
    assert rows is not None
    assert len(rows) == 2


@respx.mock
def test_sync_records_coverage_for_unpublished_sessions(tmp_path):
    """A probed-and-absent session must be recorded, or every run refetches it."""
    db = tmp_path / "s.db"
    with connect(db) as conn:
        apply_schema(conn)
    respx.get(url__regex=r".*CNMSshvol\d+\.txt").mock(return_value=httpx.Response(403))

    sync_short_volume(db, start=dt.date(2025, 8, 11), end=dt.date(2025, 8, 12))
    with connect(db, read_only=True) as conn:
        cov = conn.execute(
            "SELECT date, rows FROM short_volume_coverage ORDER BY date"
        ).fetchall()
    assert [r[1] for r in cov] == [0, 0]
    assert len(cov) == 2


@respx.mock
def test_sync_skips_already_covered_sessions(tmp_path):
    db = tmp_path / "s2.db"
    with connect(db) as conn:
        apply_schema(conn)
    route = respx.get(url__regex=r".*CNMSshvol\d+\.txt").mock(
        return_value=httpx.Response(200, text=_FILE)
    )

    sync_short_volume(db, start=dt.date(2025, 8, 15), end=dt.date(2025, 8, 15))
    first = route.call_count
    sync_short_volume(db, start=dt.date(2025, 8, 15), end=dt.date(2025, 8, 15))
    assert route.call_count == first  # no refetch


@respx.mock
def test_sync_skips_weekends(tmp_path):
    db = tmp_path / "s3.db"
    with connect(db) as conn:
        apply_schema(conn)
    route = respx.get(url__regex=r".*CNMSshvol\d+\.txt").mock(
        return_value=httpx.Response(200, text=_FILE)
    )
    # 2025-08-16 is a Saturday, 2025-08-17 a Sunday
    sync_short_volume(db, start=dt.date(2025, 8, 16), end=dt.date(2025, 8, 17))
    assert route.call_count == 0


def _seed(db, rows):
    with connect(db) as conn:
        apply_schema(conn)
        conn.executemany(
            "INSERT INTO short_volume (ticker, date, short_volume, total_volume) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )


def test_short_interest_asof_is_point_in_time(tmp_path):
    """Sessions after as_of must never be consulted."""
    db = tmp_path / "pit.db"
    _seed(
        db,
        [
            ("AAPL", dt.date(2025, 8, 11), 50, 100),  # sfrac 0.50
            ("AAPL", dt.date(2025, 8, 20), 90, 100),  # after as_of — must be ignored
        ],
    )
    by_session = _load_short_volume(db)
    asof = _short_interest_asof(by_session, dt.date(2025, 8, 15))
    assert asof["AAPL"] == pytest.approx(0.50)


def test_short_interest_asof_averages_the_formation_window(tmp_path):
    db = tmp_path / "win.db"
    _seed(
        db,
        [
            ("AAPL", dt.date(2025, 8, 11), 20, 100),
            ("AAPL", dt.date(2025, 8, 12), 40, 100),
        ],
    )
    by_session = _load_short_volume(db)
    asof = _short_interest_asof(by_session, dt.date(2025, 8, 12))
    assert asof["AAPL"] == pytest.approx(0.30)


def test_short_interest_asof_uses_only_the_last_n_sessions(tmp_path):
    """Window is fixed at 5 from the paper and must not silently widen."""
    db = tmp_path / "cap.db"
    _seed(
        db,
        [("AAPL", dt.date(2025, 8, d), 100, 100) for d in range(1, 6)]
        + [("AAPL", dt.date(2025, 8, 8), 0, 100)],
    )
    by_session = _load_short_volume(db)
    # 6 sessions exist; only the last 5 count, so the all-short early day drops out
    asof = _short_interest_asof(by_session, dt.date(2025, 8, 8), window=5)
    assert asof["AAPL"] < 1.0


def test_short_interest_asof_empty_before_any_data(tmp_path):
    db = tmp_path / "none.db"
    _seed(db, [("AAPL", dt.date(2025, 8, 11), 50, 100)])
    by_session = _load_short_volume(db)
    assert _short_interest_asof(by_session, dt.date(2020, 1, 1)) == {}


def test_load_short_volume_missing_table_is_empty(tmp_path):
    """A pre-v20 DB must degrade to an empty factor, not explode."""
    db = tmp_path / "old.db"
    with connect(db) as conn:
        conn.execute("CREATE TABLE placeholder (x INTEGER)")
    assert _load_short_volume(db) == {}
