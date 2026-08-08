"""Tests for Fundamental Screener Framework (3-tier)."""

from __future__ import annotations

import unittest

from fundamental_screener import filters_for_tier, _passes
from screener_in_data import (
    _parse_ratio_block,
    _parse_shareholding_governance,
    _yoy_quarterly_growth,
)


SAMPLE_TOP = """
<section id="top-ratios">
<ul>
<li><span class="name">Debt to equity</span><span class="nowrap value"><span class="number">0.25</span></span></li>
<li><span class="name">Promoter holding</span><span class="nowrap value"><span class="number">55.2</span>%</span></li>
<li><span class="name">Pledged percentage</span><span class="nowrap value"><span class="number">2.1</span>%</span></li>
<li><span class="name">Industry PE</span><span class="nowrap value"><span class="number">28.5</span></span></li>
<li><span class="name">Stock P/E</span><span class="nowrap value"><span class="number">22.0</span></span></li>
<li><span class="name">ROE</span><span class="nowrap value"><span class="number">18.0</span>%</span></li>
</ul>
</section>
"""

SAMPLE_SH = """
<section id="shareholding">
<table>
<tr><th></th><th>Dec 2024</th><th>Mar 2025</th></tr>
<tr><td>Promoters</td><td>52.0</td><td>53.5</td></tr>
<tr><td>FIIs</td><td>10</td><td>11</td></tr>
</table>
</section>
"""

SAMPLE_Q = """
<section id="quarters">
<table>
<tr><th></th><th>Mar 2024</th><th>Jun 2024</th><th>Sep 2024</th><th>Dec 2024</th><th>Mar 2025</th></tr>
<tr><td>Sales+</td><td>100</td><td>110</td><td>120</td><td>130</td><td>140</td></tr>
<tr><td>Net Profit</td><td>10</td><td>11</td><td>12</td><td>13</td><td>15</td></tr>
</table>
</section>
"""


class TestFundamentalParsers(unittest.TestCase):
    def test_ratio_and_shareholding(self):
        self.assertEqual(_parse_ratio_block(SAMPLE_TOP, "Debt to equity"), 0.25)
        self.assertEqual(_parse_ratio_block(SAMPLE_TOP, "Promoter holding"), 55.2)
        self.assertEqual(_parse_ratio_block(SAMPLE_TOP, "Industry PE"), 28.5)
        sh = _parse_shareholding_governance(SAMPLE_SH)
        self.assertEqual(sh["promoter_holding_pct"], 53.5)
        self.assertEqual(sh["promoter_change_pct"], 1.5)

    def test_yoy_quarterly(self):
        yoy = _yoy_quarterly_growth(SAMPLE_Q)
        # Mar 2025 140 vs Mar 2024 100 → +40%
        self.assertEqual(yoy["yoy_sales_pct"], 40.0)
        self.assertEqual(yoy["yoy_profit_pct"], 50.0)


class TestFundamentalFilters(unittest.TestCase):
    def test_watchlist_pass(self):
        flt = filters_for_tier("watchlist")
        profile = {
            "market_cap_cr": 2000.0,
            "debt_equity": 0.2,
            "promoter_holding_pct": 55.0,
            "pledged_pct": 1.0,
            "roe_pct": 18.0,
            "sales_growth_3y_pct": 12.0,
            "profit_growth_3y_pct": 15.0,
            "pe": 20.0,
            "industry_pe": 25.0,
        }
        ok, notes, soft = _passes(profile, flt)
        self.assertTrue(ok)
        self.assertTrue(any("ROE" in n for n in notes))

    def test_watchlist_fail_debt(self):
        flt = filters_for_tier("watchlist")
        profile = {
            "market_cap_cr": 2000.0,
            "debt_equity": 0.9,
            "promoter_holding_pct": 55.0,
            "pledged_pct": 1.0,
            "roe_pct": 18.0,
            "sales_growth_3y_pct": 12.0,
            "profit_growth_3y_pct": 15.0,
            "pe": 20.0,
            "industry_pe": 25.0,
        }
        ok, _, _ = _passes(profile, flt)
        self.assertFalse(ok)

    def test_strict_preset_tighter(self):
        w = filters_for_tier("watchlist")
        s = filters_for_tier("strict")
        self.assertGreater(s.min_market_cap_cr, w.min_market_cap_cr)
        self.assertLess(s.max_debt_equity, w.max_debt_equity)
        self.assertEqual(s.max_peg, 1.5)
        self.assertTrue(filters_for_tier("momentum").require_acceleration)


class TestFundamentalResultsTable(unittest.TestCase):
    def test_result_to_row_dataframe_dedupe_pipeline(self):
        """Mirrors the page path that crashed on Cloud (dedupe + table columns)."""
        import pandas as pd
        from fundamental_screener import FundamentalResult, result_to_row
        from session_utils import deduplicate_scan_results

        hit = FundamentalResult(
            ticker="INFY",
            raw_ticker="INFY.NS",
            label="Infosys",
            tier="watchlist",
            price=1500.0,
            market_cap_cr=50000.0,
            market_cap_display="₹50,000 Cr",
            debt_equity=0.1,
            interest_coverage=None,
            current_ratio=None,
            promoter_holding_pct=15.0,
            promoter_change_pct=0.0,
            pledged_pct=0.0,
            roe_pct=25.0,
            avg_roe_3y_pct=22.0,
            roce_pct=30.0,
            roa_pct=15.0,
            opm_pct=20.0,
            sales_growth_3y_pct=12.0,
            profit_growth_3y_pct=14.0,
            yoy_sales_pct=11.0,
            yoy_profit_pct=12.0,
            pe=22.0,
            industry_pe=28.0,
            peg=1.2,
            price_to_book=5.0,
            ret_3m_pct=5.0,
            ret_6m_pct=12.0,
            ret_1y_pct=20.0,
            score=40.0,
            verdict="ok",
            pass_notes=["ROE 25%"],
            fail_soft=[],
            links={"Screener": "https://www.screener.in/company/infy/consolidated/"},
        )
        rows = [result_to_row(hit, 1), result_to_row(hit, 2)]
        df = pd.DataFrame(rows)
        self.assertIn("Ticker", df.columns)
        self.assertIn("Raw", df.columns)
        deduped = deduplicate_scan_results(df, ticker_col="Ticker")
        self.assertEqual(len(deduped), 1)
        self.assertEqual(str(deduped.iloc[0]["Ticker"]), "INFY")



if __name__ == "__main__":
    unittest.main()
