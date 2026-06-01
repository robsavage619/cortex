"""DuckDB snapshot/backup to the persistent volume.

A single DuckDB file is one bad write from total data loss, and Railway volumes
have no built-in point-in-time recovery. This module writes consistent,
engine-portable snapshots via ``EXPORT DATABASE`` (Parquet + schema SQL) into a
timestamped directory beside the live DB, and prunes to the newest ``keep``.

Snapshots live on the same volume as the DB — protection against corruption and
accidental truncation, not against volume loss. For off-box durability, set
``CORTEX_BACKUP_S3_URI`` and the snapshot is also synced there (best-effort).
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

_BACKUP_DIRNAME = "backups"


def backup_root(db_path: Path) -> Path:
    """Directory that holds all snapshots, beside the live DB on the volume."""
    return db_path.parent / _BACKUP_DIRNAME


def list_backups(db_path: Path) -> list[Path]:
    """Existing snapshot directories, oldest first."""
    root = backup_root(db_path)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def run_backup(db_path: Path, *, keep: int = 7) -> Path:
    """Write a consistent snapshot of ``db_path`` and return its directory.

    Uses a fresh read-only connection so it is safe to run while the web process
    holds the DB open.
    """
    from cortex.storage.db import connect

    root = backup_root(db_path)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = root / stamp
    dest.mkdir(parents=True, exist_ok=True)

    with connect(db_path, read_only=True) as conn:
        conn.execute(f"EXPORT DATABASE '{dest.as_posix()}' (FORMAT PARQUET)")

    _maybe_upload_s3(dest, stamp)
    return dest


def prune_backups(db_path: Path, *, keep: int) -> int:
    """Delete all but the newest ``keep`` snapshots. Returns the count removed."""
    snapshots = list_backups(db_path)
    if keep < 0 or len(snapshots) <= keep:
        return 0
    stale = snapshots[: len(snapshots) - keep]
    removed = 0
    for path in stale:
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError as exc:
            log.warning("backup: failed to prune %s — %s", path, exc)
    return removed


def _maybe_upload_s3(snapshot_dir: Path, stamp: str) -> None:
    """Best-effort off-box copy when CORTEX_BACKUP_S3_URI is set (needs awscli)."""
    base = os.environ.get("CORTEX_BACKUP_S3_URI", "").rstrip("/")
    if not base:
        return
    import subprocess

    target = f"{base}/{stamp}"
    try:
        subprocess.run(  # noqa: S603 - fixed argv, env-sourced URI
            ["aws", "s3", "sync", str(snapshot_dir), target],
            check=True,
            capture_output=True,
        )
        log.info("backup: synced snapshot to %s", target)
    except (OSError, subprocess.CalledProcessError) as exc:
        log.warning("backup: S3 sync to %s failed — %s", target, exc)
