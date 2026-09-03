"""Tests for Emerging Market Growth Club theme basket."""

from __future__ import annotations

import unittest
from pathlib import Path

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
        self.assertTrue(is_theme_scan_source(EMERGING_MARKET_LABEL))
        self.assertTrue(is_nse_scan_source(EMERGING_MARKET_LABEL))
        self.assertTrue(is_nse_scan_source("Curated NSE (ROCE export names)"))
        self.assertTrue(is_nse_scan_source("Nifty 50 (NSE)"))
        self.assertFalse(is_nse_scan_source("S&P 500 (NYSE)"))

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
