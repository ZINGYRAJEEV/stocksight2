"""Tests for earnings calendar days-to-results helpers."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from earnings_calendar import (
    DAYS_TODAY_COL,
    apply_results_date_display_columns,
    days_to_results,
    load_scan_csv_compatible,
    local_today,
    place_days_before_ticker,
)


IST = ZoneInfo("Asia/Kolkata")
ET = ZoneInfo("America/New_York")


class TestDaysToResults(unittest.TestCase):
    def test_future_date(self):
        self.assertEqual(
            days_to_results("2026-10-01", as_of=date(2026, 9, 20)),
            11,
        )

    def test_same_day_zero(self):
        self.assertEqual(
            days_to_results("2026-09-20", as_of=date(2026, 9, 20)),
            0,
        )

    def test_past_date_negative(self):
        self.assertEqual(
            days_to_results("2026-09-01", as_of=date(2026, 9, 20)),
            -19,
        )

    def test_missing_date(self):
        self.assertIsNone(days_to_results(None, as_of=date(2026, 9, 20)))
        self.assertIsNone(days_to_results("", as_of=date(2026, 9, 20)))
        self.assertIsNone(days_to_results("—", as_of=date(2026, 9, 20)))

    def test_timezone_midnight_edge(self):
        # 2026-09-20 23:30 ET = already 2026-09-21 in IST
        now_et = datetime(2026, 9, 20, 23, 30, tzinfo=ET)
        now_ist_view = now_et.astimezone(IST)
        self.assertEqual(local_today("AAPL", now=now_et), date(2026, 9, 20))
        self.assertEqual(local_today("INFY.NS", now=now_et), date(2026, 9, 21))
        # Same absolute instant: US vs NSE "today" differs near midnight
        self.assertNotEqual(
            local_today("AAPL", now=now_et),
            local_today("RELIANCE.NS", now=now_et),
        )
        # Days calc uses exchange-local today
        d_us = days_to_results("2026-09-21", raw_ticker="AAPL", now=now_et)
        d_in = days_to_results("2026-09-21", raw_ticker="INFY.NS", now=now_et)
        self.assertEqual(d_us, 1)
        self.assertEqual(d_in, 0)
        self.assertEqual(now_ist_view.date(), date(2026, 9, 21))


class TestColumnPlacement(unittest.TestCase):
    def test_days_immediately_before_ticker(self):
        df = pd.DataFrame(
            {
                "Score": [1],
                "Ticker": ["INFY"],
                "Price": [10.0],
                "next_results_date": ["2026-10-01"],
                "Raw": ["INFY.NS"],
            }
        )
        out = apply_results_date_display_columns(df, raw_ticker_col="Raw", now=datetime(2026, 9, 20, 12, 0, tzinfo=IST))
        cols = list(out.columns)
        self.assertIn(DAYS_TODAY_COL, cols)
        self.assertIn("Ticker", cols)
        self.assertEqual(cols.index(DAYS_TODAY_COL), cols.index("Ticker") - 1)

    def test_place_days_before_ticker_helper(self):
        df = pd.DataFrame({"A": [1], "Ticker": ["X"], DAYS_TODAY_COL: [3], "B": [2]})
        out = place_days_before_ticker(df)
        cols = list(out.columns)
        self.assertEqual(cols.index(DAYS_TODAY_COL), cols.index("Ticker") - 1)
        self.assertEqual(cols, ["A", DAYS_TODAY_COL, "Ticker", "B"])


class TestOldCsvLoad(unittest.TestCase):
    def test_old_csv_without_new_columns(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old_scan.csv"
            path.write_text("Ticker,Price,PE\nINFY,1500,25\n", encoding="utf-8")
            df = load_scan_csv_compatible(path)
            self.assertEqual(list(df["Ticker"]), ["INFY"])
            for col in (
                DAYS_TODAY_COL,
                "next_results_date",
                "results_date_status",
                "days_to_results_at_scan",
                "scan_date",
            ):
                self.assertIn(col, df.columns)
                self.assertTrue(pd.isna(df[col].iloc[0]))


if __name__ == "__main__":
    unittest.main()
