# StockSight Copilot Instructions

- This is a Python and Streamlit stock-screening app. Screening modules and page implementations primarily live under `stocksight/`; follow the nearest existing pattern.
- Start from the named file, symbol, behavior, or test. Search narrowly, make the smallest relevant change, and avoid unrelated cleanup.
- Preserve existing public APIs and market-specific behavior. Do not assume NSE and US tickers share currency, units, symbol format, or data-source coverage.
- Add or update focused tests for behavior changes. Keep tests deterministic; mock Yahoo Finance, network calls, and other external providers.
- Run the narrowest relevant test or diagnostic available. Keep progress and final summaries concise; report checks that could not run.