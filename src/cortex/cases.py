"""Auto-construct an investment case from CORTEX factor scores + vault research.

The system builds the argument *for* the user: rather than authoring a thesis
from a blank form, the user reviews a ready-made bull/bear case synthesised
deterministically from the six-factor breakdown and the indexed research vault.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from cortex.discovery import Candidate, list_candidates

log = logging.getLogger(__name__)

# z-score thresholds for promoting a factor into the bull / risk columns.
_BULL_Z = 0.5
_RISK_Z = -0.5


@dataclass
class CasePoint:
    factor: str
    label: str
    z: float
    stat: str
    argument: str
    citation: str | None
    citation_text: str | None


@dataclass
class InvestmentCase:
    ticker: str
    composite_score: float
    composite_rank: int
    suggested_conviction: int
    trend_ok: bool | None
    headline: str
    summary: str
    bull_points: list[CasePoint]
    risk_points: list[CasePoint]
    falsifier: str


# Per-factor presentation: label, theme phrase, stat formatter, and the prose
# used when the factor reads bullish vs. bearish. Grounded in the same research
# the DISCOVERED engine is built on.
_FACTOR_META: dict[str, dict[str, object]] = {
    "momentum": {
        "label": "Momentum (12-1)",
        "theme": "momentum leader",
        "query": "12-1 month price momentum factor returns Jegadeesh Titman",
        "bull": (
            "Among the strongest price trends in the universe. Persistent winners have "
            "historically continued outperforming over the next 3–12 months."
        ),
        "risk": (
            "Price trend lags the field. Momentum is a headwind here, not a tailwind."
        ),
    },
    "low_vol": {
        "label": "Low Volatility",
        "theme": "low-volatility compounder",
        "query": "low volatility anomaly betting against beta low risk high return",
        "bull": (
            "Unusually calm relative to its return profile. Low-volatility names have "
            "historically outperformed high-flyers on a risk-adjusted basis."
        ),
        "risk": (
            "More volatile than most peers. Expect wider swings and larger drawdowns."
        ),
    },
    "sharpe": {
        "label": "Risk-Adjusted Return",
        "theme": "efficient trender",
        "query": "risk-adjusted return Sharpe ratio trend following time series",
        "bull": (
            "Return per unit of risk near the top of the field. A sustained, "
            "efficient trend — not a lucky one-off spike."
        ),
        "risk": (
            "Weak return-for-risk. What gains exist have come with outsized volatility."
        ),
    },
    "value": {
        "label": "Value (Earnings Yield)",
        "theme": "value play",
        "query": "value factor earnings yield cheap stocks book-to-market EBIT",
        "bull": (
            "Cheap relative to earnings. The value premium rewards buying "
            "profits at a discount — a durable edge in long-run returns."
        ),
        "risk": (
            "Expensive on earnings. You're paying a premium that leaves little "
            "room for disappointment."
        ),
    },
    "quality": {
        "label": "Quality (ROE)",
        "theme": "quality franchise",
        "query": "quality factor profitability ROE gross profitability Piotroski",
        "bull": (
            "A genuinely profitable, high-quality business. High-ROE names compound "
            "capital efficiently and hold up better in drawdowns."
        ),
        "risk": (
            "Profitability trails the field. Business quality is a meaningful concern."
        ),
    },
}


def _pct(v: float | None) -> str:
    return f"{v * 100:.1f}%" if v is not None else "n/a"


def _stat(factor: str, c: Candidate) -> str:
    if factor == "momentum":
        return f"{_pct(c.momentum_12_1)} trailing-year return"
    if factor == "low_vol":
        return f"{_pct(c.vol_252d)} annualised volatility"
    if factor == "sharpe":
        if c.sharpe_12m is None:
            return "n/a"
        return f"{c.sharpe_12m:.2f} return-to-vol ratio"
    if factor == "value":
        return f"{_pct(c.earnings_yield)} earnings yield"
    if factor == "quality":
        return f"{_pct(c.roe)} return on equity"
    return ""


def _z_for(factor: str, c: Candidate) -> float | None:
    return {
        "momentum": c.z_momentum,
        "low_vol": c.z_low_vol,
        "sharpe": c.z_sharpe,
        "value": c.z_value,
        "quality": c.z_quality,
    }[factor]


def _conviction_from_composite(score: float) -> int:
    if score >= 1.0:
        return 5
    if score >= 0.6:
        return 4
    if score >= 0.2:
        return 3
    if score >= -0.2:
        return 2
    return 1


def _headline(ticker: str, bull: list[CasePoint]) -> str:
    if not bull:
        return f"{ticker}: balanced multi-factor screen"
    theme = lambda p: str(_FACTOR_META[p.factor]["theme"])  # noqa: E731
    if len(bull) == 1:
        return f"{ticker}: {theme(bull[0])}"
    return f"{ticker}: {theme(bull[0])} with {theme(bull[1])} support"


def _summary(c: Candidate, bull: list[CasePoint], risk: list[CasePoint]) -> str:
    rank = (
        f"ranks #{c.composite_rank} of the discovered set at {c.composite_score:+.2f}σ"
    )
    if bull:
        names = ", ".join(
            str(_FACTOR_META[p.factor]["label"]).split(" (")[0] for p in bull[:3]
        )
        lead = f"It {rank}, carried by {names}."
    else:
        lead = f"It {rank}, with no single factor standing out."
    if risk:
        weakest = str(_FACTOR_META[risk[0].factor]["label"]).split(" (")[0]
        lead += f" Main soft spot: {weakest}."
    return lead


def _falsifier(c: Candidate, risk: list[CasePoint]) -> str:
    parts: list[str] = []
    if c.above_200d_sma:
        parts.append("Sell discipline: exit if the price loses its 200-day uptrend")
    else:
        parts.append(
            "Caution: it is already below its 200-day average (trend gate failing)"
        )
    if risk:
        weakest = str(_FACTOR_META[risk[0].factor]["theme"])
        parts.append(
            f"watch the {weakest} weakness ({risk[0].z:+.2f}σ) for deterioration"
        )
    parts.append(
        "the case is rebuilt every CORTEX run — it leaves the buy list if the "
        "composite drops below +0.75σ"
    )
    return "; ".join(parts) + "."


def build_case(
    ticker: str,
    *,
    db_path: Path,
    with_research: bool = True,
) -> InvestmentCase | None:
    """Synthesise an investment case for a discovered ticker.

    Returns None if the ticker is not in the latest discovery set.
    """
    tk = ticker.upper()
    candidate = next((c for c in list_candidates(db_path) if c.ticker == tk), None)
    if candidate is None:
        return None

    # Optional vault citation per factor (one snippet each).
    research: dict[str, tuple[str, str] | None] = {}
    if with_research:
        from cortex.rag import retrieve

        for factor, meta in _FACTOR_META.items():
            try:
                hits = retrieve(str(meta["query"]), k=1, db_path=db_path)
            except Exception as exc:  # noqa: BLE001 - degrade visibly
                log.warning("case research retrieve failed for %s: %s", factor, exc)
                hits = []
            if hits:
                clean = hits[0].text
                # strip YAML frontmatter noise from the preview
                if clean.startswith("---"):
                    clean = clean.split("---", 2)[-1]
                clean = " ".join(clean.split())[:240]
                research[factor] = (hits[0].wikilink, clean)
            else:
                research[factor] = None

    bull: list[CasePoint] = []
    risk: list[CasePoint] = []
    for factor, meta in _FACTOR_META.items():
        z = _z_for(factor, candidate)
        if z is None:
            continue
        cite = research.get(factor)
        if z >= _BULL_Z:
            bull.append(
                CasePoint(
                    factor=factor,
                    label=str(meta["label"]),
                    z=z,
                    stat=_stat(factor, candidate),
                    argument=str(meta["bull"]),
                    citation=cite[0] if cite else None,
                    citation_text=cite[1] if cite else None,
                )
            )
        elif z <= _RISK_Z:
            risk.append(
                CasePoint(
                    factor=factor,
                    label=str(meta["label"]),
                    z=z,
                    stat=_stat(factor, candidate),
                    argument=str(meta["risk"]),
                    citation=cite[0] if cite else None,
                    citation_text=cite[1] if cite else None,
                )
            )

    bull.sort(key=lambda p: p.z, reverse=True)
    risk.sort(key=lambda p: p.z)

    return InvestmentCase(
        ticker=tk,
        composite_score=candidate.composite_score,
        composite_rank=candidate.composite_rank,
        suggested_conviction=_conviction_from_composite(candidate.composite_score),
        trend_ok=candidate.above_200d_sma,
        headline=_headline(tk, bull),
        summary=_summary(candidate, bull, risk),
        bull_points=bull,
        risk_points=risk,
        falsifier=_falsifier(candidate, risk),
    )
