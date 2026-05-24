from __future__ import annotations

import logging
from functools import lru_cache

log = logging.getLogger(__name__)

# ~100 large-cap fallback tickers (used when Wikipedia fetch fails)
_FALLBACK: list[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "TSLA", "AVGO",
    "JPM", "LLY", "V", "UNH", "XOM", "MA", "JNJ", "HD", "PG", "COST", "ABBV",
    "WMT", "NFLX", "CRM", "BAC", "AMD", "MRK", "CVX", "ORCL", "KO", "PEP",
    "TMO", "ADBE", "ACN", "MCD", "CSCO", "WFC", "ABT", "LIN", "TXN", "DHR",
    "PM", "NEE", "IBM", "INTU", "AMGN", "CAT", "UNP", "SPGI", "GS", "NOW",
    "RTX", "ISRG", "BKNG", "PLD", "VRTX", "SYK", "AMAT", "BLK", "ELV", "MDT",
    "HON", "GILD", "C", "AXP", "DE", "T", "ADI", "CB", "MO", "ETN",
    "SCHW", "ZTS", "MMC", "BSX", "LRCX", "GE", "SO", "CME", "AON", "REGN",
    "PGR", "PANW", "KLAC", "SLB", "HCA", "SNPS", "CDNS", "CI", "FI", "DUK",
    "MCO", "APH", "INTC", "ICE", "MU", "ITW", "PYPL", "CTAS", "TJX", "ECL",
]


def _wiki_tickers(url: str, table_id: str) -> list[str]:
    import io

    import pandas as pd
    import requests

    resp = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; cortex-universe-fetch/1.0)"},
        timeout=15,
    )
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text), attrs={"id": table_id})
    return (
        tables[0]["Symbol"]
        .str.replace(".", "-", regex=False)
        .tolist()
    )


@lru_cache(maxsize=1)
def sp500_tickers() -> list[str]:
    """Return S&P 500 constituent tickers.

    Fetches the Wikipedia constituents table with a browser User-Agent so the
    request is not blocked.  Falls back to a hardcoded ~500 large-cap list if
    the request fails for any reason.
    """
    try:
        tickers = _wiki_tickers(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            "constituents",
        )
        log.info("Universe: loaded %d S&P 500 tickers from Wikipedia", len(tickers))
        return tickers
    except Exception as exc:
        log.warning(
            "Wikipedia S&P 500 fetch failed (%s) — using fallback universe", exc
        )
        return list(_FALLBACK)


@lru_cache(maxsize=1)
def sp400_tickers() -> list[str]:
    """Return S&P 400 mid-cap constituent tickers (Wikipedia, with empty fallback)."""
    try:
        tickers = _wiki_tickers(
            "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
            "constituents",
        )
        log.info("Universe: loaded %d S&P 400 tickers from Wikipedia", len(tickers))
        return tickers
    except Exception as exc:
        log.warning("Wikipedia S&P 400 fetch failed (%s) — skipping mid-caps", exc)
        return []


@lru_cache(maxsize=1)
def sp600_tickers() -> list[str]:
    """Return S&P 600 small-cap constituent tickers (Wikipedia, with empty fallback)."""
    try:
        tickers = _wiki_tickers(
            "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
            "constituents",
        )
        log.info("Universe: loaded %d S&P 600 tickers from Wikipedia", len(tickers))
        return tickers
    except Exception as exc:
        log.warning("Wikipedia S&P 600 fetch failed (%s) — skipping small-caps", exc)
        return []


@lru_cache(maxsize=1)
def composite_tickers() -> list[str]:
    """Return deduplicated S&P 500 + S&P 400 + S&P 600 tickers (≈1500 names)."""
    seen: set[str] = set()
    out: list[str] = []
    for t in sp500_tickers() + sp400_tickers() + sp600_tickers():
        if t not in seen:
            seen.add(t)
            out.append(t)
    log.info("Universe: composite = %d tickers", len(out))
    return out
