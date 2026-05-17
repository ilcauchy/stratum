from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
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

    def __init__(
        self,
        api_key: str,
        entitlement: str | None = None,
        timeout: float = 10.0,
        cache_dir: str | Path = "data/cache/alphavantage",
    ):
        self.api_key = api_key
        self.entitlement = entitlement
        self.timeout = timeout
        self.cache_dir = Path(cache_dir)

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

    def get_weekly_adjusted_series(
        self, symbol: str, max_age: timedelta = timedelta(days=1)
    ) -> dict[date, float]:
        cached = self._load_cached_series(symbol, max_age=max_age)
        if cached is not None:
            return cached

        payload = self._fetch_json(
            {
                "function": "TIME_SERIES_WEEKLY_ADJUSTED",
                "symbol": symbol,
                "apikey": self.api_key,
            }
        )
        if "Note" in payload:
            raise MarketDataError(str(payload["Note"]))
        if "Information" in payload:
            raise MarketDataError(str(payload["Information"]))
        if "Error Message" in payload:
            raise MarketDataError(str(payload["Error Message"]))

        series = payload.get("Weekly Adjusted Time Series")
        if not isinstance(series, dict) or not series:
            raise MarketDataError(f"No weekly adjusted history was returned for {symbol}.")

        parsed_series: dict[date, float] = {}
        for raw_date, entry in series.items():
            if not isinstance(entry, dict):
                continue
            adjusted_close = entry.get("5. adjusted close", entry.get("4. close"))
            parsed_series[datetime.strptime(raw_date, "%Y-%m-%d").date()] = parse_api_float(
                adjusted_close
            )

        if not parsed_series:
            raise MarketDataError(f"No weekly adjusted history was returned for {symbol}.")

        self._write_cached_series(symbol, parsed_series)
        return parsed_series

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

    def _cache_path(self, symbol: str) -> Path:
        safe_symbol = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in symbol)
        return self.cache_dir / f"{safe_symbol}.json"

    def _load_cached_series(
        self, symbol: str, max_age: timedelta
    ) -> dict[date, float] | None:
        cache_path = self._cache_path(symbol)
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        fetched_at_raw = payload.get("fetched_at")
        series_payload = payload.get("series")
        if not isinstance(fetched_at_raw, str) or not isinstance(series_payload, dict):
            return None

        try:
            fetched_at = datetime.fromisoformat(fetched_at_raw)
        except ValueError:
            return None

        if datetime.now(timezone.utc) - fetched_at.astimezone(timezone.utc) > max_age:
            return None

        parsed: dict[date, float] = {}
        try:
            for raw_date, value in series_payload.items():
                parsed[datetime.strptime(raw_date, "%Y-%m-%d").date()] = parse_api_float(value)
        except ValueError:
            return None
        return parsed

    def _write_cached_series(self, symbol: str, series: dict[date, float]) -> None:
        cache_path = self._cache_path(symbol)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "series": {point_date.isoformat(): price for point_date, price in sorted(series.items())},
        }
        cache_path.write_text(json.dumps(payload), encoding="utf-8")


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
