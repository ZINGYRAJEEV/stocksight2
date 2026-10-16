"""Unit tests for dual-market mood helpers (no network)."""

from __future__ import annotations

import unittest

from market_sentiment import cross_market_read, mood_emoji, vix_bucket


class TestMarketMoodHelpers(unittest.TestCase):
    def test_vix_buckets(self):
        self.assertEqual(vix_bucket(11.0), "calm")
        self.assertEqual(vix_bucket(15.0), "normal")
        self.assertEqual(vix_bucket(20.0), "elevated")
        self.assertEqual(vix_bucket(25.0), "stress")
        self.assertEqual(vix_bucket(None), "n/a")
        self.assertEqual(vix_bucket(15.5, india=True), "normal")
        self.assertEqual(vix_bucket(21.0, india=True), "stress")

    def test_mood_emoji(self):
        self.assertEqual(mood_emoji("Bullish"), "🟢")
        self.assertEqual(mood_emoji("Bearish"), "🔴")
        self.assertEqual(mood_emoji("Neutral"), "🟡")

    def test_cross_read(self):
        both_bull = cross_market_read("Bullish", "Bullish")
        self.assertIn("constructive", both_bull.lower())
        both_bear = cross_market_read("Bearish", "Bearish")
        self.assertIn("defensive", both_bear.lower())
        us_leads_risk = cross_market_read("Neutral", "Bearish")
        self.assertIn("overnight", us_leads_risk.lower())
        mixed = cross_market_read("Neutral", "Neutral")
        self.assertIn("Mixed", mixed)


if __name__ == "__main__":
    unittest.main()
