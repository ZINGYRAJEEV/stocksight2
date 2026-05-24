# StockSight — notes for coding agents

## What ships today

Python **Streamlit** multipage app under `stocksight/`: scenario screeners for NSE (Nifty 50 / Nifty 500 lists) and a US ticker list (`S&P 500 (NYSE)` in code), using **yfinance** plus `screener.py` / `signals.py`. Educational tooling only; not financial advice.

**Run (repo root `stocksight2/`):**

```bash
pip install -r requirements.txt
streamlit run Overview.py
```

(`requirements.txt` at repo root includes `stocksight/requirements.txt` so **Streamlit Cloud** installs `yfinance` and the rest.)

Alternate entry (overview content only — **no** sidebar page nav; use `Overview.py` for the full app):

```bash
streamlit run stocksight/app.py
```

| Path | Role |
|------|------|
| `requirements.txt` (repo root) | `-r stocksight/requirements.txt` — used by **Streamlit Cloud** and local `pip install -r requirements.txt`. |
| `Overview.py` (repo root) | **`st.navigation`** with grouped pages + `pg.run()`; imports `render_overview` and thin runners from `navigation_pages.py`. **Disables** auto-discovery of a `pages/` folder. |
| `navigation_pages.py` (repo root) | One callable per app page; each calls `exec_stocksight_page("….py")`. |
| `stocksight_page_loader.py` (repo root) | Resolves `stocksight/pages/*.py` and runs them with `stocksight/` on `sys.path`. |
| `stocksight/app.py` | `render_overview()` — dashboard / strategy map (no sidebar tips; those live in `Overview.py`). |
| `stocksight/pages/*.py` | Real Streamlit pages (strategy screeners, StockSight, Buy/Hold/Avoid, etc.). |
| `stocksight/screener.py` | Universes, `screen_stocks()`, `get_pe()`, RSI/volume/score helpers. |
| `stocksight/signals.py` | Scenario scan logic. |
| `stocksight/ui_components.py` | Shared CSS/widgets. |

**Imports:** Pages use `from screener import ...` (flat) when `stocksight/` is on `sys.path`. `stocksight/app.py` defines `render_overview()` for the home page (no screener import).

**Conventions:** Match existing Streamlit patterns; small focused diffs; primary dependency list in `stocksight/requirements.txt`, re-exported from root `requirements.txt` for Cloud.

**Streamlit Cloud:** Main file `Overview.py` at repo root; **dependencies** from root `requirements.txt` (includes `-r stocksight/requirements.txt`). Theme may live under `stocksight/.streamlit/`.

---

## Next development — Stock Screener (product spec)

Standalone **real-time stock screener** for Indian NSE (Nifty 500-style universe) and US NYSE names: fundamental + technical filters, ranked by a **composite score**. The section below is the **target** design to implement or port; it is **not** the current repo layout unless those files exist.

The phased batch-download + normalized-score flow described here is **not** implemented as a separate Streamlit page right now; it remains a reference for future work alongside the Flask line below.

### Target architecture (to build)

```
stock_screener/
├── CLAUDE.md            ← Product + agent notes (may stay at repo root)
├── requirements.txt
├── screener.py          ← Core: fetch, filter, score (rate-limit aware)
├── app.py               ← Flask on port 5000, SSE progress stream
├── cli.py               ← Rich terminal UI (CLI fallback)
└── templates/
    └── index.html       ← Web dashboard (Bloomberg-style)
```

**Target run (after implementation):**

```bash
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
python cli.py            # CLI fallback
```

### Reference screening filters (product)

| Filter | Condition | Rationale |
|--------|-----------|-----------|
| P/E ratio | below 20 | Value — cheaper vs earnings |
| Volume spike | above 2× 20-day average | Unusual interest / accumulation |
| RSI (14) | above 50 | Bullish momentum vs midline |

**Current Streamlit `screen_stocks()` defaults** (`stocksight/screener.py`): `pe_threshold=30.0`, `vol_multiplier=1.5`, `rsi_min=50.0` — align or migrate toward the reference row when implementing the spec.

### Composite score — target formula (normalized)

Target: **Score = 0.30 × PE_score + 0.40 × Volume_score + 0.30 × RSI_score** with range **0.0–1.0** (higher = stronger).

- `PE_score    = max(0, (20 - PE) / 20)` — lower PE scores higher; floored at 0  
- `Volume_score = min(volume_ratio / 5.0, 1.0)` — cap at 5× spike  
- `RSI_score   = max(0, (RSI - 50) / 50)` — normalize 50–100  

**Current shipped scoring** (`compute_score()` in `stocksight/screener.py`): three components capped to **40 + 30 + 30 = 100** points (not 0–1), with different PE/vol/RSI scaling. Refactor toward the normalized formula when merging the Flask product line.

### Data fetch strategy — target (rate-limit aware)

**Phase 1 — batch OHLCV**

- `yf.download()` in batches (~50 tickers).  
- ~1.5 s sleep between batches.  
- Apply volume + RSI filters immediately → smaller survivor set.

**Phase 2 — PE enrichment (survivors only)**

- `yf.Ticker(t).info` only for names passing phase 1.  
- ~300 ms between `.info` calls.  
- Apply PE below 20 (or chosen threshold).

**Current implementation:** `screen_stocks()` loops **per ticker**: `yf.Ticker(t).history(...)`, then `get_pe(stock)` (may hit `.info` / `fast_info`). No batch `yf.download()` yet — treat the two-phase plan as the optimization target.

### Ticker universes (shipped names)

| Market | Universe key in `UNIVERSES` | Notes |
|--------|-----------------------------|--------|
| NSE | `Nifty 50 (NSE)` | `NIFTY_50` in `screener.py` |
| NSE | `Nifty 500 (NSE)` | `NIFTY_50` + `NIFTY_500_EXTRA` (curated, not full index) |
| US | `S&P 500 (NYSE)` | `SP500` list — extend list in `screener.py` as needed |

NSE symbols use **`.NS`** suffix for yfinance. US list in code has no suffix.

### Operational notes

- **Market hours:** yfinance reflects the latest available session; best during / after relevant market hours.  
- **PE:** Trailing PE may be missing for some NSE names; `get_pe()` already tries `fast_info`, `trailingPE` / `forwardPE`, then price/EPS.  
- **Rate limits:** yfinance is unofficial; aggressive calls risk **429**. Batch delays + survivor-only PE fetches are the intended mitigation.  
- **Network:** Live Yahoo Finance data only.
