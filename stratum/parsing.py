from __future__ import annotations

from .config import OBJECTIVE_LABELS, build_default_form_values
from .models import InvestorProfile


def parse_non_negative_float(raw: str, field_label: str) -> float:
    normalized = raw.strip().replace(",", "")
    if not normalized:
        raise ValueError(f"{field_label} is required.")
    try:
        value = float(normalized)
    except ValueError as error:
        raise ValueError(f"{field_label} must be a number.") from error
    if value < 0:
        raise ValueError(f"{field_label} cannot be negative.")
    return value


def parse_positive_int(raw: str, field_label: str) -> int:
    normalized = raw.strip()
    if not normalized:
        raise ValueError(f"{field_label} is required.")
    try:
        value = int(normalized)
    except ValueError as error:
        raise ValueError(f"{field_label} must be an integer.") from error
    if value <= 0:
        raise ValueError(f"{field_label} must be greater than 0.")
    return value


def parse_positions(raw: str) -> dict[str, float]:
    if not raw.strip():
        return {}

    positions: dict[str, float] = {}
    normalized = raw.replace("\n", ",")
    for item in normalized.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(
                "Invalid holdings format. Use ticker:amount, for example VTI:30000,BND:15000."
            )
        ticker, amount_raw = item.split(":", 1)
        ticker = ticker.strip().upper()
        if not ticker:
            raise ValueError("Holding ticker cannot be empty.")
        amount = parse_non_negative_float(amount_raw, f"{ticker} amount")
        positions[ticker] = positions.get(ticker, 0) + amount
    return positions


def build_profile(
    capital_raw: str,
    monthly_raw: str,
    horizon_raw: str,
    drawdown_raw: str,
    objective_raw: str,
    positions_raw: str,
) -> InvestorProfile:
    objective = objective_raw.strip().lower()
    if objective not in OBJECTIVE_LABELS:
        raise ValueError("Primary objective is not supported.")

    return InvestorProfile(
        capital=parse_non_negative_float(capital_raw, "Investable capital"),
        monthly_contribution=parse_non_negative_float(monthly_raw, "Monthly contribution"),
        horizon_years=parse_positive_int(horizon_raw, "Investment horizon"),
        max_drawdown=parse_positive_int(drawdown_raw, "Maximum drawdown"),
        objective=objective,
        positions=parse_positions(positions_raw),
    )


def validate_profile_form(form_data: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    values = build_default_form_values()
    values.update({key: value.strip() for key, value in form_data.items() if key in values})

    errors: dict[str, str] = {}
    try:
        parse_non_negative_float(values["capital"], "Investable capital")
    except ValueError as error:
        errors["capital"] = str(error)

    try:
        parse_non_negative_float(values["monthly_contribution"], "Monthly contribution")
    except ValueError as error:
        errors["monthly_contribution"] = str(error)

    try:
        parse_positive_int(values["horizon_years"], "Investment horizon")
    except ValueError as error:
        errors["horizon_years"] = str(error)

    try:
        parse_positive_int(values["max_drawdown"], "Maximum drawdown")
    except ValueError as error:
        errors["max_drawdown"] = str(error)

    if values["objective"] not in OBJECTIVE_LABELS:
        errors["objective"] = "Please select a valid objective."

    try:
        parse_positions(values["positions"])
    except ValueError as error:
        errors["positions"] = str(error)

    return values, errors
