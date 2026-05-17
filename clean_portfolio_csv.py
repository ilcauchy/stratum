from __future__ import annotations

import argparse

from stratum.portfolio_csv import (
    DEFAULT_PORTFOLIO_CSV_PATH,
    DEFAULT_RAW_PORTFOLIO_CSV_PATH,
    clean_portfolio_csv,
)


def parse_position_override(raw: str) -> tuple[str, float]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(
            "Use SYMBOL=QUANTITY, for example AAPL=0 or SOFI=120"
        )

    symbol_raw, quantity_raw = raw.split("=", 1)
    symbol = symbol_raw.strip().upper()
    if not symbol:
        raise argparse.ArgumentTypeError("Symbol cannot be empty.")

    try:
        quantity = float(quantity_raw.strip().replace(",", ""))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Quantity must be numeric.") from error

    if quantity < 0:
        raise argparse.ArgumentTypeError("Quantity cannot be negative.")
    return symbol, quantity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean a Yahoo Finance portfolio export into Stratum's cleaned CSV."
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_RAW_PORTFOLIO_CSV_PATH,
        help=f"Source portfolio CSV. Defaults to {DEFAULT_RAW_PORTFOLIO_CSV_PATH}.",
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_PORTFOLIO_CSV_PATH,
        help=f"Cleaned portfolio CSV output. Defaults to {DEFAULT_PORTFOLIO_CSV_PATH}.",
    )
    parser.add_argument(
        "--zero-symbol",
        action="append",
        default=[],
        help="Force the ending quantity of a symbol to 0 by adding a synthetic reconciliation row.",
    )
    parser.add_argument(
        "--set-position",
        action="append",
        type=parse_position_override,
        default=[],
        metavar="SYMBOL=QUANTITY",
        help="Force a symbol to end at an exact quantity, for example --set-position SOFI=120.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    expected_positions = {symbol.strip().upper(): 0.0 for symbol in args.zero_symbol}
    for symbol, quantity in args.set_position:
        expected_positions[symbol] = quantity

    target_path, notes = clean_portfolio_csv(
        source=args.source,
        target=args.target,
        expected_positions=expected_positions,
    )

    print(f"Wrote cleaned CSV to {target_path}")
    if notes:
        print("Reconciliation notes:")
        for note in notes:
            print(f"- {note}")
    else:
        print("No reconciliation changes were needed.")


if __name__ == "__main__":
    main()
