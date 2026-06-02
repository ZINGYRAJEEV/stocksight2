# Intraday Autopilot

Continuous job that runs your **daily playbook** on **NSE + US**: gap → open → ORB → trend/ATH → VWAP → lunch (manage only) → afternoon → **square-off** → EOD.

## Safety defaults

| Mode | Behaviour |
|------|-----------|
| `dry_run` | Logs signals only — no orders |
| `paper` | **Default** — virtual ledger (`paper_trading`) |
| `live` | ICICI Breeze MIS — requires `AUTOPILOT_ENABLED=true` and `AUTOPILOT_LIVE_CONFIRM=YES` |

**Kill switch** in UI or state file stops all actions immediately.

## Streamlit

**Algo Strategy → Intraday Autopilot**

- Shows current phase (IST / ET)
- Run one tick manually
- View regime, watchlist, event log

## Local continuous run

```bat
python scripts\run_autopilot.py --loop --interval 300 --mode paper
```

Single tick:

```bat
python scripts\run_autopilot.py --once --markets NSE --mode paper
```

Force square-off:

```bat
python scripts\run_autopilot.py --once --phase square_off --markets NSE
```

## Schedule (built-in)

### NSE (IST)

| Phase | Time (approx) | Strategies |
|-------|----------------|------------|
| pre_open | 8:00–9:15 | Context |
| gap_scan | 9:15–9:20 | GAP |
| mood_shortlist | 9:20–9:30 | Watchlist top 5 |
| opening | 9:30–9:45 | GAP, MOMENTUM, BROAD |
| orb | 9:45–10:15 | ORB, MOMENTUM |
| trend_ath | 10:00–12:30 | MOMENTUM, ATH, BROAD |
| vwap | 10:30–13:00 | VWAP |
| lunch | 12:30–14:00 | **No new entries** |
| afternoon | 14:30–15:15 | MOMENTUM, BROAD |
| square_off | 15:15–15:25 | Close all autopilot positions |
| eod | 15:30+ | P&L summary |

### US (ET)

Parallel phases for premarket, open, ORB, VWAP, power hour, square-off ~3:55 PM ET.

## Scoring & risk

- Merges intraday scan + **Quality Gate** score
- Respects max open positions, max trades/day, min gate score, min R:R
- Regime from gap mood adjusts aggression

## SEBI / production

This is a **research automation** layer, not exchange-approved algo infrastructure. Production requires broker hosting, strategy approval, Algo IDs, throttles, and audit logs per SEBI.

## State files (local, gitignored)

- `stocksight/.intraday_autopilot_state.json`
- `stocksight/.paper_trading.json`
