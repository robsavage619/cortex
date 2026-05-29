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
"""

from __future__ import annotations

import hashlib
import io
import logging
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from cortex.config import sec_user_agent

log = logging.getLogger(__name__)

_IDENTITY = sec_user_agent()
_CIK_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
_RATE_SLEEP = 0.12  # seconds between EDGAR filing XML downloads


class InsiderSourceError(Exception):
    """Raised when Form 4 data cannot be fetched or parsed."""


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


def _set_identity() -> None:
    try:
        import edgar

        edgar.set_identity(_IDENTITY)
    except ImportError as exc:
        raise InsiderSourceError("edgartools is not installed") from exc


def _fetch_cik_ticker_map() -> dict[str, str]:
    """Return {zero-padded-CIK: ticker} from SEC's company_tickers.json."""
    for attempt in range(4):
        resp = requests.get(
            _CIK_TICKER_URL,
            headers={"User-Agent": _IDENTITY},
            timeout=30,
        )
        if resp.status_code == 429:
            wait = _RETRY_SLEEP * (attempt + 1)
            log.warning("insiders: 429 on company_tickers.json, sleeping %.0fs", wait)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return {
            str(v["cik_str"]).zfill(10): v["ticker"].upper()
            for v in resp.json().values()
        }
    msg = "EDGAR rate-limited after retries — try again in a few minutes"
    raise InsiderSourceError(msg)


def _ticker_to_cik(cik_ticker: dict[str, str]) -> dict[str, str]:
    return {v.upper(): k for k, v in cik_ticker.items()}


def _parse_role(form4: object) -> tuple[str, str]:
    """Return (filer_cik, role) from the first reporting owner."""
    try:
        owners = form4.reporting_owners.owners  # type: ignore[attr-defined]
        if not owners:
            return "", "other"
        owner = owners[0]
        filer_cik = str(getattr(owner, "cik", "") or "")
        if getattr(owner, "is_officer", False):
            return filer_cik, "officer"
        if getattr(owner, "is_director", False):
            return filer_cik, "director"
        if getattr(owner, "is_ten_pct_owner", False):
            return filer_cik, "owner"
        return filer_cik, "other"
    except Exception:  # noqa: BLE001
        return "", "other"


def _coerce_date(val: object) -> date | None:
    """Coerce a date-like value to date, returning None on failure."""
    if isinstance(val, date):
        return val
    if hasattr(val, "date"):
        return val.date()  # type: ignore[return-value]
    if isinstance(val, str):
        try:
            return date.fromisoformat(val)
        except ValueError:
            return None
    return None


