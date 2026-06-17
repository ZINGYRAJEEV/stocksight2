"""Valuation Rulebook — interactive forward model for any stock."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from valuation_model import (
    COMMON_MISTAKES,
    META,
    SECTOR_KEYS,
    SECTOR_LABELS,
    SECTOR_RULEBOOK,
    ValuationInputs,
    apply_baseline_to_session,
    assess_wealth_creation,
    build_buying_price_cagr_table,
    build_cagr_sensitivity_table,
    build_key_assumptions,
    build_target_cagr_buying_table,
    default_estimate_year,
    default_revenue_cr_y0,
    load_valuation_baseline,
    project_valuation,
    projection_sheet_df,
    revenue_for_mar_fy,
    shares_reference_df,
    style_cagr_buying_table,
    style_projection_sheet,
    style_target_cagr_table,
)
from ui_components import inject_css, page_audience_note, safe_set_page_config


def _mistake_cards() -> None:
    st.markdown("#### ⚠️ Four common mistakes")
    cols = st.columns(2)
    for i, card in enumerate(COMMON_MISTAKES):
        with cols[i % 2]:
            st.markdown(
                f"""
<div style='background:#1a1208;border:1px solid #78350f;border-left:4px solid #f59e0b;
            border-radius:10px;padding:14px 16px;margin-bottom:12px;'>
  <div style='font-weight:700;color:#fcd34d;margin-bottom:6px;'>{card["title"]}</div>
  <div style='font-size:0.88rem;color:#fde68a;line-height:1.45;'>{card["body"]}</div>
</div>
""",
                unsafe_allow_html=True,
            )


def _parse_growth_path(text: str) -> list[float]:
    out: list[float] = []
    for part in (text or "").split(","):
        part = part.strip().replace("%", "")
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out


def _render_workbook_diff_guide() -> None:
    with st.expander("📋 Why your Google Sheet may differ from this screen", expanded=False):
        st.markdown(
            """
| Topic | Your manual sheet (IndiaMart example) | This tool (default) |
|-------|--------------------------------------|---------------------|
| **History** | Often starts at Mar 2020–2023 | Screener **Sales+** back to Mar 2018 |
| **Projection start** | Mar **2024** sales 1,197 Cr | Yellow col = latest Mar FY (**2026** = 1,569 Cr) |
| **Sales growth** | **10%, 5%, 15%** per year | Flat **~14%** (3Y CAGR) |
| **OPM** | **33% → 30%** ramp | Flat **~31%** (trailing) |
| **P/E** | **31 → 28 → 25 → 35** (your view) | Auto **de-rate** 26 → 17 |
| **P&L** | Other income, interest, depreciation, tax% | Simplified: Sales × OPM → PAT |
| **Rule 9 table** | **CAGR % → max buying price** | Now shows **both** layouts |

**To mirror your IndiaMart workbook:** set **Estimate year = 2024**, **Row 1 = 1,197**, enable **year-by-year growth** `10, 5, 15`,
**OPM start 24 / terminal 30**, **P/E start 31 / terminal 35**, **shares 6**, **3 projection years**.
Historical **Mar 2023 = 985 Cr** matches Screener — same as your sheet.
"""
        )


def _render_wealth_verdict(assessment, base) -> None:
    st.markdown("#### 💰 Wealth creation read (educational)")
    st.caption(
        "The model always outputs a **target price** (PAT × P/E) — that is **not** a buy call on every stock. "
        "Read **valuation stance** first. Not SEBI-registered advice."
    )
    st.markdown(
        f"""
