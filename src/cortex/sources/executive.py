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
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

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


# ── GDELT ingestion (organic discovery from news) ────────────────────────────
#
# News co-occurrence of an administration figure + a company is NOISY — most hits
# are analyst notes, not a presidential mention. We do NOT try to perfectly
# classify here; we cast a focused net and let the price-reaction gate
# (`price_reaction`) be the real filter. A "mention" with no abnormal move after
# it is exactly the noise we want to drop downstream.

_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Administration figures + market-impact framing. Kept tight to raise precision.
_ADMIN = '("Trump" OR "White House" OR "President")'
_GDELT_QUERIES = (
    f'{_ADMIN} (praised OR endorsed OR "talked up" OR touted OR named)',
    f"{_ADMIN} (shares OR stock) (surged OR jumped OR soared OR popped)",
)

# Company names too generic to match safely in a headline; the ticker/name would
# fire on the common English word. The reaction gate can't rescue a wrong ticker.
_AMBIGUOUS_NAMES = frozenset(
    {
        "target",
        "visa",
        "gap",
        "nvr",
        "ball",
        "now",
        "key",
        "all",
        "it",
        "ceva",
        "amp",
        "fast",
        "well",
        "dish",
        "host",
        "loews",
        "apa",
    }
)

# Bearish headline cues → a "talked down" mention (negative stance).
_NEGATIVE_CUES = re.compile(
    r"\b(slam|slamm|attack|criticis|blast|threat|tariff|probe|sue|ban)\w*",
    re.IGNORECASE,
)


def _name_index(names: dict[str, str]) -> list[tuple[re.Pattern[str], str]]:
    """Compile distinctive company-name → ticker matchers (word-boundary, ci).

    Uses the leading distinctive token of each company name (e.g. "ServiceNow",
    "Nvidia", "Dell") plus the ticker itself when the ticker is not a common
    word. Ambiguous names are skipped — the price-reaction gate cannot undo a
    mis-attributed ticker.
    """
    index: list[tuple[re.Pattern[str], str]] = []
    seen: set[str] = set()
    for ticker, name in names.items():
        # Distinctive lead token: strip common corporate suffixes/punctuation.
        lead = re.split(r"[\s,]", name.strip())[0].strip(".")
        for token in {lead, name.strip()}:
            key = token.lower()
            if len(token) < 4 or key in _AMBIGUOUS_NAMES or key in seen:
                continue
            seen.add(key)
            index.append(
                (re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE), ticker)
            )
    return index


def _stance_for(title: str) -> str:
    return "negative" if _NEGATIVE_CUES.search(title) else "positive"


def fetch_gdelt_articles(
    query: str, *, timespan: str = "3m", maxrecords: int = 250
) -> list[dict[str, Any]]:
    """One GDELT DOC 2.0 query. Returns [] on rate-limit/parse failure.

    GDELT throttles hard (≈1 request / 5s); callers MUST space requests.
    """
    import httpx

    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "sort": "datedesc",
        "timespan": timespan,
        "maxrecords": str(maxrecords),
    }
    try:
        resp = httpx.get(_GDELT_URL, params=params, timeout=30.0)
        if resp.status_code != 200 or not resp.text.lstrip().startswith("{"):
            log.warning("GDELT: non-JSON/throttled response for %r", query[:40])
            return []
        return resp.json().get("articles", [])
    except Exception as exc:  # noqa: BLE001 - degrade visibly, never crash a sync
        log.warning("GDELT: query failed — %s", exc)
        return []


def extract_mentions(
    articles: list[dict[str, Any]], names: dict[str, str]
) -> list[ExecutiveMention]:
    """Match universe companies named in article titles → ExecutiveMentions."""
    index = _name_index(names)
    out: list[ExecutiveMention] = []
    for art in articles:
        title = str(art.get("title") or "")
        seen_dt = str(art.get("seendate") or "")
        url = str(art.get("url") or "") or None
        try:
            mdate = datetime.strptime(seen_dt[:8], "%Y%m%d").date()
        except ValueError:
            continue
        hit_tickers: set[str] = set()
        for pattern, ticker in index:
            if pattern.search(title):
                hit_tickers.add(ticker)
        # A title naming many companies is a roundup, not a mention — skip.
        if not hit_tickers or len(hit_tickers) > 2:
            continue
        for ticker in hit_tickers:
            out.append(
                ExecutiveMention(
                    ticker=ticker,
                    mention_date=mdate,
                    speaker="President",
                    source_type="news",
                    source_url=url,
                    quote=title[:280],
                    stance=_stance_for(title),
                )
            )
    return out


def fetch_mentions_gdelt(
    db_path: Path, *, timespan: str = "3m", sleep_s: float = 6.0
) -> int:
    """Discover executive mentions from news via GDELT and store them.

    Runs a small number of focused queries (spaced to respect GDELT's limiter),
    matches universe companies in the headlines, and upserts. Returns new count.
    """
    from cortex.sources.universe import sp500_names

    names = sp500_names()
    if not names:
        log.warning("GDELT: empty universe name map; skipping fetch")
        return 0
    all_mentions: list[ExecutiveMention] = []
    for i, query in enumerate(_GDELT_QUERIES):
        if i > 0:
            time.sleep(sleep_s)  # GDELT: ~1 req / 5s
        articles = fetch_gdelt_articles(query, timespan=timespan)
        all_mentions.extend(extract_mentions(articles, names))
    return store_mentions(all_mentions, db_path)


# ── Price-reaction gate (the quality filter + "bump and trend after") ─────────


def price_reaction(ticker: str, mention_date: date) -> dict[str, Any]:
    """Abnormal return after a mention vs SPY — the bump and the trend after.

    Finds the first trading day on/after ``mention_date`` (day 0) and measures
    the company's return minus SPY's over +1, +5, +20 trading days. Also returns
    the forward close path for a sparkline. This is the honest test of whether a
    mention actually moved the stock; noise shows ~0 abnormal return.
    """
    from cortex.sources.market import MarketSourceError, history_for

    empty: dict[str, Any] = {"ticker": ticker.upper(), "available": False}
    period = "6mo" if (date.today() - mention_date).days < 150 else "1y"
    try:
        bars = history_for(ticker, period=period)
        spy = history_for("SPY", period=period)
    except MarketSourceError as exc:
        log.warning("reaction: price fetch failed for %s — %s", ticker, exc)
        return empty
    if not bars or not spy:
        return empty

    iso = mention_date.isoformat()
    closes = [(b.date[:10], b.close) for b in bars]
    spy_closes = {d: c for d, c in ((b.date[:10], b.close) for b in spy)}

    day0 = next((i for i, (d, _) in enumerate(closes) if d >= iso), None)
    if day0 is None or day0 >= len(closes) - 1:
        return empty

    base = closes[day0][1]
    spy_base = spy_closes.get(closes[day0][0])
    if not base or not spy_base:
        return empty

    def abn(h: int) -> float | None:
        j = day0 + h
        if j >= len(closes):
            return None
        d, c = closes[j]
        spy_c = spy_closes.get(d)
        if not c or not spy_c:
            return None
        return (c / base - 1.0) - (spy_c / spy_base - 1.0)

    path = [c for _, c in closes[day0 : day0 + 21]]
    return {
        "ticker": ticker.upper(),
        "available": True,
        "day0_date": closes[day0][0],
        "abn_1d": abn(1),
        "abn_5d": abn(5),
        "abn_20d": abn(20),
        "forward_path": path,
    }


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
