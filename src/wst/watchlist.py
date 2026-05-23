from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class WatchlistError(Exception):
    """Raised when the watchlist file is missing or malformed."""


@dataclass(frozen=True)
class WatchItem:
    ticker: str
    rationale: str
    added_by: str


def load_watchlist(path: Path) -> list[WatchItem]:
    """Load the shared watchlist YAML.

    Expected shape:
        items:
          - ticker: AAPL
            rationale: "Services margin expansion"
            added_by: rob

    Raises:
        WatchlistError: if the file is missing or any item is malformed.
    """
    if not path.is_file():
        raise WatchlistError(f"Watchlist not found at {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("items")
    if not isinstance(entries, list):
        raise WatchlistError(f"Watchlist {path} must contain a top-level 'items' list")

    items: list[WatchItem] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise WatchlistError(f"Watchlist item #{i} is not a mapping: {entry!r}")
        try:
            ticker = str(entry["ticker"]).strip().upper()
        except KeyError as exc:
            raise WatchlistError(f"Watchlist item #{i} missing 'ticker'") from exc
        if not ticker:
            raise WatchlistError(f"Watchlist item #{i} has an empty ticker")
        items.append(
            WatchItem(
                ticker=ticker,
                rationale=str(entry.get("rationale", "")).strip(),
                added_by=str(entry.get("added_by", "")).strip(),
            )
        )
    return items


def tickers(items: list[WatchItem]) -> list[str]:
    """De-duplicated, order-preserving list of tickers."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item.ticker not in seen:
            seen.add(item.ticker)
            out.append(item.ticker)
    return out
