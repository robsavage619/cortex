from __future__ import annotations

import datetime as dt

from cortex.sources import congress
from cortex.sources.congress import (
    CongressTrade,
    _clean_filer,
    _parse_date,
    _parse_ptr_html,
    fetch_senate_trades,
    filter_trades,
)

# A trimmed copy of a real eFD PTR report table (two transactions, one bond row
# with no ticker that must be skipped).
_PTR_HTML = """
<table class="table">
  <thead><tr class="header">
    <th>#</th><th>Transaction Date</th><th>Owner</th><th>Ticker</th>
    <th>Asset Name</th><th>Asset Type</th><th>Type</th><th>Amount</th><th>Comment</th>
  </tr></thead>
  <tbody>
    <tr>
      <td>1</td><td>05/06/2026</td><td>Self</td>
      <td><a href="/x">ETOR</a></td>
      <td>eToro Group Ltd. - Class A</td><td>Stock</td>
      <td>Sale (Full)</td><td>$100,001 - $250,000</td><td>--</td>
    </tr>
    <tr>
      <td>2</td><td>05/07/2026</td><td>Spouse</td>
      <td>NVDA</td>
      <td>NVIDIA Corp</td><td>Stock</td>
      <td>Purchase</td><td>$1,001 - $15,000</td><td>--</td>
    </tr>
    <tr>
      <td>3</td><td>05/08/2026</td><td>Self</td>
      <td>--</td>
      <td>US Treasury Note</td><td>Corporate Bond</td>
      <td>Purchase</td><td>$50,001 - $100,000</td><td>--</td>
    </tr>
  </tbody>
</table>
"""


def test_parse_ptr_html_extracts_trades_and_skips_no_ticker():
    trades = _parse_ptr_html(
        _PTR_HTML,
        filer="Moreno, Bernardo (Senator)",
        report_url="https://efdsearch.senate.gov/search/view/ptr/abc/",
        disclosure_date=dt.date(2026, 5, 22),
    )
    # The bond row (ticker "--") is dropped; two stock rows remain.
    assert len(trades) == 2

    first = trades[0]
    assert first.senator == "Moreno, Bernardo"  # "(Senator)" suffix stripped
    assert first.ticker == "ETOR"
    assert first.transaction_type == "Sale (Full)"
    assert first.amount == "$100,001 - $250,000"
    assert first.transaction_date == dt.date(2026, 5, 6)
    assert first.disclosure_date == dt.date(2026, 5, 22)

    assert trades[1].ticker == "NVDA"
    assert trades[1].transaction_type == "Purchase"


def test_dedupe_id_is_stable_and_distinct():
    a = CongressTrade(
        senator="X",
        ticker="NVDA",
        transaction_type="Purchase",
        amount="$1,001 - $15,000",
        transaction_date=dt.date(2026, 5, 7),
        disclosure_date=dt.date(2026, 5, 22),
        asset_description="NVIDIA",
        report_url="https://efdsearch.senate.gov/r/1/",
    )
    same = CongressTrade(
        senator="X (different display)",
        ticker="NVDA",
        transaction_type="Purchase",
        amount="$1,001 - $15,000",
        transaction_date=dt.date(2026, 5, 7),
        disclosure_date=None,
        asset_description="NVIDIA",
        report_url="https://efdsearch.senate.gov/r/1/",
    )
    other = CongressTrade(
        senator="X",
        ticker="AAPL",
        transaction_type="Purchase",
        amount="$1,001 - $15,000",
        transaction_date=dt.date(2026, 5, 7),
        disclosure_date=dt.date(2026, 5, 22),
        asset_description="Apple",
        report_url="https://efdsearch.senate.gov/r/1/",
    )
    # Same trade facts → same id (ignores display name / disclosure date).
    assert a.dedupe_id == same.dedupe_id
    assert a.dedupe_id != other.dedupe_id


def test_parse_date_handles_known_formats_and_junk():
    assert _parse_date("05/06/2026") == dt.date(2026, 5, 6)
    assert _parse_date("2026-05-06") == dt.date(2026, 5, 6)
    assert _parse_date("--") is None
    assert _parse_date(None) is None


def test_clean_filer_strips_role_suffix():
    assert _clean_filer("Fetterman, John (Senator)") == "Fetterman, John"
    assert _clean_filer("Smith, Jane (Former Senator)") == "Smith, Jane"


def test_fetch_senate_trades_skips_known_report_urls(monkeypatch):
    rows = [
        ("Filer A", "/search/view/ptr/aaa/", "05/06/2026", "electronic"),
        ("Filer B", "/search/view/ptr/bbb/", "05/07/2026", "electronic"),
    ]
    monkeypatch.setattr(congress, "_iter_report_rows", lambda *a, **k: rows)
    monkeypatch.setattr(congress.time, "sleep", lambda *_: None)

    fetched: list[str] = []

    class _Resp:
        text = _PTR_HTML

    def _fake_get(client, method, url, **kwargs):
        fetched.append(url)
        return _Resp()

    monkeypatch.setattr(congress, "_request_with_retry", _fake_get)

    known = {f"{congress._BASE}/search/view/ptr/aaa/"}
    trades = fetch_senate_trades(client=object(), known_report_urls=known)

    # The already-stored filing (aaa) is never fetched; only bbb hits the network.
    assert fetched == [f"{congress._BASE}/search/view/ptr/bbb/"]
    # bbb's report yields the two stock rows from the sample HTML.
    assert len(trades) == 2


