"""Point-in-time fundamentals from SEC EDGAR XBRL facts (via edgartools).

Every reported fact in EDGAR carries a ``filing_date`` — the moment it became
public — which makes value & quality factors honestly backtestable for free.
We pull annual (fiscal-year) diluted EPS, net income, and stockholders' equity,
keeping the **earliest** filing per fiscal period (the value actually known
then, not later restated comparatives), and mirror them into DuckDB.

The backtest reads this table and gates each fact on ``filing_date <= as_of``:
- earnings yield = annual diluted EPS / point-in-time price
- ROE = annual net income / annual stockholders' equity
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from cortex.config import sec_user_agent

log = logging.getLogger(__name__)

_IDENTITY = sec_user_agent()

_EPS_TAG = "us-gaap:EarningsPerShareDiluted"
_NI_TAG = "us-gaap:NetIncomeLoss"
_EQ_TAGS = (
    "us-gaap:StockholdersEquity",
    "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
)


class FundamentalsSourceError(Exception):
    """Raised when EDGAR fundamentals cannot be fetched or parsed."""


@dataclass(frozen=True)
class FundamentalPoint:
    ticker: str
    period_end: date
    filing_date: date  # earliest disclosure of this fiscal period
    eps_diluted: float | None
    net_income: float | None
    equity: float | None


def _set_identity() -> None:
    try:
        import edgar

        edgar.set_identity(_IDENTITY)
    except ImportError as exc:
        raise FundamentalsSourceError("edgartools is not installed") from exc


def _earliest_by_period(
    facts: list[Any],
    concepts: tuple[str, ...],
) -> dict[date, tuple[date, float]]:
    """Map period_end → (earliest filing_date, value) for the given concept(s).

    Keeps the first filing of each fiscal period — the point-in-time value,
    not a later 10-K's restated comparative.
    """
    out: dict[date, tuple[date, float]] = {}
    for f in facts:
        if f.concept not in concepts or f.fiscal_period != "FY":
            continue
        if f.numeric_value is None or f.period_end is None or f.filing_date is None:
            continue
        pe = f.period_end
        fd = f.filing_date
        existing = out.get(pe)
        if existing is None or fd < existing[0]:
            out[pe] = (fd, float(f.numeric_value))
    return out


def fetch_fundamentals(ticker: str) -> list[FundamentalPoint]:
    """Pull point-in-time annual fundamentals for one ticker from EDGAR."""
    _set_identity()
    import edgar

    try:
        entity_facts = edgar.Company(ticker).get_facts()
        facts = entity_facts.get_all_facts() if entity_facts is not None else []
    except Exception as exc:  # noqa: BLE001 - typed source error
        raise FundamentalsSourceError(
            f"EDGAR facts failed for {ticker}: {exc}"
        ) from exc
    if not facts:
        return []

    eps = _earliest_by_period(facts, (_EPS_TAG,))
    ni = _earliest_by_period(facts, (_NI_TAG,))
    eq = _earliest_by_period(facts, _EQ_TAGS)

    periods = set(eps) | set(ni) | set(eq)
    points: list[FundamentalPoint] = []
    for pe in sorted(periods):
        fds = [d[0] for d in (eps.get(pe), ni.get(pe), eq.get(pe)) if d]
        if not fds:
            continue
        points.append(
            FundamentalPoint(
                ticker=ticker.upper(),
                period_end=pe,
                filing_date=min(fds),
                eps_diluted=eps[pe][1] if pe in eps else None,
                net_income=ni[pe][1] if pe in ni else None,
                equity=eq[pe][1] if pe in eq else None,
            )
        )
    return points


def sync_universe_fundamentals(
    db_path: Path,
    *,
    tickers: list[str] | None = None,
    progress: bool = True,
) -> int:
    """Fetch + store annual fundamentals for the whole universe. New-row count."""
    from cortex.sources.universe import sp500_tickers

    universe = tickers or sp500_tickers()
    total_new = 0
    for i, ticker in enumerate(universe):
        if progress and i % 25 == 0:
            log.info("fundamentals %d/%d", i, len(universe))
        try:
            points = fetch_fundamentals(ticker)
        except FundamentalsSourceError as exc:
            log.warning("fundamentals: skipping %s: %s", ticker, exc)
            continue
        total_new += store_fundamentals(points, db_path)
    return total_new


# ── persistence ──────────────────────────────────────────────────────────────

def store_fundamentals(points: list[FundamentalPoint], db_path: Path) -> int:
    from cortex.storage.db import connect

    if not points:
        return 0
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM fundamentals").fetchone()
        before = int(row[0]) if row else 0
        conn.executemany(
            """
            INSERT INTO fundamentals (
                ticker, period_end, filing_date, eps_diluted, net_income, equity
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (ticker, period_end) DO UPDATE SET
                filing_date = LEAST(fundamentals.filing_date, excluded.filing_date),
                eps_diluted = COALESCE(excluded.eps_diluted, fundamentals.eps_diluted),
                net_income = COALESCE(excluded.net_income, fundamentals.net_income),
                equity = COALESCE(excluded.equity, fundamentals.equity)
            """,
            [
                (
                    p.ticker,
                    p.period_end,
                    p.filing_date,
                    p.eps_diluted,
                    p.net_income,
                    p.equity,
                )
                for p in points
            ],
        )
        row = conn.execute("SELECT COUNT(*) FROM fundamentals").fetchone()
        after = int(row[0]) if row else 0
    return after - before


def list_fundamentals(db_path: Path) -> list[FundamentalPoint]:
    """All stored fundamental points, oldest filing first."""
    from cortex.storage.db import connect

    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT ticker, period_end, filing_date, eps_diluted, net_income, equity
            FROM fundamentals
            ORDER BY filing_date
            """
        ).fetchall()
    return [
        FundamentalPoint(
            ticker=r[0],
            period_end=r[1],
            filing_date=r[2],
            eps_diluted=r[3],
            net_income=r[4],
            equity=r[5],
        )
        for r in rows
    ]
