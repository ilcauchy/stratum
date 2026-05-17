from __future__ import annotations

from dataclasses import dataclass
from datetime import date


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


@dataclass
class PortfolioTransaction:
    symbol: str
    trade_date: date
    side: str
    quantity: float
    price: float
    commission: float
    current_price: float
    comment: str


@dataclass
class PortfolioHolding:
    symbol: str
    quantity: float
    current_price: float
    market_value: float
    cost_basis: float
    realized_pnl: float
    unrealized_pnl: float
    weight: float


@dataclass
class PortfolioSnapshot:
    trade_date: date
    quantities: dict[str, float]


@dataclass
class PortfolioDashboard:
    as_of_label: str
    total_market_value: float
    total_cost_basis: float
    total_realized_pnl: float
    total_unrealized_pnl: float
    holdings: list[PortfolioHolding]
    history_symbols: list[str]
    snapshots: list[PortfolioSnapshot]
    transaction_count: int
    start_date: date
    end_date: date
    transactions: list[PortfolioTransaction]
    recent_transactions: list[PortfolioTransaction]


@dataclass
class PortfolioPerformancePoint:
    trade_date: date
    total_value: float
    total_return: float


@dataclass
class HoldingWindowPerformance:
    symbol: str
    start_value: float
    end_value: float
    return_pct: float


@dataclass
class PortfolioPerformanceView:
    available: bool
    window_key: str
    start_date: date | None
    end_date: date | None
    points: list[PortfolioPerformancePoint]
    holdings: list[HoldingWindowPerformance]
    note: str
    errors: list[str]
