"""Congress member name → bioguide ID lookup for official headshot photos.

Data source: github.com/unitedstates/congress-legislators (CC0 public domain)
Photos:      bioguide.congress.gov/bioguide/photo/{L}/{bioguide_id}.jpg

Both current and historical rosters are loaded on first use and cached in-process
so trades from retired members still resolve.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

import httpx
import yaml

log = logging.getLogger(__name__)

_CURRENT_URL = (
    "https://raw.githubusercontent.com/unitedstates/congress-legislators"
    "/main/legislators-current.yaml"
)
_HISTORICAL_URL = (
    "https://raw.githubusercontent.com/unitedstates/congress-legislators"
    "/main/legislators-historical.yaml"
)
_PHOTO_BASE = "https://bioguide.congress.gov/bioguide/photo"

_TITLE_RE = re.compile(
    r"^(Hon\.?|Dr\.?|Mr\.?|Ms\.?|Mrs\.?|Rep\.?|Sen\.?)\s+", re.I
)
_SUFFIX_RE = re.compile(r",?\s+(Jr\.?|Sr\.?|I{1,3}|IV|V)$", re.I)

# normalized_name → bioguide_id
_name_to_bid: dict[str, str] = {}
# bioguide_id → full member info dict
_bid_to_info: dict[str, dict[str, Any]] = {}

_cache_lock = threading.Lock()
_loaded = False


# ── normalisation ─────────────────────────────────────────────────────────────


def _norm(name: str) -> str:
    name = _TITLE_RE.sub("", name.strip())
    name = _SUFFIX_RE.sub("", name)
    return " ".join(name.lower().split())


# ── data loading ──────────────────────────────────────────────────────────────


def _load_yaml(url: str, *, retries: int = 3) -> None:
    for attempt in range(1, retries + 1):
        try:
            resp = httpx.get(url, timeout=20, follow_redirects=True)
            resp.raise_for_status()
            members = yaml.safe_load(resp.text)
            break
        except Exception as exc:
            log.warning(
                "legislators: fetch attempt %d/%d for %s failed: %s",
                attempt,
                retries,
                url,
                exc,
            )
            if attempt == retries:
                return
            import time
            time.sleep(2 ** attempt)
    else:
        return

    for m in members or []:
        bid = m.get("id", {}).get("bioguide", "")
        if not bid:
            continue

        name_data = m.get("name", {})
        first = name_data.get("first", "")
        last = name_data.get("last", "")
        official = name_data.get("official_full", "") or f"{first} {last}"

        # Most-recent term for party / state / chamber / district
        terms = m.get("terms", [])
        latest = terms[-1] if terms else {}
        term_type = latest.get("type", "")  # "sen" or "rep"

        info: dict[str, Any] = {
            "bioguide_id": bid,
            "name": official.strip(),
            "first": first,
            "last": last,
            "party": latest.get("party", ""),
            "state": latest.get("state", ""),
            "district": latest.get("district"),
            "chamber": (
                "senate"
                if term_type == "sen"
                else "house"
                if term_type == "rep"
                else ""
            ),
            "photo_url": f"{_PHOTO_BASE}/{bid[0]}/{bid}.jpg",
            "gender": m.get("bio", {}).get("gender", ""),
            "birthday": m.get("bio", {}).get("birthday", ""),
        }

        _bid_to_info.setdefault(bid, info)

        for n in (official, f"{first} {last}", f"{last}, {first}", f"{last} {first}"):
            key = _norm(n)
            if key:
                _name_to_bid.setdefault(key, bid)


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _cache_lock:
        if _loaded:
            return
        log.info("legislators: loading member roster…")
        _load_yaml(_CURRENT_URL)
        _load_yaml(_HISTORICAL_URL)
        log.info(
            "legislators: %d members cached (%d names)",
            len(_bid_to_info),
            len(_name_to_bid),
        )
        _loaded = True


def _prewarm() -> None:
    """Background pre-warm so the first web request doesn't block for 60 s."""
    try:
        _ensure_loaded()
    except Exception as exc:
        log.warning("legislators: pre-warm failed — %s", exc)


# Kick off the pre-warm immediately on import (daemon thread — won't delay shutdown).
threading.Thread(target=_prewarm, daemon=True, name="legislators-prewarm").start()


def _resolve_bid(member_name: str) -> str | None:
    _ensure_loaded()
    key = _norm(member_name)
    if key in _name_to_bid:
        return _name_to_bid[key]
    # Last-name-only fallback
    parts = key.split()
    if parts:
        last = parts[-1]
        for k, v in _name_to_bid.items():
            if k.split()[-1] == last:
                return v
    return None


# ── public API ────────────────────────────────────────────────────────────────


def bioguide_id_for(member_name: str) -> str | None:
    """Return the bioguide ID for a member name, or None if not found."""
    return _resolve_bid(member_name)


def photo_url_for(member_name: str) -> str | None:
    """Return the official bioguide headshot URL for a member, or None."""
    bid = _resolve_bid(member_name)
    if not bid:
        return None
    return f"{_PHOTO_BASE}/{bid[0]}/{bid}.jpg"


def member_info_for(member_name: str) -> dict[str, Any] | None:
    """Return full member metadata dict, or None if not found."""
    bid = _resolve_bid(member_name)
    if not bid:
        return None
    return _bid_to_info.get(bid)
