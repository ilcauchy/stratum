import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from stratum import (
    DEFAULT_FORM_VALUES,
    InvestorProfile,
    MarketQuote,
    build_market_data_snapshot,
    build_allocation,
    build_profile,
    determine_risk_level,
    load_local_env,
    parse_positions,
    render_page,
    render_result_panel,
    run_analysis,
    select_market_data_tickers,
    validate_profile_form,
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
        page = render_page(DEFAULT_FORM_VALUES)
        self.assertIn("Generate Plan", page)
        self.assertIn("Stratum", page)

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


if __name__ == "__main__":
    unittest.main()
