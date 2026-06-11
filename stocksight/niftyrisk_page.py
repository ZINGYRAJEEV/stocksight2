"""NiftyRisk — Streamlit dashboard (blueprint + Phase 1 risk analyzer)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from niftyrisk.advice import build_improvement_hints
from niftyrisk.config import NiftyRiskConfig, SubscriptionTier, TIER_LIMITS, config_with_tier, load_config
from niftyrisk.models import Holding, Portfolio, upgrade_risk_report
from niftyrisk.portfolio import load_portfolio_csv, normalize_ticker_nse
from niftyrisk.risk_engine import analyze_portfolio
from niftyrisk.tax import estimate_capital_gains_tax
from ui_components import inject_css, page_audience_note, safe_set_page_config

META = {
    "title": "NiftyRisk",
    "emoji": "🛡️",
    "nav_title": "NiftyRisk",
}

_BLUEPRINT = Path(__file__).resolve().parent / "niftyrisk" / "blueprint.html"
_SAMPLE_CSV = Path(__file__).resolve().parent / "niftyrisk" / "sample_portfolio.csv"


def _grade_color(grade: str) -> str:
    return {
        "A": "#22c55e",
        "B": "#00d4aa",
        "C": "#fbbf24",
        "D": "#ff6b35",
        "E": "#ef4444",
        "F": "#991b1b",
    }.get(grade, "#64748b")


def _render_blueprint() -> None:
    if _BLUEPRINT.is_file():
        html = _BLUEPRINT.read_text(encoding="utf-8")
        components.html(html, height=900, scrolling=True)
    else:
        st.warning("Blueprint HTML not found at niftyrisk/blueprint.html")
        st.markdown(
            "See **docs/NIFTYRISK.md** for architecture, tiers, and roadmap."
        )


def get_active_niftyrisk_config() -> NiftyRiskConfig:
    """Session tier override, else env default from load_config()."""
    tier = st.session_state.get("niftyrisk_tier")
    return config_with_tier(tier) if tier else load_config()


def render_tier_selector(*, key_prefix: str = "nr") -> NiftyRiskConfig:
    env_cfg = load_config()
    tiers = [t.value for t in SubscriptionTier]
    active = st.session_state.get("niftyrisk_tier") or env_cfg.tier.value
    default_idx = tiers.index(active) if active in tiers else 0
    labels = {
        "free": "Free — VaR, grade, 10 holdings",
        "pro": "Pro — Monte Carlo, tax, 50 holdings",
        "elite": "Elite — stress tests, 200 holdings",
    }
    selected = st.selectbox(
        "NiftyRisk tier",
        tiers,
        index=default_idx,
        format_func=lambda x: labels.get(x, x.upper()),
        key=f"{key_prefix}_tier_select",
        help="Demo tier selector. Env default: NIFTYRISK_TIER. Pro unlocks Monte Carlo + tax; Elite adds stress.",
    )
    st.session_state["niftyrisk_tier"] = selected
    return config_with_tier(selected)


def _render_improvement_hints(report) -> None:
    hints = build_improvement_hints(report)
    if not hints:
        return
    with st.expander("💡 How to improve this portfolio", expanded=True):
        st.caption(
            "Personalised suggestions from your risk grade, concentration, beta, sectors, "
            "and Pro/Elite projections. Educational only — not advice."
        )
        for i, h in enumerate(hints, 1):
            badge = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(h["priority"], "•")
            st.markdown(f"{badge} **{i}. {h['title']}**")
            st.markdown(h["action"])
            st.caption(h["why"])


def _render_stress_results(stress_results: list) -> None:
    if not stress_results:
        return
    st.markdown("#### Stress scenarios (Elite)")
    df = pd.DataFrame(stress_results)
    show_cols = [c for c in (
        "label", "portfolio_loss_pct", "portfolio_loss_inr", "recovery_hint"
    ) if c in df.columns]
    if show_cols:
        display = df[show_cols].rename(columns={
            "label": "Scenario",
            "portfolio_loss_pct": "Est. loss %",
            "portfolio_loss_inr": "Est. loss ₹",
            "recovery_hint": "Recovery (illustrative)",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)
    if "portfolio_loss_inr" in df.columns:
        chart_df = df.set_index("label")[["portfolio_loss_inr"]]
        st.bar_chart(chart_df)


def _render_tax_panel(report, *, key_prefix: str = "nr") -> None:
    st.markdown("#### STCG / LTCG estimator (Pro+)")
    auto = getattr(report, "tax_estimate", None) or {}
    if auto.get("unrealized_gain", 0) > 0:
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Unrealized gain", f"₹{auto.get('unrealized_gain', 0):,.0f}")
        t2.metric("Est. LTCG tax", f"₹{auto.get('ltcg_tax', 0):,.0f}")
        t3.metric("Est. total tax", f"₹{auto.get('total_tax', 0):,.0f}")
        t4.caption(auto.get("note", ""))

    st.caption("Override with realized gains you plan to book this FY:")
    tc1, tc2, tc3 = st.columns(3)
    with tc1:
        stcg = st.number_input("STCG gains ₹", 0.0, key=f"{key_prefix}_stcg")
    with tc2:
        ltcg = st.number_input("LTCG gains ₹", 0.0, key=f"{key_prefix}_ltcg")
    with tc3:
        exempt_used = st.number_input("LTCG exemption used ₹", 0.0, key=f"{key_prefix}_ltcg_ex")
    if st.button("Estimate tax on entered gains", key=f"{key_prefix}_tax_btn"):
        est = estimate_capital_gains_tax(
            stcg_gains=stcg,
            ltcg_gains=ltcg,
            ltcg_exemption_used=exempt_used,
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("STCG tax (20%)", f"₹{est.stcg_tax:,.0f}")
        c2.metric("LTCG tax (12.5%)", f"₹{est.ltcg_tax:,.0f}")
        c3.metric("Total tax", f"₹{est.total_tax:,.0f}")
        st.caption(est.note)


def _render_tiers() -> None:
    cols = st.columns(3)
    for col, tier in zip(cols, SubscriptionTier):
        limits = TIER_LIMITS[tier]
        with col:
            st.markdown(f"### {tier.value.upper()}")
            st.caption(f"Max holdings: **{limits['max_holdings']}**")
            st.caption(f"Monte Carlo runs: **{limits['monte_carlo_runs']}**")
            st.caption(f"Stress tests: **{'Yes' if limits['stress_scenarios'] else 'No'}**")
            st.caption(f"Tax engine: **{'Yes' if limits['tax_engine'] else 'No'}**")


def render_risk_dashboard(report, *, key_prefix: str = "nr") -> None:
    grade = report.risk_grade
    color = _grade_color(grade)
    st.markdown(
        f"""
