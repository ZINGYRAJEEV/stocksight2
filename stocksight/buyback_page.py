"""Buyback Screener — Streamlit UI."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from buyback import (
    META,
    SMALL_HOLDER_VALUE_LIMIT_INR,
    WORTH_PLAYING_RETURN_PCT,
    BuybackInputs,
    analyze_buyback,
    analysis_to_row,
    break_even_post_price,
    expected_return_pct,
    max_shares_small_category,
    sensitivity_table,
)
from buyback_announcements import (
    SCREENER_BUYBACK_URL,
    announcements_to_rows,
    fetch_buyback_announcements,
    get_screener_feed_status,
)
from buyback_store import load_analyses, load_opportunities, save_opportunities
from screener import get_stock_links
from ui_components import inject_css, page_audience_note, safe_set_page_config


def _return_style(series: pd.Series) -> list[str]:
    styles: list[str] = []
    for v in series:
        try:
            x = float(v)
        except (TypeError, ValueError):
            styles.append("")
            continue
        if x >= WORTH_PLAYING_RETURN_PCT:
            styles.append("background-color: #dcfce7; color: #166534; font-weight: 700;")
        elif x >= 4:
            styles.append("background-color: #ecfdf5; color: #047857;")
        elif x < 0:
            styles.append("background-color: #fee2e2; color: #991b1b;")
        else:
            styles.append("")
    return styles


SCREENER_IN_BUYBACK_URL = SCREENER_BUYBACK_URL


def _render_how_to_use() -> None:
    with st.expander("📖 How to use this Buyback Screener (step-by-step)", expanded=True):
        st.markdown(
            f"""
### Step 1 — Find a live buyback announcement
Open **[Screener.in buyback announcements]({SCREENER_IN_BUYBACK_URL})** and scan recent disclosures.
You can also check BSE/NSE corporate announcements for the same company.

Pick a **tender offer** buyback (not open-market only) — this screener is built for tender offers.

---

### Step 2 — Collect inputs from the offer document
From the announcement / offer document, note:

| Field | Where to find it |
|-------|------------------|
| **Buyback %** | “X% of total equity” in the offer |
| **Buyback price** | Fixed tender price (₹ per share) |
| **Record date** | Cut-off date — you must hold shares before this |
| **Announcement price** | CMP around the **first** buyback announcement (use chart history) |
| **Type** | Should say **Tender** |

---

### Step 3 — Estimate small shareholder holding %
1. Open the company **annual report** on Screener or the investor relations site.
2. Search for **“Shareholding distribution”** or **“Distribution of shareholding”**.
3. Find holders in the **1–500 shares** (or similar) bucket and their **% of equity**.
4. Conservative rule: eligible small holders (≤ ₹2 lakh) often hold **less** than that bucket —
   use a **lower** estimate (e.g. if 1–500 bucket = 1.97%, try **~1%** for Bajaj Auto–style cases).

The calculator shows **max shares** for the ₹2 lakh small-shareholder limit at your price.

---

### Step 4 — Set participation %
- Default: **50%** (about half of eligible holders tend to apply).
- Conservative: **70%** (more competition → lower acceptance → lower return).

---

### Step 5 — Run the **Calculator** tab
Enter all yellow-style inputs. Green-style outputs appear automatically:

- **Small acceptance %** — estimated share of *your* shares the company will buy
- **Small expected return %** — your main decision metric
- **General acceptance / return** — if you apply without small quota (usually much lower)
- **Break-even post price** — CMP where you stop making money on unsold shares
- **Sensitivity table** — profit at different post-buyback prices

---

### Step 6 — Decide: worth playing?
If **Small expected return % ≥ {WORTH_PLAYING_RETURN_PCT:.0f}%** → the offer is worth evaluating under the
**small shareholder quota** (apply via your broker before the tender window closes).

Use the sensitivity table to see upside if the stock rises, and downside cushion if CMP falls after the offer.

---

### Step 7 — Save & track
- Click **Save to opportunity list** in the Calculator tab, or use **Manage list → Add**.
- Active offers show on the **Screener** tab with ✅ when return ≥ {WORTH_PLAYING_RETURN_PCT:.0f}%.
- Mark completed offers as **past** for reference (Bajaj Auto is pre-loaded as a worked example).

