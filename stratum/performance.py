from __future__ import annotations

import os
from datetime import date, timedelta

from .market_data import AlphaVantageClient, MarketDataError
from .models import (
    HoldingWindowPerformance,
    PortfolioDashboard,
    PortfolioPerformancePoint,
    PortfolioPerformanceView,
)


WINDOW_DAYS = {
    "1m": 31,
    "3m": 92,
    "6m": 183,
    "1y": 366,
    "3y": 366 * 3,
    "5y": 366 * 5,
    "all": None,
    "custom": None,
    "ytd": None,
}


def parse_iso_date(raw: str) -> date | None:
    normalized = raw.strip()
    if not normalized:
        return None
    return date.fromisoformat(normalized)


def parse_dashboard_as_of_label(raw: str) -> date | None:
    normalized = raw.strip()
    if not normalized:
        return None
    return date.fromisoformat(normalized.split()[0].replace("/", "-"))


def resolve_window(
    end_date: date,
    window_key: str,
    start_raw: str = "",
    end_raw: str = "",
) -> tuple[str, date | None, date]:
    requested_end = parse_iso_date(end_raw) or end_date
    if requested_end > end_date:
        requested_end = end_date

    custom_start = parse_iso_date(start_raw)
    if custom_start is not None:
        if custom_start > requested_end:
            custom_start = requested_end
        return "custom", custom_start, requested_end

    normalized_key = window_key if window_key in WINDOW_DAYS else "1y"
    if normalized_key == "all":
        return normalized_key, None, requested_end
    if normalized_key == "ytd":
        return normalized_key, date(requested_end.year, 1, 1), requested_end

    days = WINDOW_DAYS[normalized_key]
    assert days is not None
    return normalized_key, requested_end - timedelta(days=days), requested_end


def fill_forward_price_series(price_series: dict[date, float], dates: list[date]) -> dict[date, float]:
    filled: dict[date, float] = {}
    latest_price: float | None = None
    for point_date in dates:
        if point_date in price_series:
            latest_price = price_series[point_date]
        if latest_price is not None:
            filled[point_date] = latest_price
    return filled


def price_positions(
    quantities: dict[str, float], prices_by_symbol: dict[str, dict[date, float]], point_date: date
) -> float:
    total = 0.0
    for symbol, quantity in quantities.items():
        if abs(quantity) <= 1e-6:
            continue
        price = prices_by_symbol.get(symbol, {}).get(point_date)
        if price is None:
            continue
        total += quantity * price
    return total


def build_portfolio_performance(
    dashboard: PortfolioDashboard,
    window_key: str = "1y",
    start_raw: str = "",
    end_raw: str = "",
    client: AlphaVantageClient | None = None,
) -> PortfolioPerformanceView:
    dashboard_end = parse_dashboard_as_of_label(dashboard.as_of_label) or dashboard.end_date
    resolved_window, start_date, end_date = resolve_window(
        dashboard_end,
        window_key=window_key,
        start_raw=start_raw,
        end_raw=end_raw,
    )

    if client is None:
        api_key = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
        entitlement = os.getenv("ALPHAVANTAGE_ENTITLEMENT", "").strip() or None
        if not api_key:
            return PortfolioPerformanceView(
                available=False,
                window_key=resolved_window,
                start_date=start_date,
                end_date=end_date,
                points=[],
                holdings=[],
                note=(
                    "Set ALPHAVANTAGE_API_KEY to load the historical total value chart "
                    "and per-holding window performance."
                ),
                errors=[],
            )
        client = AlphaVantageClient(api_key=api_key, entitlement=entitlement)

    current_holdings = {
        holding.symbol: holding.quantity
        for holding in dashboard.holdings
        if holding.quantity > 1e-6
    }
    symbols = sorted(current_holdings)
    if not symbols:
        return PortfolioPerformanceView(
            available=False,
            window_key=resolved_window,
            start_date=start_date,
            end_date=end_date,
            points=[],
            holdings=[],
            note="No current holdings are available to build the historical asset view.",
            errors=[],
        )

    historical_prices: dict[str, dict[date, float]] = {}
    errors: list[str] = []
    for symbol in symbols:
        try:
            historical_prices[symbol] = client.get_weekly_adjusted_series(symbol)
        except MarketDataError as error:
            errors.append(f"{symbol}: {error}")

    available_symbols = sorted(symbol for symbol in symbols if symbol in historical_prices)
    if not available_symbols:
        return PortfolioPerformanceView(
            available=False,
            window_key=resolved_window,
            start_date=start_date,
            end_date=end_date,
            points=[],
            holdings=[],
            note="Historical prices could not be loaded for the current holdings.",
            errors=errors,
        )

    candidate_dates = sorted(
        {
            point_date
            for symbol in available_symbols
            for point_date in historical_prices[symbol]
            if point_date <= end_date and (start_date is None or point_date >= start_date)
        }
    )
    if not candidate_dates:
        return PortfolioPerformanceView(
            available=False,
            window_key=resolved_window,
            start_date=start_date,
            end_date=end_date,
            points=[],
            holdings=[],
            note="No price points were available inside the selected time window.",
            errors=errors,
        )

    filled_prices = {
        symbol: fill_forward_price_series(series, candidate_dates)
        for symbol, series in historical_prices.items()
    }
    raw_window_points: list[tuple[date, float]] = []
    for point_date in candidate_dates:
        portfolio_value = price_positions(current_holdings, filled_prices, point_date)
        if portfolio_value <= 0:
            continue
        raw_window_points.append((point_date, portfolio_value))

    if len(raw_window_points) < 2:
        return PortfolioPerformanceView(
            available=False,
            window_key=resolved_window,
            start_date=start_date,
            end_date=end_date,
            points=[],
            holdings=[],
            note="Not enough priced history was available to plot the total asset value for this window.",
            errors=errors,
        )

    base_total_value = raw_window_points[0][1]
    points = [
        PortfolioPerformancePoint(
            trade_date=point_date,
            total_value=total_value,
            total_return=(total_value / base_total_value) - 1.0,
        )
        for point_date, total_value in raw_window_points
    ]

    start_point_date = points[0].trade_date
    end_point_date = points[-1].trade_date
    holding_performance: list[HoldingWindowPerformance] = []
    for holding in dashboard.holdings:
        if holding.symbol not in available_symbols:
            continue
        start_price = filled_prices[holding.symbol].get(start_point_date)
        end_price = filled_prices[holding.symbol].get(end_point_date)
        if start_price is None or end_price is None or start_price <= 0:
            continue
        start_value = holding.quantity * start_price
        end_value = holding.quantity * end_price
        holding_performance.append(
            HoldingWindowPerformance(
                symbol=holding.symbol,
                start_value=start_value,
                end_value=end_value,
                return_pct=(end_value / start_value) - 1.0,
            )
        )

    return PortfolioPerformanceView(
        available=True,
        window_key=resolved_window,
        start_date=points[0].trade_date,
        end_date=points[-1].trade_date,
        points=points,
        holdings=holding_performance,
        note=(
            "This view reprices the current holdings backwards through the selected window. "
            "It is a current-holdings retrospective, not a full-account ledger. "
            "Weekly adjusted closes from Alpha Vantage are used."
        ),
        errors=errors,
    )
