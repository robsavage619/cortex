from __future__ import annotations

from datetime import date
from pathlib import Path

from wst.thesis import Thesis, list_theses


def due_for_review(
    today: date | None = None,
    *,
    db_path: Path | None = None,
) -> list[Thesis]:
    """Return open theses whose review_date is today or earlier."""
    cutoff = today or date.today()
    return [
        t
        for t in list_theses(status="open", db_path=db_path)
        if t.review_date <= cutoff
    ]
