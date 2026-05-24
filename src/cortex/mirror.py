from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from cortex.thesis import Thesis, list_theses

logger = logging.getLogger(__name__)

_BANNER = "> **Decision tool — not financial advice.**"


def _thesis_note(t: Thesis) -> str:
    tickers = ", ".join(t.tickers)
    evidence = "\n".join(f"- {e}" for e in t.evidence) if t.evidence else "- (none yet)"
    entry = (
        f"- Entry price: {t.entry_price}\n- Entry date: {t.entry_date}"
        if t.entry_price is not None
        else "- No entry recorded"
    )
    return f"""{_BANNER}

# {t.claim}

| Field | Value |
|---|---|
| ID | `{t.id}` |
| Tickers | {tickers} |
| Author | {t.author} |
| Opened | {t.opened} |
| Conviction | {t.conviction}/5 |
| Status | {t.status} |
| Review date | {t.review_date} |

## Falsifier
{t.falsifier}

## Reasoning
{t.reasoning or "(none yet)"}

## Evidence
{evidence}

## Position
{entry}
"""


def _dashboard_note(theses: list[Thesis], generated_on: date) -> str:
    open_t = [t for t in theses if t.status == "open"]
    closed_t = [t for t in theses if t.status != "open"]

    rows_open = "\n".join(
        f"| [[theses/{t.id}\\|{t.claim[:40]}]] | {', '.join(t.tickers)} "
        f"| {t.author} | {t.conviction}/5 | {t.review_date} |"
        for t in open_t
    )
    rows_closed = "\n".join(
        f"| [[theses/{t.id}\\|{t.claim[:40]}]] | {', '.join(t.tickers)} "
        f"| {t.author} | {t.status} |"
        for t in closed_t
    )

    open_section = (
        f"| Thesis | Tickers | Author | Conviction | Review |\n"
        f"|---|---|---|---|---|\n"
        f"{rows_open}"
        if open_t else "_No open theses._"
    )
    closed_section = (
        f"| Thesis | Tickers | Author | Status |\n"
        f"|---|---|---|---|\n"
        f"{rows_closed}"
        if closed_t else "_None yet._"
    )

    return f"""{_BANNER}

# CORTEX Dashboard
_Generated {generated_on}_

## Open theses ({len(open_t)})
{open_section}

## Closed / reviewed ({len(closed_t)})
{closed_section}
"""


def generate(
    vault_dir: Path,
    *,
    db_path: Path | None = None,
    today: date | None = None,
) -> int:
    """Write thesis notes + dashboard.md to vault_dir.

    Returns the count of files written.
    """
    theses = list_theses(db_path=db_path)
    today_ = today or date.today()

    theses_dir = vault_dir / "theses"
    theses_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for t in theses:
        note_path = theses_dir / f"{t.id}.md"
        content = _thesis_note(t)
        note_path.write_text(content, encoding="utf-8")
        written += 1

    dashboard = vault_dir / "dashboard.md"
    dashboard.write_text(_dashboard_note(theses, today_), encoding="utf-8")
    written += 1

    logger.info("Mirror: wrote %d files to %s", written, vault_dir)
    return written
