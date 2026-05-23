from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = _PROJECT_ROOT / "data"

DEFAULT_DUCKDB_PATH = DATA_DIR / "duckdb" / "wst.db"
DEFAULT_VAULT_DIR = Path.home() / "Vault" / "savage_vault" / "investing"


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without overwriting existing keys."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    """Runtime configuration loaded from environment / .env only."""

    duckdb_path: Path
    vault_dir: Path

    @property
    def investing_dir(self) -> Path:
        return self.vault_dir

    @property
    def dashboard_path(self) -> Path:
        return self.vault_dir / "dashboard.md"


def load_settings(
    duckdb_path: Path | None = None,
    vault_dir: Path | None = None,
) -> Settings:
    _load_dotenv(Path.cwd() / ".env")

    raw_db = os.environ.get("WST_DUCKDB_PATH", "")
    if raw_db:
        env_db = Path(raw_db)
        if env_db.suffix != ".db":
            raise ValueError(f"WST_DUCKDB_PATH must end in .db, got: {raw_db}")
        resolved_db = env_db
    else:
        resolved_db = duckdb_path or DEFAULT_DUCKDB_PATH

    resolved_vault = vault_dir or Path(
        os.environ.get("WST_VAULT_DIR", DEFAULT_VAULT_DIR)
    )
    return Settings(duckdb_path=resolved_db, vault_dir=resolved_vault)
