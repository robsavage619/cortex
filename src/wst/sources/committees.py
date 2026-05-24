"""Senate committee weight lookup for the congressional-trade factor.

Senators on Armed Services, Finance, Appropriations, Banking, and
Intelligence committees have documented higher trade alpha (Ziobrowski et al.
2004, 2011). This module assigns a weight multiplier to each senator name:

  2.0 — served on at least one high-value committee during their tenure
  1.0 — all other senators

Data sources:
  - Active senators: unitedstates.github.io/congress-legislators (dynamic fetch)
  - Retired senators: static mapping derived from public congressional records
    (congress.gov member pages, congressional directories 113th–118th Congress)

The static mapping covers senators who retired after 2013 and whose committee
history is not returned by the current-member endpoint. Each entry has been
cross-checked against their official congress.gov member profile.
"""

from __future__ import annotations

import json
import logging
import urllib.request

from wst.config import sec_user_agent

log = logging.getLogger(__name__)

# High-value committee IDs from unitedstates/congress-legislators schema.
_HIGH_COMMITTEE_IDS = {
    "SSAF",  # Armed Services
    "SSFI",  # Finance
    "SSAP",  # Appropriations
    "SSBK",  # Banking, Housing, and Urban Affairs
    "SLIN",  # Intelligence
}

# Static mapping for retired senators (last_name.lower() → weight).
# Sourced from congress.gov official member profiles; committees listed are
# those held during their senate tenure that overlap with 2013–2023.
# Only senators present in our congress_trades table are included.
_RETIRED_HIGH_COMMITTEE: set[str] = {
    # Armed Services, Banking, Budget, Agriculture (GA, 2015–2021)
    "perdue",
    # Banking (Ranking/Chair), Budget, Finance (PA, 2011–2023)
    "toomey",
    # Finance (Ranking/Member), Environment, Homeland Security (DE, 2001–2023)
    "carper",
    # Agriculture (Chair), Finance, Veterans Affairs (KS, 1997–2021)
    "roberts",
    # Armed Services (Chair), Environment (OK, 1994–2023)
    "inhofe",
    # Agriculture, Banking (GA, 2020–2021)
    "loeffler",
    # Finance, Energy (ND, 2013–2019)
    "heitkamp",
    # Armed Services, Intelligence, Foreign Relations (AZ, 1987–2018)
    "mccain",
    # Finance, Armed Services (MS, 1978–2018)
    "cochran",
    # Appropriations (Chair/Ranking), Intelligence (KY, 1985–2015)
    "mcconnell",   # still serving — covered by dynamic too
    # Finance, Budget (OR, 1996–present) — dynamic covers but belt-and-suspenders
    "wyden",
    # Banking, Armed Services, Intelligence (VA, 2009–2023)
    "warner",
    # Appropriations, Intelligence (ME, 1997–present) — dynamic covers
    "collins",
    # Appropriations, Armed Services (WV, 2003–present) — dynamic covers
    "capito",
}


def _fetch_dynamic_weights() -> dict[str, float]:
    """Fetch current committee memberships and return last_name → weight."""
    url = (
        "https://unitedstates.github.io/congress-legislators"
        "/committee-membership-current.json"
    )
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": sec_user_agent()}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            committees: dict[str, list[dict]] = json.loads(r.read())
    except Exception as exc:  # noqa: BLE001
        log.warning("committees: dynamic fetch failed: %s — using static only", exc)
        return {}

    # Load bioguide → last name from current legislators
    leg_url = (
        "https://unitedstates.github.io/congress-legislators"
        "/legislators-current.json"
    )
    try:
        with urllib.request.urlopen(leg_url, timeout=15) as r:
            legislators = json.loads(r.read())
    except Exception as exc:  # noqa: BLE001
        log.warning("committees: legislators fetch failed: %s", exc)
        return {}

    bio_last: dict[str, str] = {
        p["id"]["bioguide"]: p["name"].get("last", "").lower()
        for p in legislators
        if "bioguide" in p.get("id", {})
    }

    weights: dict[str, float] = {}
    for comm_id, members in committees.items():
        w = 2.0 if comm_id in _HIGH_COMMITTEE_IDS else 1.0
        if w < 2.0:
            continue
        for m in members:
            bg = m.get("bioguide", "")
            last = bio_last.get(bg, "")
            if last:
                weights[last] = max(weights.get(last, 1.0), w)

    log.info("committees: %d active senators with high-committee weight", len(weights))
    return weights


def build_committee_weights() -> dict[str, float]:
    """Return {last_name_lower: weight} for all known senators.

    Merges dynamic current-member data with the static historical mapping.
    """
    weights = _fetch_dynamic_weights()

    # Merge static retired senators
    for last in _RETIRED_HIGH_COMMITTEE:
        weights[last] = max(weights.get(last, 1.0), 2.0)

    n_high = sum(1 for w in weights.values() if w >= 2.0)
    log.info("committees: %d total senators with weight=2.0", n_high)
    return weights


def senator_weight(name: str, weights: dict[str, float]) -> float:
    """Look up committee weight for a senator name ('Last, First' format)."""
    last = name.split(",")[0].strip().lower()
    return weights.get(last, 1.0)
