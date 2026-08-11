"""Factor → vault evidence links.

The RAG retriever answers "what does the corpus say about momentum?" That is
useful for browsing and useless at the moment a decision is made, because it is
not attached to anything. A reader looking at ``fund 2.62`` in the ablation
table has no way to learn, from the app, that 74% of that factor is one manager
or that the paper it cites describes the opposite mechanism.

This module makes the link explicit and bidirectional. A vault note declares
which factors it bears on via a ``cortex_factors`` frontmatter list::

    cortex_factors: [fund]        # this note is evidence about the fund factor
    cortex_factors: ["*"]         # methodology — applies to every factor

Notes typed ``research-finding`` with a ``current_verdict`` are treated as
**caveats**: CORTEX's own first-party findings about what is wrong with, or
limited about, a factor. Those are what get surfaced next to the number, since
a caveat changes a decision and a citation rarely does.

The link is synced into DuckDB rather than read live, because the deployed app
has no vault on disk. Writing a note and re-running the sync is the whole
update path.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.DOTALL)

# A note claiming this applies to every factor rather than naming one.
WILDCARD = "*"


@dataclass(frozen=True)
class Evidence:
    """One vault note's bearing on one factor."""

    factor: str
    wikilink: str
    title: str
    summary: str
    kind: str
    """Vault `type` — source-summary, research-finding, analysis, overview."""
    confidence: str
    verdict: str
    """`current_verdict` where present; empty for third-party papers."""

    @property
    def is_caveat(self) -> bool:
        """First-party findings with a verdict qualify a number rather than cite it."""
        return self.kind == "research-finding" and bool(self.verdict)


def build_evidence(research_dir: Path) -> list[Evidence]:
    """Scan the vault for notes declaring a `cortex_factors` frontmatter list."""
    if not research_dir.is_dir():
        logger.warning("Research dir does not exist: %s", research_dir)
        return []

    out: list[Evidence] = []
    for note in sorted(research_dir.rglob("*.md")):
        try:
            text = note.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Skipping unreadable note %s: %s", note, exc)
            continue
        match = _FRONTMATTER_RE.match(text)
        if match is None:
            continue
        try:
            fm = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            logger.warning("Unparseable frontmatter in %s: %s", note, exc)
            continue
        if not isinstance(fm, dict):
            continue
        factors = fm.get("cortex_factors")
        if not isinstance(factors, list) or not factors:
            continue

        for factor in factors:
            out.append(
                Evidence(
                    factor=str(factor).strip().lower(),
                    wikilink=f"[[{note.stem}]]",
                    title=str(fm.get("title") or note.stem).strip(),
                    summary=str(fm.get("summary") or "").strip(),
                    kind=str(fm.get("type") or "").strip(),
                    confidence=str(fm.get("confidence") or "").strip(),
                    verdict=str(fm.get("current_verdict") or "").strip(),
                )
            )
    return out


def sync_evidence(db_path: Path, research_dir: Path) -> int:
    """Rebuild the factor_evidence table from the vault. Returns rows written."""
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    rows = build_evidence(research_dir)
    with connect(db_path) as conn:
        apply_schema(conn)
        # Full rebuild: a note that drops its cortex_factors, or is deleted,
        # must not survive as a stale claim about a factor.
        conn.execute("DELETE FROM factor_evidence")
        if rows:
            conn.executemany(
                "INSERT INTO factor_evidence "
                "(factor, wikilink, title, summary, kind, confidence, verdict) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        e.factor,
                        e.wikilink,
                        e.title,
                        e.summary,
                        e.kind,
                        e.confidence,
                        e.verdict,
                    )
                    for e in rows
                ],
            )
    logger.info("Synced %d factor-evidence links", len(rows))
    return len(rows)


def evidence_for(db_path: Path, factor: str, *, include_wildcard: bool = True) -> Any:
    """Evidence bearing on one factor, caveats first.

    Wildcard notes (methodology that applies to everything) are included by
    default but sort last — they are context, not a reason to distrust a
    specific number.
    """
    from cortex.storage.db import connect

    wanted = [factor.strip().lower()]
    if include_wildcard:
        wanted.append(WILDCARD)
    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                "SELECT factor, wikilink, title, summary, kind, confidence, verdict "
                "FROM factor_evidence WHERE factor IN "
                f"({','.join('?' for _ in wanted)})",
                wanted,
            ).fetchall()
    except Exception:  # noqa: BLE001 - table may not exist yet
        return []

    items = [Evidence(*r) for r in rows]
    items.sort(
        key=lambda e: (e.factor == WILDCARD, not e.is_caveat, e.title.lower()),
    )
    return items


def caveats_for(db_path: Path, factor: str) -> list[Evidence]:
    """Only the first-party findings that qualify this factor's number."""
    return [
        e for e in evidence_for(db_path, factor, include_wildcard=False) if e.is_caveat
    ]
