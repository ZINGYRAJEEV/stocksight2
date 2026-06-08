"""Central Brain — Streamlit dashboard for audit, rules, and live checklist."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from central_brain.audit import read_audit_tail
from central_brain.config import load_config
from central_brain.processor import process_tradingview_signal
from central_brain.rules_loader import load_rules
from central_brain_store import load_state, set_kill_switch, trades_today
from ui_components import inject_css, page_audience_note, safe_set_page_config

META = {
    "title": "Central Brain",
    "emoji": "🧠",
    "nav_title": "Central Brain",
}


def _render_checklist(cfg) -> None:
    st.markdown("#### Live verification checklist")
    items = [
        ("Signal link", "TradingView webhook → Railway `/webhook/tradingview`"),
        ("AI status", "Claude ON" if cfg.anthropic_api_key else "Rule engine only (no ANTHROPIC_API_KEY)"),
        ("API security", "Exchange key: Read/Write only · Withdrawal DISABLED"),
        ("Cloud persistence", "Mirror `.env` vars on Railway · health cron on `/health`"),
        ("Execution mode", cfg.effective_mode()),
        ("Live confirm", "YES" if cfg.live_confirm else "NO — paper fallback"),
        ("Webhook secret", "Set" if cfg.tradingview_secret else "⚠️ Not set"),
        ("BitGet keys", "Configured" if cfg.bitget.configured() else "Missing"),
    ]
    for label, val in items:
        st.checkbox(f"{label}: **{val}**", value=False, key=f"cb_chk_{label}")


def _render_audit() -> None:
    rows = read_audit_tail(limit=100)
    if not rows:
        st.info("No audit entries yet. Send a TradingView webhook or use **Test signal**.")
        return
    df = pd.DataFrame(
        [
            {
                "Time": r.get("ts", "")[:19],
                "Asset": r.get("asset", ""),
                "Action": r.get("action", ""),
                "Status": r.get("status", ""),
                "Mode": r.get("execution_mode", ""),
                "Reasoning": (r.get("reasoning") or "")[:120],
                "Exchange": r.get("exchange_source", ""),
            }
            for r in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_rules_editor() -> None:
    cfg = load_config()
    path = cfg.rules_path
    st.caption(f"Single source of truth: `{path}`")
    try:
        rules = load_rules(path)
        st.json(rules)
    except Exception as exc:
        st.error(str(exc))


def _render_test_panel() -> None:
    st.markdown("#### Test signal (paper mode)")
    c1, c2 = st.columns(2)
    with c1:
        action = st.selectbox("Action", ["buy", "sell"], key="cb_test_action")
        symbol = st.text_input("Symbol", "XRPUSDT", key="cb_test_sym")
        price = st.number_input("Price", 0.5, key="cb_test_px")
    with c2:
        vwap = st.number_input("VWAP", 0.49, key="cb_test_vwap")
        ema = st.number_input("EMA8", 0.48, key="cb_test_ema")
        rsi = st.number_input("RSI", 28.0, key="cb_test_rsi")

    if st.button("Run validation pipeline", type="primary", key="cb_test_run"):
        payload = {
            "action": action,
            "symbol": symbol,
            "price": price,
            "vwap": vwap,
            "ema8": ema,
            "rsi": rsi,
            "exchange": "bitget",
        }
        with st.spinner("Processing…"):
            result = process_tradingview_signal(payload)
        st.json(result)

    st.markdown("**Example blocked case** (RSI too high for buy):")
    if st.button("Simulate RSI block (38.26)", key="cb_test_block"):
        result = process_tradingview_signal(
            {
                "action": "buy",
                "symbol": "XRPUSDT",
                "price": 0.52,
                "vwap": 0.50,
                "ema8": 0.49,
                "rsi": 38.26,
            }
        )
        st.json(result)


def render_central_brain_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    cfg = load_config()
    state = load_state()

    st.html(f"""
    <div style='background:#1a1f2e; border:1px solid #2d3548; border-left:4px solid #7c3aed;
                border-radius:8px; padding:18px 22px; margin-bottom:14px;'>
        <div style='font-size:1.35rem; font-weight:700; color:#e8eaf0;'>{META['emoji']} {META['title']}</div>
        <div style='font-size:0.85rem; color:#a8b0c4; margin-top:6px;'>
            TradingView → schema + risk + Claude → BitGet / paper · rules.json SSOT
        </div>
    </div>
    """)

    page_audience_note(
        "Algo traders deploying a cloud webhook intermediary between TradingView and an exchange.",
        "Default: **paper trading**. Live requires CENTRAL_BRAIN_MODE=live + CENTRAL_BRAIN_LIVE_CONFIRM=YES. "
        "Run the webhook API on Railway (`scripts/run_central_brain.py`). Not SEBI algo-ID compliant for NSE live.",
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Mode", cfg.effective_mode())
    m2.metric("Trades today", trades_today(state))
    m3.metric("Max / day", cfg.max_trades_per_day)
    m4.metric("Portfolio cap", f"${cfg.portfolio_value:,.0f}")

    kill = st.toggle(
        "Kill switch (block all execution)",
        value=bool(state.get("kill_switch") or cfg.kill_switch),
        key="cb_kill",
    )
    if kill != bool(state.get("kill_switch")):
        set_kill_switch(kill)
        st.rerun()

    tab_audit, tab_rules, tab_test, tab_check, tab_arch = st.tabs(
        ["📋 Audit log", "📜 rules.json", "🧪 Test signal", "✅ Live checklist", "🏗️ Architecture"],
    )

    with tab_audit:
        _render_audit()

    with tab_rules:
        _render_rules_editor()

    with tab_test:
        _render_test_panel()

    with tab_check:
        _render_checklist(cfg)
        st.markdown("---")
        st.code(
            "TRADINGVIEW_WEBHOOK_SECRET=...\n"
            "CENTRAL_BRAIN_MODE=paper\n"
            "CENTRAL_BRAIN_LIVE_CONFIRM=YES\n"
            "PORTFOLIO_VALUE=10000\n"
            "MAX_TRADE_SIZE=500\n"
            "MAX_TRADES_PER_DAY=10\n"
            "BITGET_API_KEY=...\n"
            "BITGET_SECRET_KEY=...\n"
            "BITGET_PASSPHRASE=...\n"
            "ANTHROPIC_API_KEY=...",
            language="bash",
        )

    with tab_arch:
        st.markdown("""
**Tripartite architecture**

| Layer | Role |
|-------|------|
| **Signal** (TradingView) | Alerts with action, symbol, price, RSI, VWAP, EMA8 |
| **Logic** (Central Brain) | rules.json validation + optional Claude + risk circuit breakers |
| **Execution** (BitGet / paper) | Orders only after all gates pass |

**TradingView alert JSON example:**
```json
{
  "secret": "YOUR_WEBHOOK_SECRET",
  "action": "buy",
  "symbol": "XRPUSDT",
  "price": {{close}},
  "vwap": {{plot("VWAP")}},
  "ema8": {{plot("EMA8")}},
  "rsi": {{plot("RSI")}}
}
```

**Railway:** deploy `scripts/run_central_brain.py`, mirror `.env`, point TradingView to `https://<app>.up.railway.app/webhook/tradingview`.
        """)

    st.caption(
        "Educational infrastructure — verify exchange permissions, complete paper trading period "
        "before live. Withdrawal must stay disabled on API keys."
    )
