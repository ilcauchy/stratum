from __future__ import annotations

import os
from pathlib import Path

from .portfolio_csv import load_positions_input


ALLOCATION_TEMPLATES = {
    "conservative": {"Equities": 30, "Bonds": 45, "Cash": 20, "REITs": 5},
    "balanced": {"Equities": 50, "Bonds": 25, "Cash": 15, "REITs": 10},
    "growth": {"Equities": 70, "Bonds": 10, "Cash": 10, "REITs": 10},
    "aggressive": {"Equities": 85, "Bonds": 5, "Cash": 5, "Satellite": 5},
}

OBJECTIVE_ADJUSTMENTS = {
    "growth": {"Equities": 5, "Bonds": -5, "Cash": -5, "Satellite": 5},
    "balanced": {},
    "income": {"Equities": -5, "Bonds": 10, "Cash": 0, "REITs": -5},
}

SUGGESTED_TOOLS = {
    "Equities": ["Broad-market equity ETFs", "Global equity ETFs", "Dividend ETFs"],
    "Bonds": ["Short-duration bond funds", "Treasury ETFs", "Investment-grade bond funds"],
    "Cash": ["Money market funds", "High-yield cash accounts", "Short-term Treasuries"],
    "REITs": ["Public REIT funds", "Global REIT ETFs"],
    "Satellite": ["Sector ETFs", "High-conviction single stocks"],
}

OBJECTIVE_LABELS = {
    "growth": "Long-term Growth",
    "balanced": "Balanced Growth",
    "income": "Income & Defense",
}

RISK_LABELS = {
    "conservative": "Conservative",
    "balanced": "Balanced",
    "growth": "Growth",
    "aggressive": "Aggressive",
}

DEFAULT_FORM_VALUES = {
    "capital": "",
    "monthly_contribution": "",
    "horizon_years": "",
    "max_drawdown": "",
    "objective": "balanced",
    "positions": "",
}

ALPHAVANTAGE_BASE_URL = "https://www.alphavantage.co/query"
MARKET_DATA_TICKER_LIMIT = 5


def build_default_form_values() -> dict[str, str]:
    values = dict(DEFAULT_FORM_VALUES)
    imported_positions = load_positions_input()
    if imported_positions:
        values["positions"] = imported_positions
    return values


def load_local_env(env_path: str = ".env") -> None:
    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()
