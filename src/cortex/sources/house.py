"""House of Representatives Periodic Transaction Report (PTR) scraper.

The House Clerk publishes a daily-refreshed annual ZIP archive:
    https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip

Inside the ZIP is a {year}FD.xml index listing every disclosure filed that year.
Filtering for FilingType="P" gives Periodic Transaction Reports.  Each entry
carries a DocID; the corresponding PDF lives at:
    https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{DocID}.pdf

Electronic PTR PDFs have a consistent tabular layout and are machine-readable
via pdfplumber.  Scanned (paper) filings produce empty tables — they are skipped
and counted so nothing disappears silently.

Persistence reuses congress_trades with chamber='house', so congress_stats()
automatically includes House data once this sync runs.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_BASE = "https://disclosures-clerk.house.gov"
_ZIP_URL = _BASE + "/public_disc/financial-pdfs/{year}FD.zip"
_PDF_URL = _BASE + "/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_PTR_FILING_TYPE = "P"
_POLITE_DELAY = 0.5  # seconds between PDF fetches

_SKIP_TICKERS = {"", "--", "N/A", "TICKER", "NONE"}
_MIN_TICKER_LEN = 2  # single-letter strings like "P", "S", "J" are ownership codes, not tickers

# Tickers appear as "(AMZN) [ST]" or "(BRK/B)" in the Asset cell.
# Matches 1-5 uppercase letters with optional slash + 1-2 letters (BRK/B).
_TICKER_RE = re.compile(r"\(([A-Z]{1,5}(?:/[A-Z]{1,2})?)\)")

_OCR_MODEL = "claude-haiku-4-5-20251001"
_OCR_PROMPT = """\
This is a page from a U.S. House of Representatives Periodic Transaction Report (PTR).
Extract every stock transaction row from the table. Return ONLY a JSON array — no prose.
Each element must have exactly these keys:
  ticker            (string, e.g. "AMZN"; omit rows with no ticker)
  transaction_type  (string, e.g. "Purchase", "Sale (Full)", "S (partial)")
  amount            (string, e.g. "$1,001 - $15,000")
  transaction_date  (string MM/DD/YYYY or "" if absent)
  asset_description (string, first line of the asset name)

If the page has no transaction table, return [].
"""


class HouseSourceError(Exception):
    """Raised when House trade data cannot be fetched or parsed."""


@dataclass(frozen=True)
class HouseTrade:
    member: str
    ticker: str
    transaction_type: str
    amount: str
    transaction_date: date | None
    disclosure_date: date | None
    asset_description: str
    report_url: str = ""

    @property
    def dedupe_id(self) -> str:
        raw = "|".join(
            [
                self.report_url,
                self.ticker,
                self.transaction_type,
                self.amount,
                self.transaction_date.isoformat() if self.transaction_date else "",
            ]
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── helpers ───────────────────────────────────────────────────────────────────


def _parse_date(value: object) -> date | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _col_idx(header: list[str], keywords: tuple[str, ...]) -> int | None:
    for i, cell in enumerate(header):
        for kw in keywords:
            if kw in cell:
                return i
    return None


# ── HTTP ──────────────────────────────────────────────────────────────────────


def _request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    **kwargs: object,
) -> httpx.Response:
    last: Exception | None = None
    for i in range(attempts):
        try:
            resp = client.request(method, url, **kwargs)  # type: ignore[arg-type]
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(0.8 * (2**i))
    raise HouseSourceError(
        f"House request failed after {attempts} attempts: {method} {url}: {last}"
    ) from last


# ── index parsing ──────────────────────────────────────────────────────────────


def _download_year_index(client: httpx.Client, year: int) -> list[dict[str, str]]:
    """Download the annual ZIP and return all filing metadata records."""
    url = _ZIP_URL.format(year=year)
    try:
        resp = _request_with_retry(client, "GET", url, timeout=120.0)
    except HouseSourceError:
        log.warning("House: no ZIP for year %d (may not be published yet)", year)
        return []

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_name = f"{year}FD.xml"
            names = zf.namelist()
            if xml_name not in names:
                matches = [n for n in names if n.lower() == xml_name.lower()]
                if not matches:
                    log.warning("House: %s not in ZIP (got: %s)", xml_name, names)
                    return []
                xml_name = matches[0]
            xml_bytes = zf.read(xml_name)
    except zipfile.BadZipFile as exc:
        raise HouseSourceError(f"House: bad ZIP for year {year}") from exc

    return _parse_fd_xml(xml_bytes)


def _parse_fd_xml(xml_bytes: bytes) -> list[dict[str, str]]:
    """Parse the FD XML index into a list of member filing dicts."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise HouseSourceError(f"House: XML parse error: {exc}") from exc

    return [
        {child.tag: (child.text or "").strip() for child in member}
        for member in root.iter("Member")
    ]