---

**Quick link:** [Screener.in — buyback announcements]({SCREENER_IN_BUYBACK_URL})
"""
        )
        st.link_button(
            "🔗 Open Screener.in buyback announcements",
            SCREENER_IN_BUYBACK_URL,
            use_container_width=False,
        )


def _render_education() -> None:
    with st.expander("📘 Formulas & spreadsheet logic", expanded=False):
        st.markdown(
            f"""
**Acceptance ratio** = of your 100 shares, how many will the company buy?
- Small category: `(buyback % × 15%) ÷ (small holding % × participation %)`
- General category: uses the remaining **85%** of buyback size
- Capped at **100%** (if >100%, company likely buys all tendered shares)

**Expected return %** =
`(acceptance × buyback price) + ((1 − acceptance) × post-buyback price)` ÷ announcement price − 1

**Risk cushion**: Premium buyback can still profit even if CMP falls — see Calculator sensitivity table.
"""
        )

    with st.expander("🗺️ Mind map — key concepts", expanded=False):
        st.markdown(
            """
| Concept | Role in screener |
|---------|-------------------|
| Small shareholder quota | 15% of buyback reserved → higher acceptance |
| Acceptance ratio | Shares company likely buys from you |
| Participation | % of holders who actually tender (default 50%) |
| Post-buyback price | CMP for shares not accepted |
| Break-even | CMP where return hits 0% |
| >8% small return | **Worth playing** filter |
"""
        )


@st.cache_data(ttl=120, show_spinner=False)
def _cached_buyback_announcements(max_age_days: int, enrich_prices: bool) -> list[dict]:
    anns = fetch_buyback_announcements(
        max_age_days=max_age_days,
        enrich_prices=enrich_prices,
        mark_as_seen=True,
    )
    return announcements_to_rows(anns)


def _load_announcement_into_calculator(row: dict) -> None:
    st.session_state["bb_stock"] = row.get("Company") or "—"
    ticker = row.get("Ticker") or ""
    st.session_state["bb_raw"] = f"{ticker}.NS" if ticker and ticker != "—" else ""
    if row.get("Size %"):
        st.session_state["bb_pct"] = float(row["Size %"])
    if row.get("Offer ₹"):
        st.session_state["bb_offer"] = float(row["Offer ₹"])
    if row.get("CMP ₹"):
        px = float(row["CMP ₹"])
        st.session_state["bb_ann"] = px
        st.session_state["bb_post"] = px
    if row.get("Record date") and row["Record date"] != "—":
        st.session_state["bb_rec"] = str(row["Record date"])
    st.session_state["bb_calc_tab"] = True


def _render_screener_setup_hint() -> None:
    status = get_screener_feed_status()
    if status.get("login_configured"):
        st.success(
            "Screener.in session configured — pulling "
            f"[full-text buyback search]({SCREENER_IN_BUYBACK_URL}) automatically."
        )
        return
    with st.expander("🔐 Enable Screener.in full-text feed (recommended)", expanded=False):
        st.markdown(
            f"""
[Screener.in buyback announcements]({SCREENER_IN_BUYBACK_URL}) is a **premium-quality filing feed**
but requires a **free** Screener login when fetched programmatically.

**One-time setup** (local only, in `.streamlit/secrets.toml`):

```toml
[screener]
sessionid = "paste-from-browser"
csrftoken = "paste-from-browser"
```