<div style='border:2px solid {assessment.valuation_stance_color};border-radius:12px;padding:14px 18px;
            background:#111827;margin-bottom:12px;'>
  <div style='font-size:1.1rem;font-weight:700;color:{assessment.valuation_stance_color};'>
    Valuation stance: {assessment.valuation_stance}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(assessment.valuation_detail)
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        st.markdown(
            f"""
<div style='border:2px solid {assessment.verdict_color};border-radius:12px;padding:16px 20px;
            background:#0f172a;margin-bottom:8px;'>
  <div style='font-size:1.35rem;font-weight:700;color:{assessment.verdict_color};'>
    {assessment.verdict_emoji} {assessment.verdict}
  </div>
  <div style='color:#94a3b8;font-size:0.9rem;margin-top:6px;'>
    Wealth score <b style='color:#e2e8f0;'>{assessment.wealth_score}/100</b> ·
    Implied CAGR <b style='color:#e2e8f0;'>{assessment.implied_cagr_pct:.1f}%</b> ({assessment.holding_years}Y) ·
    Upside <b style='color:#e2e8f0;'>{assessment.upside_pct:+.1f}%</b>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
    with c2:
        st.metric("Margin of safety", f"{assessment.margin_of_safety_pct:+.1f}%")
    with c3:
        st.metric("Model target", f"₹{assessment.model_target:,.0f}")

    if assessment.strengths:
        st.markdown("**Strengths**")
        for s in assessment.strengths:
            st.markdown(f"- {s}")
    if assessment.risks:
        st.markdown("**Risks / red flags**")
        for r in assessment.risks:
            st.markdown(f"- {r}")
    if assessment.suggestions:
        st.markdown("**Suggested actions**")
        for s in assessment.suggestions:
            st.markdown(f"- {s}")

    links = base.links or {}
    if links.get("screener"):
        st.markdown(f"Verify on [Screener.in]({links['screener']}) before investing.")


def _sector_tab_content(sector_key: str) -> None:
    book = SECTOR_RULEBOOK[sector_key]
    st.markdown(f"**Row 1:** {book['row1_label']}")
    st.markdown(f"**Volume driver:** {book['volume_driver']}")
    st.markdown(f"**OPM benchmark:** {book['opm_benchmark']}")
    st.markdown(f"**Multiple:** {book['pe_benchmark']}")
    st.caption(f"Growth hint: {book['growth_hint']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Default OPM %", f"{book['opm_default_pct']:.1f}")
    mult_label = "Default P/B" if book.get("pe_is_pb") else "Default P/E"
    c2.metric(mult_label, f"{book['pe_default']:.1f}")
    c3.metric("Sector", SECTOR_LABELS[sector_key])


def render_valuation_rulebook_page() -> None:
    safe_set_page_config(
        page_title="Valuation Rulebook | StockSight",
        page_icon="🧮",
        layout="wide",
    )
    inject_css()
    page_audience_note(META["audience"], META["purpose"])

    st.markdown(
        f"""
<div style='background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);
            border:1px solid #334155;border-left:5px solid #38bdf8;
            border-radius:12px;padding:20px 24px;margin-bottom:16px;'>
  <h2 style='margin:0;color:#e2e8f0;'>{META["emoji"]} {META["title"]}</h2>
  <p style='margin:8px 0 0;color:#94a3b8;font-size:0.95rem;'>
    Generic Rule 1–6 chain (Jupiter / NAM India structure). Only Row 1 (Revenue) changes per stock —
    sector tabs (Rule 8) give the volume driver, margin benchmark, and multiple.
  </p>
</div>
""",
        unsafe_allow_html=True,
    )

    qp = st.query_params
    prefill = (st.session_state.pop("val_prefill_ticker", None) or "").strip().upper()
    qp_sym = (qp.get("ticker") or qp.get("sym") or "").strip().upper()
    default_sym = qp_sym or prefill

    c_sym, c_load = st.columns([3, 1])
    with c_sym:
        sym_in = st.text_input(
            "Stock ticker (NSE)",
            value=default_sym or st.session_state.get("val_sym_input", ""),
            placeholder="e.g. RELIANCE or TCS.NS",
            key="val_sym",
        )
    with c_load:
        st.write("")
        load_btn = st.button("Load stock", type="primary", use_container_width=True)

    if "val_baseline" not in st.session_state:
        st.session_state.val_baseline = None

    sym_to_load = (sym_in or default_sym or "").strip()
    auto_from_screen = bool(prefill) or bool(qp_sym)
    if sym_to_load and (load_btn or (auto_from_screen and st.session_state.val_baseline is None)):
        with st.spinner(f"Loading {sym_to_load}…"):
            loaded = load_valuation_baseline(sym_to_load)
            st.session_state.val_baseline = loaded
            book0 = SECTOR_RULEBOOK.get(loaded.sector_key, SECTOR_RULEBOOK["generic"])
            apply_baseline_to_session(loaded, book=book0)

    base = st.session_state.val_baseline
    if base is None:
        st.info("Enter a ticker and click **Load stock** to start the workbook.")
        st.caption("Try the exact NSE symbol — e.g. **NAM-INDIA** (with hyphen), not NAMINDIA.")
        st.markdown("#### Rule 8 — Sector benchmarks (preview)")
        tabs = st.tabs([SECTOR_LABELS[k] for k in SECTOR_KEYS])
        for tab, sk in zip(tabs, SECTOR_KEYS):
            with tab:
                _sector_tab_content(sk)
        _mistake_cards()
        return

    links = base.links or {}
    link_bits = []
    if links.get("screener"):
        link_bits.append(f"[Screener.in]({links['screener']})")
    if links.get("chartink"):
        link_bits.append(f"[Chartink]({links['chartink']})")
    if links.get("tradingview"):
        link_bits.append(f"[TradingView]({links['tradingview']})")
    st.markdown(
        f"**{base.company_name}** (`{base.display_ticker}`) · {base.sector} · "
        + " · ".join(link_bits)
    )
    for note in base.notes:
        st.caption(f"ℹ️ {note}")

    if not base.data_ok:
        st.error(
            "Yahoo did not return valid data for this ticker. "
            "Fix the symbol and click **Load stock** again — "
            "for Nippon AMC use **NAM-INDIA**."
        )
        if links.get("screener"):
            st.markdown(f"Check fundamentals on [Screener.in]({links['screener']})")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("LTP ₹", f"{base.price:,.2f}")
    m2.metric("Revenue (Cr)", f"{base.revenue_cr:,.0f}" if base.revenue_cr else "—")
    m3.metric("OPM %", f"{base.opm_pct:.1f}" if base.opm_pct is not None else "—")
    m4.metric("Shares (Cr)", f"{base.shares_cr:.2f}" if base.shares_cr else "—")

    st.markdown("---")
    st.markdown("#### Rule 8 — Sector tab")
    sector_tabs = st.tabs([SECTOR_LABELS[k] for k in SECTOR_KEYS])
    active_sector = st.session_state.get("val_sector_key", base.sector_key)
    for tab, sk in zip(sector_tabs, SECTOR_KEYS):
        with tab:
            _sector_tab_content(sk)
            if sk == base.sector_key:
                st.caption("✓ Auto-matched from Yahoo sector/industry")

    picked = st.selectbox(
        "Model sector (drives defaults)",
        options=list(SECTOR_KEYS),
        index=list(SECTOR_KEYS).index(base.sector_key),
        format_func=lambda k: SECTOR_LABELS[k],
        key="val_sector_key",
    )
    book = SECTOR_RULEBOOK[picked]

    st.markdown("#### Customise per stock")
    _render_workbook_diff_guide()
    st.caption(
        "Revenue growth: Screener.in 5yr CAGR + guidance · OPM: P&L + Rule 8 · "
        "Capex/debt: quarterly presentation · P/E: peers then de-rate · Shares: check dilution"
    )

    rev_default, rev_source = default_revenue_cr_y0(base)
    if st.session_state.get("val_loaded_ticker") != base.display_ticker:
        apply_baseline_to_session(base, book=SECTOR_RULEBOOK[base.sector_key])

    ic1, ic2, ic3, ic3b = st.columns(4)
    rev0 = ic1.number_input(
        "Rule 1 — Revenue ₹ Cr (Row 1)",
        min_value=0.0,
        step=50.0,
        key="val_rev0",
        help="Current-year estimate (yellow column). Prefilled from Yahoo; override from Screener.in.",
    )
    st.caption(f"Row 1 source: **{rev_source}**")
    rev_g = ic2.number_input(
        "Revenue growth % (Rule 3)",
        min_value=-20.0,
        max_value=80.0,
        value=float(base.revenue_growth_5y_pct or 12.0),
        step=0.5,
        key="val_rev_g",
    )
    years = ic3.number_input(
        "Projection years (orange cols)",
        min_value=1,
        max_value=10,
        value=3,
        step=1,
        key="val_years",
        help="Forward years after estimate — NAM sheet uses 2026–2028",
    )
    est_year = ic3b.number_input(
        "Estimate year (yellow col)",
        min_value=2020,
        max_value=2035,
        step=1,
        key="val_est_year",
        help="Mar FY for Row 1. Use 2024 to match an older workbook; 2026 = latest Screener year.",
    )
    screener_rev = revenue_for_mar_fy(base, int(est_year))
    if screener_rev is not None:
        c_pull, _ = st.columns([1, 3])
        with c_pull:
            if st.button(f"Use Screener Mar {est_year} sales ({screener_rev:,.0f} Cr)", key="val_pull_rev"):
                st.session_state.val_rev0 = float(screener_rev)
                st.rerun()

    use_growth_path = st.checkbox(
        "Year-by-year sales growth % (IndiaMart / Jupiter style)",
        key="val_use_growth_path",
    )
    growth_path: list[float] = []
    if use_growth_path:
        gp_text = st.text_input(
            "Growth each orange step (comma-separated %)",
            placeholder="e.g. 10, 5, 15 for three projection years after estimate",
            key="val_growth_path_text",
        )
        growth_path = _parse_growth_path(gp_text)
        if growth_path:
            st.caption(f"Applied path: **{' → '.join(f'{g:.1f}%' for g in growth_path)}**")

    ic4, ic5, ic6 = st.columns(3)
    opm = ic4.number_input(
        "OPM % — start (Rule 4)",
        min_value=0.0,
        max_value=80.0,
        step=0.5,
        key="val_opm",
    )
    terminal_opm = ic5.number_input(
        "OPM % — terminal (outer year)",
        min_value=0.0,
        max_value=80.0,
        step=0.5,
        key="val_terminal_opm",
        help="Margin expansion path — like NAM sheet 63% → 67%",
    )
    tax = ic6.number_input("Tax rate %", min_value=0.0, max_value=40.0, value=25.0, step=1.0)

    ic6b = st.columns(1)[0]
    int_drag = ic6b.number_input(
        "Interest drag % of OP",
        min_value=0.0,
        max_value=15.0,
        value=float(base.interest_drag_pct),
        step=0.5,
        help="Approximate interest cost as % drag on operating profit",
    )

    ic7, ic8, ic9 = st.columns(3)
    shares = ic7.number_input(
        "Num of shares (Cr)",
        min_value=0.01,
        step=0.01,
        key="val_shares",
        help="Yahoo share count in Cr. Your NAM sheet may show ~6.39 — adjust if matching that workbook.",
    )
    pe_is_pb = book.get("pe_is_pb", False)
    mult_label = "Fair P/B (Rule 6)" if pe_is_pb else "Fair P/E (Rule 6)"
    fair_mult = ic8.number_input(
        mult_label + " — start",
        min_value=0.5,
        max_value=120.0,
        step=0.5,
        key="val_pe_start",
        help="Starting multiple for estimate year — de-rate for outer years",
    )
    terminal_pe = ic9.number_input(
        mult_label + " — terminal",
        min_value=0.5,
        max_value=120.0,
        step=0.5,
        key="val_pe_terminal",
        help="Outer-year multiple — e.g. 45 → 30 on NAM sheet",
    )

    ic10a, ic10b, ic10c = st.columns(3)
    entry_px = ic10a.number_input(
        "Buying price ₹ (Rule 9 anchor)",
        min_value=0.01,
        step=0.05,
        key="val_entry_px",
        help="Top row of CAGR table — usually current LTP",
    )
    cagr_years = ic10b.number_input(
        "CAGR holding period (years)",
        min_value=1,
        max_value=15,
        value=int(years),
        step=1,
        help="Years in (Target ÷ Entry)^(1/N) − 1",
    )
    buy_discount = ic10c.number_input(
        "Buying-price range (% below LTP)",
        min_value=5.0,
        max_value=50.0,
        value=27.0,
        step=1.0,
        help="How far below anchor to show cheaper entries (green = higher CAGR)",
    )

    ic10, ic11 = st.columns(2)
    capex_pct = ic10.number_input(
        "Capex % of revenue (checklist)",
        min_value=0.0,
        max_value=40.0,
        value=8.0,
        step=0.5,
        help="From investor presentation — flags over-investment risk",
    )
    new_debt = ic11.number_input(
        "Incremental net debt ₹ Cr (checklist)",
        min_value=0.0,
        value=0.0,
        step=10.0,
        help="Rising debt funding growth — cross-check on concall",
    )

    bv = float(base.book_value_per_share or 0.0)
    inputs = ValuationInputs(
        revenue_cr_y0=rev0,
        revenue_growth_pct=rev_g,
        projection_years=int(years),
        opm_pct=opm,
        tax_rate_pct=tax,
        interest_drag_pct=int_drag,
        shares_cr=shares,
        fair_pe=fair_mult,
        pe_is_pb=pe_is_pb,
        book_value_per_share=bv,
        capex_pct_revenue=capex_pct,
        new_debt_cr=new_debt,
        terminal_pe=terminal_pe,
        terminal_opm_pct=terminal_opm,
        cagr_holding_years=int(cagr_years),
        base_calendar_year=int(est_year),
        revenue_growth_path=growth_path if growth_path else None,
    )
    proj = project_valuation(
        base,
        inputs,
        current_price=entry_px,
        historical=base.historical_revenue,
    )

    st.markdown("---")
    st.markdown("#### Rules 1–6 — Core chain")
    import pandas as pd

    chain_df = pd.DataFrame(proj.chain_rows)
    st.dataframe(chain_df, use_container_width=True, hide_index=True)

    wealth = assess_wealth_creation(base, inputs, proj, entry_price=entry_px)
    _render_wealth_verdict(wealth, base)

    r1, r2, r3, r4 = st.columns(4)
    terminal_year = proj.year_columns[-1].label if proj.year_columns else "—"
    r1.metric(f"Model target ({terminal_year})", f"₹{proj.fair_value_terminal:,.2f}")
    r2.metric("vs buying price", f"{proj.upside_pct:+.1f}%", help="Negative = trading above model")
    r3.metric(f"Implied CAGR ({cagr_years}Y)", f"{proj.implied_cagr_pct:.1f}%")
    if wealth.max_buy_15pct:
        r4.metric("Max buy (15% CAGR)", f"₹{wealth.max_buy_15pct:,.0f}")
    else:
        r4.metric("Shares (Cr)", f"{shares:.2f}")

    if proj.upside_pct < -5:
        st.error(
            f"**Not cheap:** LTP ₹{entry_px:,.0f} is **{abs(proj.upside_pct):.0f}% above** the model target — "
            "this stock is **not** flagged as a wealth entry at today's price."
        )
    elif abs(proj.upside_pct) <= 8:
        st.warning(
            "**Priced in:** model target ≈ current price. The formula will always print a number — "
            "here it does **not** mean undervalued; it means your assumptions are already in the share price."
        )

    st.caption(
        "🟨 **Yellow** = current-year estimate · 🟧 **Orange** = forward projections · "
        "Grey = historical (**Screener.in Sales+** when available, else Yahoo)"
    )
    if base.historical_revenue_source:
        st.caption(f"Historical columns: **{base.historical_revenue_source}**")

    grid_left, grid_right = st.columns([3, 1])
    sheet_df = projection_sheet_df(proj)

    with grid_left:
        st.markdown("#### Year-by-year projection (NAM / Jupiter layout)")
        st.dataframe(
            style_projection_sheet(sheet_df, proj),
            use_container_width=True,
            hide_index=True,
            height=min(420, 56 + len(sheet_df) * 36),
        )

    with grid_right:
        st.markdown("#### Rule 9 — CAGR sensitivity")
        st.caption(
            f"Target **₹{proj.fair_value_terminal:,.0f}** in **{cagr_years}Y** · "
            f"formula: (Target ÷ Buying price)^(1/{cagr_years}) − 1"
        )

        st.markdown("##### Workbook style — CAGR % → max buying price")
        target_cagr_df = build_target_cagr_buying_table(
            proj.fair_value_terminal,
            int(cagr_years),
        )
        if not target_cagr_df.empty:
            st.dataframe(
                style_target_cagr_table(target_cagr_df),
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("##### Entry price → expected CAGR")
        buy_df = build_buying_price_cagr_table(
            proj.fair_value_terminal,
            int(cagr_years),
            anchor_price=entry_px,
            discount_pct=buy_discount,
        )
        cagr_col = f"Exp. CAGR ({int(cagr_years)}Y) %"
        if not buy_df.empty:
            st.dataframe(
                style_cagr_buying_table(buy_df, cagr_col),
                use_container_width=True,
                hide_index=True,
                height=min(380, 56 + len(buy_df) * 36),
            )
        st.markdown("##### Num of shares")
        st.dataframe(
            shares_reference_df(proj),
            use_container_width=True,
            hide_index=True,
            height=min(320, 56 + len(proj.year_columns) * 32),
        )

    with st.expander("Rule 9 — Advanced (multiple targets × horizons)", expanded=False):
        targets = sorted(
            {
                round(entry_px * 0.8, 2),
                round(entry_px, 2),
                round(proj.fair_value_terminal * 0.85, 2),
                round(proj.fair_value_terminal, 2),
                round(proj.fair_value_terminal * 1.15, 2),
            }
        )
        horizons = [2, 3, 5, 7, 10]
        cagr_df = build_cagr_sensitivity_table(entry_px, targets, horizons)
        st.dataframe(
            cagr_df.style.background_gradient(
                subset=[c for c in cagr_df.columns if "CAGR" in c],
                cmap="RdYlGn",
                vmin=-5,
                vmax=25,
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("#### Key assumptions & sources")
    assumptions_df = build_key_assumptions(base, inputs, proj)
    st.dataframe(assumptions_df, use_container_width=True, hide_index=True)

    if capex_pct > 15 or new_debt > rev0 * 0.1:
        st.warning(
            f"High capex ({capex_pct:.1f}% of revenue) or incremental debt (₹{new_debt:,.0f} Cr) — "
            "verify ROCE and funding mix in the latest presentation."
        )

    _mistake_cards()


if __name__ == "__main__":
    render_valuation_rulebook_page()
