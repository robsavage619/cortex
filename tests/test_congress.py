from __future__ import annotations

import datetime as dt

from cortex.sources.congress import (
    CongressTrade,
    _clean_filer,
    _parse_date,
    _parse_ptr_html,
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
