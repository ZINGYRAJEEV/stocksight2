"""Streamlit panel — historical P/E chart (Screener EPS + Yahoo price)."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
except ImportError:
    go = None  # type: ignore[assignment]

try:
    from pe_history import build_pe_history, pe_history_to_dataframe
except ImportError:
    from stocksight.pe_history import build_pe_history, pe_history_to_dataframe  # type: ignore[no-redef]


@st.cache_data(ttl=900, show_spinner=False)
def _cached_pe_history(display_ticker: str, raw_ticker: str) -> tuple[list, dict]:
    points, meta = build_pe_history(display_ticker, raw_ticker)
    return points, meta


def render_pe_history_panel(
    *,
    display_ticker: Optional[str],
    raw_ticker: Optional[str] = None,
    key_prefix: str = "pe_hist",
    max_pe_hint: Optional[float] = None,
    expanded: bool = True,
) -> None:
    """Historical P/E chart for a selected NSE ticker."""
    if not display_ticker:
        return

    disp = str(display_ticker).strip().upper()
    raw = str(raw_ticker or f"{disp}.NS").strip()

    with st.expander(f"📉 Historical P/E — **{disp}**", expanded=expanded):
        with st.spinner(f"Loading EPS history (Screener.in) + prices (Yahoo) for {disp}…"):
            try:
                points, meta = _cached_pe_history(disp, raw)
            except Exception as exc:
                st.warning(f"Could not build P/E history: {exc}")
                return

        if not points:
            st.info(
                "No EPS history found on Screener.in for this name. "
                "Sign in via the Screener session panel if rate-limited."
            )
            return

        df = pe_history_to_dataframe(points)
        chart_df = df[df["P/E"].notna()].copy()
        if chart_df.empty:
            st.warning("EPS found but could not compute P/E — check Yahoo price history.")
            st.dataframe(df, use_container_width=True, hide_index=True)
            return

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Current P/E", f"{meta.get('current_pe') or '—'}")
        c2.metric("Median P/E", f"{meta.get('median_pe') or '—'}")
        c3.metric("Min P/E", f"{meta.get('min_pe') or '—'}")
        c4.metric("Max P/E", f"{meta.get('max_pe') or '—'}")
        pct_med = meta.get("pct_vs_median")
        c5.metric("vs Median", f"{pct_med:+.1f}%" if pct_med is not None else "—")

        if max_pe_hint is not None and meta.get("current_pe") is not None:
            try:
                if float(meta["current_pe"]) <= float(max_pe_hint):
                    st.success(f"Current P/E ≤ your screen max (**{max_pe_hint:.0f}**) — value-growth band.")
                else:
                    st.caption(f"Screen max P/E = {max_pe_hint:.0f} (reference line on chart).")
            except (TypeError, ValueError):
                pass

        if go is not None:
            colors = [
                "#25d366" if row["Type"] == "Current" else "#4db8ff"
                for _, row in chart_df.iterrows()
            ]
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=chart_df["Period"],
                    y=chart_df["P/E"],
                    mode="lines+markers",
                    line=dict(color="#7abeac", width=2),
                    marker=dict(size=9, color=colors),
                    name="P/E",
                    hovertemplate=(
                        "%{x}<br>P/E: %{y:.2f}<br>"
                        "EPS ₹%{customdata[0]:.2f}<br>"
                        "Price ₹%{customdata[1]}<extra></extra>"
                    ),
                    customdata=list(zip(chart_df["EPS ₹"], chart_df["Price ₹"])),
                )
            )
            if meta.get("median_pe") is not None:
                fig.add_hline(
                    y=float(meta["median_pe"]),
                    line_dash="dot",
                    line_color="#f0b429",
                    annotation_text="Median",
                    annotation_position="top left",
                )
            if max_pe_hint is not None:
                fig.add_hline(
                    y=float(max_pe_hint),
                    line_dash="dash",
                    line_color="#e05252",
                    annotation_text="Max P/E filter",
                    annotation_position="bottom left",
                )
            fig.update_layout(
                template="plotly_white",
                height=380,
                margin=dict(l=10, r=10, t=28, b=10),
                yaxis_title="P/E ratio",
                xaxis_title="Mar FY / current",
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_{disp}_pe")
        else:
            st.line_chart(chart_df.set_index("Period")["P/E"])

        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(
            f"{meta.get('eps_source', '')} · {meta.get('price_source', '')}. "
            "P/E at FY end uses price on/before 31 Mar — educational only."
        )
        if meta.get("screener_url"):
            st.markdown(f"[Open on Screener.in ↗]({meta['screener_url']})")


def render_pe_history_for_row(
    row: pd.Series,
    *,
    key_prefix: str,
    max_pe_hint: Optional[float] = None,
) -> None:
    """Resolve ticker/raw from a scan results row and render the P/E panel."""
    if row is None:
        return
    disp = str(row.get("Ticker") or row.get("Name") or "").strip()
    raw = str(row.get("Raw") or "").strip()
    if not raw and disp:
        raw = f"{disp}.NS"
    render_pe_history_panel(
        display_ticker=disp,
        raw_ticker=raw or None,
        key_prefix=key_prefix,
        max_pe_hint=max_pe_hint,
    )