def _filter_ptrs(
    records: list[dict[str, str]],
    since: date,
    until: date,
) -> list[dict[str, str]]:
    """Keep PTR filings (FilingType=P) whose FilingDate falls in [since, until]."""
    out = []
    for rec in records:
        if rec.get("FilingType", "").upper() != _PTR_FILING_TYPE:
            continue
        filing_date = _parse_date(rec.get("FilingDate", ""))
        if filing_date is None or filing_date < since or filing_date > until:
            continue
        out.append(rec)
    return out


# ── PDF parsing ───────────────────────────────────────────────────────────────


def _pdf_has_text(pdf_bytes: bytes) -> bool:
    """Return True if the PDF has a selectable text layer (electronic filing)."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            if page.extract_text():
                return True
    return False


def _render_pdf_pages(pdf_bytes: bytes, dpi: int = 150) -> list[bytes]:
    """Render each PDF page to a PNG bytes object via pypdfium2."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_bytes)
    images = []
    for page in doc:
        scale = dpi / 72
        bitmap = page.render(scale=scale, rotation=0)
        pil_img = bitmap.to_pil()
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        images.append(buf.getvalue())
    return images


def _ocr_pages_with_claude(
    page_images: list[bytes],
    member: str,
    report_url: str,
    disclosure_date: date | None,
) -> list[HouseTrade]:
    """Send scanned PDF pages to Claude vision and parse the returned JSON."""
    import json
    import os

    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HouseSourceError(
            "ANTHROPIC_API_KEY not set — export it in your shell to enable scanned PDF OCR"
        )

    client = anthropic.Anthropic(api_key=api_key)
    trades: list[HouseTrade] = []

    for i, img_bytes in enumerate(page_images):
        import base64

        img_b64 = base64.standard_b64encode(img_bytes).decode()
        try:
            response = client.messages.create(
                model=_OCR_MODEL,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img_b64,
                                },
                            },
                            {"type": "text", "text": _OCR_PROMPT},
                        ],
                    }
                ],
            )
            raw = response.content[0].text.strip()
            # Extract the JSON array robustly — Claude may wrap it in prose or
            # code fences. Use first '[' to last ']' to avoid greedy over-matching
            # on any post-array prose that itself contains brackets.
            start = raw.find("[")
            end = raw.rfind("]")
            if start == -1 or end == -1 or end < start:
                continue
            rows = json.loads(raw[start : end + 1])
            if not isinstance(rows, list):
                continue
            for row in rows:
                ticker = str(row.get("ticker", "")).strip().upper()
                if not ticker or ticker in _SKIP_TICKERS or len(ticker) < _MIN_TICKER_LEN:
                    continue
                amount = str(row.get("amount", "")).strip()
                if not amount:
                    continue
                trades.append(
                    HouseTrade(
                        member=member,
                        ticker=ticker,
                        transaction_type=str(row.get("transaction_type", "")).strip(),
                        amount=amount,
                        transaction_date=_parse_date(row.get("transaction_date")),
                        disclosure_date=disclosure_date,
                        asset_description=str(row.get("asset_description", "")).strip(),
                        report_url=report_url,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("House OCR: page %d of %s failed: %s", i + 1, report_url, exc)

    return trades


def _parse_ptr_pdf(
    pdf_bytes: bytes,
    member: str,
    report_url: str,
    disclosure_date: date | None,
    *,
    use_ocr: bool = True,
) -> list[HouseTrade]:
    """Extract transactions from a PTR PDF.

    Fast path: pdfplumber table extraction for electronic filings.
    Fallback: Claude vision OCR for scanned (no-text-layer) filings, when
    ANTHROPIC_API_KEY is set and use_ocr=True.

    House PTR PDFs use: ID | Owner | Asset | Transaction Type | Date |
    Notification Date | Amount | Cap. Gains > $200?

    The ticker is embedded in the Asset cell as "(AMZN) [ST]".
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise HouseSourceError(
            "pdfplumber not installed — run: uv add pdfplumber"
        ) from exc

    trades: list[HouseTrade] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table or len(table) < 2:
                        continue
                    header = [
                        str(c or "").strip().lower().replace("\n", " ")
                        for c in table[0]
                    ]
                    # All House PTR tables have an "asset" column
                    col_asset = _col_idx(header, ("asset",))
                    col_type = _col_idx(header, ("transaction type", "type"))
                    col_date = _col_idx(header, ("date",))
                    col_amount = _col_idx(header, ("amount",))

                    if col_asset is None or col_amount is None:
                        continue

                    defined_cols = [
                        c
                        for c in (col_asset, col_type, col_date, col_amount)
                        if c is not None
                    ]
                    max_col = max(defined_cols)

                    for row in table[1:]:
                        if len(row) <= max_col:
                            continue
                        asset_raw = str(row[col_asset] or "").strip()
                        m = _TICKER_RE.search(asset_raw)
                        if not m:
                            continue  # non-equity asset or description sub-row
                        ticker = m.group(1)
                        if len(ticker) < _MIN_TICKER_LEN or ticker in _SKIP_TICKERS:
                            continue  # ownership codes like (P), (S), (J)

                        amount = str(row[col_amount] or "").strip()
                        if not amount or amount in {"--", "N/A"}:
                            continue

                        tx_type = (
                            " ".join(str(row[col_type] or "").split())
                            if col_type is not None
                            else ""
                        )
                        tx_date_raw = (
                            str(row[col_date] or "").strip()
                            if col_date is not None
                            else ""
                        )
                        amount = " ".join(amount.split())
                        # First line of asset cell is the human-readable name
                        asset_desc = asset_raw.split("\n")[0].strip()

                        trades.append(
                            HouseTrade(
                                member=member,
                                ticker=ticker,
                                transaction_type=tx_type,
                                amount=amount,
                                transaction_date=_parse_date(tx_date_raw),
                                disclosure_date=disclosure_date,
                                asset_description=asset_desc,
                                report_url=report_url,
                            )
                        )
    except Exception as exc:  # noqa: BLE001
        log.warning("House: PDF parse error %s: %s", report_url, exc)

    if trades:
        return trades

    # ── OCR fallback for scanned filings ──────────────────────────────────────
    if not use_ocr:
        return []
    if _pdf_has_text(pdf_bytes):
        # Had a text layer but no parseable trades — genuine empty filing
        return []

    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.debug("House: scanned PDF skipped (ANTHROPIC_API_KEY not set): %s", report_url)
        return []

    log.info("House: scanned PDF → OCR via Claude: %s", report_url)
    try:
        pages = _render_pdf_pages(pdf_bytes)
        return _ocr_pages_with_claude(pages, member, report_url, disclosure_date)
    except Exception as exc:  # noqa: BLE001
        log.warning("House: OCR failed for %s: %s", report_url, exc)
        return []


# ── public fetch API ──────────────────────────────────────────────────────────


def fetch_house_trades(
    *,
    since: date | None = None,
    until: date | None = None,
    years: list[int] | None = None,
    max_pdfs: int = 500,
    timeout: float = 60.0,
) -> list[HouseTrade]:
    """Fetch House PTR trades for the given date window.

    Downloads annual ZIP archives, filters for PTR filings in the window,
    then fetches and parses each PDF.

    Args:
        since: Earliest filing date. Defaults to last 90 days.
        until: Latest filing date. Defaults to today.
        years: Year list to fetch (derived from since/until if omitted).
        max_pdfs: Hard cap on PDFs downloaded across all years.
        timeout: Per-request timeout in seconds.

    Raises:
        HouseSourceError: On a fatal network failure.  Per-PDF parse failures
            are logged and skipped — fail visibly, not silently.
    """
    since = since or (date.today() - timedelta(days=90))
    until = until or date.today()

    if years is None:
        years = list(range(since.year, until.year + 1))

    client = httpx.Client(
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    )

    all_trades: list[HouseTrade] = []
    pdfs_fetched = skipped_empty = parse_failures = 0

    try:
        for year in years:
            log.info("House: downloading %d annual index…", year)
            records = _download_year_index(client, year)
            ptrs = _filter_ptrs(records, since, until)
            log.info("House: %d PTR filings in window for %d", len(ptrs), year)

            for rec in ptrs:
                if pdfs_fetched >= max_pdfs:
                    log.info("House: max_pdfs=%d reached, stopping", max_pdfs)
                    return all_trades

                doc_id = rec.get("DocID", "").strip()
                if not doc_id:
                    continue

                member = " ".join(
                    p
                    for p in (
                        rec.get("Prefix", ""),
                        rec.get("First", ""),
                        rec.get("Last", ""),
                        rec.get("Suffix", ""),
                    )
                    if p
                ).strip()
                disclosure_date = _parse_date(rec.get("FilingDate", ""))
                pdf_url = _PDF_URL.format(year=year, doc_id=doc_id)

                try:
                    resp = _request_with_retry(client, "GET", pdf_url, timeout=timeout)
                    pdfs_fetched += 1
                    trades = _parse_ptr_pdf(
                        resp.content, member, pdf_url, disclosure_date
                    )
                    if trades:
                        all_trades.extend(trades)
                    else:
                        skipped_empty += 1
                except Exception as exc:  # noqa: BLE001
                    parse_failures += 1
                    log.warning("House: failed %s: %s", pdf_url, exc)

                time.sleep(_POLITE_DELAY)
    finally:
        client.close()

    log.info(
        "House: %d trades from %d PDFs (%d empty/scanned, %d failures)",
        len(all_trades),
        pdfs_fetched,
        skipped_empty,
        parse_failures,
    )
    return all_trades


def backfill_house_trades(
    db_path: Path,
    *,
    start_year: int,
    max_pdfs_per_year: int = 5000,
    timeout: float = 60.0,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Backfill House PTR data year by year from start_year to today.

    Returns the total number of newly stored rows.
    """
    total_new = 0
    current_year = date.today().year
    for year in range(start_year, current_year + 1):
        trades = fetch_house_trades(
            since=date(year, 1, 1),
            until=date(year, 12, 31) if year < current_year else date.today(),
            years=[year],
            max_pdfs=max_pdfs_per_year,
            timeout=timeout,
        )
        new = store_house_trades(trades, db_path)
        total_new += new
        if progress:
            progress(f"{year}: {len(trades)} trades ({new} new)")
    return total_new


# ── persistence ───────────────────────────────────────────────────────────────


def store_house_trades(trades: list[HouseTrade], db_path: Path) -> int:
    """Upsert House trades into congress_trades. Returns count of new rows."""
    from cortex.storage.db import connect

    if not trades:
        return 0
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM congress_trades").fetchone()
        before = int(row[0]) if row else 0
        conn.executemany(
            """
            INSERT INTO congress_trades (
                id, senator, ticker, transaction_type, amount,
                transaction_date, disclosure_date, asset_description,
                report_url, chamber
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'house')
            ON CONFLICT (id) DO NOTHING
            """,
            [
                (
                    t.dedupe_id,
                    t.member,
                    t.ticker,
                    t.transaction_type,
                    t.amount,
                    t.transaction_date,
                    t.disclosure_date,
                    t.asset_description,
                    t.report_url,
                )
                for t in trades
            ],
        )
        row = conn.execute("SELECT COUNT(*) FROM congress_trades").fetchone()
        after = int(row[0]) if row else 0
    return after - before
