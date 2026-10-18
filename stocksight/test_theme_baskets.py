"""Tests for Emerging Market Growth Club theme basket."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from pathlib import Path

import pandas as pd

from theme_baskets import (
    EMERGING_MARKET_GROWTH_CLUB,
    EMERGING_MARKET_GROWTH_CLUB_TICKERS,
    EMERGING_MARKET_LABEL,
    emerging_market_universe,
    is_nse_scan_source,
    is_theme_scan_source,
    nse_scan_sources,
    theme_universe_map,
)


class TestEmergingMarketBasket(unittest.TestCase):
    def test_core_and_peer_names(self):
        self.assertEqual(len(EMERGING_MARKET_GROWTH_CLUB), 18)
        tickers = emerging_market_universe()
        self.assertEqual(tickers, EMERGING_MARKET_GROWTH_CLUB_TICKERS)
        self.assertEqual(len(set(tickers)), 18)
        core = {
            "E2E.NS",
            "SUDEEPPHRM.NS",
            "AEROFLEX.NS",
            "AMANTA.NS",
            "BLUESTONE.NS",
        }
        self.assertTrue(core.issubset(set(tickers)))
        labels = {r["label"] for r in EMERGING_MARKET_GROWTH_CLUB}
        self.assertIn("Sudeep Pharma", labels)
        self.assertIn("Netweb Technologies", labels)
        self.assertIn("Kalyan Jewellers", labels)

    def test_in_nse_equity_cache(self):
        cache = Path(__file__).resolve().parent / "data" / "nse_equity_symbols.txt"
        self.assertTrue(cache.is_file())
        listed = set(cache.read_text(encoding="utf-8").split())
        for t in EMERGING_MARKET_GROWTH_CLUB_TICKERS:
            self.assertIn(t, listed, f"{t} missing from NSE equity snapshot")

    def test_nse_scan_source_helpers(self):
        from multibagger import CURATED_EUROPE_LABEL

        self.assertTrue(is_theme_scan_source(EMERGING_MARKET_LABEL))
        self.assertTrue(is_nse_scan_source(EMERGING_MARKET_LABEL))
        self.assertTrue(is_nse_scan_source("Curated NSE (ROCE export names)"))
        self.assertTrue(is_nse_scan_source("Nifty 50 (NSE)"))
        self.assertFalse(is_nse_scan_source("S&P 500 (NYSE)"))
        self.assertFalse(is_nse_scan_source(CURATED_EUROPE_LABEL))
        self.assertNotIn(CURATED_EUROPE_LABEL, nse_scan_sources([CURATED_EUROPE_LABEL]))

    def test_europe_fundamentals_keep_native_eur_market_cap(self):
        from multibagger import (
            MultibaggerFilters,
            _passes_filters,
            currency_for_ticker,
            extract_multibagger_fundamentals,
        )

        fund = extract_multibagger_fundamentals(
            {
                "currency": "EUR",
                "marketCap": 2_000_000_000,
                "returnOnCapitalEmployed": 0.2,
            }
        )

        self.assertEqual(currency_for_ticker("SAP.DE"), "EUR")
        self.assertEqual(fund["market_cap_eur_bn"], 2.0)
        self.assertIsNone(fund["market_cap_usd_bn"])
        self.assertEqual(fund["market_cap_display"], "€2.00 B")
        from screener import EUROPE_LARGE_CAP_LABEL, get_universe_tickers

        self.assertEqual(len(get_universe_tickers(EUROPE_LARGE_CAP_LABEL)), 22)
        from multibagger import CURATED_EUROPE_LABEL, EQUITY_SCAN_SOURCES
        self.assertIn(CURATED_EUROPE_LABEL, EQUITY_SCAN_SOURCES)
        from screener import EUROPE_BENCHMARK, benchmark_ticker_for, get_stock_links

        self.assertEqual(benchmark_ticker_for("SAP.DE"), EUROPE_BENCHMARK)
        self.assertIn("SAP:ETR", get_stock_links("SAP.DE")["Google Finance"])
        self.assertFalse(
            _passes_filters(
                fund,
                MultibaggerFilters(apply_mcap_filter=True, max_market_cap_eur_bn=1.5),
            )
        )

    def test_earnings_surprise_uses_eur_cap_threshold(self):
        from earnings_surprise_screener import EarningsSurpriseFilters, _passes_filters

        fund = {
            "currency": "EUR",
            "market_cap_eur_bn": 2.0,
            "roce_pct": 20.0,
        }
        qoq = {"qoq_sales_pct": 20.0, "qoq_profit_pct": 30.0}

        passed, _ = _passes_filters(
            qoq,
            fund,
            {},
            EarningsSurpriseFilters(
                require_future_quality=False,
                min_roce_pct=10.0,
                min_market_cap_eur_bn=1.5,
            ),
        )
        rejected, _ = _passes_filters(
            qoq,
            fund,
            {},
            EarningsSurpriseFilters(
                require_future_quality=False,
                min_roce_pct=10.0,
                min_market_cap_eur_bn=2.5,
            ),
        )

        self.assertTrue(passed)
        self.assertFalse(rejected)

    def test_pead_uses_eur_cap_and_local_liquidity_thresholds(self):
        from pead_screener import PEADFilters, _passes_filters

        fund = {
            "currency": "EUR",
            "market_cap_eur_bn": 2.0,
        }
        metrics = {"days_since_results": 30, "avg_daily_value_native_mn": 2.0}
        passed, _ = _passes_filters(
            1.5,
            metrics,
            fund,
            PEADFilters(
                relaxed_scan=True,
                min_market_cap_eur_bn=1.5,
                min_avg_daily_value_eur_mn=1.0,
            ),
        )
        rejected, _ = _passes_filters(
            1.5,
            metrics,
            fund,
            PEADFilters(
                relaxed_scan=True,
                min_market_cap_eur_bn=2.5,
                min_avg_daily_value_eur_mn=1.0,
            ),
        )

        self.assertTrue(passed)
        self.assertFalse(rejected)

    def test_volume_led_uses_eur_market_cap_threshold(self):
        from volume_led_screener import (
            BaseScreenThresholds,
            VolumeLedFundamentals,
            evaluate_base_screen,
        )

        fund = VolumeLedFundamentals(
            sales_growth_1y_pct=30.0,
            sales_growth_3y_pct=20.0,
            profit_growth_1y_pct=40.0,
            profit_growth_3y_pct=25.0,
            qtr_sales_var_pct=25.0,
            qtr_profit_var_pct=35.0,
            roce_pct=30.0,
            debt_equity=0.2,
            market_cap_eur_bn=2.0,
            currency="EUR",
        )

        passed, _, _, _, _ = evaluate_base_screen(
            fund,
            BaseScreenThresholds(
                min_sales_growth_3y_pct=15.0,
                min_qtr_sales_var_pct=15.0,
                min_profit_growth_3y_pct=20.0,
                min_roce_pct=20.0,
                min_market_cap_eur_bn=1.0,
            ),
        )
        rejected, _, _, _, _ = evaluate_base_screen(
            fund,
            BaseScreenThresholds(
                min_sales_growth_3y_pct=15.0,
                min_qtr_sales_var_pct=15.0,
                min_profit_growth_3y_pct=20.0,
                min_roce_pct=20.0,
                min_market_cap_eur_bn=3.0,
            ),
        )

        self.assertTrue(passed)
        self.assertFalse(rejected)
        fund.market_cap_eur_bn = None
        missing_cap, _, _, _, _ = evaluate_base_screen(
            fund,
            BaseScreenThresholds(
                min_sales_growth_3y_pct=15.0,
                min_qtr_sales_var_pct=15.0,
                min_profit_growth_3y_pct=20.0,
                min_roce_pct=20.0,
                min_market_cap_eur_bn=0.0,
            ),
        )
        self.assertFalse(missing_cap)

    def test_popular_screens_expose_europe_with_native_financials(self):
        from multibagger import CURATED_EUROPE_LABEL, currency_for_ticker
        from popular_screens import SCAN_SOURCES, _fundamentals

        fund = _fundamentals(
            {"currency": "EUR", "marketCap": 2_000_000_000, "totalRevenue": 100_000_000},
            default_currency=currency_for_ticker("SAP.DE"),
        )

        self.assertIn(CURATED_EUROPE_LABEL, SCAN_SOURCES)
        self.assertEqual(fund["currency"], "EUR")
        self.assertEqual(fund["market_cap_eur_bn"], 2.0)
        self.assertIsNone(fund["revenue_cr"])

    def test_peter_lynch_uses_eur_large_cap_value(self):
        from peter_lynch import _is_large_cap

        self.assertTrue(_is_large_cap({"market_cap_eur_bn": 60.0}, "EUR"))
        self.assertFalse(_is_large_cap({"market_cap_eur_bn": 40.0}, "EUR"))

    def test_multibagger_patterns_builds_annuals_from_yahoo(self):
        from multibagger_patterns_screener import _yahoo_annuals

        columns = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]
        stock = SimpleNamespace(
            financials=pd.DataFrame(
                [
                    [200.0, 160.0, 120.0, 100.0],
                    [30.0, 20.0, 12.0, 10.0],
                    [50.0, 40.0, 30.0, 25.0],
                ],
                index=["Total Revenue", "Net Income", "Operating Income"],
                columns=columns,
            ),
            cashflow=pd.DataFrame(
                [[40.0, 30.0, 20.0, 15.0]],
                index=["Operating Cash Flow"],
                columns=columns,
            ),
        )

        annuals = _yahoo_annuals(stock)

        self.assertEqual(len(annuals.sales), 4)
        self.assertEqual(annuals.sales[0], (2022, 100.0))
        self.assertEqual(annuals.net_profit[-1], (2025, 30.0))
        self.assertEqual(annuals.opm_pct[2025], 25.0)
        self.assertEqual(annuals.cfo[-1], (2025, 40.0))
        self.assertIn("Yahoo Finance", annuals.source)

    def test_multibagger_patterns_uses_eur_cap_bounds(self):
        from multibagger_patterns_screener import MultibaggerPatternFilters, _passes

        metrics = {
            "sales_yoy_pct": 90.0,
            "profit_yoy_pct": 150.0,
            "cfo_to_pat": 1.2,
            "opm_delta_3y_pp": 4.0,
            "market_cap_eur_bn": 2.0,
            "currency": "EUR",
            "roce_pct": 20.0,
            "pe": 20.0,
            "asset_light": True,
        }
        passed, _ = _passes(
            metrics,
            MultibaggerPatternFilters(
                min_sales_yoy_pct=40.0,
                min_profit_yoy_pct=80.0,
                require_profit_beats_sales=True,
                require_cash_backed=True,
                min_market_cap_eur_bn=1.0,
                max_market_cap_eur_bn=3.0,
            ),
            [],
            False,
        )
        self.assertTrue(passed)

    def test_wired_into_universes(self):
        from multibagger import SCAN_SOURCES, resolve_scan_tickers
        from screener import UNIVERSES, get_universe_tickers

        self.assertIn(EMERGING_MARKET_LABEL, UNIVERSES)
        self.assertEqual(
            get_universe_tickers(EMERGING_MARKET_LABEL),
            EMERGING_MARKET_GROWTH_CLUB_TICKERS,
        )
        self.assertIn(EMERGING_MARKET_LABEL, SCAN_SOURCES)
        # Theme appears right after curated NSE
        self.assertEqual(SCAN_SOURCES[1], EMERGING_MARKET_LABEL)
        resolved = resolve_scan_tickers(EMERGING_MARKET_LABEL)
        self.assertEqual(len(resolved), 18)
        self.assertEqual([r for _, r in resolved], EMERGING_MARKET_GROWTH_CLUB_TICKERS)

    def test_nse_scan_sources_order(self):
        from multibagger import SCAN_SOURCES

        ordered = nse_scan_sources(SCAN_SOURCES)
        self.assertIn(EMERGING_MARKET_LABEL, ordered)
        self.assertLess(ordered.index(EMERGING_MARKET_LABEL), ordered.index("Nifty 50 (NSE)"))

    def test_theme_map_and_investment_course_sector(self):
        m = theme_universe_map()
        self.assertIn(EMERGING_MARKET_LABEL, m)
        from investment_course_screener import SECTOR_SCAN_SOURCES

        self.assertIn(EMERGING_MARKET_LABEL, SECTOR_SCAN_SOURCES)
        self.assertEqual(
            SECTOR_SCAN_SOURCES[EMERGING_MARKET_LABEL],
            EMERGING_MARKET_GROWTH_CLUB_TICKERS,
        )


if __name__ == "__main__":
    unittest.main()
