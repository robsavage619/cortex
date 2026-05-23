from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

API_BASE = "https://api.financialdatasets.ai"


class FinancialDatasetsError(Exception):
    """Raised on financialdatasets.ai request/parse failures or missing key."""


@dataclass(frozen=True)
class PriceSnapshot:
    ticker: str
    price: float | None
    day_change_percent: float | None


@dataclass(frozen=True)
class NewsItem:
    ticker: str
    title: str
    url: str
    published: str
    sentiment: str | None


@dataclass(frozen=True)
class InsiderTrade:
    ticker: str
    insider_name: str
    transaction_type: str
    shares: float | None
    value: float | None
    filing_date: str


class FinancialDatasetsClient:
    """Thin read-only REST client for financialdatasets.ai.

    No write/trade endpoints exist on this service; this client only reads.
    """

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = API_BASE,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise FinancialDatasetsError(
                "FINANCIAL_DATASETS_API_KEY is not set; cannot fetch market data"
            )
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout, headers={"X-API-KEY": api_key}
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> FinancialDatasetsClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.get(f"{self._base_url}{path}", params=params)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FinancialDatasetsError(f"GET {path} failed: {exc}") from exc
        if not isinstance(data, dict):
            raise FinancialDatasetsError(f"GET {path} returned non-object payload")
        return data

    def price_snapshot(self, ticker: str) -> PriceSnapshot:
        data = self._get("/prices/snapshot", {"ticker": ticker})
        snap = data.get("snapshot", data)
        return PriceSnapshot(
            ticker=ticker,
            price=_as_float(snap.get("price")),
            day_change_percent=_as_float(snap.get("day_change_percent")),
        )

    def news(self, ticker: str, *, limit: int = 5) -> list[NewsItem]:
        data = self._get("/news", {"ticker": ticker, "limit": limit})
        items = data.get("news", [])
        out: list[NewsItem] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            out.append(
                NewsItem(
                    ticker=ticker,
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    published=str(item.get("date", "")).strip(),
                    sentiment=_opt_str(item.get("sentiment")),
                )
            )
        return out

    def insider_trades(self, ticker: str, *, limit: int = 10) -> list[InsiderTrade]:
        data = self._get("/insider-trades", {"ticker": ticker, "limit": limit})
        items = data.get("insider_trades", [])
        out: list[InsiderTrade] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            out.append(
                InsiderTrade(
                    ticker=ticker,
                    insider_name=str(item.get("name", "")).strip(),
                    transaction_type=str(item.get("transaction_type", "")).strip(),
                    shares=_as_float(item.get("transaction_shares")),
                    value=_as_float(item.get("transaction_value")),
                    filing_date=str(item.get("filing_date", "")).strip(),
                )
            )
        return out


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace("$", ""))
        except ValueError:
            return None
    return None


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
