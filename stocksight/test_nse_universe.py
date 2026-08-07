"""Unit tests for full NSE equity universe loader."""

from __future__ import annotations

import unittest
from unittest.mock import patch


SAMPLE_CSV = """SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE
RELIANCE,Reliance Industries Limited,EQ,06-JAN-1977,10,1,INE002A01018,10
TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1
M&M,Mahindra & Mahindra Limited,EQ,03-JAN-1996,5,1,INE101A01026,5
BAJAJ-AUTO,Bajaj Auto Limited,EQ,26-MAY-2008,10,1,INE917I01010,10
SOMETHING,Odd Series Ltd,IL,01-JAN-2000,10,1,INE000000000,10
"""


class TestNseUniverse(unittest.TestCase):
    def test_parse_and_lazy_universe(self):
        from nse_universe import _parse_equity_csv, load_nse_equity_tickers
        from screener import get_universe_tickers

        parsed = _parse_equity_csv(SAMPLE_CSV)
        self.assertIn("RELIANCE.NS", parsed)
        self.assertIn("M&M.NS", parsed)
        self.assertIn("BAJAJ-AUTO.NS", parsed)
        self.assertNotIn("SOMETHING.NS", parsed)  # IL series skipped

        with patch("nse_universe._download_equity_csv", return_value=SAMPLE_CSV):
            with patch("nse_universe._CACHE_FILE") as mock_file:
                mock_file.is_file.return_value = False
                # force in-memory path via empty cache + download
                import nse_universe as nu

                nu._SYMBOLS = None
                syms = nu._parse_equity_csv(SAMPLE_CSV)
                self.assertGreaterEqual(len(syms), 4)

        full = get_universe_tickers("Nifty 50 (NSE)")
        self.assertEqual(len(full), 50)
        all_label = "All NSE equities (~2300) - very slow"
        # Uses disk cache from earlier download in this env
        all_syms = get_universe_tickers(all_label)
        self.assertGreater(len(all_syms), 1000)
        self.assertTrue(all(s.endswith(".NS") for s in all_syms[:20]))
        # Legacy label still resolves
        legacy = get_universe_tickers("All NSE equities (full list — very slow)")
        self.assertEqual(len(legacy), len(all_syms))


if __name__ == "__main__":
    unittest.main()
