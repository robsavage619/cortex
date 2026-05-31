"""Congress member name → bioguide ID lookup for official headshot photos.

Data source: github.com/unitedstates/congress-legislators (CC0 public domain)
Photos:      bioguide.congress.gov/bioguide/photo/{L}/{bioguide_id}.jpg

The CSV is fetched once on first use and cached in-process.  Both current and
historical rosters are loaded so trades from retired members still resolve.
"""

from __future__ import annotations

import logging
import re
import threading

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

# Strip honorifics / titles before matching
_TITLE_RE = re.compile(
    r"^(Hon\.?|Dr\.?|Mr\.?|Ms\.?|Mrs\.?|Rep\.?|Sen\.?)\s+", re.I
)
_SUFFIX_RE = re.compile(r",?\s+(Jr\.?|Sr\.?|I{1,3}|IV|V)$", re.I)

_cache: dict[str, str] = {}  # normalized_name → bioguide_id
_cache_lock = threading.Lock()
_loaded = False


# ── normalisation ─────────────────────────────────────────────────────────────


def _norm(name: str) -> str:
    name = _TITLE_RE.sub("", name.strip())
    name = _SUFFIX_RE.sub("", name)
    return " ".join(name.lower().split())


# ── data loading ──────────────────────────────────────────────────────────────


def _load_yaml(url: str) -> None:
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        members = yaml.safe_load(resp.text)
    except Exception as exc:
        log.warning("legislators: failed to fetch %s: %s", url, exc)
        return

    for m in members or []:
        bid = m.get("id", {}).get("bioguide", "")
        if not bid:
            continue
        name = m.get("name", {})
        first = name.get("first", "")
        last = name.get("last", "")
        official = name.get("official_full", "")
        # Index every reasonable name form so fuzzy matching isn't needed
        for n in (official, f"{first} {last}", f"{last}, {first}", f"{last} {first}"):
            key = _norm(n)
            if key:
                _cache.setdefault(key, bid)


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
        log.info("legislators: %d name entries cached", len(_cache))
        _loaded = True


# ── public API ────────────────────────────────────────────────────────────────


def bioguide_id_for(member_name: str) -> str | None:
    """Return the bioguide ID for a member name, or None if not found.

    Tries exact normalised match first, then last-name-only fallback.
    """
    _ensure_loaded()
    key = _norm(member_name)
    if key in _cache:
        return _cache[key]

    # Last-name fallback — less precise but catches "Nancy Pelosi" vs "Pelosi, Nancy"
    parts = key.split()
    if parts:
        last = parts[-1]
        for k, v in _cache.items():
            if k.split()[-1] == last:
                return v
    return None


def photo_url_for(member_name: str) -> str | None:
    """Return the official bioguide headshot URL for a member, or None."""
    bid = bioguide_id_for(member_name)
    if not bid:
        return None
    return f"{_PHOTO_BASE}/{bid[0]}/{bid}.jpg"
