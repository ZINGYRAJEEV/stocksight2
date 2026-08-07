"""Tests for Investment Course scan checkpoint / chunk resume."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_course_screener import InvestmentCourseFilters, InvestmentCourseResult, ScanChunkResult
import scan_checkpoint_store as ckpt


def _sample_hit(ticker: str = "INFY") -> InvestmentCourseResult:
    return InvestmentCourseResult(
        ticker=ticker,
        raw_ticker=f"{ticker}.NS",
        label=ticker,
        category="Fast Grower",
        sector="Technology",
        price=100.0,
        pe=20.0,
        fy_median_pe=22.0,
        pct_vs_median=-9.0,
        n_fy_points=5,
        sales_growth_3y_pct=18.0,
        profit_growth_3y_pct=20.0,
        sales_growth_ttm_pct=15.0,
        profit_growth_ttm_pct=16.0,
        peg=1.0,
        peg_verdict="ok",
        roce_pct=25.0,
        market_cap_cr=5000.0,
        market_cap_display="₹5,000 Cr",
        opm_latest_pct=20.0,
        opm_delta_pp=1.0,
        interest_latest=1.0,
        interest_delta=-0.1,
        interest_reducing=True,
        tax_latest=25.0,
        tax_falling=False,
        net_profit_yoy_pct=15.0,
        checklist_score=5,
        checklist_max=7,
    )


class TestScanCheckpoint(unittest.TestCase):
    def test_roundtrip_and_match(self):
        flt = InvestmentCourseFilters(mode="step0_categorize", max_peg=1.0)
        h = ckpt.filters_fingerprint(flt)
        self.assertEqual(len(h), 16)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ckpt.json"
            with patch.object(ckpt, "CHECKPOINT_PATH", path):
                hits = [_sample_hit("INFY"), _sample_hit("TCS")]
                ckpt.save_checkpoint(
                    universe="All NSE equities (~2300) - very slow",
                    mode="step0_categorize",
                    filters_hash=h,
                    next_index=100,
                    total=2369,
                    hits=hits,
                )
                loaded = ckpt.load_checkpoint()
                self.assertIsNotNone(loaded)
                self.assertTrue(
                    ckpt.checkpoint_matches(
                        loaded,
                        universe="All NSE equities (~2300) - very slow",
                        mode="step0_categorize",
                        filters_hash=h,
                    )
                )
                self.assertFalse(
                    ckpt.checkpoint_matches(
                        loaded,
                        universe="Nifty 50 (NSE)",
                        mode="step0_categorize",
                        filters_hash=h,
                    )
                )
                restored = ckpt.hits_from_checkpoint(loaded)
                self.assertEqual(len(restored), 2)
                self.assertEqual(restored[0].ticker, "INFY")
                ckpt.clear_checkpoint()
                self.assertIsNone(ckpt.load_checkpoint())

    def test_merge_hits(self):
        a = [_sample_hit("INFY")]
        b = [_sample_hit("INFY"), _sample_hit("TCS")]
        m = ckpt.merge_hits(a, b)
        self.assertEqual([r.ticker for r in m], ["INFY", "TCS"])

    def test_scan_chunk_bounds(self):
        from investment_course_screener import scan_investment_course

        uni = [("A", "A.NS"), ("B", "B.NS"), ("C", "C.NS"), ("D", "D.NS")]
        seen: list[str] = []

        def fake_resolve(_src):
            return list(uni)

        # Force empty body by raising in ticker path after progress — use cancel after 0
        with patch(
            "investment_course_screener.resolve_investment_course_tickers",
            side_effect=fake_resolve,
        ):
            # cancel immediately so we don't hit network
            chunk = scan_investment_course(
                "dummy",
                filters=InvestmentCourseFilters(include_wealth=False, need_pe_history=False),
                start_index=1,
                max_tickers=2,
                cancel_cb=lambda: True,
            )
            self.assertIsInstance(chunk, ScanChunkResult)
            self.assertTrue(chunk.cancelled)
            self.assertEqual(chunk.next_index, 1)
            self.assertEqual(chunk.total, 4)
            self.assertFalse(chunk.done)


if __name__ == "__main__":
    unittest.main()
