# IntraBot — Intraday Automation Engine

A fully automated intraday scanner + trader for **NSE (Nifty)** and **US (NYSE)**.  
**Paper mode by default.** Plug in Breeze (NSE) or Alpaca (US) keys to go live.

Open in StockSight: **Algo Strategy → IntraBot Automation**

---

## Architecture

```
stocksight/intrabot/
├── config.py          ← All parameters (RISK, BROKER_CONFIG)
├── data_fetcher.py    ← yfinance / Breeze + RSI, EMA, VWAP, ATR
├── strategies.py      ← 6 scanners (Gap, Momentum, ORB, ATH, VWAP, Broad)
├── risk_manager.py    ← Position sizing, trailing stops, daily loss halt
├── executor.py        ← Paper / Breeze (NSE) / Alpaca stub (US)
├── alerts.py          ← Event log + optional webhook
├── scheduler.py       ← IST / ET session phases
└── engine.py          ← Orchestrator

scripts/run_intrabot.py   ← CLI loop
intrabot_page.py          ← Streamlit UI + event log table
```

---

## Session schedule (summary)

| IST (NSE) | Phase | Strategies |
|-----------|-------|--------------|
| 09:15–09:20 | Gap scanner | Gap-Up, Broad |
| 09:20–09:30 | Mood shortlist (top 3) | — |
| 09:30–09:45 | Opening scan | Momentum, Gap, Broad |
| 09:45–10:15 | ORB entries | ORB, Momentum |
| 10:30–13:00 | VWAP + ATH | VWAP, ATH |
| 12:30–15:00 | Lunch monitor | No new entries |
| 14:30–15:15 | Afternoon | VWAP, Momentum, Broad |
| 15:15–15:30 | NSE square-off | Close positions |

US phases follow NYSE hours (gap, open, ORB, afternoon, square-off).  
**Every 60s (continuous mode):** position monitor — trailing stops.

---

## Risk defaults

| Parameter | Default | Config |
|-----------|---------|--------|
| Capital per trade | 5% | `RISK.capital_per_trade_pct` |
| Max open positions | 5 | `RISK.max_open_positions` |
| Stop loss | 1% | `RISK.stop_loss_pct` |
| Target R:R | 1:2 | `RISK.target_rr` |
| Trail after | +1.5% | `RISK.trail_stop_after_pct` |
| Trail distance | 0.8% | `RISK.trail_stop_distance_pct` |
| Daily loss halt | -2% | `RISK.max_daily_loss_pct` |

---

## UI features

- **Event log** — every scan, order, trail update, halt (newest first)
- **Live progress** during scans
- **Continuous mode** — tick + monitor on an interval
- **Force phase** — test gap / ORB / square-off
- **Kill switch** — stop all actions

---

## CLI

```bat
python scripts\run_intrabot.py --once --mode auto --markets NSE
python scripts\run_intrabot.py --loop --interval 60 --mode auto
```

---

## Going live

- **NSE:** Breeze credentials in `.streamlit/secrets.toml` · uncheck Paper in UI  
- **US:** Set `ALPACA_API_KEY` / `ALPACA_API_SECRET` (stub — extend `executor.py`)  
- **Zerodha:** Set `KITE_API_KEY` / `KITE_ACCESS_TOKEN` in env (extend executor)

---

## State file (gitignored)

`stocksight/.intrabot_state.json` — watchlist, log, trail stops, daily P&L flags.

---

*Educational framework — not financial advice. Test in paper mode first.*
