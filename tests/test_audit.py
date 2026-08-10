from __future__ import annotations

from datetime import date

import pytest

from cortex.audit import format_report, run_audit
from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "cortex.sources.universe.sp500_tickers", lambda: ["AAPL", "MSFT"]
    )
    monkeypatch.setattr("cortex.sources.universe.sp400_tickers", lambda: [])
    db = tmp_path / "audit.db"
    with connect(db) as conn:
        apply_schema(conn)
        # Amendment duplicate: same natural key, two report_urls.
        conn.executemany(
            "INSERT INTO congress_trades (id, senator, ticker, transaction_type,"
            " amount, transaction_date, report_url, chamber)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "a1",
                    "Doe",
                    "AAPL",
                    "Purchase",
                    "$1k",
                    date(2024, 1, 5),
                    "u1",
                    "senate",
                ),
                (
                    "a2",
                    "Doe",
                    "AAPL",
                    "Purchase",
                    "$1k",
                    date(2024, 1, 5),
                    "u2",
                    "senate",
                ),
                ("b1", "Roe", "BAD!!", "Sale", "$1k", date(2024, 2, 1), "u3", "house"),
                ("c1", "Roe", "GMBL", "Sale", "$1k", date(2024, 3, 1), "u4", "house"),
            ],
        )
        conn.execute(
            "INSERT INTO insider_buys (id, ticker, issuer_cik, transaction_date,"
            " filing_date) VALUES ('i1', 'AAPL', '1', DATE '2024-01-02',"
            " DATE '2024-01-03')"
        )
        conn.execute(
            "INSERT INTO fund_holdings (id, manager, manager_cik, ticker, action)"
            " VALUES ('f1', 'BRK', '2', 'AAPL', 'EXIT')"
        )
        conn.execute(
            "INSERT INTO executive_mentions (id, ticker, mention_date)"
            " VALUES ('e1', 'AAPL', DATE '2024-01-01')"
        )
        conn.execute(
            "INSERT INTO candidates (ticker, as_of_date, composite_score,"
            " composite_rank) VALUES ('ZZZZ', DATE '2024-01-01', 0.1, 45)"
        )
    return db


def test_audit_counts_amendment_duplicates(seeded_db):
    report = run_audit(seeded_db)
    dupes = report.sections["congress_amendment_duplicates"]
    assert dupes["dup_groups"] == 1
    assert dupes["excess_rows"] == 1
    assert dupes["total_rows"] == 4


def test_audit_flags_pattern_fail_tickers(seeded_db):
    tickers = run_audit(seeded_db).sections["suspicious_tickers"]
    assert tickers["pattern_fail_tickers"] == 1
    assert "BAD!!" in tickers["pattern_fail_top20"]
    assert tickers["pattern_fail_rows"] == 1


def test_audit_baselines_and_rank_fakes(seeded_db):
    report = run_audit(seeded_db)
    assert report.sections["collapse_baselines"]["insider_buys_rows"] == 1
    assert report.sections["fund_actions"]["exit_rows"] == 1
    assert report.sections["executive_analysis"]["meaningful_null"] == 1
    assert report.sections["candidate_rank_fakes"]["rows_over_rank_30"] == 1


def test_audit_report_renders(seeded_db):
    report = run_audit(seeded_db)
    text = format_report(report)
    assert "congress_amendment_duplicates" in text
    assert report.to_json().startswith("{")


def test_event_yield_catches_a_source_the_loader_cannot_read(tmp_path):
    """The check exists because row-level audits missed four defects in a day.

    A source can be perfectly well-formed on disk and still produce zero scored
    events — 71,958 13F EXIT rows did exactly that, and 14,551 House rows
    produced ~247. Both are invisible to every other check in this module and
    glaring in the yield column.
    """
    db = tmp_path / "yield.db"
    with connect(db) as conn:
        apply_schema(conn)
        # Well-formed rows whose transaction_type the sign parser cannot read.
        conn.executemany(
            "INSERT INTO congress_trades "
            "(id, senator, ticker, transaction_type, amount, transaction_date, "
            "disclosure_date, chamber) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f"x{i}",
                    "Rep. Nobody",
                    "AAPL",
                    "GIBBERISH",
                    "$1,001 - $15,000",
                    date(2025, 1, 2),
                    date(2025, 1, 20),
                    "house",
                )
                for i in range(25)
            ],
        )

    section = run_audit(db).sections["event_yield"]
    assert section["congress_rows"] == 25
    assert section["congress_events"] == 0
    assert section["congress_yield"] == "0.0%"


def test_event_yield_reports_a_healthy_source(tmp_path):
    db = tmp_path / "ok.db"
    with connect(db) as conn:
        apply_schema(conn)
        conn.execute(
            "INSERT INTO congress_trades "
            "(id, senator, ticker, transaction_type, amount, transaction_date, "
            "disclosure_date, chamber) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "a",
                "Sen. Somebody",
                "AAPL",
                "Purchase",
                "$1,001 - $15,000",
                date(2025, 1, 2),
                date(2025, 1, 20),
                "senate",
            ),
        )
    section = run_audit(db).sections["event_yield"]
    assert section["congress_events"] == 1
    assert section["congress_yield"] == "100.0%"


def test_event_yield_handles_empty_tables(tmp_path):
    db = tmp_path / "empty.db"
    with connect(db) as conn:
        apply_schema(conn)
    section = run_audit(db).sections["event_yield"]
    assert section["congress_rows"] == 0
    assert section["congress_yield"] == "n/a (no rows)"