1. Log in at [screener.in](https://www.screener.in/login/).
2. Open DevTools → Application → Cookies → `www.screener.in`.
3. Copy `sessionid` and `csrftoken` into the block above.
4. Restart Streamlit.

Without login we still scan **recent Screener filings** across Nifty 500 (rotating batch) plus Google News.
"""
        )


def _render_live_announcements() -> None:
    st.markdown("#### 📢 Live buyback announcements")
    st.caption(
        "Screener.in filings + Google News RSS — refreshed automatically so you see new offers early. "
        "Cross-check PDFs on NSE / BSE before trading."
    )
    _render_screener_setup_hint()

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        st.link_button(
            "🔗 Screener.in buyback filings",
            SCREENER_IN_BUYBACK_URL,
            use_container_width=True,
        )
    with c2:
        new_only = st.checkbox("New only", value=False, key="bb_ann_new_only")
    with c3:
        enrich = st.checkbox("Load CMP", value=True, key="bb_ann_enrich")
    with c4:
        max_days = st.selectbox("Window", [7, 14, 30, 45], index=2, key="bb_ann_days")

    refresh_sec = st.slider("Auto-refresh (seconds)", 60, 600, 180, 60, key="bb_ann_refresh")

    @st.fragment(run_every=timedelta(seconds=int(refresh_sec)))
    def _live_feed() -> None:
        if st.button("🔄 Refresh now", key="bb_ann_manual_refresh"):
            _cached_buyback_announcements.clear()
        with st.spinner("Fetching buyback headlines…"):
            rows = _cached_buyback_announcements(int(max_days), bool(enrich))
        if new_only:
            rows = [r for r in rows if r.get("")]
        new_count = sum(1 for r in rows if r.get(""))
        if new_count:
            st.success(f"**{new_count}** new announcement(s) since your last visit.")
        elif rows:
            st.info(f"**{len(rows)}** headline(s) in the last {max_days} days — none new since last check.")
        else:
            st.warning("No buyback headlines found. Try widening the window or check Screener.in directly.")
            return

        df = pd.DataFrame(rows)
        screener_n = sum(1 for r in rows if str(r.get("Source", "")).startswith("Screener"))
        news_n = len(rows) - screener_n
        st.caption(f"Sources: **{screener_n}** Screener.in · **{news_n}** Google News")

        show_cols = [
            "", "Age", "Company", "Headline", "Source", "Type", "Offer ₹", "Size %",
            "Record date", "CMP ₹", "Premium %", "Est. small ret %", "Worth watch",
            "Announcement", "Screener", "NSE",
        ]
        show_cols = [c for c in show_cols if c in df.columns]
        st.dataframe(
            df[show_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Announcement": st.column_config.LinkColumn(display_text="News ↗"),
                "Screener": st.column_config.LinkColumn(display_text="Screener ↗"),
                "NSE": st.column_config.LinkColumn(display_text="NSE ↗"),
                "Offer ₹": st.column_config.NumberColumn(format="₹%.0f"),
                "CMP ₹": st.column_config.NumberColumn(format="₹%.2f"),
                "Premium %": st.column_config.NumberColumn(format="%+.1f"),
                "Est. small ret %": st.column_config.NumberColumn(format="%+.2f"),
                "Size %": st.column_config.NumberColumn(format="%.2f"),
            },
        )

        st.markdown("**Quick actions**")
        for i, row in enumerate(rows[:12]):
            label = f"{'🆕 ' if row.get('') else ''}{row.get('Company', '—')} — {str(row.get('Headline', ''))[:70]}…"
            with st.expander(label, expanded=bool(row.get("")) and i < 3):
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Offer price", f"₹{row['Offer ₹']:,.0f}" if row.get("Offer ₹") else "—")
                m2.metric("Premium", f"{row['Premium %']:+.1f}%" if row.get("Premium %") is not None else "—")
                m3.metric("Est. small return", f"{row['Est. small ret %']:+.2f}%" if row.get("Est. small ret %") is not None else "—")
                m4.metric("Age", row.get("Age", "—"))
                if row.get("Parse notes"):
                    st.caption(row["Parse notes"])
                b1, b2, b3 = st.columns(3)
                with b1:
                    if st.button("🧮 Load into calculator", key=f"bb_load_calc_{row.get('id', i)}"):
                        _load_announcement_into_calculator(row)
                        st.toast(f"Loaded {row.get('Company')} — open Calculator tab")
                        st.rerun()
                with b2:
                    st.link_button("Open news", row.get("Announcement") or SCREENER_IN_BUYBACK_URL)
                with b3:
                    st.link_button("Screener company", row.get("Screener") or SCREENER_IN_BUYBACK_URL)

    _live_feed()


def _render_screener_table(analyses: list) -> None:
    active = [a for a in analyses if a.status == "active"]
    past = [a for a in analyses if a.status != "active"]

    if active:
        st.markdown("#### 🟢 Active opportunities")
        df = pd.DataFrame([analysis_to_row(a) for a in active])
        show = [c for c in df.columns if c != "Raw"]
        styler = df[show].style.apply(_return_style, subset=["Small return %"])
        st.dataframe(
            styler,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Small return %": st.column_config.NumberColumn(format="%+.2f"),
                "General return %": st.column_config.NumberColumn(format="%+.2f"),
                "Small acceptance %": st.column_config.NumberColumn(format="%.1f"),
                "General acceptance %": st.column_config.NumberColumn(format="%.1f"),
                "Premium %": st.column_config.NumberColumn(format="%+.1f"),
                "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
            },
        )

    st.markdown("#### 📚 Past / reference (incl. Bajaj Auto case study)")
    if past:
        df = pd.DataFrame([analysis_to_row(a) for a in past])
        show = [c for c in df.columns if c not in ("Raw", "Status")]
        styler = df[show].style.apply(_return_style, subset=["Small return %"])
        st.dataframe(styler, use_container_width=True, hide_index=True)
    else:
        st.info("No past entries.")


def _render_calculator() -> None:
    st.markdown("#### 🧮 Buyback calculator")
    st.caption(
        f"Steps 2–6: pull offer data from "
        f"[Screener.in buyback announcements]({SCREENER_IN_BUYBACK_URL}), then fill inputs below."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        stock = st.text_input("Stock", "Bajaj Auto", key="bb_stock")
        raw = st.text_input("Ticker (optional)", "BAJAJ-AUTO.NS", key="bb_raw")
        bb_pct = st.number_input("Buyback % of equity", 0.0, 20.0, 1.41, 0.01, key="bb_pct")
        small_h = st.number_input(
            "Small shareholder holding % (annual report est.)",
            0.1, 50.0, 1.0, 0.1,
            key="bb_small_h",
            help="From shareholding distribution: eligible holders ≤ ₹2L bucket",
        )
    with c2:
        part = st.slider("Shareholder participation %", 10, 100, 50, key="bb_part")
        ann_px = st.number_input("Pre-record / announcement price (₹)", 1.0, 500000.0, 6900.0, key="bb_ann")
        bb_px = st.number_input("Buyback offer price (₹)", 1.0, 500000.0, 10000.0, key="bb_offer")
        post_px = st.number_input(
            "Post-buyback price for unsold shares (₹)",
            1.0, 500000.0, 6900.0,
            key="bb_post",
            help="Often assume same as announcement price if stock is stable",
        )
    with c3:
        rec = st.text_input("Record date (note)", "29-Feb-2024", key="bb_rec")
        max_sh = max_shares_small_category(ann_px)
        st.metric("Max shares (≤ ₹2L quota)", max_sh)
        st.caption(f"At ₹{ann_px:,.0f}: {max_sh} shares × price ≤ ₹{SMALL_HOLDER_VALUE_LIMIT_INR:,}")

    inp = BuybackInputs(
        stock=stock,
        raw_ticker=raw,
        buyback_pct=bb_pct,
        small_holder_holding_pct=small_h,
        participation_pct=float(part),
        announcement_price=ann_px,
        buyback_price=bb_px,
        record_date=rec,
        post_buyback_price=post_px,
    )
    links = get_stock_links(raw) if raw else {}
    a = analyze_buyback(inp, links=links)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Small acceptance %", f"{a.small_acceptance_pct:.1f}%")
    m2.metric("Small expected return", f"{a.small_expected_return_pct:+.2f}%")
    m3.metric("General acceptance %", f"{a.general_acceptance_pct:.1f}%")
    m4.metric("Break-even post price", f"₹{a.small_break_even_post_price:,.0f}")

    if a.worth_playing:
        st.success(f"✅ Small shareholder return ≥ {WORTH_PLAYING_RETURN_PCT:.0f}% — worth evaluating participation.")
    else:
        st.warning(f"Small return below {WORTH_PLAYING_RETURN_PCT:.0f}% at current assumptions.")

    st.markdown("**Sensitivity — post-buyback price vs return (small category)**")
    sens = pd.DataFrame(
        sensitivity_table(ann_px, bb_px, a.small_acceptance_pct)
    )
    st.dataframe(
        sens.style.apply(
            lambda s: [
                "background-color: #dcfce7; font-weight: 600;" if float(v) >= WORTH_PLAYING_RETURN_PCT
                else ("background-color: #fee2e2;" if float(v) < 0 else "")
                for v in s
            ],
            subset=["Expected return %"],
        ),
        use_container_width=True,
        hide_index=True,
    )

    if st.button("💾 Save to opportunity list", key="bb_save"):
        items = load_opportunities()
        items = [x for x in items if x.stock.lower() != stock.lower()]
        items.insert(0, inp)
        save_opportunities(items)
        st.success(f"Saved {stock}.")
        st.rerun()


def _render_add_form() -> None:
    with st.expander("➕ Add / update opportunity manually", expanded=False):
        with st.form("bb_add_form"):
            fc1, fc2 = st.columns(2)
            with fc1:
                stock = st.text_input("Stock name")
                raw = st.text_input("Ticker", placeholder="RELIANCE.NS")
                status = st.selectbox("Status", ["active", "past"])
            with fc2:
                bb_pct = st.number_input("Buyback %", 0.0, 20.0, 1.0)
                small_h = st.number_input("Small holder holding %", 0.1, 20.0, 1.0)
                part = st.number_input("Participation %", 10.0, 100.0, 50.0)
            fp1, fp2, fp3 = st.columns(3)
            with fp1:
                ann = st.number_input("Announcement price", 0.0, value=1000.0)
            with fp2:
                offer = st.number_input("Buyback price", 0.0, value=1100.0)
            with fp3:
                post = st.number_input("Post-buyback price", 0.0, value=1000.0)
            rec = st.text_input("Record date")
            if st.form_submit_button("Add"):
                inp = BuybackInputs(
                    stock=stock,
                    raw_ticker=raw,
                    buyback_pct=bb_pct,
                    small_holder_holding_pct=small_h,
                    participation_pct=part,
                    announcement_price=ann,
                    buyback_price=offer,
                    post_buyback_price=post or ann,
                    record_date=rec,
                    status=status,
                )
                items = load_opportunities()
                items = [x for x in items if x.stock.lower() != stock.lower()]
                items.insert(0, inp)
                save_opportunities(items)
                st.rerun()


def render_buyback_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.html(f"""
    <div style='background:#1c1917; border:1px solid #44403c; border-left:4px solid #f59e0b;
                border-radius:8px; padding:18px 22px; margin-bottom:14px;'>
        <div style='font-size:1.35rem; font-weight:700; color:#fafaf9;'>{META['emoji']} {META['title']}</div>
        <div style='font-size:0.85rem; color:#d6d3d1; margin-top:6px;'>
            Live announcements · Acceptance ratio · Small vs General return · Break-even
        </div>
    </div>
    """)

    page_audience_note(META["audience"], META["purpose"])
    _render_how_to_use()
    _render_education()

    tab_live, tab_screen, tab_calc, tab_manage = st.tabs(
        ["📢 Live announcements", "📋 Screener", "🧮 Calculator", "📁 Manage list"],
    )

    analyses = load_analyses()

    with tab_live:
        _render_live_announcements()

    with tab_screen:
        worth = [a for a in analyses if a.worth_playing and a.status == "active"]
        if worth:
            st.success(
                f"**{len(worth)}** active offer(s) with small-holder return ≥ {WORTH_PLAYING_RETURN_PCT:.0f}%."
            )
        _render_screener_table(analyses)

    with tab_calc:
        _render_calculator()

    with tab_manage:
        _render_add_form()
        if st.button("Reset to sample data (Bajaj Auto, TCS, Wipro)", key="bb_reset"):
            from buyback import SAMPLE_OPPORTUNITIES

            save_opportunities(list(SAMPLE_OPPORTUNITIES))
            st.rerun()
        st.caption("Data stored in `stocksight/.buyback_opportunities.json` (local).")

    st.caption(
        "⚠️ Acceptance ratios are **estimates** — actual tender participation varies. "
        "Verify offer documents on NSE/BSE. Not financial advice."
    )
