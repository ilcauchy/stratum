import os
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from stratum import (
    DEFAULT_FORM_VALUES,
    InvestorProfile,
    MarketQuote,
    build_default_form_values,
    build_current_holdings,
    build_holding_history,
    build_net_positions,
    build_market_data_snapshot,
    build_allocation,
    build_profile,
    build_portfolio_performance,
    build_position_market_values,
    build_transactions,
    determine_risk_level,
    format_positions_input,
    load_portfolio_csv,
    load_portfolio_dashboard,
    load_positions_input,
    load_local_env,
    parse_positions,
    reconcile_positions,
    render_page,
    render_result_panel,
    run_analysis,
    resolve_window,
    select_market_data_tickers,
    validate_profile_form,
    write_portfolio_csv,
)


class StratumTests(unittest.TestCase):
    class FakeMarketClient:
        provider_name = "Fake Provider"

        def get_quote(self, symbol):
            return MarketQuote(
                symbol=symbol,
                price=100.0,
                previous_close=98.0,
                change=2.0,
                change_percent=2.04,
                latest_trading_day="2026-04-24",
                volume=123456,
            )

    class FakeHistoricalClient:
        def __init__(self, series_by_symbol):
            self.series_by_symbol = series_by_symbol

        def get_weekly_adjusted_series(self, symbol):
            if symbol not in self.series_by_symbol:
                raise RuntimeError(symbol)
            return self.series_by_symbol[symbol]

    def test_parse_positions_merges_duplicate_tickers(self):
        positions = parse_positions("VTI:30000, BND:15000, VTI:5000")
        self.assertEqual(positions["VTI"], 35000)
        self.assertEqual(positions["BND"], 15000)

    def test_parse_positions_supports_multiline_input(self):
        positions = parse_positions("VTI:30000\nBND:15000")
        self.assertEqual(positions["VTI"], 30000)
        self.assertEqual(positions["BND"], 15000)

    def test_determine_risk_level_for_growth_profile(self):
        profile = InvestorProfile(
            capital=100000,
            monthly_contribution=5000,
            horizon_years=15,
            max_drawdown=30,
            objective="growth",
            positions={},
        )
        self.assertEqual(determine_risk_level(profile), "growth")

    def test_build_allocation_totals_one_hundred(self):
        allocation = build_allocation("balanced", "income")
        self.assertEqual(sum(allocation.values()), 100)

    def test_run_analysis_flags_concentration(self):
        profile = InvestorProfile(
            capital=100000,
            monthly_contribution=3000,
            horizon_years=8,
            max_drawdown=20,
            objective="balanced",
            positions={"AAPL": 40000, "BND": 10000},
        )
        result = run_analysis(profile)
        self.assertTrue(any("AAPL" in warning for warning in result.concentration_warnings))

    def test_validate_profile_form_returns_error_for_bad_positions(self):
        values, errors = validate_profile_form(
            {
                "capital": "100000",
                "monthly_contribution": "3000",
                "horizon_years": "10",
                "max_drawdown": "20",
                "objective": "balanced",
                "positions": "bad-format",
            }
        )
        self.assertEqual(values["objective"], "balanced")
        self.assertIn("positions", errors)

    def test_build_profile_parses_valid_form_values(self):
        profile = build_profile("100000", "3000", "10", "20", "balanced", "VTI:40000")
        self.assertEqual(profile.capital, 100000)
        self.assertEqual(profile.positions["VTI"], 40000)

    def test_select_market_data_tickers_respects_rank_and_limit(self):
        tickers = select_market_data_tickers(
            {
                "QQQ": 10000,
                "VTI": 40000,
                "BND": 15000,
                "VXUS": 12000,
                "VNQ": 8000,
                "AAPL": 5000,
            }
        )
        self.assertEqual(tickers, ["VTI", "BND", "VXUS", "QQQ", "VNQ"])

    def test_build_market_data_snapshot_uses_client(self):
        profile = InvestorProfile(
            capital=100000,
            monthly_contribution=3000,
            horizon_years=10,
            max_drawdown=20,
            objective="balanced",
            positions={"VTI": 40000, "BND": 15000},
        )
        snapshot = build_market_data_snapshot(profile, client=self.FakeMarketClient())
        self.assertEqual(snapshot.provider, "Fake Provider")
        self.assertEqual(len(snapshot.quotes), 2)
        self.assertFalse(snapshot.errors)

    def test_build_market_data_snapshot_without_api_key_returns_setup_note(self):
        profile = InvestorProfile(
            capital=100000,
            monthly_contribution=3000,
            horizon_years=10,
            max_drawdown=20,
            objective="balanced",
            positions={"VTI": 40000},
        )
        with patch.dict("os.environ", {}, clear=True):
            snapshot = build_market_data_snapshot(profile)
        self.assertFalse(snapshot.enabled)
        self.assertIn("ALPHAVANTAGE_API_KEY", snapshot.note)

    def test_load_local_env_populates_missing_env_values(self):
        with TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("ALPHAVANTAGE_API_KEY=test-key\n", encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True):
                load_local_env(str(env_path))
                self.assertEqual(os.environ["ALPHAVANTAGE_API_KEY"], "test-key")

    def test_render_page_contains_form_defaults(self):
        page = render_page(DEFAULT_FORM_VALUES, dashboard_html="<section>Dashboard</section>")
        self.assertIn("Generate Plan", page)
        self.assertIn("Stratum", page)
        self.assertIn("Dashboard", page)

    def test_render_result_panel_includes_market_data(self):
        profile = InvestorProfile(
            capital=100000,
            monthly_contribution=3000,
            horizon_years=10,
            max_drawdown=20,
            objective="balanced",
            positions={"VTI": 40000},
        )
        result = run_analysis(profile)
        snapshot = build_market_data_snapshot(profile, client=self.FakeMarketClient())
        panel = render_result_panel(profile, result, market_snapshot=snapshot)
        self.assertIn("Market Data", panel)
        self.assertIn("Fake Provider", panel)

    def test_build_net_positions_ignores_non_trade_rows(self):
        rows = [
            {
                "Symbol": "AAPL",
                "Quantity": "50",
                "Transaction Type": "BUY",
            },
            {
                "Symbol": "AAPL",
                "Quantity": "77",
                "Transaction Type": "SELL",
            },
            {
                "Symbol": "AAPL",
                "Quantity": "",
                "Transaction Type": "",
            },
        ]
        positions = build_net_positions(rows)
        self.assertEqual(positions["AAPL"], -27.0)

    def test_reconcile_positions_adds_synthetic_rows_to_expected_zero(self):
        headers = [
            "Symbol",
            "Current Price",
            "Trade Date",
            "Purchase Price",
            "Quantity",
            "Commission",
            "Comment",
            "Transaction Type",
        ]
        rows = [
            {
                "Symbol": "AAPL",
                "Current Price": "271.06",
                "Trade Date": "20210223",
                "Purchase Price": "120.72",
                "Quantity": "50",
                "Commission": "",
                "Comment": "",
                "Transaction Type": "BUY",
            },
            {
                "Symbol": "AAPL",
                "Current Price": "271.06",
                "Trade Date": "20220505",
                "Purchase Price": "157.38",
                "Quantity": "26",
                "Commission": "",
                "Comment": "",
                "Transaction Type": "BUY",
            },
            {
                "Symbol": "AAPL",
                "Current Price": "271.06",
                "Trade Date": "20250716",
                "Purchase Price": "210.7",
                "Quantity": "77",
                "Commission": "",
                "Comment": "",
                "Transaction Type": "SELL",
            },
        ]

        cleaned_rows, notes = reconcile_positions(headers, rows, {"AAPL": 0.0})

        self.assertEqual(build_net_positions(cleaned_rows)["AAPL"], 0.0)
        self.assertEqual(cleaned_rows[-1]["Transaction Type"], "BUY")
        self.assertEqual(cleaned_rows[-1]["Quantity"], "1")
        self.assertIn("Synthetic reconciliation", cleaned_rows[-1]["Comment"])
        self.assertTrue(notes)

    def test_portfolio_csv_round_trip(self):
        headers = ["Symbol", "Quantity", "Transaction Type"]
        rows = [{"Symbol": "QQQ", "Quantity": "10", "Transaction Type": "BUY"}]
        with TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "portfolio.csv"
            write_portfolio_csv(csv_path, headers, rows)
            loaded_headers, loaded_rows = load_portfolio_csv(csv_path)

        self.assertEqual(loaded_headers, headers)
        self.assertEqual(loaded_rows, rows)

    def test_build_position_market_values_keeps_positive_positions_only(self):
        rows = [
            {
                "Symbol": "QQQ",
                "Current Price": "100",
                "Quantity": "10",
                "Transaction Type": "BUY",
            },
            {
                "Symbol": "QQQ",
                "Current Price": "100",
                "Quantity": "3",
                "Transaction Type": "SELL",
            },
            {
                "Symbol": "AAPL",
                "Current Price": "50",
                "Quantity": "5",
                "Transaction Type": "SELL",
            },
        ]
        positions = build_position_market_values(rows)
        self.assertEqual(positions, {"QQQ": 700.0})

    def test_build_transactions_and_current_holdings(self):
        rows = [
            {
                "Symbol": "SPY",
                "Trade Date": "20240101",
                "Purchase Price": "500",
                "Quantity": "2",
                "Commission": "1",
                "Current Price": "550",
                "Comment": "",
                "Transaction Type": "BUY",
            },
            {
                "Symbol": "SPY",
                "Trade Date": "20240201",
                "Purchase Price": "520",
                "Quantity": "1",
                "Commission": "0",
                "Current Price": "550",
                "Comment": "",
                "Transaction Type": "SELL",
            },
        ]
        transactions = build_transactions(rows)
        holdings, total_realized_pnl = build_current_holdings(transactions)

        self.assertEqual(len(transactions), 2)
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0].symbol, "SPY")
        self.assertAlmostEqual(holdings[0].quantity, 1.0)
        self.assertAlmostEqual(holdings[0].market_value, 550.0)
        self.assertAlmostEqual(holdings[0].realized_pnl, 19.5)
        self.assertAlmostEqual(total_realized_pnl, 19.5)

    def test_build_holding_history_extends_to_as_of_date(self):
        rows = [
            {
                "Symbol": "QQQ",
                "Trade Date": "20240101",
                "Purchase Price": "400",
                "Quantity": "1",
                "Commission": "0",
                "Current Price": "450",
                "Comment": "",
                "Transaction Type": "BUY",
            }
        ]
        transactions = build_transactions(rows)
        snapshots = build_holding_history(
            transactions,
            ["QQQ"],
            as_of_date=date(2024, 2, 1),
        )

        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[-1].quantities["QQQ"], 1.0)

    def test_load_positions_input_uses_cleaned_portfolio_csv(self):
        headers = [
            "Symbol",
            "Current Price",
            "Quantity",
            "Transaction Type",
        ]
        rows = [
            {
                "Symbol": "SPY",
                "Current Price": "500",
                "Quantity": "2",
                "Transaction Type": "BUY",
            },
            {
                "Symbol": "QQQ",
                "Current Price": "400",
                "Quantity": "1",
                "Transaction Type": "BUY",
            },
        ]
        with TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "portfolio.cleaned.csv"
            write_portfolio_csv(csv_path, headers, rows)
            loaded_positions = load_positions_input(csv_path)

        self.assertEqual(loaded_positions, "SPY:1000.00,QQQ:400.00")

    def test_load_portfolio_dashboard_reads_holdings_and_history(self):
        headers = [
            "Symbol",
            "Current Price",
            "Date",
            "Time",
            "Trade Date",
            "Purchase Price",
            "Quantity",
            "Commission",
            "Comment",
            "Transaction Type",
        ]
        rows = [
            {
                "Symbol": "SPY",
                "Current Price": "500",
                "Date": "2026/04/24",
                "Time": "16:00 EDT",
                "Trade Date": "20240101",
                "Purchase Price": "400",
                "Quantity": "2",
                "Commission": "0",
                "Comment": "",
                "Transaction Type": "BUY",
            },
            {
                "Symbol": "QQQ",
                "Current Price": "300",
                "Date": "2026/04/24",
                "Time": "16:00 EDT",
                "Trade Date": "20240201",
                "Purchase Price": "250",
                "Quantity": "1",
                "Commission": "0",
                "Comment": "",
                "Transaction Type": "BUY",
            },
        ]
        with TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "portfolio.cleaned.csv"
            write_portfolio_csv(csv_path, headers, rows)
            dashboard = load_portfolio_dashboard(csv_path)

        self.assertIsNotNone(dashboard)
        assert dashboard is not None
        self.assertEqual(dashboard.holdings[0].symbol, "SPY")
        self.assertEqual(dashboard.history_symbols, ["SPY", "QQQ"])
        self.assertEqual(dashboard.as_of_label, "2026/04/24 16:00 EDT")

    def test_resolve_window_supports_custom_and_ytd(self):
        key, start_date, end_date = resolve_window(
            date(2026, 4, 24),
            window_key="ytd",
        )
        self.assertEqual(key, "ytd")
        self.assertEqual(start_date, date(2026, 1, 1))
        self.assertEqual(end_date, date(2026, 4, 24))

        key, start_date, end_date = resolve_window(
            date(2026, 4, 24),
            window_key="1y",
            start_raw="2025-01-01",
            end_raw="2025-12-31",
        )
        self.assertEqual(key, "custom")
        self.assertEqual(start_date, date(2025, 1, 1))
        self.assertEqual(end_date, date(2025, 12, 31))

    def test_build_portfolio_performance_prices_current_holdings_over_window(self):
        headers = [
            "Symbol",
            "Current Price",
            "Date",
            "Time",
            "Trade Date",
            "Purchase Price",
            "Quantity",
            "Commission",
            "Comment",
            "Transaction Type",
        ]
        rows = [
            {
                "Symbol": "SPY",
                "Current Price": "500",
                "Date": "2026/04/24",
                "Time": "16:00 EDT",
                "Trade Date": "2024-01-05".replace("-", ""),
                "Purchase Price": "400",
                "Quantity": "1",
                "Commission": "0",
                "Comment": "",
                "Transaction Type": "BUY",
            },
            {
                "Symbol": "QQQ",
                "Current Price": "300",
                "Date": "2026/04/24",
                "Time": "16:00 EDT",
                "Trade Date": "2024-01-12".replace("-", ""),
                "Purchase Price": "200",
                "Quantity": "2",
                "Commission": "0",
                "Comment": "",
                "Transaction Type": "BUY",
            },
        ]
        with TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "portfolio.cleaned.csv"
            write_portfolio_csv(csv_path, headers, rows)
            dashboard = load_portfolio_dashboard(csv_path)

        assert dashboard is not None
        client = self.FakeHistoricalClient(
            {
                "SPY": {
                    date(2024, 1, 5): 400.0,
                    date(2024, 1, 12): 410.0,
                    date(2024, 1, 19): 420.0,
                },
                "QQQ": {
                    date(2024, 1, 5): 200.0,
                    date(2024, 1, 12): 210.0,
                    date(2024, 1, 19): 220.0,
                },
            }
        )
        performance = build_portfolio_performance(
            dashboard,
            window_key="all",
            client=client,
        )

        self.assertTrue(performance.available)
        self.assertEqual(performance.points[0].total_return, 0.0)
        self.assertAlmostEqual(performance.points[0].total_value, 800.0)
        self.assertAlmostEqual(performance.points[-1].total_value, 860.0)
        self.assertAlmostEqual(performance.points[-1].total_return, 0.075)
        holding_returns = {item.symbol: item.return_pct for item in performance.holdings}
        self.assertAlmostEqual(holding_returns["SPY"], 0.05)
        self.assertAlmostEqual(holding_returns["QQQ"], 0.1)

    def test_build_portfolio_performance_rebases_returns_inside_window(self):
        headers = [
            "Symbol",
            "Current Price",
            "Date",
            "Time",
            "Trade Date",
            "Purchase Price",
            "Quantity",
            "Commission",
            "Comment",
            "Transaction Type",
        ]
        rows = [
            {
                "Symbol": "QQQ",
                "Current Price": "300",
                "Date": "2026/04/24",
                "Time": "16:00 EDT",
                "Trade Date": "20241220",
                "Purchase Price": "200",
                "Quantity": "1",
                "Commission": "0",
                "Comment": "",
                "Transaction Type": "BUY",
            }
        ]
        with TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "portfolio.cleaned.csv"
            write_portfolio_csv(csv_path, headers, rows)
            dashboard = load_portfolio_dashboard(csv_path)

        assert dashboard is not None
        dashboard.as_of_label = "2026/04/24 16:00 EDT"
        client = self.FakeHistoricalClient(
            {
                "QQQ": {
                    date(2024, 12, 27): 210.0,
                    date(2025, 1, 3): 220.0,
                    date(2025, 1, 10): 230.0,
                },
                "SPY": {
                    date(2024, 12, 27): 400.0,
                    date(2025, 1, 3): 404.0,
                    date(2025, 1, 10): 408.0,
                },
            }
        )
        performance = build_portfolio_performance(
            dashboard,
            window_key="ytd",
            end_raw="2025-01-10",
            client=client,
        )

        self.assertTrue(performance.available)
        self.assertEqual(performance.points[0].trade_date, date(2025, 1, 3))
        self.assertAlmostEqual(performance.points[0].total_return, 0.0)
        self.assertAlmostEqual(performance.points[-1].total_return, (230.0 / 220.0) - 1.0)

    def test_build_default_form_values_prefills_positions_from_portfolio_csv(self):
        headers = [
            "Symbol",
            "Current Price",
            "Quantity",
            "Transaction Type",
        ]
        rows = [
            {
                "Symbol": "SPY",
                "Current Price": "500",
                "Quantity": "2",
                "Transaction Type": "BUY",
            }
        ]
        with TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                data_dir = Path(tmpdir) / "data"
                data_dir.mkdir()
                write_portfolio_csv(data_dir / "portfolio.cleaned.csv", headers, rows)
                values = build_default_form_values()
            finally:
                os.chdir(original_cwd)

        self.assertEqual(values["positions"], "SPY:1000.00")

    def test_format_positions_input_sorts_by_descending_value(self):
        text = format_positions_input({"QQQ": 400.0, "SPY": 1000.0})
        self.assertEqual(text, "SPY:1000.00,QQQ:400.00")


if __name__ == "__main__":
    unittest.main()
