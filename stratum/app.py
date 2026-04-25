from __future__ import annotations

import argparse

from .analysis import run_analysis
from .cli import collect_profile, print_market_data, print_report
from .market_data import build_market_data_snapshot
from .web import run_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Stratum market analysis workspace")
    parser.add_argument("--cli", action="store_true", help="Run in command-line mode")
    parser.add_argument("--host", default="127.0.0.1", help="Host address for the web server")
    parser.add_argument("--port", type=int, default=8000, help="Port for the web server")
    args = parser.parse_args()

    if args.cli:
        profile = collect_profile()
        result = run_analysis(profile)
        print_report(profile, result)
        print_market_data(build_market_data_snapshot(profile))
        return

    run_server(args.host, args.port)
