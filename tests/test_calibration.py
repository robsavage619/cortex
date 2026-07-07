from __future__ import annotations

from datetime import date

import pytest

from cortex.calibration import compute
from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema
from cortex.thesis import create, record_review, update


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "test.db"
    with connect(path) as conn:
        apply_schema(conn)
    return path


def _seed(db, author: str, conviction: int, outcome: str) -> None:
    t = create(
        tickers=["TST"],
        author=author,
        conviction=conviction,
        claim="test claim",
        falsifier="test falsifier",
        review_date=date(2026, 1, 1),
        status="open",
        db_path=db,
    )
    update(
        t.id,
        status="confirmed" if outcome == "correct" else "invalidated",
        db_path=db,
    )
    record_review(t.id, outcome=outcome, db_path=db)


def test_empty_db_returns_zero(db):
    report = compute(db)
    assert report.brier_score == 0.0
    assert report.buckets == []
    assert report.per_author == {}


def test_all_correct_high_conviction(db):
    for _ in range(4):
        _seed(db, "rob", conviction=5, outcome="correct")
    report = compute(db)
    assert report.brier_score < 0.1
    assert len(report.buckets) == 1
    assert report.buckets[0].conviction == 5
    assert report.buckets[0].hit_rate == pytest.approx(1.0)


def test_all_wrong_high_conviction_is_overconfident(db):
    for _ in range(5):
        _seed(db, "rob", conviction=5, outcome="wrong")
    report = compute(db)
    assert report.overconfident is True


def test_small_sample_does_not_flag_overconfident(db):
    for _ in range(4):
        _seed(db, "rob", conviction=5, outcome="wrong")
    report = compute(db)
    assert report.overconfident is False


def test_unclear_outcomes_excluded(db):
    t = create(
        tickers=["TST"],
        author="rob",
        conviction=3,
        claim="test",
        falsifier="test",
        review_date=date(2026, 1, 1),
        db_path=db,
    )
    record_review(t.id, outcome="unclear", db_path=db)
    report = compute(db)
    assert report.brier_score == 0.0
    assert report.buckets == []


def test_per_author_split(db):
    _seed(db, "rob", conviction=4, outcome="correct")
    _seed(db, "ari", conviction=2, outcome="wrong")
    report = compute(db)
    assert "rob" in report.per_author
    assert "ari" in report.per_author
    assert report.per_author["rob"] != report.per_author["ari"]


def test_mixed_convictions_buckets(db):
    _seed(db, "rob", conviction=2, outcome="correct")
    _seed(db, "rob", conviction=4, outcome="wrong")
    _seed(db, "rob", conviction=4, outcome="correct")
    report = compute(db)
    convictions = {b.conviction for b in report.buckets}
    assert {2, 4} == convictions
    bucket4 = next(b for b in report.buckets if b.conviction == 4)
    assert bucket4.total == 2
    assert bucket4.correct == 1
    assert bucket4.hit_rate == pytest.approx(0.5)


def test_process_score_separates_decision_from_outcome(db):
    # A losing bet graded as a good decision should lift the process score.
    t = create(
        tickers=["TST"],
        author="rob",
        conviction=4,
        claim="c",
        falsifier="f",
        review_date=date(2026, 1, 1),
        db_path=db,
    )
    update(t.id, status="invalidated", db_path=db)
    record_review(t.id, outcome="wrong", decision_quality="good", db_path=db)

    report = compute(db_path=db)
    assert report.process_score == 1.0
    assert report.decision_counts["good"] == 1
    assert len(report.trend) == 1


def test_single_review_does_not_crash(db):
    _seed(db, "rob", conviction=5, outcome="correct")
    report = compute(db)
    assert report.brier_score == pytest.approx(0.0)
    assert len(report.trend) == 1
    assert report.trend[0].brier_rolling10 is None


def test_all_unclear_outcomes_returns_empty_report(db):
    for _ in range(3):
        _seed(db, "rob", conviction=3, outcome="unclear")
    report = compute(db)
    assert report.brier_score == 0.0
    assert report.buckets == []
    assert report.trend == []


def test_trend_cumulative_vs_rolling_diverge_on_recent_shift(db):
    # 10 correct high-conviction reviews, then 10 wrong ones. The cumulative
    # series smooths the collapse; the rolling-10 series must expose it.
    for _ in range(10):
        _seed(db, "rob", conviction=5, outcome="correct")
    for _ in range(10):
        _seed(db, "rob", conviction=5, outcome="wrong")
    report = compute(db)
    last = report.trend[-1]
    assert last.brier_rolling10 is not None
    # Rolling window is all-wrong at conviction 5 → Brier = (1.0 - 0)^2 = 1.0
    assert last.brier_rolling10 == pytest.approx(1.0)
    # Cumulative mixes both halves → about 0.5, far below the true recent 1.0
    assert last.brier_cumulative == pytest.approx(0.5, abs=0.05)
    assert last.brier_rolling10 > last.brier_cumulative


def test_rolling_none_until_ten_graded(db):
    for _ in range(9):
        _seed(db, "rob", conviction=4, outcome="correct")
    report = compute(db)
    assert all(p.brier_rolling10 is None for p in report.trend)
    _seed(db, "rob", conviction=4, outcome="correct")
    report = compute(db)
    assert report.trend[-1].brier_rolling10 is not None