def fetch_insider_buys(
    universe_tickers: set[str],
    *,
    from_year: int = 2017,
) -> list[InsiderBuyEvent]:
    """Fetch Form 4 open-market purchase events for S&P 500 companies.

    Queries EDGAR per-company (targeted requests) rather than scanning
    all quarterly Form 4 filings universe-wide. Iterates filings newest-first
    and stops when we pass from_year — avoiding unnecessary XML downloads.

    Args:
        universe_tickers: Set of ticker symbols to scan.
        from_year: Only include filings on or after Jan 1 of this year.
    """
    _set_identity()
    import edgar

    cik_ticker = _fetch_cik_ticker_map()
    ticker_cik = _ticker_to_cik(cik_ticker)
    from_date = date(from_year, 1, 1)

    events: list[InsiderBuyEvent] = []
    ticker_list = sorted(t.upper() for t in universe_tickers)
    log.info("insiders: scanning %d tickers for Form 4 purchases", len(ticker_list))

    for i, ticker in enumerate(ticker_list):
        cik = ticker_cik.get(ticker)
        if not cik:
            log.debug("insiders: no CIK for %s, skipping", ticker)
            continue

        try:
            co = edgar.Company(cik)
            filings = co.get_filings(form="4")
        except Exception as exc:  # noqa: BLE001
            log.warning("insiders: %s (%s) filings fetch failed: %s", ticker, cik, exc)
            continue

        ticker_hits = 0
        for f in filings or []:
            fd = _coerce_date(f.filing_date)
            if fd is None:
                continue
            if fd < from_date:
                break  # filings are newest-first; past horizon → stop

            try:
                form4: object = f.obj()
                if form4 is None:
                    time.sleep(_RATE_SLEEP)
                    continue

                purchases = getattr(form4, "common_stock_purchases", None)
                if purchases is None or len(purchases) == 0:
                    time.sleep(_RATE_SLEEP)
                    continue
            except Exception as exc:  # noqa: BLE001
                log.debug("insiders: %s %s parse error: %s", ticker, fd, exc)
                time.sleep(_RATE_SLEEP)
                continue

            filer_name = str(getattr(form4, "insider_name", "") or "")
            filer_cik, role = _parse_role(form4)

            for _, row in purchases.iterrows():
                # Verify open-market purchase code — exclude awards/exercises
                code = str(row.get("Code", "") or "")
                if code != "P":
                    continue

                tx_date = _coerce_date(row.get("Date"))
                if tx_date is None:
                    continue

                shares = float(row.get("Shares") or 0)
                price = float(row.get("Price") or 0)
                if shares <= 0 or price <= 0:
                    continue

                events.append(
                    InsiderBuyEvent(
                        ticker=ticker,
                        issuer_cik=cik,
                        filer_cik=filer_cik,
                        filer_name=filer_name,
                        filer_role=role,
                        transaction_date=tx_date,
                        filing_date=fd,
                        shares=shares,
                        value_usd=shares * price,
                    )
                )
                ticker_hits += 1

            time.sleep(_RATE_SLEEP)

        if ticker_hits:
            log.info(
                "insiders: %s — %d purchases since %d", ticker, ticker_hits, from_year
            )

        if (i + 1) % 50 == 0:
            log.info(
                "insiders: %d/%d tickers scanned, %d events so far",
                i + 1,
                len(ticker_list),
                len(events),
            )

    log.info(
        "insiders: total %d purchase events across %d tickers",
        len(events),
        len({e.ticker for e in events}),
    )
    return events


# ── incremental sync ─────────────────────────────────────────────────────────


