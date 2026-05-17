from __future__ import annotations

from textwrap import dedent

from .config import OBJECTIVE_LABELS, RISK_LABELS
from .formatters import (
    format_currency,
    format_number,
    format_signed_number,
    format_signed_percent,
)
from .models import AnalysisResult, InvestorProfile, MarketDataSnapshot
from .parsing import parse_non_negative_float, parse_positions, parse_positive_int
from .portfolio_csv import load_positions_input


def ask_non_negative_float(prompt: str) -> float:
    while True:
        try:
            return parse_non_negative_float(input(prompt), prompt.rstrip("：:"))
        except ValueError as error:
            print(error)


def ask_positive_int(prompt: str) -> int:
    while True:
        try:
            return parse_positive_int(input(prompt), prompt.rstrip("：:"))
        except ValueError as error:
            print(error)


def ask_choice(prompt: str, mapping: dict[str, str]) -> str:
    options = " / ".join(f"{key}:{value}" for key, value in mapping.items())
    while True:
        raw = input(f"{prompt} ({options}): ").strip().lower()
        if raw in mapping:
            return raw
        print("Input is not in the supported options. Please try again.")


def collect_profile() -> InvestorProfile:
    print(
        dedent(
            """
            Stratum uses your capital, time horizon, drawdown tolerance,
            and current holdings to generate a baseline allocation plan.
            It is not real-time investment advice and does not replace professional tax or legal guidance.
            """
        ).strip()
    )
    print()

    capital = ask_non_negative_float("Investable capital: ")
    monthly = ask_non_negative_float("Planned monthly contribution: ")
    horizon = ask_positive_int("Investment horizon in years: ")
    drawdown = ask_positive_int("Maximum drawdown you can tolerate (%, e.g. 15): ")
    objective = ask_choice("Primary objective", OBJECTIVE_LABELS)

    imported_positions = load_positions_input()
    positions_prompt = "Current holdings (optional, format VTI:30000,BND:15000): "
    if imported_positions:
        positions_prompt = (
            "Current holdings (blank uses data/portfolio.cleaned.csv): "
        )

    while True:
        try:
            raw_positions = input(positions_prompt)
            if not raw_positions.strip() and imported_positions:
                raw_positions = imported_positions
            positions = parse_positions(raw_positions)
            break
        except ValueError as error:
            print(error)

    return InvestorProfile(
        capital=capital,
        monthly_contribution=monthly,
        horizon_years=horizon,
        max_drawdown=drawdown,
        objective=objective,
        positions=positions,
    )


def print_report(profile: InvestorProfile, result: AnalysisResult) -> None:
    print("\n========== Stratum Report ==========")
    print(f"Risk profile: {RISK_LABELS[result.risk_level]}")
    print(f"Primary objective: {OBJECTIVE_LABELS[profile.objective]}")
    print(f"Investment horizon: {profile.horizon_years} years")
    print(f"Maximum drawdown: {profile.max_drawdown}%")
    print(f"Investable capital: {format_currency(profile.capital)}")
    print(f"Mapped holdings: {format_currency(result.invested_amount)}")
    print(f"Estimated cash ratio: {result.cash_ratio:.0%}")

    print("\nTarget allocation:")
    for asset, percentage in result.allocation.items():
        print(f"- {asset}: {percentage}%")

    print("\nRisk flags:")
    for warning in result.concentration_warnings:
        print(f"- {warning}")

    print("\nAction plan:")
    for action in result.rebalance_actions:
        print(f"- {action}")

    print("\nPortfolio principles:")
    for principle in result.principles:
        print(f"- {principle}")


def print_market_data(snapshot: MarketDataSnapshot) -> None:
    print("\nMarket data:")
    print(f"- Provider: {snapshot.provider}")
    print(f"- Note: {snapshot.note}")

    if snapshot.quotes:
        for quote in snapshot.quotes:
            volume = f", volume {quote.volume:,}" if quote.volume is not None else ""
            print(
                f"- {quote.symbol}: last {format_number(quote.price)}, "
                f"change {format_signed_number(quote.change)} ({format_signed_percent(quote.change_percent)}), "
                f"prev close {format_number(quote.previous_close)}, "
                f"session {quote.latest_trading_day or 'n/a'}{volume}"
            )

    for error in snapshot.errors:
        print(f"- Error: {error}")
