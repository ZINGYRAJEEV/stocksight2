"""Tests for Emerging Market Growth Club theme basket."""

from __future__ import annotations

import unittest
from pathlib import Path

from theme_baskets import (
    EMERGING_MARKET_GROWTH_CLUB,
    EMERGING_MARKET_GROWTH_CLUB_TICKERS,
    EMERGING_MARKET_LABEL,
    emerging_market_universe,
    theme_universe_map,
)


class TestEmergingMarketBasket(unittest.TestCase):
    def test_five_validated_names(self):
        self.assertEqual(len(EMERGING_MARKET_GROWTH_CLUB), 5)
        tickers = emerging_market_universe()
        self.assertEqual(tickers, EMERGING_MARKET_GROWTH_CLUB_TICKERS)
        self.assertEqual(
            set(tickers),
            {
                "E2E.NS",
                "SUDEEPPHRM.NS",
                "AEROFLEX.NS",
                "AMANTA.NS",
                "BLUESTONE.NS",
            },
        )
        # Name corrections documented for OCR/infographic mismatches
        labels = {r["label"] for r in EMERGING_MARKET_GROWTH_CLUB}
        self.assertIn("Sudeep Pharma", labels)
        self.assertIn("Amanta Healthcare", labels)
        self.assertIn("Bluestone Jewellery", labels)

    def test_in_nse_equity_cache(self):
        cache = Path(__file__).resolve().parent / "data" / "nse_equity_symbols.txt"
        self.assertTrue(cache.is_file())
        listed = set(cache.read_text(encoding="utf-8").split())
        for t in EMERGING_MARKET_GROWTH_CLUB_TICKERS:
            self.assertIn(t, listed, f"{t} missing from NSE equity snapshot")

    def test_wired_into_universes(self):
        from screener import UNIVERSES, get_universe_tickers
        from multibagger import SCAN_SOURCES, resolve_scan_tickers

        self.assertIn(EMERGING_MARKET_LABEL, UNIVERSES)
        self.assertEqual(
            get_universe_tickers(EMERGING_MARKET_LABEL),
            EMERGING_MARKET_GROWTH_CLUB_TICKERS,
        )
        self.assertIn(EMERGING_MARKET_LABEL, SCAN_SOURCES)
        resolved = resolve_scan_tickers(EMERGING_MARKET_LABEL)
        self.assertEqual(len(resolved), 5)
        self.assertEqual([r for _, r in resolved], EMERGING_MARKET_GROWTH_CLUB_TICKERS)

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
