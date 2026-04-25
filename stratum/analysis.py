from __future__ import annotations

from .config import (
    ALLOCATION_TEMPLATES,
    OBJECTIVE_ADJUSTMENTS,
    SUGGESTED_TOOLS,
)
from .models import AnalysisResult, InvestorProfile


def determine_risk_level(profile: InvestorProfile) -> str:
    score = 0

    if profile.horizon_years >= 15:
        score += 3
    elif profile.horizon_years >= 8:
        score += 2
    elif profile.horizon_years >= 3:
        score += 1

    if profile.max_drawdown >= 35:
        score += 3
    elif profile.max_drawdown >= 25:
        score += 2
    elif profile.max_drawdown >= 15:
        score += 1

    if profile.objective == "growth":
        score += 2
    elif profile.objective == "balanced":
        score += 1

    if score <= 2:
        return "conservative"
    if score <= 4:
        return "balanced"
    if score <= 7:
        return "growth"
    return "aggressive"


def build_allocation(risk_level: str, objective: str) -> dict[str, int]:
    allocation = dict(ALLOCATION_TEMPLATES[risk_level])
    for asset, delta in OBJECTIVE_ADJUSTMENTS[objective].items():
        allocation[asset] = allocation.get(asset, 0) + delta

    allocation = {asset: max(value, 0) for asset, value in allocation.items()}
    total = sum(allocation.values())
    normalized: dict[str, int] = {}
    running_total = 0
    items = list(allocation.items())
    for index, (asset, value) in enumerate(items):
        if index == len(items) - 1:
            normalized[asset] = 100 - running_total
            break
        percentage = round(value * 100 / total)
        normalized[asset] = percentage
        running_total += percentage
    return normalized


def analyze_positions(
    positions: dict[str, float], total_capital: float
) -> tuple[float, float, list[str]]:
    if total_capital <= 0:
        return (
            0.0,
            1.0,
            ["No investable capital was provided. Build a cash buffer before taking market risk."],
        )

    invested_amount = sum(positions.values())
    cash_ratio = max(total_capital - invested_amount, 0) / total_capital
    warnings: list[str] = []

    for ticker, amount in sorted(positions.items(), key=lambda item: item[1], reverse=True):
        ratio = amount / total_capital
        if ratio >= 0.35:
            warnings.append(
                f"{ticker} is {ratio:.0%} of total capital. Concentration is high, and it should likely be reduced toward the 20%-25% range."
            )
        elif ratio >= 0.2:
            warnings.append(
                f"{ticker} is {ratio:.0%} of total capital. It is approaching a concentration limit, so future contributions should diversify elsewhere first."
            )

    if invested_amount > total_capital:
        warnings.append(
            "Mapped holdings exceed the investable capital entered. Check whether any amounts were duplicated."
        )

    if not warnings:
        warnings.append(
            "No obvious concentration risk was detected. The main discipline to watch now is periodic rebalancing."
        )

    return invested_amount, cash_ratio, warnings


def build_rebalance_actions(
    profile: InvestorProfile, allocation: dict[str, int], cash_ratio: float
) -> list[str]:
    actions = []
    emergency_fund_months = 6 if profile.max_drawdown <= 20 else 3
    emergency_fund = profile.monthly_contribution * emergency_fund_months

    if profile.capital < emergency_fund:
        actions.append(
            f"Keep about {emergency_fund:,.0f} in liquid reserves before scaling into risk assets."
        )
    elif cash_ratio > 0.35:
        actions.append(
            "Cash is above target. Phase new capital in over the next 3-6 months based on the target mix."
        )
    elif cash_ratio < 0.05:
        actions.append(
            "The cash buffer is thin. Consider holding at least 5%-10% for flexibility and short-term needs."
        )

    top_assets = sorted(allocation.items(), key=lambda item: item[1], reverse=True)[:2]
    for asset, percentage in top_assets:
        tools = ", ".join(SUGGESTED_TOOLS.get(asset, []))
        actions.append(f"Start with {asset} ({percentage}%) as a core sleeve. Prefer tools like: {tools}.")

    if profile.monthly_contribution > 0:
        actions.append(
            f"Split the {profile.monthly_contribution:,.0f} monthly contribution into systematic buys instead of relying on one-time market timing."
        )

    actions.append(
        "Rebalance annually or whenever an allocation drifts more than 5% from target, rather than trading too often."
    )
    return actions


def build_principles(profile: InvestorProfile) -> list[str]:
    principles = [
        "Define the job of the portfolio first, then set the asset mix. Do not let hot themes drive the plan backwards.",
        "Favor broad, low-cost instruments for the core portfolio. Single stocks belong only in a risk-budgeted satellite sleeve.",
        "Expected return and drawdown tolerance must be evaluated together. The losses you can truly hold through define the portfolio you can own.",
    ]

    if profile.horizon_years <= 3:
        principles.append(
            "A short time horizon calls for tighter downside control rather than aggressive return-seeking."
        )
    else:
        principles.append(
            "A long time horizon shifts the edge toward steady contributions and discipline rather than short-term market calls."
        )

    return principles


def run_analysis(profile: InvestorProfile) -> AnalysisResult:
    risk_level = determine_risk_level(profile)
    allocation = build_allocation(risk_level, profile.objective)
    invested_amount, cash_ratio, warnings = analyze_positions(
        profile.positions, profile.capital
    )
    actions = build_rebalance_actions(profile, allocation, cash_ratio)
    principles = build_principles(profile)

    return AnalysisResult(
        risk_level=risk_level,
        allocation=allocation,
        invested_amount=invested_amount,
        cash_ratio=cash_ratio,
        concentration_warnings=warnings,
        rebalance_actions=actions,
        principles=principles,
    )


def select_market_data_tickers(positions: dict[str, float], limit: int = 5) -> list[str]:
    ranked = sorted(positions.items(), key=lambda item: item[1], reverse=True)
    return [ticker for ticker, _ in ranked[:limit]]