<div style="background:#111827;border:1px solid #1f2d45;border-radius:12px;padding:20px;
            display:flex;align-items:center;gap:24px;flex-wrap:wrap;">
  <div style="font-size:56px;font-weight:800;color:{color};">{grade}</div>
  <div>
    <div style="font-size:13px;color:#64748b;letter-spacing:2px;">RISK GRADE</div>
    <div style="font-size:22px;font-weight:700;color:#e2e8f0;">Score {report.risk_score}/100</div>
    <div style="font-size:12px;color:#64748b;">Lower is better · A = conservative · F = aggressive</div>
  </div>
  <div style="margin-left:auto;text-align:right;">
    <div style="font-size:13px;color:#64748b;">Portfolio value</div>
    <div style="font-size:24px;font-weight:700;color:#00d4aa;">₹{report.total_value:,.0f}</div>
    <div style="font-size:11px;color:#64748b;">{report.holdings_count} holdings · tier {report.tier}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("VaR (1d 95%)", f"₹{report.var_1d_inr:,.0f}", f"{report.var_1d_pct:.2f}%")
    m2.metric("CVaR (1d)", f"{report.cvar_1d_pct:.2f}%")
    m3.metric("Annual vol", f"{report.annual_vol_pct or '—'}%")
    m4.metric("Beta vs Nifty", report.beta_nifty if report.beta_nifty is not None else "—")
    m5.metric("Max drawdown", f"{report.max_drawdown_pct or '—'}%")

    m6, m7, m8 = st.columns(3)
    m6.metric("Sharpe", report.sharpe_ratio if report.sharpe_ratio is not None else "—")
    m7.metric("Sortino", report.sortino_ratio if report.sortino_ratio is not None else "—")
    m8.metric("Top-3 concentration", f"{report.concentration_top3_pct:.1f}%")

    if report.benchmark_return_pct is not None:
        st.caption(
            f"Period return: portfolio **{report.portfolio_return_pct}%** vs "
            f"Nifty **{report.benchmark_return_pct}%** "
            f"(excess **{report.excess_return_pct}%**)"
        )

    if report.flags:
        st.warning("Flags: " + " · ".join(report.flags))

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Holdings")
        st.dataframe(pd.DataFrame(report.holding_risk), use_container_width=True, hide_index=True)
    with c2:
        st.markdown("#### Sector allocation")
        if report.sector_weights:
            sec_df = pd.DataFrame(
                [{"Sector": k, "Weight %": v} for k, v in report.sector_weights.items()]
            ).sort_values("Weight %", ascending=False)
            st.bar_chart(sec_df.set_index("Sector")["Weight %"])
        else:
            st.caption("No sector data")

    if getattr(report, "monte_carlo", None):
        st.markdown("#### Monte Carlo (1-year projection · Pro+)")
        mc = getattr(report, "monte_carlo", {}) or {}
        c3, c4, c5, c6 = st.columns(4)
        c3.metric("Median terminal", f"₹{mc.get('median_terminal', 0):,.0f}")
        c4.metric("5th percentile", f"₹{mc.get('p5_terminal', 0):,.0f}")
        c5.metric("95th percentile", f"₹{mc.get('p95_terminal', 0):,.0f}")
        c6.metric("Prob. loss", f"{mc.get('prob_loss', 0)}%")
        st.caption(
            f"Based on **{mc.get('runs', 0):,}** simulations over "
            f"**{mc.get('horizon_days', 252)}** trading days from ₹{mc.get('initial_value', 0):,.0f}."
        )

    stress_results = getattr(report, "stress_results", None) or []
    if stress_results:
        _render_stress_results(stress_results)

    if getattr(report, "tax_estimate", None) is not None:
        _render_tax_panel(report, key_prefix=key_prefix)

    _render_improvement_hints(report)

    if report.notes:
        for n in report.notes:
            if "Upgrade" in n:
                st.info(n)


