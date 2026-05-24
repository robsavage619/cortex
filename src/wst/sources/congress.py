"""Reliable Senate financial-disclosure scraper (efdsearch.senate.gov).

The Senate Electronic Financial Disclosure (eFD) site is a Django + DataTables
app, not a JSON API. Pulling Periodic Transaction Reports (PTRs) requires a
three-step handshake:

1. ``GET /search/`` to obtain a CSRF token + cookie.
2. ``POST /search/home/`` with ``prohibition_agreement=1`` to accept the terms
   gate — this establishes the ``sessionid`` cookie. Skipping it makes every
   subsequent search return empty.
3. ``POST /search/report/data/`` (DataTables endpoint) to page through filings,
   then fetch + parse each report's HTML transaction table.

Filings served as scanned PDFs (``/search/view/paper/...``) are skipped and
counted — they would require OCR. Everything is wrapped in retries with
exponential backoff and polite inter-request delays so a transient blip or a
rate-limit nudge doesn't sink a sync.

This module scrapes; persistence and the API read from a DuckDB mirror so the
live site is hit only by the ``wst congress-sync`` command, never per request.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

_BASE = "https://efdsearch.senate.gov"
_SEARCH_URL = f"{_BASE}/search/"
_HOME_URL = f"{_BASE}/search/home/"
_DATA_URL = f"{_BASE}/search/report/data/"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# DataTables "report_types" code 11 == Periodic Transaction Report.
_PTR_REPORT_TYPE = 11
_PAGE_SIZE = 100
_POLITE_DELAY = 0.4  # seconds between requests to the live site


class CongressSourceError(Exception):
    """Raised when Senate trade data cannot be fetched or parsed."""


@dataclass(frozen=True)
class CongressTrade:
    senator: str
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


# ── date / text helpers ────────────────────────────────────────────────────────

def _parse_date(value: object) -> date | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def recent_window(days: int, today: date | None = None) -> date:
    return (today or date.today()) - timedelta(days=days)


_TAG_RE = re.compile(r"<[^>]+>")
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_HREF_RE = re.compile(r'href="(/search/view/(ptr|paper)/[^"]+)"')
_FILER_SUFFIX_RE = re.compile(r"\s*\((?:Senator|Senate|Candidate|Former Senator)\)\s*$")


def _clean(html: str) -> str:
    text = _TAG_RE.sub("", html)
    text = text.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
    return " ".join(text.split()).strip()


def _clean_filer(filer: str) -> str:
    return _FILER_SUFFIX_RE.sub("", filer).strip()


# ── HTTP with retry ──────────────────────────────────────────────────────────

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
    raise CongressSourceError(
        f"eFD request failed after {attempts} attempts: {method} {url}: {last}"
    ) from last


def _open_efd_session(timeout: float = 30.0) -> httpx.Client:
    """Open a session that has accepted the eFD terms gate."""
    client = httpx.Client(
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    )
    try:
        _accept_agreement(client)
        return client
    except Exception:
        client.close()
        raise


def _accept_agreement(client: httpx.Client) -> None:
    """Run (or re-run) the CSRF + terms-gate handshake on an existing client.

    Idempotent — safe to call again mid-scrape when a session cookie expires.
    """
    landing = _request_with_retry(client, "GET", _SEARCH_URL)
    token = client.cookies.get("csrftoken")
    if not token:
        match = re.search(
            r"name=['\"]csrfmiddlewaretoken['\"] value=['\"]([^'\"]+)",
            landing.text,
        )
        token = match.group(1) if match else None
    if not token:
        raise CongressSourceError("eFD: no CSRF token on landing page")

    _request_with_retry(
        client,
        "POST",
        _HOME_URL,
        data={"csrfmiddlewaretoken": token, "prohibition_agreement": "1"},
        headers={"Referer": _SEARCH_URL},
    )
    if "sessionid" not in client.cookies:
        raise CongressSourceError("eFD: agreement step did not establish a session")


# ── scraping ───────────────────────────────────────────────────────────────────

def _post_report_page(
    client: httpx.Client,
    since: date,
    until: date | None,
    start: int,
    *,
    allow_reauth: bool = True,
) -> dict[str, Any]:
    """POST one DataTables page; transparently re-auth if the session expired.

    A long backfill outlives the eFD session cookie. When that happens the
    endpoint returns the HTML agreement page instead of JSON — we detect the
    non-JSON body, re-accept the terms gate, and retry the same page once.
    """
    token = client.cookies.get("csrftoken") or ""
    resp = _request_with_retry(
        client,
        "POST",
        _DATA_URL,
        data={
            "draw": "1",
            "start": str(start),
            "length": str(_PAGE_SIZE),
            "report_types": f"[{_PTR_REPORT_TYPE}]",
            "filer_types": "[]",
            "submitted_start_date": since.strftime("%m/%d/%Y 00:00:00"),
            "submitted_end_date": (
                until.strftime("%m/%d/%Y 23:59:59") if until else ""
            ),
            "candidate_state": "",
            "senator_state": "",
            "office_id": "",
            "first_name": "",
            "last_name": "",
            "csrfmiddlewaretoken": token,
        },
        headers={"Referer": _SEARCH_URL, "X-Requested-With": "XMLHttpRequest"},
    )
    try:
        return resp.json()
    except ValueError as exc:
        if allow_reauth:
            log.info("eFD: session expired at start=%d; re-authing", start)
            _accept_agreement(client)
            time.sleep(_POLITE_DELAY)
            return _post_report_page(client, since, until, start, allow_reauth=False)
        raise CongressSourceError(
            f"eFD: report/data did not return JSON after re-auth: {exc}"
        ) from exc


def _iter_report_rows(
    client: httpx.Client,
    since: date,
    until: date | None,
    max_reports: int,
) -> list[tuple[str, str, str, str]]:
    """Page the DataTables endpoint, returning (filer, href, filing_date, kind)."""
    rows_out: list[tuple[str, str, str, str]] = []
    start = 0
    while len(rows_out) < max_reports:
        payload = _post_report_page(client, since, until, start)

        rows = payload.get("data", [])
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            if len(row) < 5:
                continue
            match = _HREF_RE.search(str(row[3]))
            if not match:
                continue
            rows_out.append((str(row[2]), match.group(1), str(row[4]), match.group(2)))

        start += _PAGE_SIZE
        total = int(payload.get("recordsTotal", 0) or 0)
        if start >= total:
            break
        time.sleep(_POLITE_DELAY)

    return rows_out[:max_reports]


def _parse_ptr_html(
    html: str,
    filer: str,
    report_url: str,
    disclosure_date: date | None,
) -> list[CongressTrade]:
    """Parse a PTR report's transaction table.

    Columns: #, Transaction Date, Owner, Ticker, Asset Name, Asset Type,
    Type, Amount, Comment.
    """
    trades: list[CongressTrade] = []
    for tr in _TR_RE.findall(html):
        cells = [_clean(c) for c in _TD_RE.findall(tr)]
        if len(cells) < 8:
            continue
        ticker = cells[3].upper()
        if ticker in {"", "--", "N/A", "TICKER"}:
            continue
        trades.append(
            CongressTrade(
                senator=_clean_filer(filer),
                ticker=ticker,
                transaction_type=cells[6],
                amount=cells[7],
                transaction_date=_parse_date(cells[1]),
                disclosure_date=disclosure_date,
                asset_description=cells[4],
                report_url=report_url,
            )
        )
    return trades


def fetch_senate_trades(
    *,
    since: date | None = None,
    until: date | None = None,
    max_reports: int = 250,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> list[CongressTrade]:
    """Scrape Senate Periodic Transaction Reports into CongressTrade rows.

    Args:
        since: Earliest filing date to include. Defaults to the last 90 days.
        until: Latest filing date to include. Defaults to no upper bound. Used to
            slice the archive into windows for a resumable backfill.
        max_reports: Cap on PTR filings to fetch (each is one HTTP request).
        timeout: Per-request timeout in seconds.
        client: Pre-opened session (mainly for testing); otherwise one is created.

    Raises:
        CongressSourceError: on a fatal session/network failure. Per-report parse
            failures are logged and skipped, never fatal — fail visibly, not silently.
    """
    since = since or recent_window(90)
    owns_client = client is None
    client = client or _open_efd_session(timeout=timeout)
    try:
        report_rows = _iter_report_rows(client, since, until, max_reports)
        trades: list[CongressTrade] = []
        skipped_pdf = 0
        parse_failures = 0
        for filer, href, filing_date, kind in report_rows:
            if kind == "paper":
                skipped_pdf += 1
                continue
            try:
                report = _request_with_retry(client, "GET", f"{_BASE}{href}")
                trades.extend(
                    _parse_ptr_html(
                        report.text,
                        filer,
                        f"{_BASE}{href}",
                        _parse_date(filing_date),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - degrade visibly, keep going
                parse_failures += 1
                log.warning("eFD: failed to parse %s: %s", href, exc)
            time.sleep(_POLITE_DELAY)

        log.info(
            "eFD: %d trades from %d PTR filings (skipped %d scanned PDFs, %d failures)",
            len(trades),
            len(report_rows),
            skipped_pdf,
            parse_failures,
        )
        return trades
    finally:
        if owns_client:
            client.close()


def backfill_senate_trades(
    db_path: Path,
    *,
    start_year: int,
    window_days: int = 180,
    max_reports_per_window: int = 3000,
    timeout: float = 30.0,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Backfill the eFD archive in time windows, persisting after each one.

    Walks backwards from today to Jan 1 of ``start_year`` in ``window_days``
    slices, reusing a single session. Each window is fetched and stored
    independently, so a mid-backfill failure only loses the current window —
    re-running resumes cleanly because ``store_trades`` dedupes on conflict.

    Returns the total number of newly stored rows.
    """
    client = _open_efd_session(timeout=timeout)
    total_new = 0
    floor = date(start_year, 1, 1)
    until: date | None = date.today()
    try:
        while until is not None and until >= floor:
            since = max(floor, until - timedelta(days=window_days))
            trades = fetch_senate_trades(
                since=since,
                until=until,
                max_reports=max_reports_per_window,
                client=client,
            )
            new = store_trades(trades, db_path)
            total_new += new
            if progress is not None:
                progress(
                    f"{since:%Y-%m-%d}..{until:%Y-%m-%d}: "
                    f"{len(trades)} trades ({new} new)"
                )
            until = since - timedelta(days=1)
            time.sleep(_POLITE_DELAY)
    finally:
        client.close()
    return total_new


