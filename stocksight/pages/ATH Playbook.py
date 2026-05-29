"""ATH Strategy Playbook — the complete rule-based framework for All-Time-High breakouts (intraday, swing, long-term)."""
import streamlit as st
from ui_components import inject_css, safe_set_page_config

safe_set_page_config(page_title="ATH Strategy Playbook | StockSight", page_icon="🏔️", layout="wide")
inject_css()

st.markdown(
    """
<div style='background:linear-gradient(135deg,#0a1f1a 0%,#0f2a22 100%);
            border:1px solid #1a3b31; border-left:5px solid #00e5a0;
            border-radius:12px; padding:20px 24px; margin-bottom:16px;'>
  <div style='font-size:1.6rem; font-weight:800; color:#e8f7ef;'>🏔️ All-Time High Strategy</div>
  <div style='color:#a3d8b8; margin-top:6px; font-size:0.95rem;'>
    A complete rule-based framework for identifying, entering, and riding ATH breakouts —
    for <b>intraday</b>, <b>weekly swing</b>, and <b>long-term</b> analysis.
  </div>
</div>
""",
    unsafe_allow_html=True,
)

st.info(
    "🧭 **Where to act in StockSight:** "
    "**⚡ Intraday Screener → 🏔️ ATH strategy** (day breakouts) · "
    "**🏔️ Weekly Swing ATH** (52-week-high breakouts) · "
    "**🚀 Long-Term ATH** (monthly all-time-high leaders). "
    "This page is the rulebook behind all three."
)

# ── 01 ────────────────────────────────────────────────────────
st.markdown("## 01 · What Is ATH & Why It Works")
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown(
        "**Definition**\n\n"
        "All-Time High (ATH) is the highest price a stock has ever traded. A breakout above "
        "ATH is one of the most powerful setups — **every prior seller is in profit and there is "
        "zero overhead resistance**."
    )
with c2:
    st.markdown(
        "**Psychology**\n\n"
        "- No trapped sellers above ATH — price moves freely\n"
        "- FOMO from institutions + retail drives momentum\n"
        "- Market is in **price discovery** — trend accelerates\n"
        "- Strong fundamentals often confirm the move"
    )
with c3:
    st.markdown(
        "**Statistical edge**\n\n"
        "- ATH breakouts: **55–65%** weekly follow-through\n"
        "- 52W-high stocks often continue **6–12 months**\n"
        "- Low-base + volume = institutional buying\n"
        "- Index ATH names outperform **70%+** over 1 year"
    )

st.markdown("---")

# ── 02 ────────────────────────────────────────────────────────
st.markdown("## 02 · Core ATH Entry Rules")
RULES = [
    ("📌", "Rule 1 — Confirm with Volume",
     "Breakout volume must be **1.5× to 2× the 20-day average**. A low-volume ATH breakout is a trap — "
     "it lacks institutional participation. Wait for the **candle close**, not the intraday touch."),
    ("📐", "Rule 2 — The Base Must Be Tight",
     "Best breakouts come after a **tight, flat consolidation of 3–8 weeks** (weekly) or 5–15 days (daily). "
     "A wide, loose base means weak conviction — skip it."),
    ("📊", "Rule 3 — Price Must Close Above Prior ATH",
     "Do not enter on an intraday touch. Wait for a **confirmed daily/weekly close above the prior ATH**. "
     "This filters out false breakouts and news spikes that reverse by end of session."),
    ("📈", "Rule 4 — Trend Must Be Intact (Moving Averages)",
     "Price must trade above **20 EMA > 50 EMA > 200 EMA**. A stock breaking ATH while below its 50 EMA is a red flag."),
    ("🧮", "Rule 5 — Sector / Market in Sync",
     "Highest-probability ATH trades occur when **stock + sector + broader index** all trend up together. "
     "A lone stock at ATH while its sector falls = weak setup."),
    ("🛑", "Rule 6 — Define Stop Loss Immediately",
     "Stop **just below the breakout base** (prior consolidation low). Intraday: 0.5–1% below entry. "
     "Swing/long-term: 5–8% below the breakout. **No stop = no trade.**"),
    ("🎯", "Rule 7 — Target with R:R (Minimum 1:2)",
     "If your stop is 3% below entry, the minimum target is 6% above. ATH breakouts tend to run "
     "**1.5×–3× the base depth** — use that projection as the first target."),
    ("🔁", "Rule 8 — Retest = Second-Chance Entry",
     "If a stock breaks ATH then pulls back to retest that level (now support), this is often the "
     "**highest-conviction entry**. Pullback volume should be **lower** than the breakout day."),
]
for emoji, title, body in RULES:
    st.markdown(
        f"""
<div style='background:#0f2a22; border:1px solid #1a3b31; border-left:4px solid #00e5a0;
            border-radius:8px; padding:12px 16px; margin-bottom:8px;'>
  <div style='color:#e8f7ef; font-weight:700;'>{emoji} {title}</div>
  <div style='color:#a3d8b8; font-size:0.9rem; margin-top:4px;'>{body}</div>
</div>
""",
        unsafe_allow_html=True,
    )

