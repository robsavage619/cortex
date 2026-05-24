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


@lru_cache(maxsize=1)
def sp500_tickers() -> list[str]:
    """Return S&P 500 constituent tickers.

    Fetches the Wikipedia constituents table with a browser User-Agent so the
    request is not blocked.  Falls back to a hardcoded ~500 large-cap list if
    the request fails for any reason.
    """
    try:
        import io

        import pandas as pd
        import requests

        resp = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0 (compatible; wst-universe-fetch/1.0)"},
            timeout=15,
        )
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), attrs={"id": "constituents"})
        tickers: list[str] = (
            tables[0]["Symbol"]
            .str.replace(".", "-", regex=False)
            .tolist()
        )
        log.info("Universe: loaded %d tickers from Wikipedia", len(tickers))
        return tickers
    except Exception as exc:
        log.warning(
            "Wikipedia S&P 500 fetch failed (%s) — using fallback universe", exc
        )
        return list(_FALLBACK)
