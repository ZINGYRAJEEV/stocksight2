"""Valuation Rulebook — interactive forward model for any stock."""

from __future__ import annotations

import pandas as pd
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
    load_valuation_baseline,
    project_valuation,
    projection_sheet_df,
    revenue_for_mar_fy,
    shares_reference_df,
)
from ui_components import inject_css, page_audience_note, safe_set_page_config


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


def _render_verdict_banner(assessment, entry_px: float, terminal_year: str) -> None:
    st.markdown(
        f"""
<div style='border:2px solid {assessment.valuation_stance_color};border-radius:14px;
            padding:18px 22px;background:#0f172a;margin:8px 0 16px;'>
  <div style='font-size:0.8rem;letter-spacing:0.06em;color:#94a3b8;text-transform:uppercase;'>
    Your read (educational — not advice)
  </div>
  <div style='font-size:1.45rem;font-weight:700;color:{assessment.valuation_stance_color};margin-top:4px;'>
    {assessment.valuation_stance}
  </div>
  <div style='font-size:1.05rem;color:#e2e8f0;margin-top:8px;'>
    {assessment.verdict_emoji} {assessment.verdict}
    · Target <b>₹{assessment.model_target:,.0f}</b> ({terminal_year})
    · vs LTP ₹{entry_px:,.0f}
    · Implied CAGR <b>{assessment.implied_cagr_pct:.1f}%</b>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    if assessment.valuation_detail:
        st.caption(assessment.valuation_detail)


def _render_help_drawer() -> None:
    with st.expander("How this works · sector tips · common mistakes", expanded=False):
        st.markdown(
            """
**In one line:** project sales → profit → apply a P/E (or P/B) → get a **target price**,
then compare to today’s price and see what CAGR that implies.
"""
        )
        st.markdown("**Sector defaults**")
        for sk in SECTOR_KEYS:
            book = SECTOR_RULEBOOK[sk]
            st.markdown(
                f"- **{SECTOR_LABELS[sk]}** — OPM ~{book['opm_default_pct']:.0f}% · "
                f"{'P/B' if book.get('pe_is_pb') else 'P/E'} ~{book['pe_default']:.0f} · "
                f"{book['volume_driver']}"
            )
        st.markdown("**Common mistakes**")
        for card in COMMON_MISTAKES:
            st.markdown(f"- **{card['title']}** — {card['body']}")


def render_valuation_rulebook_page() -> None:
    safe_set_page_config(
        page_title="Valuation Rulebook | StockSight",
        page_icon="🧮",
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} Valuation Rulebook")
    st.caption(
        "Load a stock → see a clear **cheap / fair / expensive** read → tweak assumptions if needed."
    )
    page_audience_note(META["audience"], META["purpose"])
    _render_help_drawer()

    qp = st.query_params
    prefill = (st.session_state.pop("val_prefill_ticker", None) or "").strip().upper()
    qp_sym = (qp.get("ticker") or qp.get("sym") or "").strip().upper()
    default_sym = qp_sym or prefill

    c_sym, c_load = st.columns([3, 1])
    with c_sym:
        sym_in = st.text_input(
            "Stock ticker (NSE)",
            value=default_sym or st.session_state.get("val_sym_input", ""),
            placeholder="e.g. RELIANCE, TCS, or NAM-INDIA",
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
        st.info("Enter a ticker and click **Load stock** to see the valuation report.")
        return

    links = base.links or {}
    link_bits = []
    if links.get("screener"):
        link_bits.append(f"[Screener]({links['screener']})")
    if links.get("tradingview"):
        link_bits.append(f"[TradingView]({links['tradingview']})")
    st.markdown(
        f"**{base.company_name}** · `{base.display_ticker}` · {base.sector}"
        + (f" · {' · '.join(link_bits)}" if link_bits else "")
    )
    for note in (base.notes or [])[:2]:
        st.caption(note)

    if not base.data_ok:
        st.error(
            "Could not load market data for this ticker. "
            "Try the exact NSE symbol (e.g. **NAM-INDIA**) and Load again."
        )
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Price ₹", f"{base.price:,.2f}" if base.price else "—")
    m2.metric("Revenue ₹ Cr", f"{base.revenue_cr:,.0f}" if base.revenue_cr else "—")
    m3.metric("OPM %", f"{base.opm_pct:.1f}" if base.opm_pct is not None else "—")
    m4.metric("Shares Cr", f"{base.shares_cr:.2f}" if base.shares_cr else "—")

    with st.expander("✏️ Assumptions (edit to recalculate)", expanded=True):
        picked = st.selectbox(
            "Sector playbook",
            options=list(SECTOR_KEYS),
            index=list(SECTOR_KEYS).index(base.sector_key)
            if base.sector_key in SECTOR_KEYS
            else 0,
            format_func=lambda k: SECTOR_LABELS[k],
            key="val_sector_key",
            help="Sets sensible default margins and multiples for this business type.",
        )
        book = SECTOR_RULEBOOK[picked]

        if st.session_state.get("val_loaded_ticker") != base.display_ticker:
            apply_baseline_to_session(base, book=SECTOR_RULEBOOK[base.sector_key])

        pending_rev = st.session_state.pop("val_rev0_pending", None)
        if pending_rev is not None:
            try:
                st.session_state.val_rev0 = float(pending_rev)
            except (TypeError, ValueError):
                pass

        st.markdown("**Growth & sales**")
        ic1, ic2, ic3, ic3b = st.columns(4)
        rev0 = ic1.number_input("Revenue ₹ Cr", min_value=0.0, step=50.0, key="val_rev0")
        rev_g = ic2.number_input(
            "Sales growth % / yr",
            min_value=-20.0,
            max_value=80.0,
            value=float(base.revenue_growth_5y_pct or 12.0),
            step=0.5,
            key="val_rev_g",
        )
        years = ic3.number_input(
            "Years ahead",
            min_value=1,
            max_value=10,
            value=3,
            step=1,
            key="val_years",
        )
        est_year = ic3b.number_input(
            "Estimate year",
            min_value=2020,
            max_value=2035,
            step=1,
            key="val_est_year",
        )
        screener_rev = revenue_for_mar_fy(base, int(est_year))
        if screener_rev is not None:
            if st.button(
                f"Fill revenue from Screener Mar {est_year} ({screener_rev:,.0f} Cr)",
                key="val_pull_rev",
            ):
                st.session_state.val_rev0_pending = float(screener_rev)
                st.rerun()

        use_growth_path = st.checkbox(
            "Custom growth each year (instead of flat %)",
            key="val_use_growth_path",
        )
        growth_path: list[float] = []
        if use_growth_path:
            gp_text = st.text_input(
                "Growth path % (comma-separated)",
                placeholder="e.g. 10, 5, 15",
                key="val_growth_path_text",
            )
            growth_path = _parse_growth_path(gp_text)

        st.markdown("**Margins & valuation**")
        ic4, ic5, ic6 = st.columns(3)
        opm = ic4.number_input("OPM % now", min_value=0.0, max_value=80.0, step=0.5, key="val_opm")
        terminal_opm = ic5.number_input(
            "OPM % later",
            min_value=0.0,
            max_value=80.0,
            step=0.5,
            key="val_terminal_opm",
        )
        tax = ic6.number_input("Tax %", min_value=0.0, max_value=40.0, value=25.0, step=1.0)

        pe_is_pb = book.get("pe_is_pb", False)
        mult = "P/B" if pe_is_pb else "P/E"
        ic7, ic8, ic9 = st.columns(3)
        shares = ic7.number_input("Shares Cr", min_value=0.01, step=0.01, key="val_shares")
        fair_mult = ic8.number_input(
            f"{mult} now",
            min_value=0.5,
            max_value=120.0,
            step=0.5,
            key="val_pe_start",
        )
        terminal_pe = ic9.number_input(
            f"{mult} later",
            min_value=0.5,
            max_value=120.0,
            step=0.5,
            key="val_pe_terminal",
        )

        st.markdown("**Buy-zone settings**")
        ic10a, ic10b, ic10c = st.columns(3)
        entry_px = ic10a.number_input(
            "Your buy price ₹",
            min_value=0.01,
            step=0.05,
            key="val_entry_px",
        )
        cagr_years = ic10b.number_input(
            "Hold years",
            min_value=1,
            max_value=15,
            value=int(years),
            step=1,
            key="val_cagr_years",
        )
        buy_discount = ic10c.number_input(
            "Cheaper entries (% below price)",
            min_value=5.0,
            max_value=50.0,
            value=27.0,
            step=1.0,
            key="val_buy_discount",
        )

        st.markdown("**Optional risk inputs**")
        r1, r2, r3 = st.columns(3)
        int_drag = r1.number_input(
            "Interest drag % of OP",
            min_value=0.0,
            max_value=15.0,
            value=float(base.interest_drag_pct or 0.0),
            step=0.5,
            key="val_int_drag",
        )
        capex_pct = r2.number_input(
            "Capex % of revenue",
            min_value=0.0,
            max_value=40.0,
            value=8.0,
            step=0.5,
            key="val_capex",
        )
        new_debt = r3.number_input(
            "Extra net debt ₹ Cr",
            min_value=0.0,
            value=0.0,
            step=10.0,
            key="val_new_debt",
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
    wealth = assess_wealth_creation(base, inputs, proj, entry_price=entry_px)
    terminal_year = proj.year_columns[-1].label if proj.year_columns else "—"

    st.markdown("#### Result")
    _render_verdict_banner(wealth, float(entry_px), terminal_year)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"Target ({terminal_year})", f"₹{proj.fair_value_terminal:,.0f}")
    k2.metric("vs your price", f"{proj.upside_pct:+.1f}%")
    k3.metric(f"Implied CAGR ({int(cagr_years)}Y)", f"{proj.implied_cagr_pct:.1f}%")
    if wealth.max_buy_15pct:
        k4.metric("Max buy @ 15% CAGR", f"₹{wealth.max_buy_15pct:,.0f}")
    else:
        k4.metric("Wealth score", f"{wealth.wealth_score}/100")

    if proj.upside_pct < -5:
        st.error(
            f"At ₹{entry_px:,.0f} you are **{abs(proj.upside_pct):.0f}% above** the model target — "
            "not a cheap entry under these assumptions."
        )
    elif abs(proj.upside_pct) <= 8:
        st.warning("Price is roughly in line with the model — little margin of safety.")

    if wealth.strengths or wealth.risks or wealth.suggestions:
        with st.expander("Strengths, risks & suggested next steps", expanded=False):
            if wealth.strengths:
                st.markdown("**Strengths**")
                for s in wealth.strengths:
                    st.markdown(f"- {s}")
            if wealth.risks:
                st.markdown("**Risks**")
                for r in wealth.risks:
                    st.markdown(f"- {r}")
            if wealth.suggestions:
                st.markdown("**Next steps**")
                for s in wealth.suggestions:
                    st.markdown(f"- {s}")

    st.markdown("#### Projection")
    st.caption("History → this year → forward years. Change assumptions above to refresh.")
    sheet_df = projection_sheet_df(proj)
    st.dataframe(
        sheet_df,
        use_container_width=True,
        hide_index=True,
        height=min(420, 56 + len(sheet_df) * 36),
    )

    st.markdown("#### What price fits your CAGR goal?")
    st.caption(
        f"If the target is **₹{proj.fair_value_terminal:,.0f}** in **{int(cagr_years)} years**, "
        "these are max buy prices for each expected return."
    )
    c_left, c_right = st.columns(2)
    with c_left:
        target_cagr_df = build_target_cagr_buying_table(
            proj.fair_value_terminal,
            int(cagr_years),
        )
        if not target_cagr_df.empty:
            show_tgt = [c for c in target_cagr_df.columns if c != "_cagr"]
            st.dataframe(target_cagr_df[show_tgt], use_container_width=True, hide_index=True)
    with c_right:
        buy_df = build_buying_price_cagr_table(
            proj.fair_value_terminal,
            int(cagr_years),
            anchor_price=entry_px,
            discount_pct=buy_discount,
        )
        if not buy_df.empty:
            show_buy = [c for c in buy_df.columns if c != "Buying price (raw)"]
            st.dataframe(
                buy_df[show_buy],
                use_container_width=True,
                hide_index=True,
                height=min(320, 56 + len(buy_df) * 36),
            )

    if capex_pct > 15 or new_debt > rev0 * 0.1:
        st.warning(
            f"High capex ({capex_pct:.1f}% of revenue) or incremental debt (₹{new_debt:,.0f} Cr) — "
            "check ROCE and funding in the latest presentation."
        )

    with st.expander("Details (model chain, shares, assumptions, advanced CAGR)", expanded=False):
        st.markdown("**Model chain**")
        st.dataframe(pd.DataFrame(proj.chain_rows), use_container_width=True, hide_index=True)
        st.markdown("**Shares reference**")
        st.dataframe(
            shares_reference_df(proj),
            use_container_width=True,
            hide_index=True,
            height=min(280, 56 + len(proj.year_columns) * 32),
        )
        st.markdown("**Key assumptions**")
        st.dataframe(
            build_key_assumptions(base, inputs, proj),
            use_container_width=True,
            hide_index=True,
        )
        st.markdown("**Advanced CAGR matrix**")
        targets = sorted(
            {
                round(entry_px * 0.8, 2),
                round(entry_px, 2),
                round(proj.fair_value_terminal * 0.85, 2),
                round(proj.fair_value_terminal, 2),
                round(proj.fair_value_terminal * 1.15, 2),
            }
        )
        st.dataframe(
            build_cagr_sensitivity_table(entry_px, targets, [2, 3, 5, 7, 10]),
            use_container_width=True,
            hide_index=True,
        )


if __name__ == "__main__":
    render_valuation_rulebook_page()
