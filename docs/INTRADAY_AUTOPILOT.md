# Intraday Autopilot — User Guide

**Intraday Autopilot** is StockSight’s scheduled trading assistant for **NSE (India)** and **US** markets. It follows a full intraday playbook—gap scan, opening drive, ORB, trend/ATH, VWAP, lunch manage-only, afternoon momentum, square-off, and end-of-day reporting—and can run in **dry-run**, **paper**, or **live** mode.

Open it in the app: **Algo Strategy → Intraday Autopilot**

---

## What it does (in plain language)

| Capability | Description |
|------------|-------------|
| **Time-based playbook** | Automatically picks what to do based on the clock (IST for NSE, ET for US)—not one static scan all day. |
| **Six intraday strategies** | GAP, MOMENTUM, BROAD, ORB, VWAP, ATH—the same engine as the Intraday Screener. |
| **Gap mood & watchlist** | Morning gap scan sets market regime and a **priority watchlist** (top gap-up names). |
| **Quality Gate scoring** | Only candidates above your **min gate score** with acceptable R:R are considered. |
| **Risk limits** | Caps open positions, trades per market per day, and uses stop-based sizing in paper/live. |
| **Square-off** | Scheduled phase closes autopilot positions before the close (paper ledger or live Breeze MIS). |
| **Kill switch** | One toggle stops **all** autopilot actions immediately. |
| **Live progress** | Progress bar, status panel, and activity log while a tick runs. |
| **Continuous mode** | UI or CLI can repeat ticks every N seconds through the session. |

---

## Trading modes

| Mode | Orders | Best for |
|------|--------|----------|
| **dry_run** | None — logs what it *would* do | Learning the schedule and signals |
| **paper** | Virtual trades in **Paper Trading** ledger | **Default** — test for days/weeks |
| **live** | Real **ICICI Breeze** MIS buy/sell (when enabled) | Experienced users only, with env flags |

**Live mode requirements**

- Valid Breeze credentials in `.streamlit/secrets.toml` (daily session token)
- Environment: `AUTOPILOT_ENABLED=true` and `AUTOPILOT_LIVE_CONFIRM=YES`
- Kill switch **off**
- NSE data API: **Auto** or **Breeze** (not Yahoo-only for broker-aligned live flow)

---

## Does it auto-book trades?

**Sometimes — but not for every ticker the scan finds.** A match in the screener is only the first step; autopilot books a trade only when **mode**, **phase**, **session**, **filters**, and **risk limits** all allow it.

### When it does **not** book

| Situation | What happens |
|-----------|----------------|
| **dry_run** mode | Logs only (e.g. `DRY-RUN BUY …`) — **no** paper or live order |
| Phase **pre_open**, **gap_scan**, **mood_shortlist** | Gap scan + watchlist only — **no** entries |
| Phase **lunch** | **Manage only** — no new trades |
| Phase **square_off** or **eod** | Closes positions or reports P&L — **no** new buys |
| **Market closed** (during an entry phase) | Tick skipped (`session_closed`) |
| **Kill switch** on | All autopilot actions blocked |

### When it **can** book

During **entry phases** — **opening**, **orb**, **trend_ath**, **vwap**, **afternoon** (and similar phases that allow new entries):

1. Runs the intraday strategy scan (watchlist + universe).
2. Ranks matches using **Quality Gate** (must meet **min gate score**, default 58).
3. Skips **Avoid** tier and names below **min R:R** (default 1.2).
4. Walks the ranked list and books the **top** qualifiers until limits are hit:
   - **Max 3** open autopilot positions per market
   - **Max 5** trades per market per day
5. Position size uses **risk % per trade** (default 1%) vs entry/stop in **paper** mode.

### What “book” means by mode

| Mode | What gets placed |
|------|------------------|
| **paper** (default in UI) | Virtual **BUY** in **Paper Trading**, tagged `autopilot_NSE` or `autopilot_US` |
| **live** | Real **ICICI Breeze** market buy (MIS) + stop-loss sell (when env flags + Breeze are enabled) |
| **dry_run** | **Nothing** — you only see what it would have done |

