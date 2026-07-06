from __future__ import annotations

from datetime import date

from cortex.sources.funds import FundMove, store_fund_moves
from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema


def _move(action: str, shares: int) -> FundMove:
    return FundMove(
        manager="Berkshire",
        manager_cik="0001067983",
        ticker="AAPL",
        issuer="Apple Inc",
        action=action,
        shares=shares,
        prev_shares=100_000_000,
        value=0,
        pct_change=-100.0 if action == "EXIT" else -50.0,
        period=date(2024, 3, 31),
    )


def test_exit_survives_trim_upsert(tmp_path):
    db = tmp_path / "funds.db"
    with connect(db) as conn:
        apply_schema(conn)

    assert store_fund_moves([_move("EXIT", 0)], db) == 1
    # Re-sync recomputes the same (manager, ticker, period) as a TRIM.
    assert store_fund_moves([_move("TRIM", 50_000_000)], db) == 0

    with connect(db, read_only=True) as conn:
        action, shares = conn.execute(
            "SELECT action, shares FROM fund_holdings"
        ).fetchone()
    assert action == "EXIT"
    assert shares == 0


def test_non_exit_rows_still_update(tmp_path):
    db = tmp_path / "funds.db"
    with connect(db) as conn:
        apply_schema(conn)

    store_fund_moves([_move("ADD", 120_000_000)], db)
    store_fund_moves([_move("TRIM", 50_000_000)], db)

    with connect(db, read_only=True) as conn:
        action, shares = conn.execute(
            "SELECT action, shares FROM fund_holdings"
        ).fetchone()
    assert action == "TRIM"
    assert shares == 50_000_000


def test_exit_replacing_exit_updates_in_place(tmp_path):
    db = tmp_path / "funds.db"
    with connect(db) as conn:
        apply_schema(conn)

    store_fund_moves([_move("EXIT", 0)], db)
    store_fund_moves([_move("EXIT", 0)], db)

    with connect(db, read_only=True) as conn:
        count = conn.execute("SELECT count(*) FROM fund_holdings").fetchone()[0]
    assert count == 1
