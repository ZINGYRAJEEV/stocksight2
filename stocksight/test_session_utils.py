"""Tests for session_utils helpers used by screener result tables."""

from __future__ import annotations

import unittest

import pandas as pd

from session_utils import deduplicate_scan_results


class TestDeduplicateScanResults(unittest.TestCase):
    def test_drops_duplicate_tickers_keeps_first(self):
        df = pd.DataFrame(
            [
                {"Ticker": "INFY", "Score": 10},
                {"Ticker": "TCS", "Score": 20},
                {"Ticker": "INFY", "Score": 99},
            ]
        )
        out = deduplicate_scan_results(df)
        self.assertEqual(len(out), 2)
        self.assertEqual(list(out["Ticker"]), ["INFY", "TCS"])
        self.assertEqual(int(out.iloc[0]["Score"]), 10)

    def test_accepts_ticker_col_kwarg(self):
        """Regression: Streamlit Cloud TypeError when callers pass ticker_col=."""
        df = pd.DataFrame(
            [
                {"Symbol": "A", "Score": 1},
                {"Symbol": "A", "Score": 2},
                {"Symbol": "B", "Score": 3},
            ]
        )
        out = deduplicate_scan_results(df, ticker_col="Symbol")
        self.assertEqual(len(out), 2)
        self.assertEqual(list(out["Symbol"]), ["A", "B"])

    def test_fallback_when_ticker_missing_uses_raw(self):
        df = pd.DataFrame(
            [
                {"Raw": "INFY.NS", "Score": 1},
                {"Raw": "INFY.NS", "Score": 2},
            ]
        )
        out = deduplicate_scan_results(df)
        self.assertEqual(len(out), 1)

    def test_empty_and_none(self):
        self.assertTrue(deduplicate_scan_results(pd.DataFrame()).empty)
        self.assertIsNone(deduplicate_scan_results(None))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