st.warning(
    "**Golden Rule:** Never chase an ATH breakout already **8–10%+ extended** from its base. "
    "Wait for the retest or skip it — the risk:reward deteriorates significantly."
)

st.markdown("---")

# ── 03 ────────────────────────────────────────────────────────
st.markdown("## 03 · ATH Breakout Structure")
st.code(
    """──────────────────────────────── Target 2  (+15% to +20%)
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ Target 1  (+8% to +10%)
════════════════════════════════ ◄ ATH BREAKOUT LEVEL  (entry zone begins)
════════════════════════════════ ◄ Prior ATH / Retest support  (best entry on pullback)
· · · · · · · · · · · · · · · · ·  Consolidation / Base  (tight = bullish)
· · · · · · · · · · · · · · · · ·
──────────────────────────────── ◄ Stop Loss  (below base / breakout candle low)

Entry:        On close above ATH
Best Entry:   Retest of ATH level
Confirmation: Volume 1.5x+
Stop:         Below base low
Target 1:     8–10% above breakout
Target 2:     Base depth × 1.5""",
    language="text",
)

st.markdown("---")

# ── 04 ────────────────────────────────────────────────────────
st.markdown("## 04 · Intraday vs Swing vs Long-Term")
st.markdown(
    """
| Parameter | 🏔️ Intraday ATH | 🏔️ Swing (Weekly) | 🚀 Long-Term (Monthly) |
|-----------|-----------------|--------------------|------------------------|
| **Timeframe** | 5m / 15m chart | Daily / Weekly | Weekly / Monthly |
| **ATH reference** | Day's / prior day's high | 52-week high breakout | All-time historical high |
| **Volume filter** | 2× avg intraday on breakout | 1.5× 20-day avg | Above-average monthly |
| **Entry trigger** | 15m close above ATH | Daily/weekly close > 52W high | Monthly close > ATH |
| **Stop loss** | 0.5–1% or VWAP break | 5–8% below breakout | Below base / 10–15% trail |
| **Target** | 1–2% (1:2 R:R min) | 10–20% above breakout | 30–100%+ multibagger |
| **Key indicators** | VWAP, RSI 5m, Volume | EMA 20/50, RSI 14, MACD | EMA 200, Rel. Strength, PE |
| **Best suited for** | Active traders, liquid names | Part-time / momentum | Investors / compounders |
| **Universe to use** | Nifty 50 / liquid US | Nifty 500 / S&P 500 | Nifty 500 / S&P 500 |

*In StockSight: Intraday ATH lives inside the **Intraday Screener** (select the 🏔️ strategy); the
**Weekly Swing ATH** and **Long-Term ATH** pages cover the other two tiers.*
"""
)

st.markdown("### ⏰ When to scan — by time zone (IST · NL · US ET)")
st.caption(
    "Times shown for **summer** (IST = UTC+5:30 · NL/CEST = UTC+2 · US/ET = UTC−4). "
    "In winter subtract 1 hour from the NL and US columns. NL = Netherlands (Europe/Amsterdam)."
)

tz_intraday, tz_swing, tz_long = st.tabs(
    ["🏔️ Intraday ATH (clock)", "🏔️ Weekly Swing ATH (cadence)", "🚀 Long-Term ATH (cadence)"]
)

