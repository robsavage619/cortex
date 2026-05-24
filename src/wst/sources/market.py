from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

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
    news_urls: list[str]
    company_name: str | None = None
    website: str | None = None


@dataclass
class PriceBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketSourceError(Exception):
    """Raised when yfinance data cannot be fetched or parsed."""


_VALID_PERIODS = frozenset(
    {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd", "max"}
)

# yfinance interval to use per period. Intraday periods need finer resolution.
_PERIOD_INTERVAL: dict[str, str] = {
    "1d": "5m",
    "5d": "1h",
}


def history_for(ticker: str, *, period: str = "6mo") -> list[PriceBar]:
    """Fetch OHLC history for ticker via yfinance (free, no key).

    Args:
        ticker: Symbol to fetch.
        period: yfinance period window (e.g. ``1d``, ``5d``, ``6mo``, ``1y``).

    Returns:
        Price bars oldest first. Intraday periods (1d, 5d) return sub-daily
        bars; the ``date`` field is ``YYYY-MM-DD HH:MM`` for those.

    Raises:
        MarketSourceError: On an invalid period or a fetch/parse failure.
    """
    if period not in _VALID_PERIODS:
        raise MarketSourceError(
            f"Invalid period {period!r}; expected one of {sorted(_VALID_PERIODS)}"
        )

    try:
        import yfinance as yf
    except ImportError as exc:
        raise MarketSourceError("yfinance is not installed") from exc

    interval = _PERIOD_INTERVAL.get(period, "1d")
    intraday = interval != "1d"

    try:
        frame = yf.Ticker(ticker).history(period=period, interval=interval)
    except Exception as exc:
        raise MarketSourceError(
            f"yfinance history failed for {ticker}: {exc}"
        ) from exc

    bars: list[PriceBar] = []
    for idx, row in frame.iterrows():
        close = _as_float(row.get("Close"))
        if close is None:
            continue
        ts: Any = idx
        if intraday:
            # Normalize to local naive datetime string "YYYY-MM-DD HH:MM"
            try:
                dt = ts.to_pydatetime().astimezone(None).replace(tzinfo=None)
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = str(ts)[:16]
        else:
            date_str = ts.date().isoformat()
        bars.append(
            PriceBar(
                date=date_str,
                open=_as_float(row.get("Open")) or close,
                high=_as_float(row.get("High")) or close,
                low=_as_float(row.get("Low")) or close,
                close=close,
                volume=_as_float(row.get("Volume")) or 0.0,
            )
        )
    return bars


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
        news_items: list[tuple[str, str]] = []
        for item in news[:news_limit]:
            if not item:
                continue
            content = item.get("content", {})
            if isinstance(content, dict):
                title = str(content.get("title", "")).strip()
                url = (
                    str(content.get("canonicalUrl", {}).get("url", "")).strip()
                    if isinstance(content.get("canonicalUrl"), dict)
                    else str(content.get("url", "")).strip()
                )
            else:
                title = str(item.get("title", "")).strip()
                url = str(item.get("link", "")).strip()
            if title:
                news_items.append((title, url))

        return PriceContext(
            ticker=ticker.upper(),
            price=price,
            day_change_percent=day_change,
            week_52_high=_as_float(info.get("fiftyTwoWeekHigh")),
            week_52_low=_as_float(info.get("fiftyTwoWeekLow")),
            market_cap=_as_float(info.get("marketCap")),
            pe_ratio=_as_float(info.get("trailingPE")),
            news_headlines=[t for t, _ in news_items],
            news_urls=[u for _, u in news_items],
            company_name=info.get("longName") or info.get("shortName") or None,
            website=info.get("website") or None,
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
