"""Full data refresh, runnable as an isolated subprocess.

The sync (congress → funds → discover → volatility) is memory-heavy: it pulls
hundreds of tickers through yfinance/pandas. Running it inside the web process
means an OOM there takes down the live site. So the API spawns this as a
separate process (``cortex sync-all``); the OS OOM-killer targets *this*
process and the web server keeps serving.

Progress is streamed to a small JSON file on the same volume as the DuckDB so
the API can report status across the process boundary.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# A run still flagged ``running`` but with no status update in this long is
# treated as dead (the process was almost certainly OOM-killed), so the API and
# UI recover instead of spinning forever. A full sync takes ~5 min.
STALE_AFTER_SECONDS = 1800

_STEPS = ("congress", "funds", "discover", "volatility", "executive")


def default_status_path(db_path: Path) -> Path:
    """Status JSON lives beside the DuckDB file, on the persistent volume."""
    return db_path.parent / "refresh_status.json"


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def initial_state() -> dict[str, Any]:
    return {
        "running": True,
        "started_at": _now(),
        "finished_at": None,
        "error": None,
        "steps": {s: "queued" for s in _STEPS},
    }


def write_status(status_path: Path, state: dict[str, Any]) -> None:
    """Atomically write status JSON (temp file + os.replace) so a concurrent
    reader never sees a half-written file."""
    payload = {**state, "updated_at": _now()}
    status_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(status_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, status_path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_status(status_path: Path) -> dict[str, Any]:
    """Read sync status, returning an idle default if missing/corrupt.

    Applies a staleness guard: a ``running`` run whose ``updated_at`` is older
    than :data:`STALE_AFTER_SECONDS` is reported as failed so callers don't
    spin forever after an OOM kill.
    """
    idle: dict[str, Any] = {
        "running": False,
        "started_at": None,
        "finished_at": None,
        "steps": {},
        "error": None,
    }
    try:
        raw = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return idle
    if not isinstance(raw, dict):
        return idle

    if raw.get("running"):
        updated = raw.get("updated_at")
        age = 0.0
        if isinstance(updated, str):
            try:
                age = (
                    datetime.now(tz=UTC) - datetime.fromisoformat(updated)
                ).total_seconds()
            except ValueError:
                age = 0.0
        if age > STALE_AFTER_SECONDS:
            raw["running"] = False
            raw["finished_at"] = raw.get("finished_at") or _now()
            raw["error"] = (
                "sync process stopped responding (no heartbeat) — "
                "likely killed for memory; press Sync to retry"
            )
    return raw


def record_run(
    db_path: Path, source: str, *, ok: bool, rows_new: int | None, detail: str
) -> None:
    """Persist a per-source sync outcome to the ``sync_runs`` table.

    This is what powers freshness telemetry: a congress-only cron run records a
    fresh congress timestamp without touching funds' last-success time, so the
    UI can show each source's true staleness independently.
    """
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    # Store an explicit naive-UTC timestamp rather than relying on DuckDB's
    # CURRENT_TIMESTAMP default, which records local wall-clock and would make
    # freshness ages wrong by the server's UTC offset.
    ran_at = datetime.now(tz=UTC).replace(tzinfo=None)
    try:
        with connect(db_path) as conn:
            apply_schema(conn)
            conn.execute(
                "INSERT INTO sync_runs (source, ran_at, ok, rows_new, detail) "
                "VALUES (?, ?, ?, ?, ?)",
                [source, ran_at, ok, rows_new, detail[:500]],
            )
    except Exception as exc:  # noqa: BLE001 - telemetry must never break a sync
        log.warning("sync: failed to record run for %s: %s", source, exc)


def read_freshness(db_path: Path) -> list[dict[str, Any]]:
    """Return the latest run per source, newest first, for the freshness UI.

    Each entry: ``{source, last_ok_at, last_run_at, ok, rows_new, detail,
    age_seconds}``. ``last_ok_at`` is the most recent *successful* run, so a
    source that just failed still shows when it was last good.
    """
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    try:
        with connect(db_path, read_only=True) as conn:
            rows = conn.execute(
                """
                WITH latest AS (
                    SELECT source, MAX(ran_at) AS ran_at
                    FROM sync_runs GROUP BY source
                ),
                latest_ok AS (
                    SELECT source, MAX(ran_at) AS ok_at
                    FROM sync_runs WHERE ok GROUP BY source
                )
                SELECT r.source, r.ran_at, r.ok, r.rows_new, r.detail, o.ok_at
                FROM sync_runs r
                JOIN latest l ON l.source = r.source AND l.ran_at = r.ran_at
                LEFT JOIN latest_ok o ON o.source = r.source
                ORDER BY r.ran_at DESC
                """
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - degrade visibly, never 500
        # Table may not exist yet on a fresh DB; create it lazily and return [].
        with contextlib.suppress(Exception), connect(db_path) as conn:
            apply_schema(conn)
        log.warning("freshness: read failed — %s", exc)
        return []

    # record_run stores naive-UTC timestamps; compare in the same frame.
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    out: list[dict[str, Any]] = []
    for source, ran_at, ok, rows_new, detail, ok_at in rows:
        age = (now - ran_at).total_seconds() if ran_at else None
        out.append(
            {
                "source": source,
                "last_run_at": ran_at.isoformat() if ran_at else None,
                "last_ok_at": ok_at.isoformat() if ok_at else None,
                "ok": bool(ok),
                "rows_new": rows_new,
                "detail": detail,
                "age_seconds": age,
            }
        )
    return out


def run_full_sync(
    db_path: Path,
    status_path: Path | None = None,
    only: Iterable[str] | None = None,
) -> None:
    """Run congress → funds → discover → volatility, streaming progress to disk.

    Each stage is independently guarded: a failure in one is recorded and the
    next still runs. Designed to be the entrypoint of an isolated subprocess.

    Args:
        db_path: DuckDB path.
        status_path: Override for the cross-process status file.
        only: If given, run just these steps (subset of :data:`_STEPS`). Lets a
            per-source Railway cron job refresh, e.g., only congress daily while
            funds refreshes weekly.
    """
    status_path = status_path or default_status_path(db_path)
    selected = tuple(s for s in _STEPS if only is None or s in set(only))

    state = initial_state()
    state["steps"] = {s: "queued" for s in selected}
    write_status(status_path, state)

    failures: dict[str, str] = {}

    def step(name: str, value: str) -> None:
        state["steps"][name] = value
        write_status(status_path, state)

    def done(source: str, rows_new: int | None, msg: str) -> None:
        step(source, msg)
        record_run(db_path, source, ok=True, rows_new=rows_new, detail=msg)

    def failed(source: str, exc: Exception) -> None:
        log.warning("sync: %s failed: %s", source, exc)
        detail = str(exc)
        step(source, f"failed — {detail}")
        record_run(db_path, source, ok=False, rows_new=None, detail=detail)
        failures[source] = detail

    try:
        if "congress" in selected:
            try:
                step("congress", "running")
                from cortex.sources.congress import (
                    existing_senate_report_urls,
                    fetch_senate_trades,
                    recent_window,
                    store_trades,
                )
                from cortex.sources.house import (
                    existing_house_report_urls,
                    fetch_house_trades,
                    store_house_trades,
                )

                senate = fetch_senate_trades(
                    since=recent_window(120),
                    max_reports=400,
                    known_report_urls=existing_senate_report_urls(db_path),
                )
                new_s = store_trades(senate, db_path)
                # OCR of scanned filings is memory-heavy — skip on the server.
                # Incremental skip means each sync only touches new disclosures.
                house = fetch_house_trades(
                    since=recent_window(120),
                    max_pdfs=200,
                    use_ocr=False,
                    known_report_urls=existing_house_report_urls(db_path),
                )
                new_h = store_house_trades(house, db_path)
                done(
                    "congress",
                    new_s + new_h,
                    f"done — {len(senate) + len(house)} trades "
                    f"({new_s + new_h} new)",
                )
            except Exception as exc:  # noqa: BLE001 - record and continue
                failed("congress", exc)

        if "funds" in selected:
            try:
                step("funds", "running")
                from cortex.sources.funds import sync_all_managers

                new_funds = sync_all_managers(db_path)
                done("funds", new_funds, f"done — {new_funds} new moves")
            except Exception as exc:  # noqa: BLE001 - record and continue
                failed("funds", exc)

        if "discover" in selected:
            try:
                step("discover", "running")
                from cortex.discovery import run_discovery
                from cortex.thesis import list_theses

                active = list_theses(status="open", db_path=db_path) + list_theses(
                    status="pending", db_path=db_path
                )
                force = list({t for thesis in active for t in thesis.tickers})
                candidates = run_discovery(db_path, top_n=30, force_include=force)
                done(
                    "discover",
                    len(candidates),
                    f"done — {len(candidates)} candidates",
                )
            except Exception as exc:  # noqa: BLE001 - record visibly
                failed("discover", exc)
                state["error"] = str(exc)

        if "volatility" in selected:
            try:
                step("volatility", "running")
                from cortex.sources.universe import sp500_tickers
                from cortex.volatility_screen import run_volatility_screen

                vol = run_volatility_screen(db_path, tickers=sp500_tickers())
                done("volatility", len(vol), f"done — {len(vol)} stocks")
            except Exception as exc:  # noqa: BLE001 - record and continue
                failed("volatility", exc)

        if "executive" in selected:
            try:
                step("executive", "running")
                from cortex.sources.executive import fetch_mentions_whitehouse

                new_mentions = fetch_mentions_whitehouse(db_path)
                done(
                    "executive",
                    new_mentions,
                    f"done — {new_mentions} new White House mentions",
                )
            except Exception as exc:  # noqa: BLE001 - record and continue
                failed("executive", exc)

    except Exception as exc:  # noqa: BLE001 - import/db fatal
        log.exception("sync: fatal error: %s", exc)
        state["error"] = str(exc)
        for name, val in state["steps"].items():
            if val in ("queued", "running"):
                state["steps"][name] = f"failed — {exc}"
                failures[name] = str(exc)
    finally:
        state["running"] = False
        state["finished_at"] = _now()
        write_status(status_path, state)
        if failures:
            from cortex.alerts import alert_sync_failure

            alert_sync_failure(failures)
