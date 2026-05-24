from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from cortex.storage.db import connect

VALID_STATUSES = {"pending", "open", "confirmed", "invalidated", "closed"}
VALID_OUTCOMES = {"correct", "wrong", "unclear"}
VALID_DECISION_QUALITY = {"good", "flawed", "unclear"}
VALID_STANCES = {"agree", "disagree"}

_THESIS_COLS = (
    "id, tickers, author, opened, conviction, claim, falsifier, reasoning,"
    " evidence, review_date, status, entry_price, entry_date, base_rate,"
    " pre_mortem, change_my_mind, sizing_rationale, why_now, activate_at,"
    " created_at"
)


class ThesisError(Exception):
    """Raised on invalid thesis data or DB failures."""


@dataclass
class Thesis:
    id: str
    tickers: list[str]
    author: str
    opened: date
    conviction: int
    claim: str
    falsifier: str
    reasoning: str | None
    evidence: list[str]
    review_date: date
    status: str
    entry_price: float | None
    entry_date: date | None
    base_rate: str | None
    pre_mortem: str | None
    change_my_mind: str | None
    sizing_rationale: str | None
    why_now: str | None
    activate_at: datetime | None
    created_at: datetime


@dataclass
class Dissent:
    id: str
    thesis_id: str
    author: str
    stance: str
    conviction: int | None
    note: str | None
    created_at: datetime


def _validate(
    conviction: int,
    status: str,
    claim: str,
    falsifier: str,
    tickers: list[str],
    author: str,
) -> None:
    if conviction not in range(1, 6):
        raise ThesisError(f"conviction must be 1–5, got {conviction}")
    if status not in VALID_STATUSES:
        raise ThesisError(f"status must be one of {VALID_STATUSES}, got {status!r}")
    if not claim.strip():
        raise ThesisError("claim must not be empty")
    if not falsifier.strip():
        raise ThesisError("falsifier must not be empty")
    if not tickers:
        raise ThesisError("tickers must not be empty")
    if not author.strip():
        raise ThesisError("author must not be empty")


def _row_to_thesis(row: tuple) -> Thesis:
    (
        id_, tickers, author, opened, conviction, claim, falsifier, reasoning,
        evidence, review_date, status, entry_price, entry_date, base_rate,
        pre_mortem, change_my_mind, sizing_rationale, why_now, activate_at,
        created_at,
    ) = row
    return Thesis(
        id=id_,
        tickers=list(tickers) if tickers else [],
        author=author,
        opened=opened,
        conviction=conviction,
        claim=claim,
        falsifier=falsifier,
        reasoning=reasoning,
        evidence=list(evidence) if evidence else [],
        review_date=review_date,
        status=status,
        entry_price=entry_price,
        entry_date=entry_date,
        base_rate=base_rate,
        pre_mortem=pre_mortem,
        change_my_mind=change_my_mind,
        sizing_rationale=sizing_rationale,
        why_now=why_now,
        activate_at=activate_at,
        created_at=created_at,
    )


def create(
    *,
    tickers: list[str],
    author: str,
    conviction: int,
    claim: str,
    falsifier: str,
    review_date: date,
    opened: date | None = None,
    reasoning: str | None = None,
    evidence: list[str] | None = None,
    entry_price: float | None = None,
    entry_date: date | None = None,
    base_rate: str | None = None,
    pre_mortem: str | None = None,
    change_my_mind: str | None = None,
    sizing_rationale: str | None = None,
    why_now: str | None = None,
    activate_at: datetime | None = None,
    status: str = "open",
    db_path: Path | None = None,
) -> Thesis:
    """Insert a new thesis and return it.

    When ``activate_at`` is in the future the thesis is created in the
    ``pending`` cooling-off state regardless of the requested status.
    """
    if activate_at is not None and activate_at > datetime.now():
        status = "pending"
    _validate(conviction, status, claim, falsifier, tickers, author)
    thesis_id = str(uuid.uuid4())
    opened_ = opened or date.today()
    evidence_ = evidence or []

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO theses (
                id, tickers, author, opened, conviction, claim, falsifier,
                reasoning, evidence, review_date, status, entry_price,
                entry_date, base_rate, pre_mortem, change_my_mind,
                sizing_rationale, why_now, activate_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                thesis_id, tickers, author, opened_, conviction, claim,
                falsifier, reasoning, evidence_, review_date, status,
                entry_price, entry_date, base_rate, pre_mortem, change_my_mind,
                sizing_rationale, why_now, activate_at,
            ],
        )
    return get(thesis_id, db_path=db_path)


def get(thesis_id: str, *, db_path: Path | None = None) -> Thesis:
    """Fetch a single thesis by ID; raises ThesisError if not found."""
    with connect(db_path, read_only=True) as conn:
        row = conn.execute(
            f"SELECT {_THESIS_COLS} FROM theses WHERE id = ?",
            [thesis_id],
        ).fetchone()
    if row is None:
        raise ThesisError(f"Thesis not found: {thesis_id}")
    return _row_to_thesis(row)


