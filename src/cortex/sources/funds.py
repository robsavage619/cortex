"""Institutional fund-manager moves from SEC 13F filings (via edgartools).

Every manager with >$100M AUM files a Form 13F-HR quarterly listing its US
equity holdings. By diffing a manager's two most recent 13F-HR filings we
recover their *moves* — new positions, adds, trims, and exits — which is the
"smart money" counterpart to the congressional feed.

Quarterly with a ~45-day disclosure lag (not real-time), but free, authoritative,
and comprehensive. Reads via edgartools; persistence mirrors the congress source
so the API serves a DuckDB table rather than hitting EDGAR per request.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from cortex.config import sec_user_agent

log = logging.getLogger(__name__)

# SEC fair-access requires a descriptive name + contact email User-Agent.
_IDENTITY = sec_user_agent()

# Curated notable managers — all CIKs verified to have ≥2 13F-HR filings.
MANAGERS: dict[str, str] = {
    # original 8
    "ARK Invest · Cathie Wood": "0001697748",
    "Berkshire Hathaway · Buffett": "0001067983",
    "Pershing Square · Ackman": "0001336528",
    "Scion · Michael Burry": "0001649339",
    "Appaloosa · Tepper": "0001656456",
    "Duquesne · Druckenmiller": "0001536411",
    "Bridgewater · Dalio": "0001350694",
    "Renaissance Technologies": "0001037389",
    # expansion — high-conviction long/short equity managers
    "Coatue · Philippe Laffont": "0001135730",
    "Tiger Global · Chase Coleman": "0001167483",
    "D1 Capital · Dan Sundheim": "0001747057",
    "Third Point · Dan Loeb": "0001040273",
    "Lone Pine · Steve Mandel": "0001061165",
    "Viking Global · Andreas Halvorsen": "0001103804",
}


class FundsSourceError(Exception):
    """Raised when 13F data cannot be fetched or parsed."""


@dataclass(frozen=True)
class FundMove:
    manager: str
    manager_cik: str
    ticker: str
    issuer: str
    action: str  # NEW | ADD | TRIM | EXIT
    shares: int
    prev_shares: int
    value: int
    pct_change: float | None
    period: date

    @property
    def dedupe_id(self) -> str:
        raw = f"{self.manager_cik}|{self.ticker}|{self.period.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _set_identity() -> None:
    try:
        import edgar

        edgar.set_identity(_IDENTITY)
    except ImportError as exc:
        raise FundsSourceError("edgartools is not installed") from exc


def _s(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _holdings_by_ticker(infotable: Any) -> dict[str, tuple[int, int, str]]:
    """Aggregate a 13F info table to {ticker: (shares, value, issuer)}.

    Multiple share classes / co-managers for one issuer are summed.
    """
    agg: dict[str, tuple[int, int, str]] = {}
    for _, row in infotable.iterrows():
        ticker = _s(row.get("Ticker")).upper()
        if not ticker or _s(row.get("Type")) != "Shares":
            continue
        try:
            shares = int(float(row.get("SharesPrnAmount") or 0))
            value = int(float(row.get("Value") or 0))
        except (TypeError, ValueError):
            continue
        prev_sh, prev_val, _issuer = agg.get(ticker, (0, 0, _s(row.get("Issuer"))))
        agg[ticker] = (prev_sh + shares, prev_val + value, _s(row.get("Issuer")))
    return agg


def _diff_holdings(
    manager: str,
    cik: str,
    latest: dict[str, tuple[int, int, str]],
    prior: dict[str, tuple[int, int, str]],
    period: date,
) -> list[FundMove]:
    """Compute moves from two consecutive holdings snapshots."""
    moves: list[FundMove] = []
    for ticker, (shares, value, issuer) in latest.items():
        prev_shares = prior.get(ticker, (0, 0, ""))[0]
        if prev_shares == 0:
            action = "NEW"
            pct: float | None = None
        elif shares > prev_shares:
            action = "ADD"
            pct = (shares - prev_shares) / prev_shares
        elif shares < prev_shares:
            action = "TRIM"
            pct = (shares - prev_shares) / prev_shares
        else:
            continue
        moves.append(
            FundMove(
                manager=manager,
                manager_cik=cik,
                ticker=ticker,
                issuer=issuer,
                action=action,
                shares=shares,
                prev_shares=prev_shares,
                value=value,
                pct_change=pct,
                period=period,
            )
        )
    for ticker, (prev_sh, _v, issuer) in prior.items():
        if ticker not in latest:
            moves.append(
                FundMove(
                    manager=manager,
                    manager_cik=cik,
                    ticker=ticker,
                    issuer=issuer,
                    action="EXIT",
                    shares=0,
                    prev_shares=prev_sh,
                    value=0,
                    pct_change=-1.0,
                    period=period,
                )
            )
    return moves


def fetch_manager_moves(manager: str, cik: str) -> list[FundMove]:
    """Diff a manager's two latest 13F-HR filings into a list of moves."""
    _set_identity()
    import edgar

    try:
        filings = edgar.Company(cik).get_filings(form="13F-HR")
    except Exception as exc:  # noqa: BLE001 - surface as a typed source error
        raise FundsSourceError(
            f"13F fetch failed for {manager} ({cik}): {exc}"
        ) from exc

    if filings is None or len(filings) < 2:
        log.warning("funds: %s (%s) has <2 13F-HR filings; skipping", manager, cik)
        return []

    latest_filing: Any = filings[0]
    prior_filing: Any = filings[1]
    try:
        latest = _holdings_by_ticker(latest_filing.obj().infotable)
        prior = _holdings_by_ticker(prior_filing.obj().infotable)
    except Exception as exc:  # noqa: BLE001 - degrade visibly
        raise FundsSourceError(
            f"13F parse failed for {manager} ({cik}): {exc}"
        ) from exc

    period = latest_filing.filing_date
    if isinstance(period, str):
        period = date.fromisoformat(period)

    moves = _diff_holdings(manager, cik, latest, prior, period)
    log.info("funds: %s — %d moves (as of %s)", manager, len(moves), period)
    return moves