def _render_analyzer() -> None:
    cfg = render_tier_selector(key_prefix="nr")
    limits = cfg.limits()
    st.caption(
        f"Active tier: **{cfg.tier.value.upper()}** · up to **{limits['max_holdings']}** holdings · "
        f"lookback **{limits['lookback_days']}** days"
    )

    tab_csv, tab_manual = st.tabs(["Upload CSV", "Manual entry"])

    portfolio: Portfolio | None = None
    icici_port = st.session_state.get("niftyrisk_icici_portfolio")
    if icici_port:
        c_ic1, c_ic2 = st.columns([3, 1])
        with c_ic1:
            st.info(
                f"**ICICI holdings loaded** — {len(icici_port.holdings)} positions from "
                "**ICICI Positions & Orders** (Holdings tab). Click **Analyze risk** below."
            )
        with c_ic2:
            if st.button("Clear ICICI import", key="nr_clear_icici"):
                st.session_state.pop("niftyrisk_icici_portfolio", None)
                st.session_state.pop("niftyrisk_report", None)
                st.rerun()
        portfolio = icici_port

    with tab_csv:
        uploaded = st.file_uploader(
            "Portfolio CSV",
            type=["csv"],
            help="NiftyRisk format (ticker, quantity, avg_price) or ICICI Holdings export "
            "(stock_code, Ticker (.NS), quantity, demat_* columns).",
        )
        if _SAMPLE_CSV.is_file():
            st.download_button(
                "Download sample CSV",
                _SAMPLE_CSV.read_bytes(),
                file_name="niftyrisk_sample.csv",
                mime="text/csv",
            )
        if uploaded:
            try:
                portfolio = load_portfolio_csv(uploaded.read(), name="Uploaded")
                st.session_state.pop("niftyrisk_icici_portfolio", None)
                st.success(f"Loaded **{len(portfolio.holdings)}** holdings")
            except ValueError as exc:
                st.error(str(exc))
        st.caption(
            "**Formats:** `ticker,quantity,avg_price` (NiftyRisk) · full ICICI export from Holdings tab "
            "(uses **Ticker (.NS)**, **quantity** or **demat_avail_quantity**, **average_price** / **ltp**)."
        )

    with tab_manual:
        max_rows = int(limits["max_holdings"])
        ui_rows = 10 if cfg.tier == SubscriptionTier.FREE else min(max_rows, 25)
        st.caption(f"Enter up to **{ui_rows}** rows (tier max **{max_rows}**)")
        rows = []
        for i in range(ui_rows):
            c1, c2, c3 = st.columns(3)
            with c1:
                t = st.text_input(f"Ticker {i+1}", key=f"nr_t_{i}", placeholder="RELIANCE")
            with c2:
                q = st.number_input(f"Qty {i+1}", min_value=0.0, value=0.0, key=f"nr_q_{i}")
            with c3:
                p = st.number_input(f"Avg price {i+1}", min_value=0.0, value=0.0, key=f"nr_p_{i}")
            if t and q > 0:
                rows.append(Holding(ticker=normalize_ticker_nse(t), quantity=q, avg_price=p))
        if st.button("Build portfolio from rows", key="nr_build_manual") and rows:
            portfolio = Portfolio(name="Manual", holdings=rows)

    prev = upgrade_risk_report(st.session_state.get("niftyrisk_report"))
    if prev and prev.tier != cfg.tier.value:
        st.warning("Tier changed — click **Analyze risk** again to apply Pro/Elite features.")

    if st.button("▶ Analyze risk", type="primary", key="nr_analyze") and portfolio:
        with st.spinner("Fetching NSE prices and running risk engine…"):
            try:
                report = analyze_portfolio(portfolio, config=cfg)
                st.session_state["niftyrisk_report"] = report
            except Exception as exc:
                st.error(f"Analysis failed: {exc}")

    report = upgrade_risk_report(st.session_state.get("niftyrisk_report"))
    if report:
        st.session_state["niftyrisk_report"] = report
        render_risk_dashboard(report)


