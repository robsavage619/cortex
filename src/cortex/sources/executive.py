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
from dataclasses import dataclass
from datetime import date
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


# ── White House transcript ingestion (organic discovery, authoritative) ──────
#
# We pivoted off news co-occurrence (too noisy: "President" matches global news,
# and company names collide with common words). whitehouse.gov category RSS feeds
# carry the FULL text of statements/fact-sheets/releases with exact dates — and
# the speaker is definitionally the administration. We scan that text for
# companies named with a *precise* matcher, then let `price_reaction` confirm
# whether the market actually moved.

# Category feeds with real volume + full-text `content:encoded`. (The /remarks/
# feed exists but the admin tags almost nothing there.)
_WH_FEEDS = (
    "https://www.whitehouse.gov/briefings-statements/feed/",
    "https://www.whitehouse.gov/releases/feed/",
    "https://www.whitehouse.gov/fact-sheets/feed/",
)

# ONLY true trailing legal suffixes are stripped — NOT descriptive words like
# "International"/"Group"/"Industries", which are the distinctive part of names
# like "American International Group" (stripping them left the false-positive
# word "American"). "Dell Technologies" → "Dell" still works.
_SUFFIXES = re.compile(
    r"[\s,]+(inc|incorporated|corp|corporation|company|companies|co|"
    r"technologies|holdings|plc|ltd|limited|n\.?v|s\.?a)\b\.?$",
    re.IGNORECASE,
)

# Single-token company names that collide with everyday words / proper nouns —
# matched only inside a fuller phrase, never alone. Includes offenders observed
# in real White House text (American, Waters→"waters", Edison→Thomas Edison…).
_COMMON_WORDS = frozenset(
    {
        "target", "visa", "gap", "ball", "now", "key", "all", "it", "fast",
        "well", "dish", "host", "apple", "amp", "gen", "ceva", "match", "ally",
        "centene", "loews", "snap", "block", "paramount", "expedia", "american",
        "national", "united", "general", "first", "capital", "state", "live",
        "southern", "waters", "edison", "boston", "public", "global", "allstate",
        "best", "dollar", "tractor", "huntington", "western", "eastern", "union",
        "pool", "dover", "progressive", "mccormick",
    }
)

# Multi-word company names that are also generic English phrases — excluded
# wholesale (e.g. "Waste Management" fires on "nuclear waste management",
# "Expand Energy" on "expand energy").
_SKIP_TICKERS = frozenset({"WM", "EXE"})

_NEGATIVE_CUES = re.compile(
    r"\b(slam|slamm|attack|criticis|blast|threaten|tariff on|probe|sue|sued|ban)\w*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Matcher:
    pattern: re.Pattern[str]
    ticker: str


def _company_matchers(names: dict[str, str]) -> list[_Matcher]:
    """Compile precise company matchers — high precision over recall.

    - Multi-word names match only as the FULL phrase ("American Express", not
      "American") — kills lead-token collisions.
    - Single-word names match alone only if distinctive (len ≥ 4, not in the
      common-word stoplist).
    - We deliberately do NOT match bare ticker symbols: in prose they collide
      with acronyms (ICE = immigration, IP = internet protocol, WM, EXE). The
      cost is missing a few acronym-brands (IBM) — acceptable for precision.
    """
    out: list[_Matcher] = []
    for ticker, raw in names.items():
        if ticker.upper() in _SKIP_TICKERS:
            continue
        cleaned = _SUFFIXES.sub("", raw).strip(" ,.&").strip()
        toks = [t for t in re.split(r"[\s,]+", cleaned) if t]
        if len(toks) >= 2:
            phrase = r"\s+".join(re.escape(t) for t in toks)
            out.append(_Matcher(re.compile(rf"\b{phrase}\b", re.IGNORECASE), ticker))
        elif toks and len(toks[0]) >= 4 and toks[0].lower() not in _COMMON_WORDS:
            out.append(
                _Matcher(
                    re.compile(rf"\b{re.escape(toks[0])}\b", re.IGNORECASE), ticker
                )
            )
    return out


def _strip_html(html_text: str) -> str:
    import html as _html

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _sentence_around(text: str, start: int, end: int) -> str:
    """Return the sentence containing [start, end) as the quote."""
    left = max(text.rfind(". ", 0, start), text.rfind("? ", 0, start)) + 1
    ends = [i for i in (text.find(s, end) for s in (". ", "? ", "! ")) if i != -1]
    right = min(ends) + 1 if ends else min(len(text), end + 160)
    return text[left:right].strip()[:280]


def _parse_feed(xml_text: str) -> list[dict[str, str]]:
    """Parse an RSS feed into [{title, link, date, body}] (full text)."""
    items: list[dict[str, str]] = []
    for raw in re.findall(r"<item>(.*?)</item>", xml_text, re.S):
        title = re.search(r"<title>(.*?)</title>", raw, re.S)
        link = re.search(r"<link>(.*?)</link>", raw, re.S)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.S)
        body = re.search(r"<content:encoded>(.*?)</content:encoded>", raw, re.S)
        iso = ""
        if pub:
            from email.utils import parsedate_to_datetime

            try:
                iso = parsedate_to_datetime(pub.group(1).strip()).date().isoformat()
            except (TypeError, ValueError):
                iso = ""
        items.append(
            {
                "title": _strip_html(title.group(1)) if title else "",
                "link": (link.group(1).strip() if link else ""),
                "date": iso,
                "body": _strip_html(body.group(1)) if body else "",
            }
        )
    return items


