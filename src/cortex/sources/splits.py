"""Persistent stock-split history, used to reconcile EPS with adjusted prices.

The price cache stores yfinance ``auto_adjust=True`` closes, which are re-based
retroactively by every split. EDGAR reports ``EarningsPerShareDiluted`` on the
share count in force at the time of the filing. Dividing one by the other gives
an earnings yield inflated by the cumulative split factor since that filing —
BKNG showed an implied P/E of 1.3 that way.

:func:`split_factor_since` returns that cumulative factor so EPS can be restated
onto the same per-share basis the adjusted price series uses.

Coverage is tracked per ticker (not per row) because "no splits ever" and "never
fetched" are indistinguishable in the ``splits`` table alone, and the difference
decides whether a lookup is trustworthy or silently wrong.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

_FETCH_BATCH = 40


def load_splits(
    db_path: Path,
    tickers: list[str],
    *,
    fetch_missing: bool = True,
) -> dict[str, list[tuple[date, float]]]:
    """Split events per ticker, oldest first, fetching any uncovered names."""
    wanted = sorted({t.upper() for t in tickers if t})
    if not wanted:
        return {}

    if fetch_missing:
        missing = [t for t in wanted if t not in _covered(db_path, wanted)]
        if missing:
            _fetch(db_path, missing)

    return _read(db_path, wanted)


def split_factor_since(
    events: list[tuple[date, float]], since: date, as_of: date
) -> float:
    """Cumulative split ratio applied strictly after ``since``, through ``as_of``.

    A 20:1 split returns 20.0, meaning one pre-split share became 20 shares, so
    as-reported per-share figures from before it must be divided by 20 to sit on
    the current basis.
    """
    factor = 1.0
    for dt, ratio in events:
        if since < dt <= as_of and ratio > 0:
            factor *= ratio
    return factor


def store_splits(db_path: Path, events: dict[str, list[tuple[date, float]]]) -> int:
    """Persist split events and mark every supplied ticker as covered.

    Tickers with an empty list are still recorded as covered — that is the
    "confirmed no splits" case, and omitting it would re-fetch them forever.
    """
    from cortex.storage.db import connect

    rows = [
        (ticker, dt, float(ratio))
        for ticker, evs in events.items()
        for dt, ratio in evs
        if ratio and ratio > 0
    ]
    with connect(db_path) as conn:
        if rows:
            conn.executemany(
                "INSERT INTO splits (ticker, date, ratio) VALUES (?, ?, ?) "
                "ON CONFLICT (ticker, date) DO NOTHING",
                rows,
            )
        conn.executemany(
            # DuckDB resolves a bare CURRENT_TIMESTAMP here as a column name.
            "INSERT INTO split_coverage (ticker) VALUES (?) "
            "ON CONFLICT (ticker) DO UPDATE SET fetched_at = now()",
            [(t,) for t in events],
        )
    return len(rows)


def _covered(db_path: Path, tickers: list[str]) -> set[str]:
    from cortex.storage.db import connect

    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                "SELECT ticker FROM split_coverage WHERE ticker IN "
                f"({','.join('?' * len(tickers))})",
                tickers,
            ).fetchall()
    except Exception:  # noqa: BLE001 - table may not exist yet
        return set()
    return {r[0] for r in rows}


def _read(db_path: Path, tickers: list[str]) -> dict[str, list[tuple[date, float]]]:
    from cortex.storage.db import connect

    out: dict[str, list[tuple[date, float]]] = {t: [] for t in tickers}
    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                "SELECT ticker, date, ratio FROM splits WHERE ticker IN "
                f"({','.join('?' * len(tickers))}) ORDER BY ticker, date",
                tickers,
            ).fetchall()
    except Exception:  # noqa: BLE001 - table may not exist yet
        return out
    for ticker, dt, ratio in rows:
        out.setdefault(ticker, []).append((dt, float(ratio)))
    return out


def _fetch(db_path: Path, tickers: list[str]) -> None:
    """Pull split history from yfinance in batches and cache it."""
    import yfinance as yf

    for i in range(0, len(tickers), _FETCH_BATCH):
        batch = tickers[i : i + _FETCH_BATCH]
        events: dict[str, list[tuple[date, float]]] = {}
        try:
            tk = yf.Tickers(" ".join(batch))
        except Exception:  # noqa: BLE001 - network/parse failure, surfaced below
            log.warning("Split fetch failed for batch %s", batch[:5], exc_info=True)
            continue
        for ticker in batch:
            try:
                series = tk.tickers[ticker].splits
            except Exception:  # noqa: BLE001 - per-ticker failure must not abort
                log.warning("Split fetch failed for %s", ticker, exc_info=True)
                continue
            evs: list[tuple[date, float]] = []
            if series is not None and len(series) > 0:
                for idx, ratio in series.items():
                    evs.append((date.fromisoformat(str(idx)[:10]), float(ratio)))
            events[ticker] = evs
        if events:
            stored = store_splits(db_path, events)
            log.info("Splits: cached %d events across %d tickers", stored, len(events))


def uncovered(db_path: Path, tickers: list[str]) -> list[str]:
    """Tickers with no split-coverage record — their EPS cannot be trusted."""
    wanted = sorted({t.upper() for t in tickers if t})
    covered = _covered(db_path, wanted)
    return [t for t in wanted if t not in covered]
