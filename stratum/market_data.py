from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .analysis import select_market_data_tickers
from .config import ALPHAVANTAGE_BASE_URL, MARKET_DATA_TICKER_LIMIT
from .models import InvestorProfile, MarketDataSnapshot, MarketQuote


class MarketDataError(RuntimeError):
    pass


def parse_api_float(raw: object) -> float:
    if raw in (None, ""):
        return 0.0
    return float(str(raw).strip())


def parse_api_int(raw: object) -> int | None:
    if raw in (None, ""):
        return None
    return int(float(str(raw).strip()))


def parse_api_percent(raw: object) -> float:
    if raw in (None, ""):
        return 0.0
    normalized = str(raw).strip().rstrip("%")
    return float(normalized)


class AlphaVantageClient:
    provider_name = "Alpha Vantage"

    def __init__(self, api_key: str, entitlement: str | None = None, timeout: float = 10.0):
        self.api_key = api_key
        self.entitlement = entitlement
        self.timeout = timeout

    def get_quote(self, symbol: str) -> MarketQuote:
        params = {
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": self.api_key,
        }
        if self.entitlement:
            params["entitlement"] = self.entitlement

        payload = self._fetch_json(params)
        quote = payload.get("Global Quote", {})
        if not quote or not quote.get("05. price"):
            raise MarketDataError(f"No quote data was returned for {symbol}.")

        return MarketQuote(
            symbol=symbol,
            price=parse_api_float(quote.get("05. price")),
            previous_close=parse_api_float(quote.get("08. previous close")),
            change=parse_api_float(quote.get("09. change")),
            change_percent=parse_api_percent(quote.get("10. change percent")),
            latest_trading_day=quote.get("07. latest trading day", ""),
            volume=parse_api_int(quote.get("06. volume")),
        )

    def _fetch_json(self, params: dict[str, str]) -> dict[str, object]:
        url = f"{ALPHAVANTAGE_BASE_URL}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "stratum/1.0"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as error:
            raise MarketDataError(f"Market data request failed with HTTP {error.code}.") from error
        except URLError as error:
            raise MarketDataError(f"Market data request failed: {error.reason}.") from error
        except OSError as error:
            raise MarketDataError(f"Market data request failed: {error}.") from error


def build_market_data_snapshot(
    profile: InvestorProfile, client: AlphaVantageClient | None = None
) -> MarketDataSnapshot:
    if not profile.positions:
        return MarketDataSnapshot(
            provider=AlphaVantageClient.provider_name,
            enabled=False,
            note="Add one or more holdings tickers to load market quotes for the portfolio.",
            quotes=[],
            errors=[],
        )

    if client is None:
        api_key = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
        entitlement = os.getenv("ALPHAVANTAGE_ENTITLEMENT", "").strip() or None
        if not api_key:
            return MarketDataSnapshot(
                provider=AlphaVantageClient.provider_name,
                enabled=False,
                note=(
                    "Set ALPHAVANTAGE_API_KEY to enable live market data. "
                    "By default Alpha Vantage returns the latest provider quote; "
                    "US realtime or delayed entitlements require provider support."
                ),
                quotes=[],
                errors=[],
            )
        client = AlphaVantageClient(api_key=api_key, entitlement=entitlement)

    tracked_tickers = select_market_data_tickers(
        profile.positions, limit=MARKET_DATA_TICKER_LIMIT
    )
    quotes: list[MarketQuote] = []
    errors: list[str] = []
    for ticker in tracked_tickers:
        try:
            quotes.append(client.get_quote(ticker))
        except MarketDataError as error:
            errors.append(f"{ticker}: {error}")

    note = (
        f"Showing latest provider quotes for up to {len(tracked_tickers)} holdings. "
        "This keeps the page within common API rate limits."
    )
    if not quotes and errors:
        note = "Market data could not be loaded for the current holdings."

    return MarketDataSnapshot(
        provider=client.provider_name,
        enabled=bool(quotes),
        note=note,
        quotes=quotes,
        errors=errors,
    )
