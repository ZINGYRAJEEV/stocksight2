"""Unit tests for Investment Course post-scan Steps 3–6 helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from investment_course_analysis import (
    STORY_CHECKS,
    category_research_items,
    draft_story_paragraph,
    enrich_research_links,
    practical_stance,
)


def _sample_result(**overrides):
    base = dict(
        label="Premier Energies",
        ticker="PREMIERENE",
        category="Fast Grower",
        sector="Technology",
        sales_growth_3y_pct=76.0,
        profit_growth_3y_pct=370.0,
        opm_latest_pct=30.0,
        peg=0.09,
        pct_vs_50dma=-1.1,
        pct_vs_200dma=None,
        is_strong_wealth=True,
        upside_pct=80.0,
        implied_cagr_pct=22.0,
        checklist_score=7,
        checklist_max=8,
        price=1042.0,
        max_buy_15pct=1237.0,
        pct_vs_median=-67.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestCategoryResearch(unittest.TestCase):
    def test_fast_grower_has_growth_prompts(self):
        items = category_research_items("Fast Grower")
        ids = {i["id"] for i in items}
        self.assertIn("understand", ids)
        self.assertIn("growth_source", ids)
        self.assertGreaterEqual(len(items), 4)

    def test_unknown_category_still_has_defaults(self):
        items = category_research_items("Asset Play")
        self.assertTrue(any(i["id"] == "understand" for i in items))


class TestStoryHelpers(unittest.TestCase):
    def test_story_checks_cover_core_manual_steps(self):
        ids = {c["id"] for c in STORY_CHECKS}
        self.assertTrue({"scam", "glassdoor", "concall", "credit"} <= ids)

    def test_draft_story_includes_category_and_blanks(self):
        text = draft_story_paragraph(_sample_result())
        self.assertIn("Fast Grower", text)
        self.assertIn("____", text)
        self.assertIn("Premier Energies", text)

    def test_enrich_links_adds_youtube(self):
        links = enrich_research_links({}, "PREMIERENE", "Premier Energies")
        self.assertIn("YouTube interviews", links)
        self.assertIn("Google scam check", links)
        self.assertIn("PREMIERENE", links["Screener.in"])


class TestPracticalStance(unittest.TestCase):
    def test_strong_wealth_candidate_label(self):
        stance = practical_stance(_sample_result(), None)
        self.assertIn("label", stance)
        self.assertIn("size", stance)
        self.assertTrue(stance["bull"])
        self.assertIn("Candidate", stance["label"])

    def test_stress_fail_marks_watchlist(self):
        stance = practical_stance(
            _sample_result(),
            {"survives_stress": False, "upside_pct": -10, "implied_cagr_pct": 5},
        )
        self.assertIn("Watchlist", stance["label"])
        self.assertTrue(any("stress" in b.lower() for b in stance["bear"]))

    def test_slow_grower_default_pass(self):
        stance = practical_stance(_sample_result(category="Slow Grower", is_strong_wealth=False))
        self.assertIn("pass", stance["label"].lower())


class TestStressWealthSnapshot(unittest.TestCase):
    @patch("valuation_model.assess_wealth_creation")
    @patch("valuation_model.project_valuation")
    @patch("valuation_model.build_default_valuation_inputs")
    @patch("valuation_model.load_valuation_baseline")
    def test_stress_applies_haircuts_and_flags(
        self, mock_load, mock_inputs, mock_proj, mock_assess
    ):
        from valuation_model import ValuationInputs, stress_wealth_snapshot

        base = MagicMock()
        base.data_ok = True
        base.price = 1000.0
        base.historical_revenue = [(2024, 1000.0)]
        mock_load.return_value = base

        mock_inputs.return_value = ValuationInputs(
            revenue_cr_y0=1000.0,
            revenue_growth_pct=30.0,
            projection_years=3,
            opm_pct=28.0,
            tax_rate_pct=25.0,
            interest_drag_pct=0.0,
            shares_cr=10.0,
            fair_pe=30.0,
            terminal_pe=20.0,
            terminal_opm_pct=28.0,
            base_calendar_year=2024,
            cagr_holding_years=3,
        )
        mock_proj.return_value = MagicMock()

        wealth = MagicMock()
        wealth.verdict = "Not for wealth at this price"
        wealth.verdict_emoji = "🔴"
        wealth.wealth_score = 40
        wealth.valuation_stance = "Above model target"
        wealth.valuation_stance_color = "#ef4444"
        wealth.valuation_detail = "stressed"
        wealth.model_target = 850.0
        wealth.upside_pct = -15.0
        wealth.implied_cagr_pct = -5.0
        wealth.max_buy_15pct = 700.0
        wealth.margin_of_safety_pct = -20.0
        wealth.strengths = []
        wealth.risks = ["Stress"]
        wealth.suggestions = []
        mock_assess.return_value = wealth

        out = stress_wealth_snapshot(
            "PREMIERENE.NS",
            growth_haircut_pp=10.0,
            opm_haircut_pp=3.0,
            pe_haircut_pct=15.0,
        )
        self.assertTrue(out)
        self.assertFalse(out["is_strong_wealth"])
        self.assertFalse(out["survives_stress"])
        self.assertEqual(out["assumptions"]["growth_pct"], 20.0)  # 30 - 10
        self.assertEqual(out["assumptions"]["opm_pct"], 25.0)  # 28 - 3
        self.assertAlmostEqual(out["assumptions"]["fair_pe"], 25.5)  # 30 * 0.85
        self.assertFalse(out["assumptions"]["still_below_max_buy_15"])

        # Ensure project_valuation received stressed inputs
        _base, inputs, kwargs = mock_proj.call_args[0][0], mock_proj.call_args[0][1], mock_proj.call_args[1]
        self.assertEqual(inputs.revenue_growth_pct, 20.0)
        self.assertEqual(kwargs.get("current_price"), 1000.0)


class TestSectorGrouping(unittest.TestCase):
    def test_group_by_sector_largest_first(self):
        from investment_course_screener import group_results_by_sector

        rs = [
            _sample_result(ticker="A", sector="Technology", score=10),
            _sample_result(ticker="B", sector="Technology", score=20),
            _sample_result(ticker="C", sector="Financial Services", score=5),
        ]
        grouped = group_results_by_sector(rs, rank_by="score")
        self.assertEqual(list(grouped.keys())[0], "Technology")
        self.assertEqual([r.ticker for r in grouped["Technology"]], ["B", "A"])
        self.assertEqual(len(grouped["Financial Services"]), 1)


class TestSectorUniverse(unittest.TestCase):
    def test_sector_sources_available(self):
        from investment_course_screener import (
            SECTOR_SCAN_SOURCES,
            resolve_investment_course_tickers,
            universe_ticker_count,
        )

        self.assertTrue(SECTOR_SCAN_SOURCES)
        bank_key = next(k for k in SECTOR_SCAN_SOURCES if "Bank" in k and "PSU" not in k)
        tickers = resolve_investment_course_tickers(bank_key)
        self.assertGreaterEqual(len(tickers), 5)
        self.assertTrue(all(r.endswith(".NS") for _, r in tickers))
        self.assertEqual(universe_ticker_count(bank_key), len(tickers))


class TestDataQualityGates(unittest.TestCase):
    def test_psb_style_missing_cagr_dropped(self):
        from investment_course_screener import InvestmentCourseFilters, passes_data_quality_gates

        flt = InvestmentCourseFilters(require_growth_cagr=True, drop_unclassified=True)
        self.assertFalse(
            passes_data_quality_gates(
                category="Unclassified",
                sales_3y=None,
                profit_3y=None,
                flt=flt,
            )
        )

    def test_fast_grower_with_cagr_kept(self):
        from investment_course_screener import InvestmentCourseFilters, passes_data_quality_gates

        flt = InvestmentCourseFilters(require_growth_cagr=True, drop_unclassified=True)
        self.assertTrue(
            passes_data_quality_gates(
                category="Fast Grower",
                sales_3y=20.0,
                profit_3y=25.0,
                flt=flt,
            )
        )


if __name__ == "__main__":
    unittest.main()
