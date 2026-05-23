from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VAULT_DIR = Path.home() / "Vault" / "savage_vault" / "wall-street"


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
    """Runtime configuration. API keys come from the environment / .env only."""

    vault_dir: Path
    financialdatasets_api_key: str | None

    @property
    def watchlist_path(self) -> Path:
        return self.vault_dir / "watchlist.yaml"

    @property
    def dashboard_dir(self) -> Path:
        return self.vault_dir / "dashboard"


def load_settings(vault_dir: Path | None = None) -> Settings:
    _load_dotenv(Path.cwd() / ".env")
    resolved = vault_dir or Path(os.environ.get("WST_VAULT_DIR", DEFAULT_VAULT_DIR))
    return Settings(
        vault_dir=resolved,
        financialdatasets_api_key=os.environ.get("FINANCIAL_DATASETS_API_KEY"),
    )