def fetch_all_manager_moves(
    manager: str, cik: str, *, from_year: int = 2014
) -> list[FundMove]:
    """Walk all consecutive 13F-HR filing pairs back to from_year.

    Returns moves for every historical quarter, each stamped with the later
    (more recent) filing's filing_date as period. The dedupe hash in FundMove
    ensures re-runs are idempotent.
    """
    _set_identity()
    import edgar

    try:
        filings = edgar.Company(cik).get_filings(form="13F-HR")
    except Exception as exc:  # noqa: BLE001
        raise FundsSourceError(
            f"13F fetch failed for {manager} ({cik}): {exc}"
        ) from exc

    if filings is None or len(filings) < 2:
        log.warning("funds: %s (%s) has <2 13F-HR filings; skipping", manager, cik)
        return []

    n = len(filings)
    all_moves: list[FundMove] = []
    for k in range(n - 1):
        later_filing: Any = filings[k]
        earlier_filing: Any = filings[k + 1]

        period = later_filing.filing_date
        if isinstance(period, str):
            period = date.fromisoformat(period)
        if period.year < from_year:
            break  # filings are newest-first; no need to go further back

        try:
            later_h = _holdings_by_ticker(later_filing.obj().infotable)
            earlier_h = _holdings_by_ticker(earlier_filing.obj().infotable)
        except Exception:  # noqa: BLE001 - log and skip this quarter
            log.warning(
                "funds: %s (%s) parse failed for pair %d/%d (period=%s), skipping",
                manager,
                cik,
                k,
                n - 1,
                period,
            )
            continue

        moves = _diff_holdings(manager, cik, later_h, earlier_h, period)
        log.info(
            "funds: %s — %d moves (period=%s, pair %d/%d)",
            manager,
            len(moves),
            period,
            k + 1,
            n - 1,
        )
        all_moves.extend(moves)

    return all_moves


def sync_all_managers(db_path: Path, *, historical: bool = False) -> int:
    """Fetch + store moves for every curated manager. Returns new-row count.

    When historical=True, walks all filing pairs back to 2014 instead of just
    the latest two.
    """
    total_new = 0
    fetch = fetch_all_manager_moves if historical else fetch_manager_moves
    for manager, cik in MANAGERS.items():
        try:
            moves = fetch(manager, cik)
        except FundsSourceError as exc:
            log.warning("funds: skipping %s: %s", manager, exc)
            continue
        total_new += store_fund_moves(moves, db_path)
    return total_new


# ── persistence ──────────────────────────────────────────────────────────────


def store_fund_moves(moves: list[FundMove], db_path: Path) -> int:
    """Upsert moves into fund_holdings. Returns the count of new rows."""
    from cortex.storage.db import connect

    if not moves:
        return 0
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM fund_holdings").fetchone()
        before = int(row[0]) if row else 0
        conn.executemany(
            """
            INSERT INTO fund_holdings (
                id, manager, manager_cik, ticker, issuer, action,
                shares, prev_shares, value, pct_change, period
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                action = excluded.action,
                shares = excluded.shares,
                prev_shares = excluded.prev_shares,
                value = excluded.value,
                pct_change = excluded.pct_change
            """,
            [
                (
                    m.dedupe_id,
                    m.manager,
                    m.manager_cik,
                    m.ticker,
                    m.issuer,
                    m.action,
                    m.shares,
                    m.prev_shares,
                    m.value,
                    m.pct_change,
                    m.period,
                )
                for m in moves
            ],
        )
        row = conn.execute("SELECT COUNT(*) FROM fund_holdings").fetchone()
        after = int(row[0]) if row else 0
    return after - before


def list_fund_moves(
    db_path: Path,
    *,
    ticker: str | None = None,
    actions: tuple[str, ...] = ("NEW", "ADD"),
    limit: int = 100,
) -> list[FundMove]:
    """Read fund moves from the mirror, biggest dollar value first.

    Defaults to buy-side actions (NEW/ADD) for the "smart money buys" view.
    """
    from cortex.storage.db import connect

    clauses: list[str] = []
    params: list[object] = []
    if ticker is not None:
        clauses.append("ticker = ?")
        params.append(ticker.upper())
    if actions:
        placeholders = ", ".join("?" for _ in actions)
        clauses.append(f"action IN ({placeholders})")
        params.extend(actions)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            f"""
            SELECT manager, manager_cik, ticker, issuer, action,
                   shares, prev_shares, value, pct_change, period
            FROM fund_holdings
            {where}
            ORDER BY period DESC, value DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [
        FundMove(
            manager=r[0],
            manager_cik=r[1],
            ticker=r[2],
            issuer=r[3],
            action=r[4],
            shares=int(r[5]) if r[5] is not None else 0,
            prev_shares=int(r[6]) if r[6] is not None else 0,
            value=int(r[7]) if r[7] is not None else 0,
            pct_change=r[8],
            period=r[9],
        )
        for r in rows
    ]
