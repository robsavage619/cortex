"""Activist stake events from SEC Schedule 13D filings.

When a party acquires >5% of a public company with intent to influence control,
they must file SC 13D within 10 business days.  The filing date is the
point-in-time gate: we know about the stake only on/after that date.

Brav & Jiang (2008) document +7–8% abnormal returns in the (-20, +20) day
window around initial 13D filings, with 10–30% drift over 12–18 months.  This
effect holds in large-cap stocks (unlike Form 4 insider buys, which are
predominantly a small-cap signal).

We use INITIAL SC 13D filings only (not amendments) as the buy signal.
Amendments often accompany partial exits or settlements which carry a mixed
or negative signal.

Point-in-time: gated on filing_date.  Universe filter: S&P 500 tickers only
(matched via SEC CIK→ticker map).
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_IDENTITY = "Rob Savage household-research rob.savage.research@gmail.com"
_CIK_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
_RATE_SLEEP = 0.15  # seconds between EDGAR requests


class ActivismSourceError(Exception):
    """Raised when 13D data cannot be fetched or parsed."""


@dataclass(frozen=True)
class ActivistEvent:
    ticker: str
    subject_cik: str
    filer: str
    filing_date: date

    @property
    def dedupe_id(self) -> str:
        raw = f"{self.subject_cik}|{self.filing_date.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _set_identity() -> None:
    try:
        import edgar
        edgar.set_identity(_IDENTITY)
    except ImportError as exc:
        raise ActivismSourceError("edgartools is not installed") from exc


def _fetch_cik_ticker_map() -> dict[str, str]:
    """Return {zero-padded-CIK: ticker} from SEC's company_tickers.json."""
    resp = requests.get(
        _CIK_TICKER_URL,
        headers={"User-Agent": _IDENTITY},
        timeout=30,
    )
    resp.raise_for_status()
    return {
        str(v["cik_str"]).zfill(10): v["ticker"].upper()
        for v in resp.json().values()
    }


def _extract_subject_cik(filing: object) -> str | None:
    """Parse the subject company CIK from a 13D filing header."""
    try:
        hdr = str(getattr(filing, "header", "") or "")
        # Header contains "Subject Company" section with CIK in brackets
        m = re.search(r"Subject Company.*?\[(\d{10})\]", hdr, re.DOTALL)
        if m:
            return m.group(1)
    except Exception:  # noqa: BLE001
        pass
    return None


def _ticker_to_cik(cik_ticker: dict[str, str]) -> dict[str, str]:
    """Invert {cik: ticker} → {ticker: cik}."""
    return {v.upper(): k for k, v in cik_ticker.items()}


def fetch_activism_events(
    universe_tickers: set[str],
    *,
    from_year: int = 2014,
) -> list[ActivistEvent]:
    """Fetch SC 13D filings where each universe ticker is the SUBJECT company.

    Queries EDGAR per company (503 targeted requests) rather than scanning
    all quarterly SC 13D filings universe-wide (~139k header downloads).
    EDGAR's company filings endpoint returns 13D filings where that company
    is the subject/issuer, not the filer.
    """
    _set_identity()
    import edgar

    cik_ticker = _fetch_cik_ticker_map()
    ticker_cik = _ticker_to_cik(cik_ticker)
    from_date = date(from_year, 1, 1)

    events: list[ActivistEvent] = []
    ticker_list = sorted(t.upper() for t in universe_tickers)
    log.info(
        "activism: scanning %d tickers for SC 13D subject filings", len(ticker_list)
    )

    for i, ticker in enumerate(ticker_list):
        cik = ticker_cik.get(ticker)
        if not cik:
            log.debug("activism: no CIK for %s, skipping", ticker)
            continue
        try:
            co = edgar.Company(cik)
            filings = co.get_filings(form="SC 13D")
        except Exception as exc:  # noqa: BLE001
            log.warning("activism: %s (%s) fetch failed: %s", ticker, cik, exc)
            continue

        if not filings:
            continue

        ticker_hits = 0
        for f in filings:
            fd = f.filing_date
            if isinstance(fd, str):
                fd = date.fromisoformat(fd)
            if fd < from_date:
                break  # filings are newest-first; stop when we go back far enough
            events.append(
                ActivistEvent(
                    ticker=ticker,
                    subject_cik=cik,
                    filer=str(getattr(f, "company", "") or ""),
                    filing_date=fd,
                )
            )
            ticker_hits += 1

        if ticker_hits:
            log.info(
                "activism: %s — %d 13D filings since %d", ticker, ticker_hits, from_year
            )

        if (i + 1) % 50 == 0:
            log.info("activism: %d/%d tickers scanned, %d events so far",
                     i + 1, len(ticker_list), len(events))
        time.sleep(_RATE_SLEEP)

    log.info("activism: total events: %d across %d tickers", len(events),
             len({e.ticker for e in events}))
    return events


# ── persistence ───────────────────────────────────────────────────────────────

def store_activism_events(events: list[ActivistEvent], db_path: Path) -> int:
    """Upsert activism events into activist_stakes. Returns new-row count."""
    from wst.storage.db import connect

    if not events:
        return 0
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM activist_stakes").fetchone()
        before = int(row[0]) if row else 0
        conn.executemany(
            """
            INSERT INTO activist_stakes (id, ticker, subject_cik, filer, filing_date)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET filer = excluded.filer
            """,
            [
                (e.dedupe_id, e.ticker, e.subject_cik, e.filer, e.filing_date)
                for e in events
            ],
        )
        row = conn.execute("SELECT COUNT(*) FROM activist_stakes").fetchone()
        after = int(row[0]) if row else 0
    return after - before


def list_activism_events(
    db_path: Path, *, ticker: str | None = None, limit: int = 100
) -> list[ActivistEvent]:
    """Read activism events from the DB, most recent first."""
    from wst.storage.db import connect

    clauses: list[str] = []
    params: list[object] = []
    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker.upper())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            f"""
            SELECT ticker, subject_cik, filer, filing_date
            FROM activist_stakes
            {where}
            ORDER BY filing_date DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [
        ActivistEvent(ticker=r[0], subject_cik=r[1], filer=r[2], filing_date=r[3])
        for r in rows
    ]
