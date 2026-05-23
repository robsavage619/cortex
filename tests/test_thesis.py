from __future__ import annotations

from datetime import date

import pytest

from wst.storage.db import connect
from wst.storage.schemas import apply_schema
from wst.thesis import ThesisError, create, get, list_theses, record_review, update


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "test.db"
    with connect(path) as conn:
        apply_schema(conn)
    return path


def _make(db, **kwargs):
    defaults = dict(
        tickers=["AAPL"],
        author="rob",
        conviction=3,
        claim="Services margin expands to 40%",
        falsifier="Services margin misses 35% for two quarters",
        review_date=date(2026, 12, 1),
        db_path=db,
    )
    defaults.update(kwargs)
    return create(**defaults)


# --- create / get ---

def test_create_and_get_roundtrip(db):
    t = _make(db)
    fetched = get(t.id, db_path=db)
    assert fetched.id == t.id
    assert fetched.claim == "Services margin expands to 40%"
    assert fetched.tickers == ["AAPL"]
    assert fetched.status == "open"


def test_get_missing_raises(db):
    with pytest.raises(ThesisError, match="not found"):
        get("nonexistent-id", db_path=db)


# --- validation ---

def test_invalid_conviction(db):
    with pytest.raises(ThesisError, match="conviction"):
        _make(db, conviction=6)


def test_invalid_conviction_zero(db):
    with pytest.raises(ThesisError, match="conviction"):
        _make(db, conviction=0)


def test_empty_claim(db):
    with pytest.raises(ThesisError, match="claim"):
        _make(db, claim="   ")


def test_empty_falsifier(db):
    with pytest.raises(ThesisError, match="falsifier"):
        _make(db, falsifier="")


def test_empty_tickers(db):
    with pytest.raises(ThesisError, match="tickers"):
        _make(db, tickers=[])


def test_invalid_status(db):
    with pytest.raises(ThesisError, match="status"):
        _make(db, status="maybe")


# --- list ---

def test_list_all(db):
    _make(db, tickers=["AAPL"])
    _make(db, tickers=["MSFT"], author="ari")
    assert len(list_theses(db_path=db)) == 2


def test_list_filter_author(db):
    _make(db, author="rob")
    _make(db, author="ari")
    results = list_theses(author="rob", db_path=db)
    assert len(results) == 1
    assert results[0].author == "rob"


def test_list_filter_status(db):
    t = _make(db)
    update(t.id, status="closed", db_path=db)
    assert len(list_theses(status="open", db_path=db)) == 0
    assert len(list_theses(status="closed", db_path=db)) == 1


# --- update ---

def test_update_status(db):
    t = _make(db)
    updated = update(t.id, status="confirmed", db_path=db)
    assert updated.status == "confirmed"


def test_update_invalid_status(db):
    t = _make(db)
    with pytest.raises(ThesisError, match="Invalid status"):
        update(t.id, status="bogus", db_path=db)


def test_update_entry_price(db):
    t = _make(db)
    updated = update(t.id, entry_price=185.5, db_path=db)
    assert updated.entry_price == pytest.approx(185.5)


# --- record_review ---

def test_record_review(db):
    t = _make(db)
    record_review(t.id, outcome="correct", note="hit target", db_path=db)


def test_record_review_invalid_outcome(db):
    t = _make(db)
    with pytest.raises(ThesisError, match="outcome"):
        record_review(t.id, outcome="maybe", db_path=db)


def test_record_review_missing_thesis(db):
    with pytest.raises(ThesisError, match="not found"):
        record_review("bad-id", outcome="correct", db_path=db)


def test_record_review_idempotent(db):
    t = _make(db)
    record_review(t.id, outcome="correct", reviewed_on=date(2026, 12, 1), db_path=db)
    record_review(t.id, outcome="wrong", reviewed_on=date(2026, 12, 1), db_path=db)