def list_theses(
    *,
    author: str | None = None,
    status: str | None = None,
    db_path: Path | None = None,
) -> list[Thesis]:
    """Return theses, optionally filtered by author and/or status."""
    clauses: list[str] = []
    params: list[str] = []
    if author:
        clauses.append("author = ?")
        params.append(author)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            f"SELECT {_THESIS_COLS} FROM theses {where} ORDER BY opened DESC",
            params,
        ).fetchall()
    return [_row_to_thesis(r) for r in rows]


def update(
    thesis_id: str,
    *,
    status: str | None = None,
    reasoning: str | None = None,
    evidence: list[str] | None = None,
    entry_price: float | None = None,
    entry_date: date | None = None,
    db_path: Path | None = None,
) -> Thesis:
    """Patch mutable fields on a thesis.

    Pre-commitment fields (base rate, pre-mortem, etc.) are intentionally
    immutable after creation — they are not patchable here.
    """
    existing = get(thesis_id, db_path=db_path)
    new_status = status or existing.status
    if new_status not in VALID_STATUSES:
        raise ThesisError(f"Invalid status: {new_status!r}")
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE theses SET
                status      = ?,
                reasoning   = ?,
                evidence    = ?,
                entry_price = ?,
                entry_date  = ?
            WHERE id = ?
            """,
            [
                new_status,
                reasoning if reasoning is not None else existing.reasoning,
                evidence if evidence is not None else existing.evidence,
                entry_price if entry_price is not None else existing.entry_price,
                entry_date if entry_date is not None else existing.entry_date,
                thesis_id,
            ],
        )
    return get(thesis_id, db_path=db_path)


def activate(thesis_id: str, *, db_path: Path | None = None) -> Thesis:
    """Promote a pending (cooling-off) thesis to open."""
    existing = get(thesis_id, db_path=db_path)
    if existing.status != "pending":
        raise ThesisError(
            f"Thesis {thesis_id} is not pending (status={existing.status})"
        )
    with connect(db_path) as conn:
        conn.execute("UPDATE theses SET status = 'open' WHERE id = ?", [thesis_id])
    return get(thesis_id, db_path=db_path)


def record_review(
    thesis_id: str,
    *,
    outcome: str,
    decision_quality: str | None = None,
    note: str | None = None,
    reviewed_on: date | None = None,
    db_path: Path | None = None,
) -> None:
    """Record a review: an outcome grade and an optional decision-quality grade.

    Outcome and decision quality are deliberately separate axes — a losing
    bet that was well-reasoned is still a good *decision* (anti-resulting).
    """
    if outcome not in VALID_OUTCOMES:
        raise ThesisError(f"outcome must be one of {VALID_OUTCOMES}, got {outcome!r}")
    if decision_quality is not None and decision_quality not in VALID_DECISION_QUALITY:
        raise ThesisError(
            f"decision_quality must be one of {VALID_DECISION_QUALITY},"
            f" got {decision_quality!r}"
        )
    get(thesis_id, db_path=db_path)
    on = reviewed_on or date.today()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reviews"
            " (thesis_id, reviewed_on, outcome, decision_quality, note)"
            " VALUES (?, ?, ?, ?, ?)",
            [thesis_id, on, outcome, decision_quality, note],
        )


def add_dissent(
    thesis_id: str,
    *,
    author: str,
    stance: str,
    conviction: int | None = None,
    note: str | None = None,
    db_path: Path | None = None,
) -> Dissent:
    """Log a partner's counter-view (agree/disagree) on a thesis."""
    if stance not in VALID_STANCES:
        raise ThesisError(f"stance must be one of {VALID_STANCES}, got {stance!r}")
    if not author.strip():
        raise ThesisError("author must not be empty")
    get(thesis_id, db_path=db_path)
    dissent_id = str(uuid.uuid4())
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO dissents (id, thesis_id, author, stance, conviction, note)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [dissent_id, thesis_id, author, stance, conviction, note],
        )
    return list_dissents(thesis_id, db_path=db_path)[-1]


def list_dissents(thesis_id: str, *, db_path: Path | None = None) -> list[Dissent]:
    """Return all dissents recorded against a thesis, oldest first."""
    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            "SELECT id, thesis_id, author, stance, conviction, note, created_at"
            " FROM dissents WHERE thesis_id = ? ORDER BY created_at",
            [thesis_id],
        ).fetchall()
    return [
        Dissent(
            id=r[0],
            thesis_id=r[1],
            author=r[2],
            stance=r[3],
            conviction=r[4],
            note=r[5],
            created_at=r[6],
        )
        for r in rows
    ]
