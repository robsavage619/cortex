from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wst.storage.db import connect


@dataclass
class BucketStats:
    conviction: int
    total: int
    correct: int
    hit_rate: float


@dataclass
class CalibrationReport:
    """Calibration summary over reviewed theses."""

    brier_score: float
    overconfident: bool
    buckets: list[BucketStats]
    per_author: dict[str, float]


def _fetch_reviewed_rows(
    db_path: Path | None,
) -> list[tuple[str, int, str]]:
    """Return (author, conviction, outcome) for all reviewed theses."""
    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT t.author, t.conviction, r.outcome
            FROM theses t
            JOIN reviews r ON r.thesis_id = t.id
            WHERE t.status IN ('confirmed', 'invalidated', 'closed')
               OR r.outcome IN ('correct', 'wrong')
            """
        ).fetchall()
    return [(str(a), int(c), str(o)) for a, c, o in rows]


def _outcome_to_binary(outcome: str) -> float | None:
    if outcome == "correct":
        return 1.0
    if outcome == "wrong":
        return 0.0
    return None


def _conviction_to_prob(conviction: int) -> float:
    return conviction / 5.0


def compute(db_path: Path | None = None) -> CalibrationReport:
    """Compute Brier score, bucket hit-rates, and per-author scores.

    Uses sklearn for the Brier calculation so the math is validated.
    Skips 'unclear' outcomes — they don't count toward calibration.
    """
    from sklearn.metrics import brier_score_loss

    rows = _fetch_reviewed_rows(db_path)
    if not rows:
        return CalibrationReport(
            brier_score=0.0,
            overconfident=False,
            buckets=[],
            per_author={},
        )

    y_true: list[float] = []
    y_prob: list[float] = []
    author_true: dict[str, list[float]] = {}
    author_prob: dict[str, list[float]] = {}
    bucket_data: dict[int, list[float]] = {i: [] for i in range(1, 6)}

    for author, conviction, outcome in rows:
        binary = _outcome_to_binary(outcome)
        if binary is None:
            continue
        prob = _conviction_to_prob(conviction)
        y_true.append(binary)
        y_prob.append(prob)
        bucket_data[conviction].append(binary)
        author_true.setdefault(author, []).append(binary)
        author_prob.setdefault(author, []).append(prob)

    if not y_true:
        return CalibrationReport(
            brier_score=0.0,
            overconfident=False,
            buckets=[],
            per_author={},
        )

    brier = float(brier_score_loss(y_true, y_prob))

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
        per_author[author] = float(brier_score_loss(a_true, a_prob))

    overconfident = any(
        b.hit_rate < _conviction_to_prob(b.conviction) - 0.10 for b in buckets
    )

    return CalibrationReport(
        brier_score=brier,
        overconfident=overconfident,
        buckets=buckets,
        per_author=per_author,
    )
