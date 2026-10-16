---
description: "Use for StockSight screener implementation and tests. Covers market-data boundaries, units, and deterministic screening tests."
applyTo: ["stocksight/**/*screener*.py", "stocksight/**/test_*.py", "test_screen.py"]
---

# Screener File Guidance

- Keep universe resolution, provider access, filtering, and rendering in their existing modules; do not combine them in a page callback.
- Treat ticker suffixes, quote currency, market-cap units, and financial-statement units as market-specific. Convert only at a documented boundary.
- A provider failure or absent value is unknown, not zero and not a passing signal. Preserve that distinction through filters and results.
- Mock Yahoo Finance and all network-backed helpers in tests. Assert both expected results and that irrelevant provider paths are not called.
- Cover universe resolution and filter behavior with small fixtures; avoid large scans and live-market tests.