def fetch_insider_buys_incremental(
    universe_tickers: set[str],
    db_path: Path,
    *,
    from_year: int = 2017,
) -> int:
    """Fetch and store Form 4 purchases per ticker, resuming where we left off.

    Already-synced tickers are skipped (checks DB for existing rows). Returns
    total new rows inserted across all tickers.
    """
    _set_identity()
    import edgar

    from cortex.storage.db import connect

    cik_ticker = _fetch_cik_ticker_map()
    ticker_cik = _ticker_to_cik(cik_ticker)
    from_date = date(from_year, 1, 1)

    # Load already-synced tickers so we can skip them on resume
    with connect(db_path, read_only=True) as conn:
        done_rows = conn.execute("SELECT DISTINCT ticker FROM insider_buys").fetchall()
    done_tickers = {r[0] for r in done_rows}

    ticker_list = sorted(t.upper() for t in universe_tickers)
    total_new = 0
    log.info(
        "insiders: %d tickers to scan (%d already done, skipping)",
        len(ticker_list),
        len(done_tickers),
    )

    for i, ticker in enumerate(ticker_list):
        if ticker in done_tickers:
            continue

        cik = ticker_cik.get(ticker)
        if not cik:
            log.debug("insiders: no CIK for %s, skipping", ticker)
            continue

        try:
            co = edgar.Company(cik)
            filings = co.get_filings(form="4")
        except Exception as exc:  # noqa: BLE001
            log.warning("insiders: %s (%s) filings fetch failed: %s", ticker, cik, exc)
            continue

        ticker_events: list[InsiderBuyEvent] = []
        for f in filings or []:
            fd = _coerce_date(f.filing_date)
            if fd is None:
                continue
            if fd < from_date:
                break

            try:
                form4: object = f.obj()
                if form4 is None:
                    time.sleep(_RATE_SLEEP)
                    continue
                purchases = getattr(form4, "common_stock_purchases", None)
                if purchases is None or len(purchases) == 0:
                    time.sleep(_RATE_SLEEP)
                    continue
            except Exception as exc:  # noqa: BLE001
                log.debug("insiders: %s %s parse error: %s", ticker, fd, exc)
                time.sleep(_RATE_SLEEP)
                continue

            filer_name = str(getattr(form4, "insider_name", "") or "")
            filer_cik, role = _parse_role(form4)

            for _, row in purchases.iterrows():
                code = str(row.get("Code", "") or "")
                if code != "P":
                    continue
                tx_date = _coerce_date(row.get("Date"))
                if tx_date is None:
                    continue
                shares = float(row.get("Shares") or 0)
                price = float(row.get("Price") or 0)
                if shares <= 0 or price <= 0:
                    continue
                ticker_events.append(
                    InsiderBuyEvent(
                        ticker=ticker,
                        issuer_cik=cik,
                        filer_cik=filer_cik,
                        filer_name=filer_name,
                        filer_role=role,
                        transaction_date=tx_date,
                        filing_date=fd,
                        shares=shares,
                        value_usd=shares * price,
                    )
                )
            time.sleep(_RATE_SLEEP)

        new = store_insider_buys(ticker_events, db_path)
        total_new += new
        if ticker_events:
            log.info(
                "insiders: %s — %d purchases, %d new rows",
                ticker,
                len(ticker_events),
                new,
            )
            print(
                f"[{i + 1}/{len(ticker_list)}] {ticker}: {len(ticker_events)} buys "
                f"({new} new)",
                flush=True,
            )
        elif (i + 1) % 50 == 0:
            print(
                f"[{i + 1}/{len(ticker_list)}] scanned, {total_new} new rows so far",
                flush=True,
            )

    log.info("insiders: incremental sync done — %d new rows total", total_new)
    return total_new


# ── bulk-index approach ───────────────────────────────────────────────────────

_FULL_INDEX_BASE = "https://www.sec.gov/Archives/edgar/full-index"
_ARCHIVES_BASE = "https://www.sec.gov/Archives"
_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
_HEADERS = {"User-Agent": _IDENTITY}
_MAX_WORKERS = 3  # EDGAR allows ~10 req/s; 3 workers × ~3 req/s ≈ safe
_RETRY_SLEEP = 12.0  # back-off seconds on 429


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


def _download_form_index(year: int, quarter: int) -> list[tuple[str, str, str]]:
    """Download form.idx for one quarter; return Form 4 rows: (cik, acc_no, date_filed).

    form.idx is fixed-width sorted by form type:
      Form Type (12) | Company Name (62) | CIK (12) | Date Filed (12) | Filename
    """
    url = f"{_FULL_INDEX_BASE}/{year}/QTR{quarter}/form.idx"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("insiders: failed to fetch %s: %s", url, exc)
        return []

    results: list[tuple[str, str, str]] = []
    in_data = False
    for line in io.StringIO(resp.text):
        line = line.rstrip("\n")
        if line.startswith("---"):
            in_data = True
            continue
        if not in_data or len(line) < 60:
            continue
        # Split right-to-left: filename, date, CIK are all token-safe (no spaces)
        parts = line.split()
        if len(parts) < 4:
            continue
        # form type is the first token
        if parts[0] != "4":
            continue
        filename = parts[-1]  # e.g. edgar/data/123456/0001234567-24-000001.txt
        date_filed = parts[-2]  # e.g. 2024-02-12
        cik_raw = parts[-3]  # e.g. 1084869
        # Validate date format
        if len(date_filed) != 10 or date_filed[4] != "-":
            continue
        # Derive accession number from filename
        acc_no = filename.rsplit("/", 1)[-1].replace(".txt", "")
        cik = cik_raw.zfill(10)
        results.append((cik, acc_no, date_filed))

    return results


_Form4Row = tuple[str, str, str, float, float, str, str]