with tz_intraday:
    st.markdown(
        "**If you trade the 🇮🇳 Indian market (NSE) — scan the Intraday Screener with the 🏔️ ATH strategy:**\n\n"
        "| 🇮🇳 IST | 🇳🇱 NL (CEST) | 🇺🇸 US (ET) | What to do |\n"
        "|--------|--------------|-----------|------------|\n"
        "| 9:15–9:30 AM | 5:45–6:00 AM | 11:45 PM–12:00 AM | **Don't scan ATH yet** — mark the opening range, watch gaps. |\n"
        "| 10:00–11:00 AM | 6:30–7:30 AM | 12:30–1:30 AM | **Best ATH window** — scan now; volume is real, breakouts hold. |\n"
        "| 12:00–1:00 PM | 8:30–9:30 AM | 2:30–3:30 AM | Lunch lull — **avoid new ATH entries** (fake volume). |\n"
        "| 2:00–3:00 PM | 10:00–11:00 AM | 4:00–5:00 AM | Second ATH window — re-scan for afternoon breakouts. |\n"
        "| 3:15–3:30 PM | 11:15 AM–12:00 PM | 5:15–6:00 AM | **Square off** intraday; no fresh ATH trades into the close. |\n"
    )
    st.markdown(
        "**If you trade the 🇺🇸 US market (NYSE/NASDAQ) — scan the Intraday Screener with the 🏔️ ATH strategy:**\n\n"
        "| 🇺🇸 US (ET) | 🇳🇱 NL (CEST) | 🇮🇳 IST | What to do |\n"
        "|-----------|--------------|--------|------------|\n"
        "| 9:30–9:45 AM | 3:30–3:45 PM | 7:00–7:15 PM | **Don't scan ATH yet** — mark opening range, let the first 5 min settle. |\n"
        "| 9:45–11:00 AM | 3:45–5:00 PM | 7:15–8:30 PM | **Best ATH window** — scan now; opening-hour volume confirms breakouts. |\n"
        "| 11:00 AM–1:30 PM | 5:00–7:30 PM | 8:30–11:00 PM | Mid-day chop — fewer, cleaner ATH trades only. |\n"
        "| 3:00–3:55 PM | 9:00–9:55 PM | 12:30–1:25 AM | Power hour — re-scan for end-of-day ATH momentum. |\n"
        "| 3:55–4:00 PM | 9:55–10:00 PM | 1:25–1:30 AM | **Close out** intraday; no overnight on intraday ATH. |\n"
    )
    st.info(
        "🇳🇱 **Living in the Netherlands?** The US ATH window (**3:45–5:00 PM CEST**) is the most convenient — "
        "you catch the US opening hour after work hours start. The NSE ATH window falls in your **early morning "
        "(6:30–7:30 AM CEST)**."
    )

with tz_swing:
    st.markdown(
        "Swing ATH is a **weekly** decision — you don't watch a clock, you scan on a **cadence**:\n\n"
        "| When | 🇮🇳 IST | 🇳🇱 NL (CEST) | 🇺🇸 US (ET) | What to do |\n"
        "|------|--------|--------------|-----------|------------|\n"
        "| **Fri / weekend** (after weekly close) | Sat morning | Fri 12:00 PM+ / weekend | Fri after 4:00 PM | **Run Weekly Swing ATH** to find fresh 52-week-high breakouts on confirmed weekly candles. |\n"
        "| **Sun / Mon pre-open** | Mon 8:00 AM | Mon 4:30 AM | Sun evening | Build your watchlist; mark breakout + retest levels. |\n"
        "| **Intraday (any session)** | use clock above | use clock above | use clock above | Enter watchlist names on a **daily/weekly close above the level** (or a low-volume retest). |\n"
    )
    st.caption(
        "Why weekend: the weekly candle only finalises at Friday's close, so a weekend scan avoids acting on an "
        "unconfirmed mid-week breakout. NSE weekly closes Friday ~3:30 PM IST; US weekly closes Friday 4:00 PM ET."
    )

with tz_long:
    st.markdown(
        "Long-Term ATH is a **monthly** decision — scan on a slow cadence and hold for months/years:\n\n"
        "| When | 🇮🇳 IST | 🇳🇱 NL (CEST) | 🇺🇸 US (ET) | What to do |\n"
        "|------|--------|--------------|-----------|------------|\n"
        "| **Month-end / 1st week** | after monthly close | after monthly close | after monthly close | **Run Long-Term ATH** to find true all-time-high breakouts above the 200-DMA with quality fundamentals. |\n"
        "| **Same week** | any time | any time | any time | Verify ROE / debt / promoter holding + earnings on Screener.in / NSE before committing. |\n"
        "| **On a confirmed monthly close > ATH** | — | — | — | Scale in over **2–3 tranches**; trail a wide **10–15%** stop; review monthly. |\n"
    )
    st.caption(
        "Why month-end: the monthly candle finalises on the last trading day of the month, so scanning in the "
        "first few days of the new month acts only on confirmed all-time-high breakouts — not intra-month noise."
    )

st.markdown("---")

