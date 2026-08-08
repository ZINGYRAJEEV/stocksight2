"""Tests for Fundamental Screener funnel shortlist store."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fundamental_funnel_store import (
    TIER_STRICT,
    TIER_WATCHLIST,
    clear_all_shortlists,
    load_tier_shortlist,
    save_tier_shortlist,
    shortlist_as_universe,
    shortlist_summary,
)
from fundamental_screener import FundamentalResult


def _hit(ticker: str) -> FundamentalResult:
    return FundamentalResult(
        ticker=ticker,
        raw_ticker=f"{ticker}.NS",
        label=ticker,
        tier="watchlist",
        price=100.0,
        market_cap_cr=1000.0,
        market_cap_display="₹1,000 Cr",
        debt_equity=0.1,
        interest_coverage=None,
        current_ratio=None,
        promoter_holding_pct=50.0,
        promoter_change_pct=0.0,
        pledged_pct=0.0,
        roe_pct=20.0,
        avg_roe_3y_pct=18.0,
        roce_pct=22.0,
        roa_pct=10.0,
        opm_pct=15.0,
        sales_growth_3y_pct=12.0,
        profit_growth_3y_pct=14.0,
        yoy_sales_pct=11.0,
        yoy_profit_pct=12.0,
        pe=20.0,
        industry_pe=25.0,
        peg=1.2,
        price_to_book=4.0,
        ret_3m_pct=5.0,
        ret_6m_pct=12.0,
        ret_1y_pct=18.0,
        score=30.0,
        verdict="ok",
    )


class TestFundamentalFunnelStore(unittest.TestCase):
    def test_watchlist_refresh_and_clear_on_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "funnel.json"
            with patch("fundamental_funnel_store.FUNNEL_PATH", path):
                save_tier_shortlist(
                    TIER_WATCHLIST,
                    [_hit("INFY"), _hit("TCS")],
                    source_universe="Nifty 50 (NSE)",
                )
                block = load_tier_shortlist(TIER_WATCHLIST)
                self.assertIsNotNone(block)
                self.assertEqual(block["count"], 2)
                uni = shortlist_as_universe(TIER_WATCHLIST)
                self.assertEqual([r for _, r in uni], ["INFY.NS", "TCS.NS"])
                self.assertIn("2 names", shortlist_summary(TIER_WATCHLIST))

                # Refresh overwrites
                save_tier_shortlist(
                    TIER_WATCHLIST,
                    [_hit("RELIANCE")],
                    source_universe="Curated",
                )
                uni2 = shortlist_as_universe(TIER_WATCHLIST)
                self.assertEqual([r for _, r in uni2], ["RELIANCE.NS"])

                # Empty Tier 1 clears shortlist
                save_tier_shortlist(TIER_WATCHLIST, [], source_universe="Curated")
                self.assertIsNone(load_tier_shortlist(TIER_WATCHLIST))
                self.assertEqual(shortlist_as_universe(TIER_WATCHLIST), [])

    def test_strict_independent_of_watchlist(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "funnel.json"
            with patch("fundamental_funnel_store.FUNNEL_PATH", path):
                save_tier_shortlist(
                    TIER_WATCHLIST, [_hit("INFY")], source_universe="Nifty 50"
                )
                save_tier_shortlist(
                    TIER_STRICT, [_hit("TCS")], source_universe="Last Watchlist"
                )
                self.assertEqual(
                    [r for _, r in shortlist_as_universe(TIER_WATCHLIST)],
                    ["INFY.NS"],
                )
                self.assertEqual(
                    [r for _, r in shortlist_as_universe(TIER_STRICT)],
                    ["TCS.NS"],
                )
                clear_all_shortlists()
                self.assertIsNone(load_tier_shortlist(TIER_WATCHLIST))
                self.assertIsNone(load_tier_shortlist(TIER_STRICT))

    def test_scan_accepts_ticker_override(self):
        from fundamental_screener import filters_for_tier, scan_fundamental_framework

        with patch(
            "fundamental_screener.resolve_scan_tickers",
            return_value=[("SHOULD_NOT", "SKIP.NS")],
        ):
            with patch(
                "fundamental_screener.fetch_screener_company_html",
                return_value="",
            ):
                # Empty HTML → no hits, but must iterate only override list (len 1)
                seen: list[str] = []

                def cb(i, t, s):
                    seen.append(s)

                hits = scan_fundamental_framework(
                    "Nifty 50 (NSE)",
                    filters=filters_for_tier("strict"),
                    progress_cb=cb,
                    tickers=[("Infosys", "INFY.NS")],
                )
                self.assertEqual(seen, ["INFY.NS"])
                self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