def filter_trades(
    trades: list[CongressTrade],
    tickers: list[str],
    *,
    since: date | None = None,
) -> list[CongressTrade]:
    """Keep trades whose ticker is in the watchlist, optionally within a window."""
    wanted = {t.upper() for t in tickers}
    out: list[CongressTrade] = []
    for trade in trades:
        if trade.ticker not in wanted:
            continue
        if since is not None:
            ref = trade.disclosure_date or trade.transaction_date
            if ref is None or ref < since:
                continue
        out.append(trade)
    out.sort(
        key=lambda t: t.disclosure_date or t.transaction_date or date.min,
        reverse=True,
    )
    return out


# ── persistence (DuckDB mirror) ──────────────────────────────────────────────

def store_trades(trades: list[CongressTrade], db_path: Path) -> int:
    """Upsert trades into congress_trades. Returns the count of new rows."""
    from wst.storage.db import connect

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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'senate')
            ON CONFLICT (id) DO NOTHING
            """,
            [
                (
                    t.dedupe_id,
                    t.senator,
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


def list_trades(
    db_path: Path,
    *,
    ticker: str | None = None,
    since: date | None = None,
    limit: int = 100,
) -> list[CongressTrade]:
    """Read trades from the DuckDB mirror, newest disclosure first."""
    from wst.storage.db import connect

    clauses: list[str] = []
    params: list[object] = []
    if ticker is not None:
        clauses.append("ticker = ?")
        params.append(ticker.upper())
    if since is not None:
        clauses.append("COALESCE(disclosure_date, transaction_date) >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            f"""
            SELECT senator, ticker, transaction_type, amount,
                   transaction_date, disclosure_date, asset_description, report_url
            FROM congress_trades
            {where}
            ORDER BY COALESCE(disclosure_date, transaction_date) DESC NULLS LAST
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [
        CongressTrade(
            senator=r[0],
            ticker=r[1],
            transaction_type=r[2],
            amount=r[3],
            transaction_date=r[4],
            disclosure_date=r[5],
            asset_description=r[6],
            report_url=r[7] or "",
        )
        for r in rows
    ]


