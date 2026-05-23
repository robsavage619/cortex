from __future__ import annotations

from dataclasses import dataclass, field

from wst.sources.congress import CongressTrade
from wst.sources.financialdatasets import InsiderTrade, NewsItem


@dataclass(frozen=True)
class Signal:
    ticker: str
    kind: str
    summary: str


@dataclass
class TickerReport:
    """Everything assembled for one watchlist ticker (deterministic, no LLM)."""

    ticker: str
    rationale: str
    added_by: str
    price: float | None = None
    day_change_percent: float | None = None
    congress_trades: list[CongressTrade] = field(default_factory=list)
    insider_trades: list[InsiderTrade] = field(default_factory=list)
    news: list[NewsItem] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)


def _is_buy(transaction_type: str) -> bool:
    t = transaction_type.lower()
    return "purchase" in t or t == "buy"


def build_signals(report: TickerReport) -> list[Signal]:
    """Derive deterministic candidate signals from assembled data.

    These are observations, not recommendations. The LLM layer narrates them;
    the human decides.
    """
    signals: list[Signal] = []
    ticker = report.ticker

    congress_buys = [t for t in report.congress_trades if _is_buy(t.transaction_type)]
    if congress_buys:
        senators = sorted({t.senator for t in congress_buys if t.senator})
        who = ", ".join(senators[:3]) + ("…" if len(senators) > 3 else "")
        signals.append(
            Signal(
                ticker=ticker,
                kind="congress_buy",
                summary=(
                    f"{len(congress_buys)} recent Senate purchase(s)"
                    + (f" by {who}" if who else "")
                ),
            )
        )

    insider_buys = [t for t in report.insider_trades if _is_buy(t.transaction_type)]
    if len(insider_buys) >= 2:
        signals.append(
            Signal(
                ticker=ticker,
                kind="insider_cluster_buy",
                summary=f"Insider cluster buy: {len(insider_buys)} purchases on file",
            )
        )

    negative_news = [n for n in report.news if (n.sentiment or "").lower() == "negative"]
    if negative_news:
        signals.append(
            Signal(
                ticker=ticker,
                kind="news_negative",
                summary=f"{len(negative_news)} recent negative-sentiment headline(s)",
            )
        )

    if report.day_change_percent is not None and abs(report.day_change_percent) >= 5:
        direction = "up" if report.day_change_percent > 0 else "down"
        signals.append(
            Signal(
                ticker=ticker,
                kind="price_move",
                summary=f"Large daily move {direction} {report.day_change_percent:.1f}%",
            )
        )

    return signals
