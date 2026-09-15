"""Tests for growth & innovation qualitative research checklist."""

from __future__ import annotations

import unittest

from growth_innovation_research import (
    GROWTH_INNOVATION_CHECKLIST,
    checklist_rows_for_ticker,
    growth_innovation_research_links,
)


class TestGrowthInnovationResearch(unittest.TestCase):
    def test_checklist_covers_user_notes(self):
        titles = " ".join(i["title"].lower() for i in GROWTH_INNOVATION_CHECKLIST)
        self.assertIn("credit", titles)
        self.assertIn("annual report", titles)
        self.assertIn("conference", titles)
        self.assertIn("management", titles)
        self.assertIn("tijori", titles.lower() + " ".join(i["source"].lower() for i in GROWTH_INNOVATION_CHECKLIST))
        sources = " ".join(i["source"].lower() for i in GROWTH_INNOVATION_CHECKLIST)
        self.assertIn("trendlyne", sources)
        self.assertIn("tijori", sources)

    def test_links_for_nse_ticker(self):
        links = growth_innovation_research_links("NETWEB", "NETWEB.NS", "Netweb Technologies")
        self.assertIn("Screener.in", links)
        self.assertIn("Screener Documents", links)
        self.assertIn("Trendlyne", links)
        self.assertIn("Tijori Finance", links)
        self.assertIn("NETWEB", links["Screener.in"])

    def test_checklist_rows_have_urls(self):
        rows = checklist_rows_for_ticker("E2E", "E2E.NS", "E2E Networks")
        self.assertEqual(len(rows), len(GROWTH_INNOVATION_CHECKLIST))
        for row in rows:
            self.assertTrue(row.get("url"), msg=row["id"])


if __name__ == "__main__":
    unittest.main()
