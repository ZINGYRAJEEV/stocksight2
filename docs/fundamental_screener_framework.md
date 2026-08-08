# Fundamental Screener Framework — 3-Tier System

A top-down filtering framework for finding **reliable, debt-free, scam-free, fast-growth** stocks, built around Screener.in fields and designed to work alongside StockSight's BTST/momentum tooling.

---

## Overview

| Tier | Purpose | Strictness | Cadence |
|---|---|---|---|
| 1. Watchlist | Wide research funnel | Loose | Monthly |
| 2. Strict Fundamental | High-conviction buy candidates | Tight | On demand, before deploying capital |
| 3. Momentum Overlay | Entry timing on watchlist/strict names | Tight + price action | Before a swing/BTST entry |

**Workflow:**
```
Watchlist (monthly)
   -> research & track repeats
      -> Strict Fundamental (on demand)
         -> shortlist for long-term portfolio
      -> Momentum Overlay (before entry)
         -> shortlist for swing/BTST entries
```

---

## Tier 1 — Watchlist

**Screener.in query:**
```
Market Capitalization > 500 AND
Debt to equity < 0.5 AND
Promoter holding > 40 AND
Pledged percentage < 10 AND
Return on equity > 12 AND
Sales growth 3Years > 8 AND
Profit growth 3Years > 8 AND
Price to Earning < Industry PE + 5
```

**Steps:**
1. Run monthly, export the full list.
2. Read up on each new entrant (annual report, concalls, sector context) — feeds "story building" notes.
3. Track repeat appearances over time — consistency across months is a positive signal.

---

## Tier 2 — Strict Fundamental

**Screener.in query:**
```
Market Capitalization > 1000 AND
Debt to equity < 0.3 AND
Interest Coverage Ratio > 8 AND
Current ratio > 1.5 AND
Promoter holding > 50 AND
Change in promoter holding > -2 AND
Pledged percentage < 5 AND
Return on equity > 15 AND
Average return on equity 3Years > 15 AND
Return on capital employed > 18 AND
Return on assets > 8 AND
OPM > 12 AND
Sales growth 3Years > 12 AND
Profit growth 3Years > 12 AND
YOY Quarterly sales growth > 10 AND
YOY Quarterly profit growth > 10 AND
Price to Earning < Industry PE AND
PEG Ratio < 1.5 AND
Price to book value < 8
```

**Steps:**
1. Run on demand, before allocating fresh capital.
2. If it returns 0-2 stocks, relax **one** dimension at a time — start with PEG or P/B (valuation is usually the binding constraint). Never loosen debt or promoter-holding/pledge filters; those are the scam-free guardrails.
3. Cross-check survivors manually against the company-categorization framework (fast grower / stalwart / cyclical / turnaround / slow grower).
4. Size positions per the 15-20 stock portfolio rule.

---

## Tier 3 — Momentum Overlay

**Screener.in query:**
```
Market Capitalization > 500 AND
Debt to equity < 0.5 AND
Promoter holding > 40 AND
Pledged percentage < 10 AND
Return on equity > 12 AND
Sales growth 3Years > 8 AND
Profit growth 3Years > 8 AND
Return over 3months > 0 AND
Return over 6months > 10 AND
Return over 3months > Return over 1year / 4
```

**Steps:**
1. Run only against Watchlist/Strict names — not as a standalone discovery tool (risk of catching speculative pumps).
2. For every stock that clears it, identify the catalyst (earnings beat, sector re-rating, index inclusion, news). No identifiable fundamental reason = treat with suspicion.
3. Feed qualifying names into the existing BTST/swing execution rules: 50% exit at open on >=1.5% gap-up, T1 at +2%, T2 at +3.5%, defined stop-loss per screener export.

> Note: `Return over 3months > Return over 1year / 4` is a simplified acceleration proxy (checks if the recent quarter is outpacing the trailing year's average quarterly pace), not a rigorous statistical test. Validate against known cases before trusting at scale.

---

## Field Reference by Category

**Size/Liquidity:** Market Capitalization, Current price

**Debt-Free:** Debt to equity, Debt, Current ratio, Interest Coverage Ratio

**Scam-Free / Governance:** Promoter holding, Change in promoter holding, Pledged percentage

**Reliability/Quality:** Return on equity, Average ROE (3Yr/5Yr), Return on capital employed, Return on assets, OPM

**Fast Growth:** Sales growth (latest/3Yr/5Yr), Profit growth (latest/3Yr/5Yr), YOY Quarterly sales/profit growth, Sales & PAT latest quarter

**Valuation Sanity Check:** Price to Earning, Industry PE, PEG Ratio, Price to book value, EV/EBITDA, Earnings yield

**Momentum (Tier 3 only):** Return over 3/6 months, Return over 1/3/5 years

**Secondary/optional:** Sales, Profit after tax, EPS, Dividend yield, Price to Sales, Price to Free Cash Flow, Enterprise Value
