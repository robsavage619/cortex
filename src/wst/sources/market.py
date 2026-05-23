from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PriceContext:
    ticker: str
    price: float | None
    day_change_percent: float | None
    week_52_high: float | None
    week_52_low: float | None
    market_cap: float | None
    pe_ratio: float | None
    news_headlines: list[str]


class MarketSourceError(Exception):
    """Raised when yfinance data cannot be fetched or parsed."""


def context_for(ticker: str, *, news_limit: int = 5) -> PriceContext:
    """Fetch price snapshot + recent news for ticker via yfinance (free, no key).

    Degrades visibly on failure — never returns stale/silent data.
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        raise MarketSourceError("yfinance is not installed") from exc

    try:
        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info or {}

        price: float | None = _as_float(
            info.get("currentPrice") or info.get("regularMarketPrice")
        )
        prev_close: float | None = _as_float(
            info.get("previousClose") or info.get("regularMarketPreviousClose")
        )
        day_change: float | None = None
        if price is not None and prev_close and prev_close != 0:
            day_change = round((price - prev_close) / prev_close * 100, 2)

        news = yf_ticker.news or []
        headlines = [
            str(item.get("content", {}).get("title", "")).strip()
            if isinstance(item.get("content"), dict)
            else str(item.get("title", "")).strip()
            for item in news[:news_limit]
            if item
        ]
        headlines = [h for h in headlines if h]

        return PriceContext(
            ticker=ticker.upper(),
            price=price,
            day_change_percent=day_change,
            week_52_high=_as_float(info.get("fiftyTwoWeekHigh")),
            week_52_low=_as_float(info.get("fiftyTwoWeekLow")),
            market_cap=_as_float(info.get("marketCap")),
            pe_ratio=_as_float(info.get("trailingPE")),
            news_headlines=headlines,
        )
    except Exception as exc:
        raise MarketSourceError(f"yfinance fetch failed for {ticker}: {exc}") from exc


def _as_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace("$", ""))
        except ValueError:
            return None
    return None
