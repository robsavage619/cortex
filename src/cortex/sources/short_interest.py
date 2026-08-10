"""FINRA Reg SHO daily short-volume files.

FINRA publishes one consolidated file per trading session listing, for every
symbol, the share volume executed short against total volume:

    https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt
    Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market

Free, no authentication, published for the prior session.

Why *flow* and not short interest: Boehmer, Jones & Zhang (2008) find daily
short *flow* drives out the fortnightly short-*interest* level in 13 of 15
reversed sorts. Reg SHO is flow, which is the measure that carried their result.

Their informative subgroup — institutional non-program shorting — is not
separable in public data, which lacks account type. It is also about 58% of
volume, so the consolidated series retains roughly 81% of the effect's
magnitude. See ``cortex-2026-08-10-prereg-short-interest`` in the vault for the
pre-registered hypothesis and the three recorded reasons to expect a null.

Coverage is tracked per session date because a day FINRA never published (a
market holiday, or a file that never appeared) and a day we never fetched are
otherwise indistinguishable — and that difference decides whether a gap in a
ticker's series is real or an artefact.

**The archive is rolling, roughly eight years.** Probed 2026-08-10: sessions
from about 2018-08 onward return 200; 2018-07-02 and earlier return 403. So
this factor cannot reach CORTEX's 2017 backtest start, and its coverage is zero
for the first ~19 months of every run. That is a property of the source, not a
bug — but it means the short factor is measured on a shorter and later sample
than every other factor, which matters when comparing t-stats.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{ymd}.txt"
_HEADER = "Date|Symbol|ShortVolume"
_TIMEOUT = 30.0


class ShortInterestError(RuntimeError):
    """Raised only on a fatal network condition, never on a missing session."""


def _parse(text: str, wanted: set[str] | None) -> list[tuple[str, date, int, int]]:
    """Parse one daily file into (ticker, date, short_volume, total_volume)."""
    out: list[tuple[str, date, int, int]] = []
    for line in text.splitlines():
        if not line or line.startswith(_HEADER) or line.startswith("Date|"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        ymd, symbol, short_v, _exempt, total_v = parts[:5]
        symbol = symbol.strip().upper()
        if not symbol or (wanted is not None and symbol not in wanted):
            continue
        try:
            when = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
            short_i = int(short_v)
            total_i = int(total_v)
        except (ValueError, IndexError):
            continue
        # A zero-volume row carries no information and would make sfrac 0/0.
        if total_i <= 0:
            continue
        out.append((symbol, when, short_i, total_i))
    return out


def fetch_session(
    session: date,
    *,
    wanted: set[str] | None = None,
    client: httpx.Client | None = None,
) -> list[tuple[str, date, int, int]] | None:
    """Fetch one session's file.

    Returns None when FINRA published nothing for that date — a weekend, a
    market holiday, or a session older than the rolling archive. That is
    distinct from an empty list, which would mean the file existed and held no
    usable rows.

    The CDN answers **403**, not 404, for a file it is not serving; a Sunday
    and a 2017 session are indistinguishable at the HTTP layer. Treating 403 as
    a hard error made the whole backfill abort on its first weekend.
    """
    owns = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    url = _URL.format(ymd=session.strftime("%Y%m%d"))
    try:
        resp = client.get(url)
        if resp.status_code in (403, 404):
            return None
        resp.raise_for_status()
        return _parse(resp.text, wanted)
    except httpx.HTTPError as exc:
        raise ShortInterestError(f"FINRA fetch failed for {session}: {exc}") from exc
    finally:
        if owns:
            client.close()


def _covered(db_path: Path, sessions: list[date]) -> set[date]:
    from cortex.storage.db import connect

    if not sessions:
        return set()
    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                "SELECT date FROM short_volume_coverage WHERE date IN "
                f"({','.join('?' for _ in sessions)})",
                sessions,
            ).fetchall()
    except Exception:  # noqa: BLE001 - pre-v20 DB has no coverage table
        return set()
    return {r[0] for r in rows}


def sync_short_volume(
    db_path: Path,
    *,
    start: date,
    end: date | None = None,
    tickers: list[str] | None = None,
    progress: object = None,
) -> int:
    """Fetch and store every uncovered session between start and end.

    Already-covered sessions are skipped, so a re-run only touches new days.
    Returns the number of rows stored.
    """
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    end = end or date.today()
    wanted = {t.upper() for t in tickers} if tickers else None

    with connect(db_path) as conn:
        apply_schema(conn)

    sessions = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:  # FINRA publishes on trading days only
            sessions.append(cur)
        cur += timedelta(days=1)

    covered = _covered(db_path, sessions)
    todo = [s for s in sessions if s not in covered]
    if not todo:
        log.info("short_volume: all %d sessions already covered", len(sessions))
        return 0

    log.info("short_volume: fetching %d of %d sessions", len(todo), len(sessions))
    stored = 0
    no_file = 0
    with connect(db_path) as conn:
        apply_schema(conn)
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            for session in todo:
                rows = fetch_session(session, wanted=wanted, client=client)
                if rows is None:
                    # Holiday or unpublished — record the probe so the next run
                    # does not retry it forever.
                    no_file += 1
                    conn.execute(
                        "INSERT OR REPLACE INTO short_volume_coverage (date, rows) "
                        "VALUES (?, 0)",
                        [session],
                    )
                    continue
                if rows:
                    conn.executemany(
                        "INSERT OR REPLACE INTO short_volume "
                        "(ticker, date, short_volume, total_volume) "
                        "VALUES (?, ?, ?, ?)",
                        rows,
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO short_volume_coverage (date, rows) "
                    "VALUES (?, ?)",
                    [session, len(rows)],
                )
                stored += len(rows)
                if callable(progress):
                    progress(f"{session}: {len(rows)} rows")

    if no_file:
        log.info("short_volume: %d sessions had no published file", no_file)
    log.info("short_volume: stored %d rows over %d sessions", stored, len(todo))
    return stored