def extract_from_document(
    text: str,
    *,
    date_iso: str,
    url: str,
    matchers: list[_Matcher],
    max_companies: int = 8,
) -> list[ExecutiveMention]:
    """Find distinct companies named in one transcript → ExecutiveMentions.

    A document naming more than ``max_companies`` is treated as a list/roundup,
    not a set of deliberate mentions, and skipped.
    """
    try:
        mdate = date.fromisoformat(date_iso)
    except ValueError:
        return []
    hits: dict[str, re.Match[str]] = {}
    for m in matchers:
        found = m.pattern.search(text)
        if found and m.ticker not in hits:
            hits[m.ticker] = found
    if not hits or len(hits) > max_companies:
        return []
    out: list[ExecutiveMention] = []
    for ticker, match in hits.items():
        quote = _sentence_around(text, match.start(), match.end())
        # Drop hits that landed in the site's nav/menu boilerplate, not prose.
        if "Select Category" in quote or "Skip to" in quote:
            continue
        stance = "negative" if _NEGATIVE_CUES.search(quote) else "positive"
        out.append(
            ExecutiveMention(
                ticker=ticker,
                mention_date=mdate,
                speaker="President",
                source_type="whitehouse",
                source_url=url or None,
                quote=quote,
                stance=stance,
            )
        )
    return out


def fetch_whitehouse_feed(url: str) -> list[dict[str, str]]:
    """Fetch + parse one whitehouse.gov category RSS feed. [] on failure."""
    import httpx

    try:
        resp = httpx.get(
            url,
            timeout=30.0,
            headers={"User-Agent": "Mozilla/5.0 (cortex-research)"},
            follow_redirects=True,
        )
        resp.raise_for_status()
        return _parse_feed(resp.text)
    except Exception as exc:  # noqa: BLE001 - degrade visibly, never crash a sync
        log.warning("whitehouse: feed fetch failed (%s) — %s", url, exc)
        return []


def fetch_mentions_whitehouse(db_path: Path) -> int:
    """Discover executive company mentions from whitehouse.gov and store them.

    Scans the full text of recent statements/fact-sheets/releases for S&P 500
    companies named precisely, then upserts. Returns new-row count.
    """
    from cortex.sources.universe import sp500_names

    names = sp500_names()
    if not names:
        log.warning("whitehouse: empty universe name map; skipping fetch")
        return 0
    matchers = _company_matchers(names)
    all_mentions: list[ExecutiveMention] = []
    for feed_url in _WH_FEEDS:
        for item in fetch_whitehouse_feed(feed_url):
            blob = f"{item['title']}. {item['body']}"
            all_mentions.extend(
                extract_from_document(
                    blob,
                    date_iso=item["date"],
                    url=item["link"],
                    matchers=matchers,
                )
            )
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
