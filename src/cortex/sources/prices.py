"""Persistent daily price cache (DuckDB) shared by backtests and live screens.

All research price access goes through here so that (a) a backtest re-run
hits zero network and reproduces exactly, (b) live screens top up only the
missing tail instead of re-downloading years of history, and (c) tests can
seed the ``prices`` table directly and run offline.

Prices are split/dividend-adjusted (yfinance ``auto_adjust=True``). Every
dividend re-bases the whole adjusted series, so a tail top-up compares its
overlap against cached rows and re-fetches the full ticker history when they
diverge — the cache self-heals instead of silently mixing adjustment bases.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

FIELDS = ("close", "high", "low", "volume")
_YF_FIELD = {"close": "Close", "high": "High", "low": "Low", "volume": "Volume"}

# Downloading hundreds of tickers in one yf.download builds a wide float64
# frame whose concat peak OOM-kills a small instance; fetch in flat batches.
_FETCH_BATCH = 40
_OVERLAP_DAYS = 10
_ADJUST_TOL = 0.005  # relative close mismatch that triggers a full re-base


def load_closes(
    db_path: Path,
    tickers: list[str],
    start: date,
    *,
    end: date | None = None,
    fetch_missing: bool = True,
    max_staleness_days: int = 5,
) -> Any:
    """Wide DataFrame of adjusted closes (DatetimeIndex × ticker columns)."""
    return load_ohlcv(
        db_path,
        tickers,
        start,
        end=end,
        fetch_missing=fetch_missing,
        max_staleness_days=max_staleness_days,
    )["close"]


def load_ohlcv(
    db_path: Path,
    tickers: list[str],
    start: date,
    *,
    end: date | None = None,
    fetch_missing: bool = True,
    max_staleness_days: int = 5,
) -> dict[str, Any]:
    """Load cached daily bars, fetching whatever the cache is missing first.

    Args:
        db_path: DuckDB file holding the ``prices`` table.
        tickers: Tickers to load (deduplicated, order-preserving).
        start: First calendar date required.
        end: Last calendar date required; None means "through today".
        fetch_missing: When False, serve only what is cached (offline mode).
        max_staleness_days: How far cached coverage may lag ``end`` before a
            tail top-up is fetched. Live screens pass 0; backtests keep the
            default so a re-run minutes later reproduces exactly.

    Returns:
        ``{field: wide DataFrame}`` for close/high/low/volume. Tickers with
        no cached or fetchable data are absent from the columns — callers
        measure and report that gap, mirroring yfinance's silent omission.
    """
    tickers = list(dict.fromkeys(t for t in tickers if t))
    today = date.today()
    end_eff = min(end, today) if end else today
    if not tickers:
        return _empty_frames()
    if fetch_missing:
        _fetch_missing(db_path, tickers, start, end_eff, max_staleness_days)
    return _read_frames(db_path, tickers, start, end_eff)


def store_frames(
    db_path: Path,
    frames: dict[str, Any],
    *,
    cover_start: date,
    cover_end: date,
    source: str = "yfinance",
) -> int:
    """Upsert wide field frames into the cache and extend per-ticker coverage.

    Public so tests can seed synthetic price histories and so alternate
    sources (e.g. Stooq for delisted names) can share the same table.
    Returns the number of rows written.
    """
    import pandas as pd

    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    closes = frames.get("close")
    if closes is None or closes.empty:
        return 0

    stacked = {
        f: frames[f].stack() for f in FIELDS if f in frames and not frames[f].empty
    }
    long = pd.concat(stacked, axis=1).reset_index()
    long.columns = ["date", "ticker", *stacked.keys()]
    for f in FIELDS:
        if f not in long.columns:
            long[f] = float("nan")
    long = long.dropna(subset=["close"])
    if long.empty:
        return 0
    long["date"] = pd.to_datetime(long["date"]).dt.date

    with connect(db_path) as conn:
        apply_schema(conn)
        conn.register("_px_long", long)
        conn.execute(
            "INSERT OR REPLACE INTO prices "
            "(ticker, date, close, high, low, volume, source) "
            "SELECT ticker, date, close, high, low, volume, ? FROM _px_long",
            [source],
        )
        conn.unregister("_px_long")
        covered = sorted(long["ticker"].unique().tolist())
        _upsert_coverage(conn, covered, cover_start, cover_end)
    return int(len(long))


# ── internals ─────────────────────────────────────────────────────────────────


def _empty_frames() -> dict[str, Any]:
    import pandas as pd

    return {f: pd.DataFrame() for f in FIELDS}


def _upsert_coverage(
    conn: Any, tickers: list[str], cover_start: date, cover_end: date
) -> None:
    if not tickers:
        return
    existing = _coverage(conn, tickers)
    rows = []
    for t in tickers:
        old = existing.get(t)
        cs = min(cover_start, old[0]) if old else cover_start
        ce = max(cover_end, old[1]) if old else cover_end
        rows.append((t, cs, ce))
    conn.executemany(
        "INSERT OR REPLACE INTO price_coverage "
        "(ticker, cover_start, cover_end, fetched_at) "
        "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
        rows,
    )


def _coverage(conn: Any, tickers: list[str]) -> dict[str, tuple[date, date]]:
    ph = ",".join("?" for _ in tickers)
    rows = conn.execute(
        f"SELECT ticker, cover_start, cover_end FROM price_coverage "
        f"WHERE ticker IN ({ph})",
        tickers,
    ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def _fetch_missing(
    db_path: Path,
    tickers: list[str],
    start: date,
    end_eff: date,
    max_staleness_days: int,
) -> None:
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    fresh_bar = end_eff - timedelta(days=max(max_staleness_days, 0))
    with connect(db_path) as conn:
        apply_schema(conn)
        cov = _coverage(conn, tickers)

    full = [t for t in tickers if t not in cov or cov[t][0] > start]
    tail = [
        t for t in tickers if t in cov and cov[t][0] <= start and cov[t][1] < fresh_bar
    ]
    if not full and not tail:
        return
    log.info(
        "Price cache: %d full fetches, %d tail top-ups, %d already covered",
        len(full),
        len(tail),
        len(tickers) - len(full) - len(tail),
    )

    if full:
        frames = _download(full, start, end_eff)
        closes = frames["close"]
        # yfinance answers for a dead ticker with an all-NaN COLUMN; a network
        # outage yields no columns at all. `attempted` non-empty therefore
        # means yfinance responded, even if every requested name is dead.
        attempted = set(closes.columns) if not closes.empty else set()
        got = (
            set(closes.columns[closes.notna().any().to_numpy()])
            if not closes.empty
            else set()
        )
        store_frames(db_path, frames, cover_start=start, cover_end=end_eff)
        missing = [t for t in full if t not in got]
        if missing and not attempted:
            # An all-dead request returns an empty frame — indistinguishable
            # from an outage without a probe. One canary download settles it.
            probe = _download(
                ["SPY"], max(start, end_eff - timedelta(days=30)), end_eff
            )
            if not probe["close"].empty:
                attempted = {"SPY"}
        if missing and attempted:
            st = _download_stooq(missing, start, end_eff)
            st_closes = st["close"]
            if not st_closes.empty:
                store_frames(
                    db_path,
                    st,
                    cover_start=start,
                    cover_end=end_eff,
                    source="stooq",
                )
                got |= set(st_closes.columns)
            # Record coverage for names neither source can price (yfinance
            # responded — `attempted` is non-empty) so the next run serves the
            # cache instead of re-attempting hundreds of dead tickers. If a
            # transient outage ever mis-marks live names, clear their rows
            # from price_coverage to force a refetch.
            unpriced = [t for t in missing if t not in got]
            if unpriced:
                log.info(
                    "Price cache: %d names unpriced by any source: %s",
                    len(unpriced),
                    unpriced[:15],
                )
                from cortex.storage.db import connect as _connect

                with _connect(db_path) as conn:
                    _upsert_coverage(conn, unpriced, start, end_eff)

    if tail:
        tail_start = min(cov[t][1] for t in tail) - timedelta(days=_OVERLAP_DAYS)
        frames = _download(tail, tail_start, end_eff)
        rebased = _adjustment_drift(db_path, frames)
        store_frames(db_path, frames, cover_start=tail_start, cover_end=end_eff)
        if rebased:
            log.info(
                "Price cache: re-basing %d tickers after adjustment drift: %s",
                len(rebased),
                rebased[:10],
            )
            _delete(db_path, rebased)
            frames = _download(rebased, start, end_eff)
            store_frames(db_path, frames, cover_start=start, cover_end=end_eff)


# Stooq is the delisted-name fallback (yfinance drops most dead tickers).
# Its daily bars are split-adjusted but dividends are NOT reinvested — a
# disclosed basis mismatch vs yfinance auto_adjust, second-order for
# cross-sectional ranking. Politeness sleep keeps us under their rate limit.
# NOTE (2026-07-16): stooq.com currently fronts a JavaScript proof-of-work
# challenge on this endpoint, so headless fetches return HTML and price 0
# names. The path degrades gracefully; delisted coverage is therefore ~zero
# for now and shows up honestly in the backtest's universe-coverage ratio.
_STOOQ_SLEEP = 0.2


def _download_stooq(tickers: list[str], start: date, end: date) -> dict[str, Any]:
    import io
    import time

    import httpx
    import pandas as pd

    cols: dict[str, dict[str, Any]] = {f: {} for f in FIELDS}
    stooq_col = {"close": "Close", "high": "High", "low": "Low", "volume": "Volume"}
    priced = 0
    with httpx.Client(timeout=15.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for t in tickers:
            url = (
                f"https://stooq.com/q/d/l/?s={t.lower()}.us"
                f"&d1={start:%Y%m%d}&d2={end:%Y%m%d}&i=d"
            )
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                log.debug("Stooq fetch failed for %s: %s", t, exc)
                continue
            if not resp.text.startswith("Date,"):
                continue
            df = pd.read_csv(
                io.StringIO(resp.text), parse_dates=["Date"], index_col="Date"
            )
            if df.empty or "Close" not in df.columns:
                continue
            for f in FIELDS:
                if stooq_col[f] in df.columns:
                    cols[f][t] = df[stooq_col[f]]
            priced += 1
            time.sleep(_STOOQ_SLEEP)
    if priced:
        log.info("Price cache: Stooq fallback priced %d/%d names", priced, len(tickers))
    return {f: (pd.DataFrame(cols[f]) if cols[f] else pd.DataFrame()) for f in FIELDS}


def _download(tickers: list[str], start: date, end: date) -> dict[str, Any]:
    import pandas as pd
    import yfinance as yf

    parts: dict[str, list[Any]] = {f: [] for f in FIELDS}
    for i in range(0, len(tickers), _FETCH_BATCH):
        batch = tickers[i : i + _FETCH_BATCH]
        raw: Any = yf.download(
            batch,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if raw is None or raw.empty:
            continue
        multi = isinstance(raw.columns, pd.MultiIndex)
        for f in FIELDS:
            col = _YF_FIELD[f]
            if multi:
                if col in raw.columns.get_level_values(0):
                    parts[f].append(raw[col])
            elif col in raw.columns:
                parts[f].append(raw[[col]].rename(columns={col: batch[0]}))
    return {
        f: (pd.concat(parts[f], axis=1) if parts[f] else pd.DataFrame()) for f in FIELDS
    }


def _adjustment_drift(db_path: Path, frames: dict[str, Any]) -> list[str]:
    """Tickers whose freshly fetched overlap disagrees with cached closes."""
    import pandas as pd

    from cortex.storage.db import connect

    closes = frames.get("close")
    if closes is None or closes.empty:
        return []
    drifted: list[str] = []
    with connect(db_path) as conn:
        for t in closes.columns:
            s = closes[t].dropna()
            if s.empty:
                continue
            overlap = [d.date() for d in s.index[:_OVERLAP_DAYS]]
            ph = ",".join("?" for _ in overlap)
            rows = conn.execute(
                f"SELECT date, close FROM prices WHERE ticker = ? AND date IN ({ph})",
                [t, *overlap],
            ).fetchall()
            for d, cached in rows:
                new = s.get(pd.Timestamp(d))
                if (
                    new is not None
                    and cached
                    and abs(float(new) / float(cached) - 1.0) > _ADJUST_TOL
                ):
                    drifted.append(t)
                    break
    return drifted


def _delete(db_path: Path, tickers: list[str]) -> None:
    from cortex.storage.db import connect

    ph = ",".join("?" for _ in tickers)
    with connect(db_path) as conn:
        conn.execute(f"DELETE FROM prices WHERE ticker IN ({ph})", tickers)
        conn.execute(f"DELETE FROM price_coverage WHERE ticker IN ({ph})", tickers)


def _read_frames(
    db_path: Path, tickers: list[str], start: date, end_eff: date
) -> dict[str, Any]:
    import pandas as pd

    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    ph = ",".join("?" for _ in tickers)
    with connect(db_path) as conn:
        apply_schema(conn)
        df = conn.execute(
            f"SELECT ticker, date, close, high, low, volume FROM prices "
            f"WHERE date BETWEEN ? AND ? AND ticker IN ({ph})",
            [start, end_eff, *tickers],
        ).df()
    if df.empty:
        return _empty_frames()
    out: dict[str, Any] = {}
    for f in FIELDS:
        wide = df.pivot(index="date", columns="ticker", values=f).sort_index()
        wide.index = pd.to_datetime(wide.index)
        out[f] = wide
    return out
