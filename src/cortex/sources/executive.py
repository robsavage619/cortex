"""Executive-branch company mentions — a market-moving statement signal.

Unlike every other CORTEX signal (which is an SEC *filing*), this captures a
public *statement* by an executive-branch figure that names a company — e.g. the
President endorsing Dell or ServiceNow at a press conference, which has been
followed by a price pop. Stored point-in-time on the mention date so the event
study can measure the reaction honestly.

Ingestion is source-flexible (manual logging now; whitehouse.gov transcripts and
news search later) — this module only owns storage and retrieval.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

VALID_STANCES = ("positive", "negative", "neutral")


@dataclass(frozen=True)
class ExecutiveMention:
    ticker: str
    mention_date: date
    speaker: str = "President"
    source_type: str = "press_conference"
    source_url: str | None = None
    quote: str | None = None
    stance: str = "positive"

    @property
    def dedupe_id(self) -> str:
        # One mention per (ticker, speaker, date, source) — a re-log of the same
        # event is idempotent, but two separate remarks on the same day count.
        raw = (
            f"{self.ticker.upper()}|{self.speaker}|"
            f"{self.mention_date.isoformat()}|{self.source_url or ''}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def store_mentions(mentions: list[ExecutiveMention], db_path: Path) -> int:
    """Upsert mentions into executive_mentions. Returns new-row count."""
    from cortex.storage.db import connect

    if not mentions:
        return 0
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM executive_mentions").fetchone()
        before = int(row[0]) if row else 0
        conn.executemany(
            """
            INSERT INTO executive_mentions
              (id, ticker, speaker, mention_date, source_type, source_url,
               quote, stance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
              quote = excluded.quote, stance = excluded.stance,
              source_type = excluded.source_type
            """,
            [
                (
                    m.dedupe_id,
                    m.ticker.upper(),
                    m.speaker,
                    m.mention_date,
                    m.source_type,
                    m.source_url,
                    m.quote,
                    m.stance,
                )
                for m in mentions
            ],
        )
        row = conn.execute("SELECT COUNT(*) FROM executive_mentions").fetchone()
        after = int(row[0]) if row else 0
    return after - before


def list_mentions(
    db_path: Path, *, ticker: str | None = None, limit: int = 100
) -> list[ExecutiveMention]:
    """Read mentions from the DB, most recent first."""
    from cortex.storage.db import connect

    clauses: list[str] = []
    params: list[object] = []
    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker.upper())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                f"""
                SELECT ticker, mention_date, speaker, source_type, source_url,
                       quote, stance
                FROM executive_mentions
                {where}
                ORDER BY mention_date DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
    except Exception:  # noqa: BLE001 - table may not exist yet
        return []

    out: list[ExecutiveMention] = []
    for tk, mdate, speaker, source_type, source_url, quote, stance in rows:
        out.append(
            ExecutiveMention(
                ticker=tk,
                mention_date=mdate,
                speaker=speaker,
                source_type=source_type,
                source_url=source_url,
                quote=quote,
                stance=stance,
            )
        )
    return out
