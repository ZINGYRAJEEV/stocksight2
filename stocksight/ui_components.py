"""
ui_components.py — Shared UI helpers for all signal pages.
"""

import streamlit as st
import pandas as pd
from signals import SignalResult, SCENARIOS


# ─────────────────────────────────────────────
# Page-level CSS (call once per page)
# ─────────────────────────────────────────────

BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

:root {
    color-scheme: light;
    --app-bg: #f8fafc;
    --app-text: #111827;
    --button-bg: linear-gradient(135deg,#25d366,#1aa34b);
}
@media (prefers-color-scheme: dark) {
    :root {
        color-scheme: dark;
        --app-bg: #0d1f18;
        --app-text: #e8f7ef;
    }
}

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
    background-color: var(--app-bg);
    color: var(--app-text);
}
.stButton > button {
    background: var(--button-bg);
    color: #000; font-family:'IBM Plex Mono',monospace;
    font-weight:700; font-size:0.82rem; border:none; border-radius:6px;
    padding:10px 24px; letter-spacing:1px; text-transform:uppercase;
    cursor:pointer; width:100%;
}
.stButton > button:hover { opacity:0.92; }
[data-testid="stSidebar"] { background:#ffffff; border-right:1px solid #d4d4d4; color:#111827; }
[data-testid="stSidebar"] label { color:#111827 !important; font-size:0.8rem; }
.stProgress > div > div { background-color:#25d366; }
hr { border-color:#d4d4d4 !important; }
</style>
"""


def inject_css():
    st.markdown(BASE_CSS, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Scenario header banner
# ─────────────────────────────────────────────

def scenario_header(scenario_id: str):
    s = SCENARIOS[scenario_id]
    signal_colors = {
        "BUY":           ("#00e5a0", "#0a2e1e"),
        "SELL":          ("#ff4d4d", "#2e0a0a"),
        "CAUTIOUS BUY":  ("#ff9d42", "#2e1a00"),
        "WAIT":          ("#a0a0a0", "#1a1a1a"),
    }
    sig   = s["signal"]
    fc, bc = signal_colors.get(sig, ("#ffffff", "#1a1a1a"))

    st.markdown(f"""
    <div style='background:#122f25; border:1px solid #1a3b31;
                border-left:4px solid {s["color"]};
                border-radius:8px; padding:20px 24px; margin-bottom:20px;'>
        <div style='display:flex; align-items:center; gap:14px; flex-wrap:wrap;'>
            <span style='font-size:2rem;'>{s["emoji"]}</span>
            <div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1.3rem;
                            font-weight:700; color:#e8f7ef;'>{s["title"]}</div>
                <div style='font-size:0.82rem; color:#a3d8b8; margin-top:3px;'>
                    {s["description"]}
                </div>
            </div>
            <div style='margin-left:auto;
                        background:{bc}; border:1px solid {fc};
                        border-radius:20px; padding:5px 16px;
                        font-family:"IBM Plex Mono",monospace;
                        font-size:0.78rem; font-weight:700; color:{fc};
                        white-space:nowrap;'>
                {sig}
            </div>
        </div>
        <div style='display:flex; gap:24px; margin-top:14px; flex-wrap:wrap;'>
            <div style='flex:1; min-width:180px; background:#16352c;
                        border:1px solid #1a3b31; border-radius:6px; padding:10px 14px;'>
                <div style='font-size:9px; color:#a3d8b8; text-transform:uppercase;
                            letter-spacing:1.5px; margin-bottom:5px;'>Entry Trigger</div>
                <div style='font-size:0.78rem; color:#e8f7ef;'>{s["entry_note"]}</div>
            </div>
            <div style='flex:1; min-width:180px; background:#16352c;
                        border:1px solid #1a3b31; border-radius:6px; padding:10px 14px;'>
                <div style='font-size:9px; color:#a3d8b8; text-transform:uppercase;
                            letter-spacing:1.5px; margin-bottom:5px;'>Stop Loss</div>
                <div style='font-size:0.78rem; color:#e8f7ef;'>{s["sl_note"]}</div>
            </div>
            <div style='flex:1; min-width:180px; background:#16352c;
                        border:1px solid #1a3b31; border-radius:6px; padding:10px 14px;'>
                <div style='font-size:9px; color:#a3d8b8; text-transform:uppercase;
                            letter-spacing:1.5px; margin-bottom:5px;'>Targets</div>
                <div style='font-size:0.78rem; color:#e8f7ef;'>{s["target_note"]}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Trade plan card — one card per stock
# ─────────────────────────────────────────────

def trade_plan_card(r: SignalResult, scenario_id: str):
    s       = SCENARIOS[scenario_id]
    color   = s["color"]
    is_sell = r.signal_label in ("SELL / AVOID", "SELL")
    is_wait = r.signal_label in ("HOLD / WAIT", "WAIT")

    conf_color = {"HIGH": "#25d366", "MEDIUM": "#f0b429", "LOW": "#e05252"}.get(r.confidence, "#a0a0a0")

    # Candle flags
    candle_html = ""
    if r.is_green:
        candle_html += '<span style="color:#25d366; font-size:0.72rem;">● Green candle</span> &nbsp;'
    if r.reversal:
        candle_html += '<span style="color:#25d366; font-size:0.72rem;">↑ Reversal</span> &nbsp;'
    if r.rsi_rising:
        candle_html += f'<span style="color:#4db8ff; font-size:0.72rem;">RSI rising ({r.rsi_prev}→{r.rsi})</span>'
    else:
        candle_html += f'<span style="color:#ff9d42; font-size:0.72rem;">RSI flat/falling ({r.rsi_prev}→{r.rsi})</span>'

    # Levels section
    if is_sell:
        levels_html = f"""
        <div style='display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;'>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #2e1414;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Entry (current)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#e8f7ef; font-weight:700;'>{r.currency}{r.entry:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1a3b31;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>T1 (−3%)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff9d42; font-weight:600;'>{r.currency}{r.target1:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1a3b31;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>T2 (−7%)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff4d4d; font-weight:600;'>{r.currency}{r.target2:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1a3b31;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>T3 (−12%)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff4d4d; font-weight:600;'>{r.currency}{r.target3:,.2f}</div>
            </div>
        </div>
        """
    elif is_wait:
        levels_html = f"""
        <div style='background:#16352c; border:1px dashed #2a2a2a; border-radius:5px;
                    padding:10px 14px; margin-top:10px; font-size:0.78rem; color:#a3d8b8;'>
            ⏸️ Pre-calculated levels (activate only on confirmation)<br>
            <span style='color:#7abeac;'>Entry zone:</span> {r.currency}{r.entry:,.2f} &nbsp;|&nbsp;
            <span style='color:#7abeac;'>SL:</span> {r.currency}{r.stop_loss:,.2f} &nbsp;|&nbsp;
            <span style='color:#7abeac;'>T1:</span> {r.currency}{r.target1:,.2f} &nbsp;|&nbsp;
            <span style='color:#7abeac;'>T2:</span> {r.currency}{r.target2:,.2f}
        </div>
        """
    else:
        levels_html = f"""
        <div style='display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;'>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c3020;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Entry</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#e8f7ef; font-weight:700;'>{r.currency}{r.entry:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #2e1414;'>
                <div style='font-size:9px; color:#e05252; letter-spacing:1px;
                            text-transform:uppercase;'>Stop Loss</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff6b6b; font-weight:600;'>{r.currency}{r.stop_loss:,.2f}</div>
                <div style='font-size:9px; color:#a3d8b8; margin-top:2px;'>
                    Risk {r.risk_pct:.1f}%</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c2e1c;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Target 1</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#7ed4a0; font-weight:600;'>{r.currency}{r.target1:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c2e1c;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Target 2</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#25d366; font-weight:700;'>{r.currency}{r.target2:,.2f}</div>
                <div style='font-size:9px; color:#a3d8b8; margin-top:2px;'>
                    RRR {r.rrr:.1f}×</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c2e1c;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Target 3</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#1aa34b; font-weight:700;'>{r.currency}{r.target3:,.2f}</div>
            </div>
        </div>
        """

    # Links
    links_html = " &nbsp;".join([
        f'<a href="{url}" target="_blank" style="color:{color}; font-size:0.72rem; '
        f'text-decoration:none; border:1px solid {color}33; border-radius:4px; '
        f'padding:2px 8px;">{name} ↗</a>'
        for name, url in r.links.items()
    ])

    st.markdown(f"""
    <div style='background:#122f25; border:1px solid #1a3b31;
                border-left:4px solid {color};
                border-radius:8px; padding:16px 18px; margin-bottom:14px;'>

        <div style='display:flex; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; gap:8px;'>
            <div>
                <span style='font-family:"IBM Plex Mono",monospace; font-size:1.2rem;
                              font-weight:700; color:#e8f7ef;'>{r.ticker}</span>
                <span style='font-family:"IBM Plex Mono",monospace; font-size:1.1rem;
                              color:#a3d8b8; margin-left:12px;'>{r.currency}{r.price:,.2f}</span>
            </div>
            <div style='display:flex; gap:8px; align-items:center; flex-wrap:wrap;'>
                <span style='font-size:9px; background:{conf_color}22; border:1px solid {conf_color}55;
                              color:{conf_color}; border-radius:12px; padding:2px 10px;
                              font-weight:700; letter-spacing:1px;'>
                    {r.confidence} CONFIDENCE
                </span>
                <span style='font-size:9px; color:#a3d8b8; font-family:"IBM Plex Mono",monospace;'>
                    ⏱ {r.timeframe}
                </span>
            </div>
        </div>

        <div style='display:flex; gap:20px; margin-top:10px; flex-wrap:wrap;
                    font-family:"IBM Plex Mono",monospace; font-size:0.78rem;'>
            <span><span style='color:#a3d8b8;'>PE  </span>{r.pe:.1f}×</span>
            <span><span style='color:#a3d8b8;'>VOL </span>{r.vol_ratio:.2f}×&nbsp;avg</span>
            <span><span style='color:#a3d8b8;'>RSI </span>{r.rsi:.1f}</span>
        </div>

        <div style='margin-top:8px;'>{candle_html}</div>

        {levels_html}

        <div style='margin-top:12px; font-size:0.75rem; color:#7abeac;
                    border-top:1px solid #1a3b31; padding-top:8px;'>
            💡 {r.note}
        </div>

        <div style='margin-top:10px;'>{links_html}</div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Results table (compact summary)
# ─────────────────────────────────────────────

def results_table(results: list[SignalResult], scenario_id: str):
    if not results:
        return

    rows = []
    for r in results:
        rows.append({
            "Ticker":       r.ticker,
            "Price":        r.price,
            "PE":           r.pe,
            "Vol×":         r.vol_ratio,
            "RSI":          r.rsi,
            "RSI Rising":   "↑" if r.rsi_rising else "→/↓",
            "Green Candle": "✅" if r.is_green else "—",
            "Reversal":     "✅" if r.reversal  else "—",
            "Entry":        r.entry,
            "Stop Loss":    r.stop_loss,
            "Target 2":     r.target2,
            "Risk %":       r.risk_pct,
            "Confidence":   r.confidence,
        })

    df = pd.DataFrame(rows)

    link_cols_nse = ["Yahoo Finance", "Moneycontrol", "TradingView"]
    link_cols_us  = ["Yahoo Finance", "MarketWatch",  "TradingView"]

    # Add first available link set
    if results:
        for name, url in results[0].links.items():
            col_name = name
            df[col_name] = [r.links.get(name, "") for r in results]

    col_cfg = {
        "Entry":     st.column_config.NumberColumn("Entry",     format="%.2f"),
        "Stop Loss": st.column_config.NumberColumn("Stop",      format="%.2f"),
        "Target 2":  st.column_config.NumberColumn("Target 2",  format="%.2f"),
        "Risk %":    st.column_config.NumberColumn("Risk %",    format="%.1f%%"),
    }
    # Link columns
    for name in (link_cols_nse + link_cols_us):
        if name in df.columns:
            col_cfg[name] = st.column_config.LinkColumn(name, display_text="Open ↗")

    st.dataframe(
        df, use_container_width=True,
        column_config=col_cfg,
        hide_index=True,
        height=min(500, 50 + len(df) * 38),
    )


# ─────────────────────────────────────────────
# Empty / no-results state
# ─────────────────────────────────────────────

def no_results_state(scenario_id: str):
    s = SCENARIOS[scenario_id]
    st.markdown(f"""
    <div style='background:#122f25; border:1px dashed #1a3b31;
                border-radius:12px; padding:50px 40px; text-align:center;'>
        <div style='font-size:2.5rem; margin-bottom:14px;'>{s["emoji"]}</div>
        <div style='font-family:"IBM Plex Mono",monospace; color:#7abeac; font-size:1rem;'>
            No stocks currently match the <b style='color:{s["color"]};'>{s["title"]}</b> criteria.
        </div>
        <div style='color:#6a9d8a; font-size:0.8rem; margin-top:8px;'>
            Markets may not have triggered this pattern today — check again at market open or close.
        </div>
    </div>
    """, unsafe_allow_html=True)