def render_niftyrisk_page() -> None:
    safe_set_page_config(
        page_title=f"{META['title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(
        f'<div style="font-size:2rem;font-weight:800;color:#00d4aa;">{META["emoji"]} NiftyRisk</div>',
        unsafe_allow_html=True,
    )
    st.caption("Institutional-grade risk intelligence for Indian retail investors")

    page_audience_note(
        "Investors who want VaR, concentration, and Nifty-relative risk on a real portfolio — not just stock picks.",
        "Phase 1 MVP: CSV upload, historical VaR, risk grade A–F, sector weights, Nifty benchmark. "
        "Pro adds Monte Carlo + tax; Elite adds stress tests.",
    )

    tab_bp, tab_an, tab_api = st.tabs(["Product blueprint", "Risk analyzer", "API & tiers"])

    with tab_bp:
        _render_blueprint()

    with tab_an:
        _render_analyzer()

    with tab_api:
        _render_tiers()
        st.markdown("#### Run API locally")
        st.code("python scripts/run_niftyrisk.py", language="bash")
        st.markdown(
            "- `GET /health` · `GET /tiers` · `GET /stress/scenarios`  \n"
            "- `POST /analyze/csv?tier=pro` · `POST /analyze/json?tier=elite`  \n"
            "- `POST /stress/apply` · `POST /tax/estimate` (tier-gated)  \n"
            "See **docs/NIFTYRISK.md** for request examples."
        )
