from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from wst.storage.db import connect


@dataclass
class BucketStats:
    conviction: int
    total: int
    correct: int
    hit_rate: float


@dataclass
class TrendPoint:
    date: str
    brier: float


@dataclass
class CalibrationReport:
    """Calibration summary over reviewed theses."""

    brier_score: float
    overconfident: bool
    buckets: list[BucketStats]
    per_author: dict[str, float]
    process_score: float | None = None
    decision_counts: dict[str, int] = field(default_factory=dict)
    trend: list[TrendPoint] = field(default_factory=list)


@dataclass
class _ReviewRow:
    author: str
    conviction: int
    outcome: str
    decision_quality: str | None
    reviewed_on: date | None


def _fetch_reviewed_rows(db_path: Path | None) -> list[_ReviewRow]:
    """Return review rows joined to their thesis for calibration math."""
    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT t.author, t.conviction, r.outcome, r.decision_quality,
                   r.reviewed_on
            FROM theses t
            JOIN reviews r ON r.thesis_id = t.id
            WHERE t.status IN ('confirmed', 'invalidated', 'closed')
               OR r.outcome IN ('correct', 'wrong')
            ORDER BY r.reviewed_on
            """
        ).fetchall()
    return [
        _ReviewRow(
            author=str(a),
            conviction=int(c),
            outcome=str(o),
            decision_quality=dq,
            reviewed_on=ro,
        )
        for a, c, o, dq, ro in rows
    ]


def _outcome_to_binary(outcome: str) -> float | None:
    if outcome == "correct":
        return 1.0
    if outcome == "wrong":
        return 0.0
    return None


def _conviction_to_prob(conviction: int) -> float:
    return conviction / 5.0


def _decision_counts(rows: list[_ReviewRow]) -> dict[str, int]:
    counts = {"good": 0, "flawed": 0, "unclear": 0}
    for row in rows:
        if row.decision_quality in counts:
            counts[row.decision_quality] += 1
    return counts


def _process_score(counts: dict[str, int]) -> float | None:
    """Share of graded decisions judged 'good' (good vs. flawed)."""
    graded = counts.get("good", 0) + counts.get("flawed", 0)
    if graded == 0:
        return None
    return counts.get("good", 0) / graded


def compute(db_path: Path | None = None) -> CalibrationReport:
    """Compute Brier score, bucket hit-rates, and per-author scores.

    Uses sklearn for the Brier calculation so the math is validated.
    Skips 'unclear' outcomes — they don't count toward calibration.
    """
    from sklearn.metrics import brier_score_loss

    rows = _fetch_reviewed_rows(db_path)
    decision_counts = _decision_counts(rows)
    process_score = _process_score(decision_counts)
    if not rows:
        return CalibrationReport(
            brier_score=0.0,
            overconfident=False,
            buckets=[],
            per_author={},
            process_score=process_score,
            decision_counts=decision_counts,
        )

    y_true: list[float] = []
    y_prob: list[float] = []
    author_true: dict[str, list[float]] = {}
    author_prob: dict[str, list[float]] = {}
    bucket_data: dict[int, list[float]] = {i: [] for i in range(1, 6)}
    trend: list[TrendPoint] = []

    for row in rows:
        binary = _outcome_to_binary(row.outcome)
        if binary is None:
            continue
        prob = _conviction_to_prob(row.conviction)
        y_true.append(binary)
        y_prob.append(prob)
        bucket_data[row.conviction].append(binary)
        author_true.setdefault(row.author, []).append(binary)
        author_prob.setdefault(row.author, []).append(prob)
        if row.reviewed_on is not None:
            trend.append(
                TrendPoint(
                    date=row.reviewed_on.isoformat(),
                    brier=float(brier_score_loss(y_true, y_prob, pos_label=1)),
                )
            )

    if not y_true:
        return CalibrationReport(
            brier_score=0.0,
            overconfident=False,
            buckets=[],
            per_author={},
            process_score=process_score,
            decision_counts=decision_counts,
        )

    brier = float(brier_score_loss(y_true, y_prob, pos_label=1))

    buckets: list[BucketStats] = []
    for conv in range(1, 6):
        outcomes = bucket_data[conv]
        if not outcomes:
            continue
        correct = sum(1 for v in outcomes if v == 1.0)
        hit = correct / len(outcomes)
        buckets.append(
            BucketStats(
                conviction=conv,
                total=len(outcomes),
                correct=correct,
                hit_rate=hit,
            )
        )

    per_author: dict[str, float] = {}
    for author, a_true in author_true.items():
        a_prob = author_prob[author]
        per_author[author] = float(brier_score_loss(a_true, a_prob, pos_label=1))

    overconfident = any(
        b.hit_rate < _conviction_to_prob(b.conviction) - 0.10 for b in buckets
    )

    return CalibrationReport(
        brier_score=brier,
        overconfident=overconfident,
        process_score=process_score,
        decision_counts=decision_counts,
        trend=trend,
        buckets=buckets,
        per_author=per_author,
    )
