from __future__ import annotations


def format_currency(value: float) -> str:
    return f"{value:,.0f}"


def format_percent(value: float) -> str:
    return f"{value:.0%}"


def format_number(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}"


def format_signed_number(value: float, decimals: int = 2) -> str:
    return f"{value:+,.{decimals}f}"


def format_signed_percent(value: float, decimals: int = 2) -> str:
    return f"{value:+.{decimals}f}%"