# ── aggregate stats (for the Congress dashboard) ──────────────────────────────

_AMOUNT_NUM_RE = re.compile(r"\$?\s*([\d,]+)")


def _amount_midpoint(amount: str | None) -> float:
    """Map a Senate dollar-range string to a midpoint notional (USD)."""
    nums = [
        float(x.replace(",", ""))
        for x in _AMOUNT_NUM_RE.findall(amount or "")
        if x.replace(",", "").isdigit()
    ]
    if not nums:
        return 0.0
    if len(nums) == 1:
        return nums[0]
    return (nums[0] + nums[1]) / 2.0


def _trade_sign(transaction_type: str | None) -> int:
    t = (transaction_type or "").lower()
    if "purchase" in t:
        return 1
    if "sale" in t:
        return -1
    return 0


def congress_stats(db_path: Path, *, days: int = 365) -> dict[str, Any]:
    """Aggregate Senate trades into dashboard-ready summaries.

    Returns totals, a monthly buy/sell flow timeline, the most-traded tickers
    and most-active members (each split by buy/sell notional), and a
    distribution of disclosure lag (transaction → disclosure delay in days).
    Notional uses the midpoint of each filing's dollar-range bracket.
    """
    from collections import defaultdict

    from wst.storage.db import connect

    since = recent_window(days)
    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT senator, ticker, transaction_type, amount,
                   transaction_date, disclosure_date
            FROM congress_trades
            WHERE COALESCE(disclosure_date, transaction_date) >= ?
            """,
            [since],
        ).fetchall()

    buys = sells = 0
    buy_notional = sell_notional = 0.0
    members: set[str] = set()
    months: dict[str, dict[str, float]] = defaultdict(
        lambda: {"buys": 0, "sells": 0, "buy_notional": 0.0, "sell_notional": 0.0}
    )
    by_ticker: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0, "buy_notional": 0.0, "sell_notional": 0.0}
    )
    ticker_buyers: dict[str, set[str]] = defaultdict(set)
    ticker_sellers: dict[str, set[str]] = defaultdict(set)
    ticker_last: dict[str, date] = {}
    by_member: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0, "buy_notional": 0.0, "sell_notional": 0.0}
    )
    lag_buckets = {"<=30": 0, "31-45": 0, "46-90": 0, ">90": 0}
    lags: list[int] = []

    for senator, ticker, ttype, amount, txn, disc in rows:
        sign = _trade_sign(ttype)
        if sign == 0:
            continue
        notional = _amount_midpoint(amount)
        when = disc or txn
        members.add(senator)
        tkey = (ticker or "").upper()
        month = when.strftime("%Y-%m") if when else "unknown"

        if sign > 0:
            buys += 1
            buy_notional += notional
            months[month]["buys"] += 1
            months[month]["buy_notional"] += notional
            by_ticker[tkey]["buy_notional"] += notional
            by_member[senator]["buy_notional"] += notional
            ticker_buyers[tkey].add(senator)
        else:
            sells += 1
            sell_notional += notional
            months[month]["sells"] += 1
            months[month]["sell_notional"] += notional
            by_ticker[tkey]["sell_notional"] += notional
            by_member[senator]["sell_notional"] += notional
            ticker_sellers[tkey].add(senator)
        by_ticker[tkey]["count"] += 1
        by_member[senator]["count"] += 1
        if when is not None and (tkey not in ticker_last or when > ticker_last[tkey]):
            ticker_last[tkey] = when

        if disc and txn:
            lag = (disc - txn).days
            if lag >= 0:
                lags.append(lag)
                if lag <= 30:
                    lag_buckets["<=30"] += 1
                elif lag <= 45:
                    lag_buckets["31-45"] += 1
                elif lag <= 90:
                    lag_buckets["46-90"] += 1
                else:
                    lag_buckets[">90"] += 1

    timeline = [
        {"month": m, **{k: round(v, 2) for k, v in vals.items()}}
        for m, vals in sorted(months.items())
        if m != "unknown"
    ]
    top_tickers = sorted(
        (
            {
                "ticker": t,
                "count": int(v["count"]),
                "buy_notional": round(v["buy_notional"], 2),
                "sell_notional": round(v["sell_notional"], 2),
                "net_notional": round(v["buy_notional"] - v["sell_notional"], 2),
                "buyers": len(ticker_buyers[t]),
                "sellers": len(ticker_sellers[t]),
                "last_disclosure": (
                    ticker_last[t].isoformat() if t in ticker_last else None
                ),
            }
            for t, v in by_ticker.items()
        ),
        key=lambda r: abs(r["net_notional"]),
        reverse=True,
    )[:25]
    top_members = sorted(
        (
            {
                "senator": s,
                "count": int(v["count"]),
                "buy_notional": round(v["buy_notional"], 2),
                "sell_notional": round(v["sell_notional"], 2),
            }
            for s, v in by_member.items()
        ),
        key=lambda r: r["count"],
        reverse=True,
    )[:15]
    median_lag = int(sorted(lags)[len(lags) // 2]) if lags else None

    return {
        "totals": {
            "trades": buys + sells,
            "buys": buys,
            "sells": sells,
            "buy_notional": round(buy_notional, 2),
            "sell_notional": round(sell_notional, 2),
            "members": len(members),
            "tickers": len(by_ticker),
            "median_disclosure_lag_days": median_lag,
        },
        "timeline": timeline,
        "top_tickers": top_tickers,
        "top_members": top_members,
        "disclosure_lag": lag_buckets,
    }
