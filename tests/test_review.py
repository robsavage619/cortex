from __future__ import annotations

from datetime import date

import pytest

from cortex.review import due_for_review
from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema
from cortex.thesis import create


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "test.db"
    with connect(path) as conn:
        apply_schema(conn)
    return path


def _thesis(db, review_date: date):
    return create(
        tickers=["TST"],
        author="rob",
        conviction=3,
        claim="test",
        falsifier="falsifier",
        review_date=review_date,
        db_path=db,
    )


def test_due_today(db):
    today = date(2026, 6, 1)
    _thesis(db, review_date=today)
    result = due_for_review(today, db_path=db)
    assert len(result) == 1


def test_overdue_included(db):
    today = date(2026, 6, 1)
    _thesis(db, review_date=date(2026, 1, 1))
    result = due_for_review(today, db_path=db)
    assert len(result) == 1


def test_future_excluded(db):
    today = date(2026, 6, 1)
    _thesis(db, review_date=date(2026, 12, 1))
    result = due_for_review(today, db_path=db)
    assert result == []


def test_empty_queue(db):
    assert due_for_review(date(2026, 6, 1), db_path=db) == []