def _parse_form4_xml(xml_text: str) -> list[_Form4Row]:
    """Parse Form 4 XML; return P-coded non-derivative transactions.

    Each row: (issuer_cik, filer_cik, filer_name, shares, price, tx_date_str, role).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    def txt(tag: str) -> str:
        el = root.find(tag)
        return (el.text or "").strip() if el is not None else ""

    issuer_cik = txt("issuer/issuerCik").lstrip("0") or txt("issuer/issuerCik")

    # Filer info
    filer_cik = txt("reportingOwner/reportingOwnerId/rptOwnerCik").lstrip("0")
    filer_name = txt("reportingOwner/reportingOwnerId/rptOwnerName")
    rel = root.find("reportingOwner/reportingOwnerRelationship")
    if rel is not None:
        if (rel.findtext("isOfficer") or "").lower() in ("1", "true"):
            role = "officer"
        elif (rel.findtext("isDirector") or "").lower() in ("1", "true"):
            role = "director"
        elif (rel.findtext("isTenPercentOwner") or "").lower() in ("1", "true"):
            role = "owner"
        else:
            role = "other"
    else:
        role = "other"

    results = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = (tx.findtext("transactionCoding/transactionCode") or "").strip()
        if code != "P":
            continue
        acq = (
            (
                tx.findtext("transactionAmounts/transactionAcquiredDisposedCode/value")
                or ""
            )
            .strip()
            .upper()
        )
        if acq and acq != "A":
            continue  # disposals coded P are rare but skip them
        tx_date = (tx.findtext("transactionDate/value") or "").strip()
        shares_str = tx.findtext("transactionAmounts/transactionShares/value") or "0"
        price_str = (
            tx.findtext("transactionAmounts/transactionPricePerShare/value") or "0"
        )
        try:
            shares = float(shares_str)
            price = float(price_str)
        except ValueError:
            continue
        if shares <= 0 or price <= 0:
            continue
        results.append(
            (issuer_cik, filer_cik, filer_name, shares, price, tx_date, role)
        )

    return results


def _fetch_submissions_primary_docs(cik: str) -> dict[str, str]:
    """Return {acc_no: primary_doc_filename} for all Form 4 filings for one CIK.

    Uses data.sec.gov/submissions/CIK{cik}.json which includes a primaryDocument
    field — the canonical filename for the primary XML, regardless of filer convention.
    Follows pagination via filings.files[] for older filings.
    """
    cik10 = cik.zfill(10)
    result: dict[str, str] = {}

    def _process_block(block: dict) -> None:
        forms = block.get("form", [])
        acc_nos = block.get("accessionNumber", [])
        primary_docs = block.get("primaryDocument", [])
        for form, acc, doc in zip(forms, acc_nos, primary_docs, strict=False):
            if form == "4" and doc:
                result[acc] = doc

    for attempt in range(4):
        try:
            resp = requests.get(
                f"{_SUBMISSIONS_BASE}/CIK{cik10}.json",
                headers=_HEADERS,
                timeout=30,
            )
            if resp.status_code == 429:
                wait = _RETRY_SLEEP * (attempt + 1)
                time.sleep(wait)
                continue
            if resp.status_code == 404:
                return result
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.RequestException:
            return result
    else:
        return result

    filings = data.get("filings", {})
    recent = filings.get("recent", {})
    _process_block(recent)

    # Follow pagination for older filings
    for page_file in filings.get("files", []):
        name = page_file.get("name", "")
        if not name:
            continue
        for attempt in range(3):
            try:
                resp = requests.get(
                    f"{_SUBMISSIONS_BASE}/{name}",
                    headers=_HEADERS,
                    timeout=30,
                )
                if resp.status_code == 429:
                    time.sleep(_RETRY_SLEEP * (attempt + 1))
                    continue
                resp.raise_for_status()
                _process_block(resp.json())
                break
            except requests.RequestException:
                break
        time.sleep(0.1)

    return result


def _fetch_primary_doc_map(
    universe_ciks: set[str],
) -> dict[str, str]:
    """Pre-load {acc_no: primary_doc_filename} for all universe CIKs.

    503 requests at ~0.15s spacing ≈ 75 seconds; much cheaper than discovering
    the filename per-filing via 404 chains across 282K requests.
    """
    acc_to_doc: dict[str, str] = {}
    cik_list = sorted(universe_ciks)
    for i, cik in enumerate(cik_list):
        docs = _fetch_submissions_primary_docs(cik)
        acc_to_doc.update(docs)
        if (i + 1) % 50 == 0:
            print(
                f"  Primary doc map: {i + 1}/{len(cik_list)} CIKs, "
                f"{len(acc_to_doc):,} Form 4 entries",
                flush=True,
            )
        time.sleep(0.15)  # ~6.7 req/s — safely under EDGAR's 10 req/s cap
    log.info(
        "insiders: primary doc map built — %d acc → doc entries for %d CIKs",
        len(acc_to_doc),
        len(cik_list),
    )
    return acc_to_doc


def _fetch_form4_xml(
    cik: str, acc_no: str, primary_doc: str | None = None
) -> str | None:
    """Fetch Form 4 primary XML for a given accession number.

    Uses primary_doc (from submissions JSON) when available; falls back to
    common naming conventions and a .txt header scan as last resort.
    Retries on 429 with back-off.
    """
    acc_nodash = acc_no.replace("-", "")
    cik_int = cik.lstrip("0") or "0"
    base = f"{_ARCHIVES_BASE}/edgar/data/{cik_int}/{acc_nodash}"

    # Build candidate list: known primary doc first, then common fallbacks.
    # primaryDocument from submissions JSON may include an xsl subdirectory prefix
    # (e.g. "xslF345X06/rdgdoc.xml" → actual data file is "rdgdoc.xml").
    candidates: list[str] = []
    if primary_doc:
        basename = primary_doc.rsplit("/", 1)[-1]
        candidates.append(basename)
        if "/" in primary_doc:
            candidates.append(primary_doc)  # also try full path as fallback
    candidates += ["form4.xml", f"{acc_no}.xml"]

    def _get(url: str) -> str | None:
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=_HEADERS, timeout=20)
                if resp.status_code == 429:
                    time.sleep(_RETRY_SLEEP * (attempt + 1))
                    continue
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.text
            except requests.RequestException:
                return None
        return None

    for fname in candidates:
        text = _get(f"{base}/{fname}")
        if text:
            return text

    # Last resort: scan first 16 KB of the .txt submission file for <FILENAME>
    try:
        resp = requests.get(
            f"{base}/{acc_no}.txt",
            headers={**_HEADERS, "Range": "bytes=0-16383"},
            timeout=20,
        )
        if resp.status_code in (200, 206):
            for line in resp.text.splitlines():
                stripped = line.strip()
                if stripped.startswith("<FILENAME>"):
                    fname = stripped[len("<FILENAME>") :].strip()
                    if fname.endswith(".xml"):
                        text = _get(f"{base}/{fname}")
                        if text:
                            return text
    except requests.RequestException:
        pass

    return None


def fetch_insider_buys_bulk_index(
    universe_tickers: set[str],
    db_path: Path,
    *,
    from_year: int = 2017,
) -> int:
    """Fetch Form 4 purchases using EDGAR quarterly bulk index files.

    Algorithm (dramatically faster than per-company queries):
    1. Download one form.idx per quarter (~10 MB each, 37 files for 2017-2026)
    2. Filter to S&P 500 CIKs — narrows ~500k rows to ~15k filings
    3. Batch-fetch Form 4 XMLs in parallel (8 workers, EDGAR-safe rate)
    4. Parse for P-coded (open-market purchase) transactions
    5. Store per-batch to DB

    Estimated runtime: ~5-15 minutes vs. ~200 hours for per-company approach.
    """
    cik_ticker = _fetch_cik_ticker_map()
    ticker_cik = _ticker_to_cik(cik_ticker)

    # Build universe CIK set (zero-padded 10 digits)
    universe_ciks: dict[str, str] = {}  # cik → ticker
    for ticker in universe_tickers:
        cik = ticker_cik.get(ticker.upper())
        if cik:
            universe_ciks[cik] = ticker.upper()

    log.info(
        "insiders bulk: %d universe CIKs, scanning from %d",
        len(universe_ciks),
        from_year,
    )

    # Pre-load primary document filenames from submissions JSON (one request per CIK)
    print(
        f"Building primary doc map for {len(universe_ciks)} CIKs"
        f" (≈{len(universe_ciks) * 0.15 / 60:.1f} min)…",
        flush=True,
    )
    acc_to_doc = _fetch_primary_doc_map(set(universe_ciks.keys()))
    print(f"Primary doc map: {len(acc_to_doc):,} Form 4 entries", flush=True)

    # Load already-stored (cik, acc_no) pairs to skip on resume
    from cortex.storage.db import connect

    with connect(db_path, read_only=True) as conn:
        done = conn.execute(
            "SELECT DISTINCT issuer_cik || '|' || filer_cik FROM insider_buys"
        ).fetchall()
    _done = {r[0] for r in done}  # noqa: F841 — reserved for future dedup

    quarters = _quarters_since(from_year)
    log.info("insiders bulk: %d quarters to scan", len(quarters))

    # Collect all (cik, acc_no, filing_date) matches across all quarters
    filings_to_fetch: list[tuple[str, str, date]] = []
    for year, quarter in quarters:
        rows = _download_form_index(year, quarter)
        quarter_hits = [
            (cik, acc_no, date.fromisoformat(d))
            for cik, acc_no, d in rows
            if cik in universe_ciks
        ]
        filings_to_fetch.extend(quarter_hits)
        log.info(
            "insiders bulk: Q%d/%d %d Form 4 matches (%d total so far)",
            quarter,
            year,
            len(quarter_hits),
            len(filings_to_fetch),
        )
        time.sleep(0.05)  # brief pause between index downloads

    log.info("insiders bulk: %d total Form 4 filings to process", len(filings_to_fetch))
    print(
        f"Found {len(filings_to_fetch):,} Form 4 filings for S&P500 universe",
        flush=True,
    )

    total_new = 0
    batch: list[InsiderBuyEvent] = []
    _BATCH_SIZE = 500

    def _process_filing(
        args: tuple[str, str, date],
    ) -> list[InsiderBuyEvent]:
        cik, acc_no, filing_date = args
        ticker = universe_ciks.get(cik, "")
        if not ticker:
            return []
        primary_doc = acc_to_doc.get(acc_no)
        xml_text = _fetch_form4_xml(cik, acc_no, primary_doc)
        if not xml_text:
            return []
        rows = _parse_form4_xml(xml_text)
        events = []
        for _icik, filer_cik, filer_name, shares, price, tx_date_str, role in rows:
            tx_date = _coerce_date(tx_date_str)
            if tx_date is None:
                continue
            events.append(
                InsiderBuyEvent(
                    ticker=ticker,
                    issuer_cik=cik,
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

    processed = 0
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_process_filing, f): f for f in filings_to_fetch}
        for fut in as_completed(futures):
            try:
                events = fut.result()
                batch.extend(events)
            except Exception as exc:  # noqa: BLE001
                log.debug("insiders bulk: filing error: %s", exc)
            processed += 1
            if len(batch) >= _BATCH_SIZE:
                new = store_insider_buys(batch, db_path)
                total_new += new
                batch.clear()
            if processed % 500 == 0:
                print(
                    f"Processed {processed:,}/{len(filings_to_fetch):,} filings,"
                    f" {total_new:,} new rows",
                    flush=True,
                )

    if batch:
        total_new += store_insider_buys(batch, db_path)

    log.info("insiders bulk: done — %d new rows from %d filings", total_new, processed)
    print(
        f"Bulk sync complete: {total_new:,} new rows from {processed:,} filings",
        flush=True,
    )
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