**Square-off** (scheduled phase) later **sells** those autopilot positions (paper ledger or live Breeze) before the close.

### Quick check after a tick

1. Set mode to **paper** (not dry_run).  
2. **Force phase** → `opening` or `orb`.  
3. Run **one autopilot tick**.  
4. Open **Paper Trading** — look for new rows with source `autopilot_NSE` / `autopilot_US`.  
5. In the tick summary, read the **executed** list (BUY messages or errors).

---

## Market data API (NSE)

Choose how intraday bars are loaded for **NSE** scans:

| API | When to use |
|-----|-------------|
| **Auto** | Breeze if connected, otherwise Yahoo — good default for paper + live |
| **ICICI Breeze** | Live NSE prices aligned with your broker; slower on large universes |
| **Yahoo** | Faster scans for paper/dry-run testing |

**US** scans always use **Yahoo Finance** (Breeze is NSE/BSE only).

---

## Daily schedule (NSE — IST)

| Phase | Approx. time | What happens |
|-------|----------------|--------------|
| **pre_open** | 8:00–9:15 | Market context (no new trades) |
| **gap_scan** | 9:15–9:20 | Scan gaps across universe |
| **mood_shortlist** | 9:20–9:30 | Regime from gaps + **top 5 watchlist** |
| **opening** | 9:30–9:45 | GAP, MOMENTUM, BROAD — new entries allowed |
| **orb** | 9:45–10:15 | ORB, MOMENTUM |
| **trend_ath** | 10:00–12:30 | MOMENTUM, ATH, BROAD |
| **vwap** | 10:30–13:00 | VWAP pullback |
| **lunch** | 12:30–14:00 | **Manage only** — no new entries |
| **afternoon** | 14:30–15:15 | MOMENTUM, BROAD |
| **square_off** | 15:15–15:25 | Close autopilot positions |
| **eod** | 15:30+ | Paper P&L / summary |

### US (ET)

Similar flow: premarket gaps → US open → ORB → trend/ATH → VWAP → mid-day chop (no new entries) → power hour → square-off (~3:55 PM ET) → EOD.

The UI shows the **current phase** for NSE and US at the top of the page.

---

## Streamlit UI features

### Control panel

- **Mode** — dry_run / paper / live  
- **Markets** — NSE, US, or both  
- **Min gate score** — filter weak setups (default 58)  
- **Force phase** — override clock for testing (e.g. `gap_scan`, `opening`, `orb`)  
- **NSE intraday data** — Auto / Breeze / Yahoo  
- **Max tickers per scan** — universe size cap (default 60)  
- **Kill switch** — emergency stop  

### Run options

| Button / option | Behaviour |
|-----------------|-----------|
| **Run one autopilot tick** | Runs one cycle for selected markets; shows **live progress** (ticker, %, API, activity log) |
| **Continuous autopilot** | Repeats ticks every N seconds while the browser tab stays open |
| **Day state** | Regime, trades today, priority watchlist per market |
| **Event log** | Last 50 autopilot events (phases, scans, square-off, etc.) |
| **Last tick result** | JSON summary of the most recent run |

### Progress during a tick

You should see:

1. **Status** block (“Autopilot tick running…”)  
2. **Progress bar** — e.g. `Gap scan: TICKER.NS (12/50)`  
3. **Live scan panel** — elapsed time, ETA, matched / no-data counts  
4. **Activity log** — last lines of what ran  

If you only see “no ticker scan,” the current **auto phase** may be EOD, lunch (manage-only), square-off, or market closed. Use **Force phase** → `gap_scan` or `opening` to test a full scan.

---

## Command line (continuous / automation)

From the repo root:

```bat
# One tick (paper, NSE only)
python scripts\run_autopilot.py --once --markets NSE --mode paper

# Continuous — every 5 minutes (recommended for all-day local run)
python scripts\run_autopilot.py --loop --interval 300 --mode paper --data-source-nse auto

# Force a phase (e.g. square-off)
python scripts\run_autopilot.py --once --phase square_off --markets NSE --mode paper

# Yahoo for faster paper testing
python scripts\run_autopilot.py --once --markets NSE --mode paper --data-source-nse yahoo
```

