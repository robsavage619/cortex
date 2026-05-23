from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

# Senate STOCK Act filings, aggregated and served as a single JSON array.
# Source project: github.com/timothycarambat/senate-stock-watcher-data
SENATE_AGGREGATE_URL = (
    "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com"
    "/aggregate/all_transactions.json"
)


class CongressSourceError(Exception):
    """Raised when Senate trade data cannot be fetched or parsed."""


@dataclass(frozen=True)
class CongressTrade:
    senator: str
    ticker: str
    transaction_type: str
    amount: str
    transaction_date: date | None
    disclosure_date: date | None
    asset_description: str


def _parse_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _to_trade(record: dict[str, Any]) -> CongressTrade | None:
    ticker = str(record.get("ticker", "")).strip().upper()
    if not ticker or ticker in {"--", "N/A"}:
        return None
    return CongressTrade(
        senator=str(record.get("senator", "")).strip(),
        ticker=ticker,
        transaction_type=str(record.get("type", "")).strip(),
        amount=str(record.get("amount", "")).strip(),
        transaction_date=_parse_date(record.get("transaction_date")),
        disclosure_date=_parse_date(record.get("disclosure_date")),
        asset_description=str(record.get("asset_description", "")).strip(),
    )


def fetch_senate_trades(
    *,
    url: str = SENATE_AGGREGATE_URL,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> list[CongressTrade]:
    """Fetch all Senate STOCK Act transactions.

    Raises:
        CongressSourceError: on any network or parse failure (fail visibly —
            we never return a silently empty list to mask an outage).
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CongressSourceError(f"Failed to fetch Senate trades from {url}: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    if not isinstance(payload, list):
        raise CongressSourceError(
            f"Unexpected Senate payload shape from {url}: {type(payload).__name__}"
        )

    trades: list[CongressTrade] = []
    for record in payload:
        if isinstance(record, dict):
            trade = _to_trade(record)
            if trade is not None:
                trades.append(trade)
    return trades


def filter_trades(
    trades: list[CongressTrade],
    tickers: list[str],
    *,
    since: date | None = None,
) -> list[CongressTrade]:
    """Keep trades whose ticker is in the watchlist, optionally within a window.

    Filtering uses disclosure_date (when it became public) falling back to
    transaction_date. Trades with no usable date are kept when no window is set.
    """
    wanted = {t.upper() for t in tickers}
    out: list[CongressTrade] = []
    for trade in trades:
        if trade.ticker not in wanted:
            continue
        if since is not None:
            ref = trade.disclosure_date or trade.transaction_date
            if ref is None or ref < since:
                continue
        out.append(trade)
    out.sort(
        key=lambda t: t.disclosure_date or t.transaction_date or date.min,
        reverse=True,
    )
    return out


def recent_window(days: int, today: date | None = None) -> date:
    return (today or date.today()) - timedelta(days=days)