def test_filter_trades_by_ticker_and_window():
    trades = [
        CongressTrade(
            "A",
            "NVDA",
            "Purchase",
            "$1k",
            dt.date(2026, 5, 1),
            dt.date(2026, 5, 2),
            "NVIDIA",
            "",
        ),
        CongressTrade(
            "B",
            "AAPL",
            "Sale",
            "$1k",
            dt.date(2026, 5, 1),
            dt.date(2026, 5, 2),
            "Apple",
            "",
        ),
        CongressTrade(
            "C",
            "NVDA",
            "Purchase",
            "$1k",
            dt.date(2024, 1, 1),
            dt.date(2024, 1, 2),
            "NVIDIA",
            "",
        ),
    ]
    out = filter_trades(trades, ["NVDA"], since=dt.date(2026, 1, 1))
    assert [t.senator for t in out] == ["A"]  # AAPL filtered out, 2024 too old


def _trade(**overrides: object) -> CongressTrade:
    base: dict = dict(
        senator="Jane Doe",
        ticker="AAPL",
        transaction_type="Purchase",
        amount="$1,001 - $15,000",
        transaction_date=dt.date(2024, 1, 5),
        disclosure_date=dt.date(2024, 1, 20),
        asset_description="Apple Inc",
        report_url="https://efd/ptr/original",
    )
    base.update(overrides)
    return CongressTrade(**base)  # type: ignore[arg-type]


def _fresh_db(tmp_path):
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    db = tmp_path / "congress.db"
    with connect(db) as conn:
        apply_schema(conn)
    return db


def test_ticker_ok_pattern():
    from cortex.sources.congress import ticker_ok

    assert ticker_ok("AAPL")
    assert ticker_ok("BRK.B")
    assert ticker_ok("BF/B")
    assert not ticker_ok("-- AM")
    assert not ticker_ok("AET CVS")
    assert not ticker_ok("0QZI.IL")
    assert not ticker_ok("")


def test_store_trades_quarantines_invalid_tickers(tmp_path):
    from cortex.sources.congress import store_trades
    from cortex.storage.db import connect

    db = _fresh_db(tmp_path)
    store_trades(
        [_trade(), _trade(ticker="-- AM", report_url="https://efd/ptr/other")], db
    )
    with connect(db, read_only=True) as conn:
        rows = dict(
            conn.execute("SELECT ticker, ticker_ok FROM congress_trades").fetchall()
        )
    assert rows["AAPL"] is True
    assert rows["-- AM"] is False


def test_amendment_marking_keeps_newest_unmarked(tmp_path):
    from cortex.sources.congress import store_trades
    from cortex.storage.db import connect

    db = _fresh_db(tmp_path)
    original = _trade()
    amendment = _trade(
        disclosure_date=dt.date(2024, 2, 10),
        report_url="https://efd/ptr/original_amended",
    )
    store_trades([original, amendment], db)
    with connect(db, read_only=True) as conn:
        rows = dict(
            conn.execute(
                "SELECT report_url, amended FROM congress_trades"
            ).fetchall()
        )
    assert rows["https://efd/ptr/original"] is True  # superseded
    assert rows["https://efd/ptr/original_amended"] is False  # kept


def test_amendment_marking_ignores_distinct_trades(tmp_path):
    from cortex.sources.congress import store_trades
    from cortex.storage.db import connect

    db = _fresh_db(tmp_path)
    store_trades(
        [
            _trade(),
            _trade(
                transaction_date=dt.date(2024, 1, 6),
                report_url="https://efd/ptr/other-day",
            ),
        ],
        db,
    )
    with connect(db, read_only=True) as conn:
        row = conn.execute(
            "SELECT count(*) FROM congress_trades WHERE amended"
        ).fetchone()
        marked = row[0] if row else None
    assert marked == 0


def test_list_trades_hides_amended_and_quarantined(tmp_path):
    from cortex.sources.congress import list_trades, store_trades

    db = _fresh_db(tmp_path)
    store_trades(
        [
            _trade(),
            _trade(
                disclosure_date=dt.date(2024, 2, 10),
                report_url="https://efd/ptr/original_amended",
            ),
            _trade(ticker="-- AM", report_url="https://efd/ptr/garbage"),
        ],
        db,
    )
    out = list_trades(db)
    assert len(out) == 1
    assert out[0].report_url == "https://efd/ptr/original_amended"