**Live (high risk):**

```bat
set AUTOPILOT_ENABLED=true
set AUTOPILOT_LIVE_CONFIRM=YES
python scripts\run_autopilot.py --once --mode live --markets NSE --data-source-nse breeze
```

### CLI options

| Flag | Description |
|------|-------------|
| `--once` | Single tick (default) |
| `--loop` | Run forever with sleep between ticks |
| `--interval` | Seconds between ticks in loop mode (min 60) |
| `--mode` | `dry_run` \| `paper` \| `live` |
| `--markets` | `NSE`, `US`, or `NSE,US` |
| `--phase` | Force phase id (`opening`, `orb`, `square_off`, …) |
| `--data-source-nse` | `auto` \| `breeze` \| `yahoo` |
| `--min-gate` | Minimum Quality Gate score |
| `--max-tickers` | Cap universe size per scan |
| `--kill-switch-on` / `--kill-switch-off` | Toggle kill switch from CLI |

---

## GitHub Actions (optional)

Workflow **`intraday-autopilot.yml`** can run **paper** ticks on a cron schedule (Yahoo data by default in CI—no daily Breeze token). Use **workflow_dispatch** to trigger manually with mode, markets, and data source inputs.

---

## Scoring, entries, and risk

- Uses the same **intraday scan** as the Intraday Screener (filters, RSI, volume ratio, hard rejects).  
- **Quality Gate** (A–D) and score adjust candidates; regime from gap mood can reduce aggression in risk-off conditions.  
- Respects **max open positions**, **max trades per market per day**, **min R:R**, and **risk % per trade** (paper sizing).  
- **Confluence** — multiple strategies on one ticker can rank higher.  
- Paper trades are tagged `autopilot_NSE` / `autopilot_US` in the paper ledger for tracking and square-off.

---

## Local state files (gitignored)

| File | Purpose |
|------|---------|
| `stocksight/.intraday_autopilot_state.json` | Day state, watchlist, kill switch, runtime progress, event log |
| `stocksight/.paper_trading.json` | Paper positions and cash when mode = paper |

Reset by deleting these files or waiting for a new calendar day (state rolls daily).

---

## Recommended workflow for new users

1. Start Streamlit: `streamlit run Overview.py` from repo root.  
2. Open **Intraday Autopilot** — leave mode on **paper**, kill switch **off**.  
3. Set **NSE data** to **Yahoo** for a fast first test, or **Auto** if Breeze is connected.  
4. **Force phase** → `gap_scan` or `opening` → **Run one autopilot tick** and watch progress.  
5. Check **Paper Trading** for virtual fills.  
6. After you trust signals, try **dry_run** vs **paper** side by side.  
7. Only consider **live** after weeks of paper + legal/broker algo compliance review.

---

## SEBI / compliance notice

Intraday Autopilot is a **research and automation helper**, not exchange-certified algo infrastructure. Production algo trading in India typically requires broker-hosted deployment, strategy approval, **Algo IDs**, throttles, and audit trails per SEBI guidelines. Use paper mode and your own compliance review before any live deployment.

---

## Related pages in StockSight

| Page | Role |
|------|------|
| **Intraday Screener** | Manual scans, diagnostics, API speed test |
| **ICICI Breeze Screener** | NSE-focused screener + live trade form |
| **Paper Trading** | Ledger for autopilot paper fills |
| **Gap Scanner** | Standalone gap tool (autopilot runs its own gap phase) |
| **Intraday Guide** | Strategy playbook and timing notes |

---

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| No scan progress (instant 100%) | Force phase `gap_scan` or `opening`; check market session / phase |
| Breeze errors | Refresh daily session token in secrets; use **Auto** or **Yahoo** |
| Slow scans | Reduce **max tickers**; use **Yahoo** for NSE in paper mode |
| No paper trades | Raise **min gate score** test lower; check regime and session open |
| Live orders blocked | Env vars, kill switch, Breeze connection, `AUTOPILOT_LIVE_CONFIRM=YES` |

---

*Educational use only — not financial advice. Trade at your own risk.*