# ── 05 ────────────────────────────────────────────────────────
st.markdown("## 05 · How to Find ATH Stocks — Screener Rules")
c1, c2 = st.columns(2)
with c1:
    st.markdown(
        "**Technical filters**\n\n"
        "- Price = 52-week high **OR** within 2–3% of ATH\n"
        "- Volume today > **1.5×** 20-day average\n"
        "- RSI (14) between **55–75** (strong, not overextended)\n"
        "- **20 EMA > 50 EMA > 200 EMA** (bull alignment)\n"
        "- MACD histogram positive and rising\n"
        "- Up **20–50%** in last 3–6 months (momentum)\n"
        "- Tight consolidation base (low ATR % last 3 weeks)\n"
        "- Relative Strength vs index > 1.0"
    )
with c2:
    st.markdown(
        "**Fundamental filters (long-term)**\n\n"
        "- ROE > **15%** consistently for 3+ years\n"
        "- Revenue + profit growing **15%+ YoY**\n"
        "- Debt-to-Equity < **0.5** (low leverage)\n"
        "- Promoter holding > **50%** (skin in the game)\n"
        "- FII/DII buying in recent quarters\n"
        "- Operating cash flow positive & expanding\n"
        "- Not at a cyclical peak (check macro)\n"
        "- PE not more than 2× sector average"
    )
st.caption(
    "The Weekly Swing ATH page automates the technical filters; the Long-Term ATH page adds the "
    "ROE / Debt-Equity quality gates. Always confirm promoter holding and earnings on Screener.in / NSE."
)

st.markdown("---")

# ── 06 ────────────────────────────────────────────────────────
st.markdown("## 06 · False ATH Signals — What to Avoid")
FALSE = [
    ("❌ Low-volume breakout", "ATH on below-average volume = news spike / thin market. No institutional participation. **Skip.**"),
    ("❌ Overextended / parabolic", "Up 30%+ in 2 weeks, RSI > 80, no base. Buying here is chasing. **Wait for a base.**"),
    ("❌ Sector in downtrend", "Stock at ATH but the sector index declines. Lone-wolf moves are unsustainable. **Skip.**"),
    ("❌ ATH on bad fundamentals", "Declining earnings, rising debt, or promoter selling = hype/manipulation. **Avoid (long-term).**"),
    ("❌ Wide & choppy base", "A base swinging 15–20% is distribution, not consolidation. **Skip.**"),
    ("⚠️ Intraday touch only", "Hit ATH intraday but closed below. Most false breakouts happen here. **Wait for a close.**"),
]
for title, body in FALSE:
    st.markdown(
        f"""
<div style='background:#2e0a0a; border:1px solid #3b1a1a; border-left:4px solid #ff4d4d;
            border-radius:8px; padding:10px 14px; margin-bottom:8px;'>
  <span style='color:#ffd0d0; font-weight:700;'>{title}</span>
  <span style='color:#e8b8b8; font-size:0.9rem;'> — {body}</span>
</div>
""",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ── 07 ────────────────────────────────────────────────────────
st.markdown("## 07 · ATH Trade Decision Checklist")
c1, c2 = st.columns(2)
with c1:
    st.markdown(
        "**✅ Go conditions (all must be YES)**\n\n"
        "- Daily/weekly close above prior ATH confirmed\n"
        "- Volume **1.5×** or more above average\n"
        "- RSI 14 between **55 and 75** (not overbought)\n"
        "- EMA alignment bullish (20 > 50 > 200)\n"
        "- Base was tight (3–8 weeks, low volatility)\n"
        "- Sector and index trending up\n"
        "- Stop loss defined and within tolerance\n"
        "- Risk:Reward ≥ **1:2**"
    )
with c2:
    st.markdown(
        "**🚫 No-Go conditions (any one = skip)**\n\n"
        "- Only intraday touch, no closing confirmation\n"
        "- Volume below / equal to 20-day average\n"
        "- RSI > 80 (overbought, parabolic)\n"
        "- Price extended 10%+ above base without retest\n"
        "- Sectoral index in downtrend\n"
        "- Declining earnings or promoter selling\n"
        "- Index in correction / bearish phase\n"
        "- Wide / choppy base (not tight)"
    )

st.success(
    "**Key principle:** volume + confirmed close + tight base = the highest-probability ATH setup. "
    "Run the matching ATH screener, then walk every candidate through this checklist before you act."
)

st.markdown("---")
st.caption("⚠️ Educational only — not financial advice. Always pair with strict risk management (1–2% per trade, hard stops).")
