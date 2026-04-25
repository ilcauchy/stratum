from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InvestorProfile:
    capital: float
    monthly_contribution: float
    horizon_years: int
    max_drawdown: int
    objective: str
    positions: dict[str, float]


@dataclass
class AnalysisResult:
    risk_level: str
    allocation: dict[str, int]
    invested_amount: float
    cash_ratio: float
    concentration_warnings: list[str]
    rebalance_actions: list[str]
    principles: list[str]


@dataclass
class MarketQuote:
    symbol: str
    price: float
    previous_close: float
    change: float
    change_percent: float
    latest_trading_day: str
    volume: int | None = None


@dataclass
class MarketDataSnapshot:
    provider: str
    enabled: bool
    note: str
    quotes: list[MarketQuote]
    errors: list[str]
