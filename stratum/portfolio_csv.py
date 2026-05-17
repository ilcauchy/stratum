from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
from pathlib import Path

from .models import (
    PortfolioDashboard,
    PortfolioHolding,
    PortfolioSnapshot,
    PortfolioTransaction,
)


TRANSACTION_TYPES = {"BUY", "SELL"}
DEFAULT_RAW_PORTFOLIO_CSV_PATH = "data/portfolio.csv"
DEFAULT_PORTFOLIO_CSV_PATH = "data/portfolio.cleaned.csv"
DEFAULT_PORTFOLIO_HEADERS = [
    "Symbol",
    "Current Price",
    "Date",
    "Time",
    "Change",
    "Open",
    "High",
    "Low",
    "Volume",
    "Trade Date",
    "Purchase Price",
    "Quantity",
    "Commission",
    "High Limit",
    "Low Limit",
    "Comment",
    "Transaction Type",
]


def parse_decimal(raw: str) -> float:
    normalized = raw.strip()
    if not normalized:
        return 0.0
    return float(normalized.replace(",", ""))


def format_decimal(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def parse_date(raw: str, date_format: str) -> date | None:
    normalized = raw.strip()
    if not normalized:
        return None
    return datetime.strptime(normalized, date_format).date()


def load_portfolio_csv(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    csv_path = Path(path)
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or DEFAULT_PORTFOLIO_HEADERS)
        rows = [{header: row.get(header, "") for header in headers} for row in reader]
    return headers, rows


def write_portfolio_csv(
    path: str | Path, headers: list[str], rows: list[dict[str, str]]
) -> None:
    csv_path = Path(path)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def is_trade_row(row: dict[str, str]) -> bool:
    return row.get("Transaction Type", "").strip().upper() in TRANSACTION_TYPES


def build_transactions(rows: list[dict[str, str]]) -> list[PortfolioTransaction]:
    transactions: list[PortfolioTransaction] = []
    for row in rows:
        if not is_trade_row(row):
            continue

        trade_date = parse_date(row.get("Trade Date", ""), "%Y%m%d")
        symbol = row.get("Symbol", "").strip().upper()
        if trade_date is None or not symbol:
            continue

        transactions.append(
            PortfolioTransaction(
                symbol=symbol,
                trade_date=trade_date,
                side=row["Transaction Type"].strip().upper(),
                quantity=parse_decimal(row.get("Quantity", "")),
                price=parse_decimal(row.get("Purchase Price", "")),
                commission=parse_decimal(row.get("Commission", "")),
                current_price=parse_decimal(row.get("Current Price", "")),
                comment=row.get("Comment", "").strip(),
            )
        )

    transactions.sort(key=lambda transaction: (transaction.trade_date, transaction.symbol, transaction.side))
    return transactions


def build_net_positions(rows: list[dict[str, str]]) -> dict[str, float]:
    positions: dict[str, float] = {}
    for row in rows:
        if not is_trade_row(row):
            continue

        symbol = row.get("Symbol", "").strip().upper()
        if not symbol:
            continue

        quantity = parse_decimal(row.get("Quantity", ""))
        if row["Transaction Type"].strip().upper() == "BUY":
            positions[symbol] = positions.get(symbol, 0.0) + quantity
        else:
            positions[symbol] = positions.get(symbol, 0.0) - quantity
    return positions


def build_default_expected_positions(
    rows: list[dict[str, str]], tolerance: float = 1e-6
) -> dict[str, float]:
    expected_positions: dict[str, float] = {}
    for symbol, quantity in build_net_positions(rows).items():
        if quantity < -tolerance:
            expected_positions[symbol] = 0.0
    return expected_positions


def build_current_holdings(
    transactions: list[PortfolioTransaction], tolerance: float = 1e-6
) -> tuple[list[PortfolioHolding], float]:
    states: dict[str, dict[str, float]] = {}
    for transaction in transactions:
        state = states.setdefault(
            transaction.symbol,
            {
                "quantity": 0.0,
                "cost_basis": 0.0,
                "current_price": transaction.current_price,
                "realized_pnl": 0.0,
            },
        )
        state["current_price"] = transaction.current_price or state["current_price"]

        if transaction.side == "BUY":
            state["quantity"] += transaction.quantity
            state["cost_basis"] += transaction.quantity * transaction.price + transaction.commission
            continue

        if state["quantity"] > tolerance:
            average_cost = state["cost_basis"] / state["quantity"]
            reduction_quantity = min(transaction.quantity, state["quantity"])
            sale_proceeds = (reduction_quantity * transaction.price) - transaction.commission
            state["realized_pnl"] += sale_proceeds - (reduction_quantity * average_cost)
            state["cost_basis"] -= reduction_quantity * average_cost

        state["quantity"] -= transaction.quantity
        if abs(state["quantity"]) <= tolerance:
            state["quantity"] = 0.0
            state["cost_basis"] = 0.0

    total_market_value = 0.0
    total_realized_pnl = 0.0
    holdings: list[PortfolioHolding] = []
    for symbol, state in states.items():
        total_realized_pnl += state["realized_pnl"]
        quantity = state["quantity"]
        if quantity <= tolerance:
            continue

        market_value = quantity * state["current_price"]
        if market_value <= tolerance:
            continue

        total_market_value += market_value
        holdings.append(
            PortfolioHolding(
                symbol=symbol,
                quantity=quantity,
                current_price=state["current_price"],
                market_value=market_value,
                cost_basis=max(state["cost_basis"], 0.0),
                realized_pnl=state["realized_pnl"],
                unrealized_pnl=market_value - max(state["cost_basis"], 0.0),
                weight=0.0,
            )
        )

    holdings.sort(key=lambda holding: holding.market_value, reverse=True)
    if total_market_value > tolerance:
        for holding in holdings:
            holding.weight = holding.market_value / total_market_value
    return holdings, total_realized_pnl


def build_holding_history(
    transactions: list[PortfolioTransaction],
    symbols: list[str],
    as_of_date: date | None = None,
    tolerance: float = 1e-6,
) -> list[PortfolioSnapshot]:
    tracked_symbols = list(symbols)
    tracked_set = set(tracked_symbols)
    if not tracked_symbols:
        return []

    per_date: dict[date, list[PortfolioTransaction]] = {}
    for transaction in transactions:
        if transaction.symbol not in tracked_set:
            continue
        per_date.setdefault(transaction.trade_date, []).append(transaction)

    quantities = {symbol: 0.0 for symbol in tracked_symbols}
    snapshots: list[PortfolioSnapshot] = []
    for trade_date in sorted(per_date):
        for transaction in per_date[trade_date]:
            delta = transaction.quantity if transaction.side == "BUY" else -transaction.quantity
            quantities[transaction.symbol] = quantities.get(transaction.symbol, 0.0) + delta
            if abs(quantities[transaction.symbol]) <= tolerance:
                quantities[transaction.symbol] = 0.0

        snapshots.append(
            PortfolioSnapshot(
                trade_date=trade_date,
                quantities={symbol: max(quantities.get(symbol, 0.0), 0.0) for symbol in tracked_symbols},
            )
        )

    if as_of_date and snapshots and as_of_date > snapshots[-1].trade_date:
        snapshots.append(
            PortfolioSnapshot(
                trade_date=as_of_date,
                quantities=dict(snapshots[-1].quantities),
            )
        )

    return snapshots


def build_position_market_values(
    rows: list[dict[str, str]], tolerance: float = 1e-6
) -> dict[str, float]:
    transactions = build_transactions(rows)
    if not transactions:
        quantities = build_net_positions(rows)
        latest_prices: dict[str, float] = {}
        for row in rows:
            symbol = row.get("Symbol", "").strip().upper()
            if not symbol:
                continue
            latest_prices[symbol] = parse_decimal(row.get("Current Price", ""))

        market_values: dict[str, float] = {}
        for symbol, quantity in quantities.items():
            if quantity <= tolerance:
                continue
            market_value = quantity * latest_prices.get(symbol, 0.0)
            if market_value > tolerance:
                market_values[symbol] = market_value
        return market_values

    market_values: dict[str, float] = {}
    holdings, _ = build_current_holdings(transactions, tolerance=tolerance)
    for holding in holdings:
        if holding.market_value > tolerance:
            market_values[holding.symbol] = holding.market_value
    return market_values


def format_positions_input(positions: dict[str, float]) -> str:
    ranked = sorted(positions.items(), key=lambda item: item[1], reverse=True)
    return ",".join(f"{symbol}:{value:.2f}" for symbol, value in ranked)


def load_positions_input(path: str | Path = DEFAULT_PORTFOLIO_CSV_PATH) -> str:
    csv_path = Path(path)
    if not csv_path.exists():
        return ""

    _, rows = load_portfolio_csv(csv_path)
    return format_positions_input(build_position_market_values(rows))


def build_as_of_label(rows: list[dict[str, str]]) -> str:
    for row in rows:
        snapshot_date = row.get("Date", "").strip()
        snapshot_time = row.get("Time", "").strip()
        if snapshot_date and snapshot_time:
            return f"{snapshot_date} {snapshot_time}"
        if snapshot_date:
            return snapshot_date
    return ""


def load_portfolio_dashboard(
    path: str | Path = DEFAULT_PORTFOLIO_CSV_PATH,
    history_limit: int = 6,
    recent_limit: int = 8,
) -> PortfolioDashboard | None:
    csv_path = Path(path)
    if not csv_path.exists():
        return None

    _, rows = load_portfolio_csv(csv_path)
    transactions = build_transactions(rows)
    if not transactions:
        return None

    holdings, total_realized_pnl = build_current_holdings(transactions)
    history_symbols = [holding.symbol for holding in holdings[:history_limit]]
    as_of_label = build_as_of_label(rows)
    as_of_date = parse_date(as_of_label.split()[0], "%Y/%m/%d") if as_of_label else None
    snapshots = build_holding_history(transactions, history_symbols, as_of_date=as_of_date)

    total_market_value = sum(holding.market_value for holding in holdings)
    total_cost_basis = sum(holding.cost_basis for holding in holdings)
    total_unrealized_pnl = sum(holding.unrealized_pnl for holding in holdings)

    return PortfolioDashboard(
        as_of_label=as_of_label,
        total_market_value=total_market_value,
        total_cost_basis=total_cost_basis,
        total_realized_pnl=total_realized_pnl,
        total_unrealized_pnl=total_unrealized_pnl,
        holdings=holdings,
        history_symbols=history_symbols,
        snapshots=snapshots,
        transaction_count=len(transactions),
        start_date=transactions[0].trade_date,
        end_date=transactions[-1].trade_date,
        transactions=transactions,
        recent_transactions=list(reversed(transactions[-recent_limit:])),
    )


def clean_portfolio_csv(
    source: str | Path,
    target: str | Path = DEFAULT_PORTFOLIO_CSV_PATH,
    expected_positions: dict[str, float] | None = None,
) -> tuple[Path, list[str]]:
    headers, rows = load_portfolio_csv(source)
    resolved_positions = build_default_expected_positions(rows)
    if expected_positions:
        resolved_positions.update(expected_positions)

    cleaned_rows, notes = reconcile_positions(headers, rows, resolved_positions)

    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    write_portfolio_csv(target_path, headers, cleaned_rows)
    return target_path, notes


def build_reconciliation_row(
    symbol: str,
    discrepancy: float,
    template: dict[str, str] | None,
    headers: list[str],
    expected_quantity: float,
) -> dict[str, str]:
    base = {header: "" for header in headers}
    if template:
        for header in headers:
            base[header] = template.get(header, "")

    base["Symbol"] = symbol
    base["Quantity"] = format_decimal(abs(discrepancy))
    base["Commission"] = "0.0"
    base["Transaction Type"] = "BUY" if discrepancy > 0 else "SELL"
    base["Comment"] = (
        "Synthetic reconciliation to ending quantity "
        f"{format_decimal(expected_quantity)}"
    )

    if not base.get("Purchase Price"):
        base["Purchase Price"] = base.get("Current Price", "") or "0"

    return base


def reconcile_positions(
    headers: list[str],
    rows: list[dict[str, str]],
    expected_positions: dict[str, float],
    tolerance: float = 1e-6,
) -> tuple[list[dict[str, str]], list[str]]:
    cleaned_rows = list(rows)
    current_positions = build_net_positions(rows)
    notes: list[str] = []

    for raw_symbol, expected_quantity in sorted(expected_positions.items()):
        symbol = raw_symbol.strip().upper()
        current_quantity = current_positions.get(symbol, 0.0)
        discrepancy = expected_quantity - current_quantity
        if abs(discrepancy) <= tolerance:
            continue

        template = None
        for row in reversed(rows):
            if row.get("Symbol", "").strip().upper() == symbol:
                template = row
                break

        cleaned_rows.append(
            build_reconciliation_row(
                symbol=symbol,
                discrepancy=discrepancy,
                template=template,
                headers=headers,
                expected_quantity=expected_quantity,
            )
        )
        current_positions[symbol] = expected_quantity
        notes.append(
            f"{symbol}: added synthetic {'BUY' if discrepancy > 0 else 'SELL'} "
            f"for {format_decimal(abs(discrepancy))} shares to reach "
            f"{format_decimal(expected_quantity)}."
        )

    return cleaned_rows, notes


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean Yahoo Finance portfolio CSV exports")
    parser.add_argument("source", help="Path to the source portfolio CSV")
    parser.add_argument("target", help="Path to write the cleaned CSV")
    parser.add_argument(
        "--zero-symbol",
        action="append",
        default=[],
        help="Symbol whose ending quantity should be forced to 0",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    expected_positions = {symbol: 0.0 for symbol in args.zero_symbol}
    target_path, notes = clean_portfolio_csv(
        source=args.source,
        target=args.target,
        expected_positions=expected_positions,
    )

    print(f"Wrote cleaned CSV to {target_path}")
    if notes:
        for note in notes:
            print(note)
    else:
        print("No reconciliation changes were needed.")


if __name__ == "__main__":
    main()
