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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# A run still flagged ``running`` but with no status update in this long is
# treated as dead (the process was almost certainly OOM-killed), so the API and
# UI recover instead of spinning forever. A full sync takes ~5 min.
STALE_AFTER_SECONDS = 1800

_STEPS = ("congress", "funds", "discover", "volatility")


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


def run_full_sync(db_path: Path, status_path: Path | None = None) -> None:
    """Run congress → funds → discover → volatility, streaming progress to disk.

    Each stage is independently guarded: a failure in one is recorded and the
    next still runs. Designed to be the entrypoint of an isolated subprocess.
    """
    status_path = status_path or default_status_path(db_path)
    state = initial_state()
    write_status(status_path, state)

    def step(name: str, value: str) -> None:
        state["steps"][name] = value
        write_status(status_path, state)

    try:
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
            step(
                "congress",
                f"done — {len(senate) + len(house)} trades ({new_s + new_h} new)",
            )
        except Exception as exc:  # noqa: BLE001 - record and continue
            log.warning("sync: congress failed: %s", exc)
            step("congress", f"failed — {exc}")

        try:
            step("funds", "running")
            from cortex.sources.funds import sync_all_managers

            new_funds = sync_all_managers(db_path)
            step("funds", f"done — {new_funds} new moves")
        except Exception as exc:  # noqa: BLE001 - record and continue
            log.warning("sync: funds failed: %s", exc)
            step("funds", f"failed — {exc}")

        try:
            step("discover", "running")
            from cortex.discovery import run_discovery
            from cortex.thesis import list_theses

            active = list_theses(status="open", db_path=db_path) + list_theses(
                status="pending", db_path=db_path
            )
            force = list({t for thesis in active for t in thesis.tickers})
            candidates = run_discovery(db_path, top_n=30, force_include=force)
            step("discover", f"done — {len(candidates)} candidates")
        except Exception as exc:  # noqa: BLE001 - record visibly
            log.warning("sync: discovery failed: %s", exc)
            step("discover", f"failed — {exc}")
            state["error"] = str(exc)

        try:
            step("volatility", "running")
            from cortex.sources.universe import sp500_tickers
            from cortex.volatility_screen import run_volatility_screen

            vol = run_volatility_screen(db_path, tickers=sp500_tickers())
            step("volatility", f"done — {len(vol)} stocks")
        except Exception as exc:  # noqa: BLE001 - record and continue
            log.warning("sync: volatility failed: %s", exc)
            step("volatility", f"failed — {exc}")

    except Exception as exc:  # noqa: BLE001 - import/db fatal
        log.exception("sync: fatal error: %s", exc)
        state["error"] = str(exc)
        for name, val in state["steps"].items():
            if val in ("queued", "running"):
                state["steps"][name] = f"failed — {exc}"
    finally:
        state["running"] = False
        state["finished_at"] = _now()
        write_status(status_path, state)
