"""Corporate insider open-market purchase events from SEC Form 4 filings.

When a company officer or director purchases company stock on the open market
they must file Form 4 with the SEC within 2 business days (transaction code P).

Cohen, Malloy & Pomorski (2012, J. Finance) — "Decoding Inside Information"
— show officer/director open-market purchases predict returns cross-sectionally
with t-stats of 3–5. The signal is strongest for officer purchases and cluster
buys (multiple insiders buying in the same month).

We capture only "P" (open-market purchase) transaction codes. Awards (A),
option exercises (M), dispositions (S/D), and gifts (G) are excluded.

Point-in-time: gated on filing_date (SEC-accepted date, within 2 business days
of transaction). Universe filter: S&P 500 tickers only.

Ingestion uses SEC's DERA quarterly "Insider Transactions Data Sets" (Form 3/4/5
bundles with transaction codes pre-parsed into TSVs): one ~14 MB download per
quarter rather than hundreds of thousands of per-filing XML fetches.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import time
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from cortex.config import sec_user_agent

log = logging.getLogger(__name__)

_IDENTITY = sec_user_agent()
_HEADERS = {"User-Agent": _IDENTITY}
_RETRY_SLEEP = 12.0  # back-off seconds on 429

# SEC DERA "Insider Transactions Data Sets" — quarterly Form 3/4/5 bundles with
# transaction codes pre-parsed into TSVs. One ~14 MB download per quarter
# replaces hundreds of thousands of per-filing XML fetches.
_DATASET_BASE = (
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets"
)
_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "JAN",
            "FEB",
            "MAR",
            "APR",
            "MAY",
            "JUN",
            "JUL",
            "AUG",
            "SEP",
            "OCT",
            "NOV",
            "DEC",
        ],
        start=1,
    )
}


@dataclass(frozen=True)
class InsiderBuyEvent:
    ticker: str
    issuer_cik: str
    filer_cik: str
    filer_name: str
    filer_role: str  # 'officer' | 'director' | 'owner' | 'other'
    transaction_date: date
    filing_date: date
    shares: float
    value_usd: float

    @property
    def dedupe_id(self) -> str:
        raw = f"{self.issuer_cik}|{self.filer_cik}|{self.transaction_date.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _quarters_since(from_year: int) -> list[tuple[int, int]]:
    """Return (year, quarter) pairs from from_year Q1 through current quarter."""
    today = date.today()
    current_q = (today.month - 1) // 3 + 1
    out = []
    for y in range(from_year, today.year + 1):
        for q in range(1, 5):
            if y == today.year and q > current_q:
                break
            out.append((y, q))
    return out


# ── quarterly dataset ingestion ────────────────────────────────────────────────


def _parse_dataset_date(s: str) -> date | None:
    """Parse a SEC dataset 'DD-MON-YYYY' date (e.g. '28-FEB-2024')."""
    parts = (s or "").strip().split("-")
    if len(parts) != 3:
        return None
    month = _MONTHS.get(parts[1].upper())
    if month is None:
        return None
    try:
        return date(int(parts[2]), month, int(parts[0]))
    except ValueError:
        return None


def _role_from_relationship(relationship: str) -> str:
    """Map a REPORTINGOWNER relationship string to officer/director/owner/other.

    Priority: officer > director > 10%-owner > other.
    """
    rel = (relationship or "").lower()
    if "officer" in rel:
        return "officer"
    if "director" in rel:
        return "director"
    if "tenpercent" in rel:
        return "owner"
    return "other"


def _open_tsv(zf: zipfile.ZipFile, name: str) -> csv.DictReader:
    fh = io.TextIOWrapper(zf.open(name), encoding="utf-8", errors="replace")
    return csv.DictReader(fh, delimiter="\t")


def _parse_quarter_zip(content: bytes, universe: set[str]) -> list[InsiderBuyEvent]:
    """Extract P-coded open-market buys for the universe from one quarterly bundle.

    Filtering SUBMISSION to the universe first drops ~95% of rows before the
    join, so the two follow-on passes touch only relevant accessions.
    """
    events: list[InsiderBuyEvent] = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        submissions: dict[str, tuple[str, str, date]] = {}
        for row in _open_tsv(zf, "SUBMISSION.tsv"):
            if row.get("DOCUMENT_TYPE") != "4":
                continue
            ticker = (row.get("ISSUERTRADINGSYMBOL") or "").strip().upper()
            if ticker not in universe:
                continue
            filing_date = _parse_dataset_date(row.get("FILING_DATE", ""))
            if filing_date is None:
                continue
            acc = row.get("ACCESSION_NUMBER") or ""
            submissions[acc] = (
                (row.get("ISSUERCIK") or "").zfill(10),
                ticker,
                filing_date,
            )
        if not submissions:
            return []

        owners: dict[str, tuple[str, str, str]] = {}
        for row in _open_tsv(zf, "REPORTINGOWNER.tsv"):
            acc = row.get("ACCESSION_NUMBER") or ""
            if acc not in submissions or acc in owners:
                continue  # keep first reporting owner per filing
            owners[acc] = (
                (row.get("RPTOWNERCIK") or "").lstrip("0"),
                row.get("RPTOWNERNAME") or "",
                _role_from_relationship(row.get("RPTOWNER_RELATIONSHIP", "")),
            )

        for row in _open_tsv(zf, "NONDERIV_TRANS.tsv"):
            acc = row.get("ACCESSION_NUMBER") or ""
            if acc not in submissions or row.get("TRANS_CODE") != "P":
                continue
            acq = (row.get("TRANS_ACQUIRED_DISP_CD") or "").strip().upper()
            if acq and acq != "A":
                continue  # disposals coded P are rare — skip
            tx_date = _parse_dataset_date(row.get("TRANS_DATE", ""))
            if tx_date is None:
                continue
            try:
                shares = float(row.get("TRANS_SHARES") or 0)
                price = float(row.get("TRANS_PRICEPERSHARE") or 0)
            except ValueError:
                continue
            if shares <= 0 or price <= 0:
                continue
            issuer_cik, ticker, filing_date = submissions[acc]
            filer_cik, filer_name, role = owners.get(acc, ("", "", "other"))
            events.append(
                InsiderBuyEvent(
                    ticker=ticker,
                    issuer_cik=issuer_cik,
                    filer_cik=filer_cik,
                    filer_name=filer_name,
                    filer_role=role,
                    transaction_date=tx_date,
                    filing_date=filing_date,
                    shares=shares,
                    value_usd=shares * price,
                )
            )
    return events


def _download_quarter_zip(year: int, quarter: int) -> bytes | None:
    """Download one quarterly Form 345 dataset, retrying on 429."""
    url = f"{_DATASET_BASE}/{year}q{quarter}_form345.zip"
    for attempt in range(4):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=120)
        except requests.RequestException as exc:
            log.warning("insiders: %s fetch error: %s", url, exc)
            return None
        if resp.status_code == 429:
            time.sleep(_RETRY_SLEEP * (attempt + 1))
            continue
        if resp.status_code == 404:
            log.info("insiders: dataset not yet published for %dQ%d", year, quarter)
            return None
        resp.raise_for_status()
        return resp.content
    log.warning("insiders: %dQ%d rate-limited after retries", year, quarter)
    return None


def fetch_insider_buys_datasets(
    universe_tickers: set[str],
    db_path: Path,
    *,
    from_year: int = 2017,
) -> int:
    """Sync Form 4 open-market buys via SEC's quarterly Insider Transactions
    Data Sets (DERA Form 345 TSV bundles).

    One ~14 MB download per quarter (≈37 requests for 2017→now) replaces the
    ~280k per-filing XML fetches a per-filing walk would require: the transaction
    code is already a column, so we filter to ``TRANS_CODE='P'`` open-market
    buys for the universe locally. Idempotent via ``store_insider_buys``.
    """
    universe = {t.upper() for t in universe_tickers}
    quarters = _quarters_since(from_year)
    print(
        f"Insider sync via SEC datasets: {len(quarters)} quarters,"
        f" {len(universe)} universe tickers…",
        flush=True,
    )
    total_new = 0
    for year, quarter in quarters:
        content = _download_quarter_zip(year, quarter)
        if content is None:
            continue
        events = _parse_quarter_zip(content, universe)
        new = store_insider_buys(events, db_path)
        total_new += new
        print(
            f"  {year}Q{quarter}: {len(events):,} P-buys for universe,"
            f" {new:,} new (running total {total_new:,})",
            flush=True,
        )
        time.sleep(0.3)  # gentle pacing between quarterly downloads
    print(f"Insider dataset sync complete — {total_new:,} new rows", flush=True)
    return total_new


# ── persistence ───────────────────────────────────────────────────────────────


def store_insider_buys(events: list[InsiderBuyEvent], db_path: Path) -> int:
    """Upsert insider buy events into insider_buys. Returns new-row count."""
    from cortex.storage.db import connect

    if not events:
        return 0
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM insider_buys").fetchone()
        before = int(row[0]) if row else 0
        conn.executemany(
            """
            INSERT INTO insider_buys
                (id, ticker, issuer_cik, filer_cik, filer_name, filer_role,
                 transaction_date, filing_date, shares, value_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
            """,
            [
                (
                    e.dedupe_id,
                    e.ticker,
                    e.issuer_cik,
                    e.filer_cik,
                    e.filer_name,
                    e.filer_role,
                    e.transaction_date,
                    e.filing_date,
                    e.shares,
                    e.value_usd,
                )
                for e in events
            ],
        )
        row = conn.execute("SELECT COUNT(*) FROM insider_buys").fetchone()
        after = int(row[0]) if row else 0
    return after - before


def list_insider_buys(
    db_path: Path,
    *,
    ticker: str | None = None,
    role: str | None = None,
    limit: int = 100,
) -> list[InsiderBuyEvent]:
    """Read insider buy events from DB, most recent first."""
    from cortex.storage.db import connect

    clauses: list[str] = []
    params: list[object] = []
    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker.upper())
    if role:
        clauses.append("filer_role = ?")
        params.append(role)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            f"""
            SELECT ticker, issuer_cik, filer_cik, filer_name, filer_role,
                   transaction_date, filing_date, shares, value_usd
            FROM insider_buys
            {where}
            ORDER BY filing_date DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [
        InsiderBuyEvent(
            ticker=r[0],
            issuer_cik=r[1],
            filer_cik=r[2],
            filer_name=r[3],
            filer_role=r[4],
            transaction_date=r[5],
            filing_date=r[6],
            shares=float(r[7]),
            value_usd=float(r[8]),
        )
        for r in rows
    ]
