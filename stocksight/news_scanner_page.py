"""News Scanner + Pro rulebook — tiered news, watchlist sentiment, educational guide."""

from __future__ import annotations

import html
import urllib.parse
from datetime import datetime

import pandas as pd
import streamlit as st

try:
    from .news_scanner import (
        TIER_EMOJI,
        TIER_LABELS,
        analyze_ticker,
        parse_watchlist_lines,
        scan_watchlist_sentiment,
    )
    from .screener import UNIVERSES, raw_ticker_from_display
    from .ui_components import filter_column_config, inject_css, page_audience_note, safe_set_page_config
except ImportError:
    from news_scanner import (  # type: ignore[no-redef]
        TIER_EMOJI,
        TIER_LABELS,
        analyze_ticker,
        parse_watchlist_lines,
        scan_watchlist_sentiment,
    )
    from screener import UNIVERSES, raw_ticker_from_display
    from ui_components import filter_column_config, inject_css, page_audience_note, safe_set_page_config


def _tier_badge(tier: int) -> str:
    colors = {1: "#25d366", 2: "#4db8ff", 3: "#f0b429", 4: "#ff6b6b"}
    c = colors.get(tier, "#a3d8b8")
    return (
        f"<span style='background:{c}22;color:{c};border:1px solid {c}55;"
        f"padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700;'>"
        f"{TIER_EMOJI.get(tier, '')} {html.escape(TIER_LABELS.get(tier, f'Tier {tier}'))}</span>"
    )


def render_tier_reference_card() -> None:
    st.markdown("#### 📋 Tier reference — classify any headline in ~10 seconds")
    st.markdown(
        """
| Tier | What it is | Typical move | Your action |
|------|------------|----------------|-------------|
| **🔥 Tier 1** | Game-changer: big earnings beat, buyback, M&A, major order, policy win, promoter buying | **5–20%** possible | **React fast** — verify volume in **2–15 min** after headline; don't buy after huge green candle |
| **✅ Tier 2** | Material: upgrades, contracts, product launch, strong quarter | **2–8%** | Trade only with **volume + sector + trend** confirmation |
| **ℹ️ Tier 3** | Context: analyst notes, conferences, sector commentary | Small / slow | **Do not trade headline alone** — use for background |
| **🚫 Tier 4** | Noise: Telegram tips, "upper circuit", multibagger hype, influencer pumps | Trap risk | **IGNORE completely** — no exceptions |

**Golden rule:** Price = *what* · Volume = *strength* · News = *why* · Sentiment = *how far*
"""
    )


def _render_single_stock_tab(universe: str) -> None:
    st.markdown("### 🔍 Single stock deep-dive")
    st.caption(
        "Headlines from **Yahoo Finance** + **Google News** (last N days). Classified by tier with **score** and **action**. "
        "Google News often has fresher India/US coverage when Yahoo returns nothing."
    )

    max_age = int(st.session_state.get("news_scan_max_age", 7))
    c1, c2 = st.columns([2, 1])
    with c1:
        ticker = st.text_input("Ticker", placeholder="e.g. RELIANCE, TCS, AAPL", key="news_scan_ticker")
    with c2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run = st.button("Analyze news", type="primary", use_container_width=True, key="news_scan_run_one")

    if not run or not (ticker or "").strip():
        st.info("Enter a symbol and click **Analyze news**.")
        return

    with st.spinner("Fetching from Yahoo + Google News…"):
        summary = analyze_ticker(
            ticker.strip(), universe_name=universe, max_age_days=int(max_age)
        )

    raw = raw_ticker_from_display(ticker, universe)
    yahoo_url = f"https://finance.yahoo.com/quote/{raw}/news"

    st.markdown(
        f"""
<div style='background:#122f25;border:1px solid #1a3b31;border-radius:8px;padding:16px 18px;margin:12px 0;'>
  <div style='font-family:"IBM Plex Mono",monospace;font-size:1.2rem;color:#e8f7ef;font-weight:700;'>
    {html.escape(summary.ticker)}</div>
  <div style='margin-top:10px;display:flex;gap:16px;flex-wrap:wrap;font-size:0.85rem;'>
    <span><b style='color:#a3d8b8;'>News score</b> <span style='color:#25d366;font-size:1.1rem;font-weight:700;'>{summary.news_score}</span>/100</span>
    <span>{_tier_badge(summary.top_tier)}</span>
    <span><b style='color:#a3d8b8;'>Tone</b> {html.escape(summary.polarity)}</span>
    <span><b style='color:#a3d8b8;'>Macro</b> {html.escape(summary.macro_tone)}</span>
  </div>
  <div style='margin-top:12px;font-size:0.82rem;color:#c8d8e8;line-height:1.55;'>
    <b style='color:#f0b429;'>Action:</b> {html.escape(summary.action)}
  </div>
  <div style='margin-top:8px;font-size:0.78rem;color:#7abeac;'>{html.escape(summary.combo_note)}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    g_q = urllib.parse.quote(f"{summary.ticker} stock news")
    st.caption(
        f"Sources: **{summary.news_sources or '—'}** · "
        f"[Yahoo Finance]({yahoo_url}) · "
        f"[Google News search](https://news.google.com/search?q={g_q})"
    )

    if not summary.items:
        st.warning(
            f"No headlines in the last **{max_age}** days from Yahoo or Google News. "
            "Try a longer **News window**, or search the ticker on Google News manually."
        )
        return

    rows = []
    for item in summary.items:
        link = item.url if item.url.startswith("http") else None
        rows.append(
            {
                "Age": item.age_label,
                "Source": item.source or item.publisher or "—",
                "Tier": f"T{item.tier}",
                "Score": item.score,
                "Polarity": item.polarity,
                "Headline": item.title[:120],
                "Link": link,
                "Action": item.action,
                "Why": item.reason,
            }
        )
    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config=filter_column_config(
            df,
            {
                "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
                "Source": st.column_config.TextColumn(width="small"),
                "Headline": st.column_config.TextColumn(width="large"),
                "Link": st.column_config.LinkColumn("Open", display_text="↗"),
                "Action": st.column_config.TextColumn(width="medium"),
                "Why": st.column_config.TextColumn(width="medium"),
            },
        ),
    )

    with st.expander("✅ Professional pre-trade checklist", expanded=False):
        st.markdown(
            """
| Check | Good sign |
|-------|-----------|
| News | Tier 1–2 genuine trigger |
| Volume | Above average (≥ 1.5×, ideally 2×+) |
| Trend | Above 20 / 50 EMA |
| Sector | Sector strong (not lone tiny name) |
| Market | Nifty / SPY supportive |
| Risk | Stop loss defined |
| Reward | At least 1:2 R:R |

**5–6 checks green → better probability.** Avoid: already +25–40% in days, no source, pump hype, FOMO chase.
"""
        )


def _render_watchlist_tab(universe: str) -> None:
    st.markdown("### 📌 Watchlist sentiment scan")
    st.caption(
        "Paste your shortlist from the **Intraday Screener** (one ticker per line). "
        "Optional: add volume ratio after the symbol — `RELIANCE 2.5` or `TCS,1.8`. "
        "Sorted by **news score** — best trades often pair **high news score + high Vol×**."
    )

    default_text = st.session_state.get("news_watchlist_paste", "")
    pasted = st.text_area(
        "Tickers (optional Vol×)",
        value=default_text,
        height=140,
        placeholder="RELIANCE 2.8\nTCS 2.1\nINFY 1.6",
        key="news_watchlist_area",
    )

    c1, c2 = st.columns(2)
    with c1:
        scan_btn = st.button("Scan watchlist", type="primary", use_container_width=True, key="news_scan_wl")
    with c2:
        if st.button("Load from app watchlist", use_container_width=True, key="news_scan_from_wl"):
            try:
                from watchlist_store import load_watchlist
            except ImportError:
                from .watchlist_store import load_watchlist
            wl = load_watchlist()
            if wl:
                st.session_state["news_watchlist_paste"] = "\n".join(
                    str(x.get("symbol", x)).replace(".NS", "").replace(".BO", "") for x in wl
                )
                st.rerun()
            st.warning("Watchlist is empty.")

    if not scan_btn:
        st.info("Paste tickers and click **Scan watchlist**.")
        return

    entries = parse_watchlist_lines(pasted)
    if not entries:
        st.warning("No tickers parsed. Use one symbol per line.")
        return

    wl_age = int(st.session_state.get("news_scan_max_age", 7))

    if len(entries) > 35:
        st.warning(f"Scanning first 35 of {len(entries)} tickers (Yahoo rate limits).")
        entries = entries[:35]

    prog = st.progress(0, text="Classifying news…")
    summaries = []
    for i, (sym, vol) in enumerate(entries):
        prog.progress(int((i + 1) / len(entries) * 100), text=f"{sym}…")
        summaries.append(
            analyze_ticker(
                sym, universe_name=universe, vol_ratio=vol, max_age_days=wl_age
            )
        )
    prog.empty()

    summaries.sort(key=lambda s: (s.news_score, s.vol_ratio or 0), reverse=True)

    rows = []
    for s in summaries:
        raw = s.raw_ticker or raw_ticker_from_display(s.ticker, universe)
        rows.append(
            {
                "Ticker": s.ticker,
                "Yahoo Finance": f"https://finance.yahoo.com/quote/{raw}",
                "Google Finance": f"https://www.google.com/finance/quote/{raw}",
                "News score": s.news_score,
                "Top tier": f"T{s.top_tier}",
                "Polarity": s.polarity,
                "Vol×": s.vol_ratio if s.vol_ratio is not None else None,
                "Macro": s.macro_tone,
                "Top headline": (s.top_headline or "—")[:90],
                "Action": s.action[:80] if s.action else "—",
                "Combo": s.combo_note[:70] if s.combo_note else "—",
            }
        )
    df = pd.DataFrame(rows)

    st.success(
        f"Scanned **{len(summaries)}** names · sort by **News score** · "
        "look for **Tier 1–2** + **Vol× ≥ 2** + supportive macro."
    )

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config=filter_column_config(
            df,
            {
                "News score": st.column_config.ProgressColumn(
                    "News score", min_value=0, max_value=100, format="%d"
                ),
                "Vol×": st.column_config.NumberColumn(format="%.2f"),
                "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
                "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
                "Top headline": st.column_config.TextColumn(width="large"),
                "Action": st.column_config.TextColumn(width="medium"),
                "Combo": st.column_config.TextColumn(width="medium"),
            },
        ),
        height=min(480, 48 + len(df) * 38),
    )

    top = [s for s in summaries if s.news_score >= 70 and s.top_tier <= 2]
    if top:
        st.markdown("**★ Today's news leaders (Tier 1–2, score ≥ 70):** " + ", ".join(t.ticker for t in top[:8]))


def _render_universe_scan_tab(universe: str) -> None:
    st.markdown("### 🌐 Stock universe news scan")
    st.caption(
        "Scan a full universe with one click. Results are ranked by **news score** so you can quickly "
        "spot names with tradable Tier 1–2 catalysts."
    )
    all_universe_names = list(UNIVERSES.keys())
    scan_all_universes = st.checkbox(
        "Scan all universes",
        value=False,
        key="news_scan_universe_all",
        help="If enabled, scans across all configured universes instead of only the selected market/universe.",
    )
    target_universes = all_universe_names if scan_all_universes else [universe]
    total = sum(len(UNIVERSES.get(u, [])) for u in target_universes)
    c1, c2 = st.columns([2, 1])
    with c1:
        scan_full_universe = st.checkbox(
            "Scan full universe",
            value=True,
            key="news_scan_universe_full",
            help="When enabled, scans all symbols in chosen scope.",
        )
        max_scan = total if scan_full_universe else st.slider(
            "Max symbols to scan",
            min_value=10,
            max_value=max(10, total if total else 10),
            value=min(100, total if total else 100),
            step=5,
            key="news_scan_universe_max",
            help="Used only when full-universe scan is OFF.",
        )
    with c2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run_scan = st.button(
            "Scan universe",
            type="primary",
            use_container_width=True,
            key="news_scan_universe_run",
        )

    f1, f2, f3 = st.columns(3)
    with f1:
        min_score = st.slider(
            "Min news score",
            min_value=0,
            max_value=100,
            value=0,
            step=5,
            key="news_scan_universe_min_score",
            help="Default 0 shows all scanned names. Raise to 50–70 for a shortlist.",
        )
    with f2:
        only_t12 = st.checkbox(
            "Only Tier 1–2",
            value=False,
            key="news_scan_universe_only_t12",
            help="Keep off to see Tier 3 context rows too.",
        )
    with f3:
        only_with_news = st.checkbox(
            "Only with headlines",
            value=False,
            key="news_scan_universe_only_with_news",
            help="When on, hides names where no headline was found in the news window.",
        )

    if not run_scan:
        mode = "full universe" if scan_full_universe else f"first {max_scan}"
        scope = "all universes" if scan_all_universes else universe
        st.info(f"Universe size: **{total}** symbols in **{scope}**. Current scan mode: **{mode}**.")
        return

    raw_symbols: list[tuple[str, str]] = []
    for uni in target_universes:
        raw_symbols.extend([(uni, str(sym)) for sym in UNIVERSES.get(uni, [])])
    if not raw_symbols:
        st.warning("No symbols found for this universe.")
        return

    raw_symbols = raw_symbols[:max_scan]
    if scan_full_universe and total > 300:
        st.warning(
            "Full scan selected. This may take a few minutes (Yahoo + Google News per symbol)."
        )
    prog = st.progress(0, text="Starting universe news scan…")
    summaries = []
    for i, (src_universe, raw) in enumerate(raw_symbols):
        disp = str(raw).replace(".NS", "").replace(".BO", "").strip().upper()
        prog.progress(int((i + 1) / len(raw_symbols) * 100), text=f"{disp}… ({i + 1}/{len(raw_symbols)})")
        uni_age = int(st.session_state.get("news_scan_max_age", 7))
        sm = analyze_ticker(
            disp or str(raw),
            universe_name=src_universe,
            max_age_days=uni_age,
            fast_universe=True,
        )
        setattr(sm, "source_universe", src_universe)
        summaries.append(sm)
    prog.empty()

    summaries.sort(key=lambda s: s.news_score, reverse=True)
    with_headlines = sum(1 for s in summaries if (s.top_headline or "").strip())
    rows = []
    for s in summaries:
        raw = s.raw_ticker or raw_ticker_from_display(s.ticker, getattr(s, "source_universe", universe))
        hl = (s.top_headline or "").strip()
        rows.append(
            {
                "Ticker": s.ticker,
                "Universe": getattr(s, "source_universe", universe),
                "Raw": raw,
                "Yahoo Finance": f"https://finance.yahoo.com/quote/{raw}",
                "Google Finance": f"https://www.google.com/finance/quote/{raw}",
                "News score": s.news_score,
                "Top tier #": s.top_tier,
                "Top tier": f"{TIER_EMOJI.get(s.top_tier, '•')} T{s.top_tier}",
                "Headlines": len(s.items),
                "Sources": s.news_sources or "—",
                "Tier reference": f"{TIER_EMOJI.get(s.top_tier, '•')} {TIER_LABELS.get(s.top_tier, f'Tier {s.top_tier}')}",
                "Tier action": (
                    "⚡ React fast (2–15 min), confirm volume"
                    if s.top_tier == 1
                    else "✅ Trade with confirmation"
                    if s.top_tier == 2
                    else "ℹ️ Context only, not standalone trigger"
                    if s.top_tier == 3
                    else "🚫 Ignore noise"
                ),
                "Polarity": s.polarity,
                "Macro": s.macro_tone,
                "Top headline": (hl or "—")[:95],
                "Action": s.action[:90] if s.action else "—",
                "Tier1": s.tier_counts.get(1, 0),
                "Tier2": s.tier_counts.get(2, 0),
            }
        )
    df_all = pd.DataFrame(rows)
    df = df_all.copy()
    if min_score > 0:
        df = df[df["News score"] >= min_score]
    if only_t12:
        df = df[df["Top tier #"].isin((1, 2))]
    if only_with_news:
        df = df[df["Headlines"] > 0]
    df = df.reset_index(drop=True)

    if df_all.empty:
        st.error(
            "Scan returned no rows — check network access on the server (Yahoo + Google News RSS)."
        )
        return

    if df.empty:
        st.warning(
            f"**{len(df_all)}** symbols scanned · **{with_headlines}** had headlines · "
            f"**0** match your filters (min score **{min_score}**, Tier 1–2 only: **{only_t12}**, "
            f"headlines only: **{only_with_news}**). "
            "Set **Min news score** to **0**, turn off **Only Tier 1–2**, or increase **News window** (top of page)."
        )
        with st.expander("Preview — top 15 by score (ignoring filters)", expanded=True):
            preview = df_all.sort_values("News score", ascending=False).head(15)
            st.dataframe(preview, use_container_width=True, hide_index=True)
        return

    st.success(
        f"Scanned **{len(raw_symbols)}** symbols · **{with_headlines}** with headlines · "
        f"**{len(df)}** shown after filters (of {len(df_all)})."
    )
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=min(560, 48 + len(df) * 36),
        column_config=filter_column_config(
            df,
            {
                "News score": st.column_config.ProgressColumn("News score", min_value=0, max_value=100, format="%d"),
                "Top headline": st.column_config.TextColumn(width="large"),
                "Top tier": st.column_config.TextColumn("Top tier", width="small"),
                "Tier reference": st.column_config.TextColumn("Tier reference", width="medium"),
                "Tier action": st.column_config.TextColumn("Tier action", width="medium"),
                "Action": st.column_config.TextColumn(width="medium"),
                "Tier1": st.column_config.NumberColumn("Tier1", help="Count of Tier-1 headlines in last 4 days"),
                "Tier2": st.column_config.NumberColumn("Tier2", help="Count of Tier-2 headlines in last 4 days"),
                "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
                "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
                "Raw": None,
            },
        ),
    )

    with st.expander("📋 Tier reference for these results", expanded=False):
        render_tier_reference_card()

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇ Download universe sentiment CSV",
        data=csv,
        file_name=f"news_universe_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="news_scan_universe_dl_csv",
        use_container_width=True,
    )

    leaders = df["Ticker"].astype(str).head(10).tolist()
    if leaders:
        st.markdown("**★ Universe leaders today:** " + ", ".join(leaders))

    a1, a2 = st.columns(2)
    with a1:
        if st.button("➕ Add filtered leaders to Watchlist", use_container_width=True, key="news_scan_universe_add_wl"):
            try:
                from watchlist_store import add_to_watchlist
            except ImportError:
                from .watchlist_store import add_to_watchlist
            added = 0
            for raw in df["Raw"].astype(str).tolist():
                if raw:
                    add_to_watchlist(raw)
                    added += 1
            st.success(f"Added {added} symbols to watchlist.")
    with a2:
        if st.button("📌 Send top names to Watchlist scan tab", use_container_width=True, key="news_scan_universe_send_tab"):
            st.session_state["news_watchlist_paste"] = "\n".join(df["Ticker"].astype(str).head(25).tolist())
            st.success("Top names sent. Open the Watchlist scan tab and click Scan watchlist.")


def _render_rulebook_tab() -> None:
    st.markdown("### 📚 News + Sentiment Pro Rulebook")
    st.caption("News + sentiment is what separates average traders from pros. Price moves on **expectation**, not the headline.")

    st.markdown(
        """
> **The edge:** By the time most people read a headline, algos have moved the price. Your window is often **2–15 minutes**
> after a Tier 1–2 headline — **before** retail FOMO — if volume confirms.
"""
    )

    st.markdown("#### 1. How beginners usually trade ❌")
    st.markdown(
        """
```
Stock spikes 8–10%  →  Social hype  →  Beginner buys late
        →  Smart money books profit  →  Price falls  →  Beginner trapped
```

**Typical mistakes:** buying after a huge green candle · WhatsApp/Telegram tips · ignoring volume & news quality · no stop loss · FOMO
"""
    )

    st.markdown("#### 2. How professionals think ✅")
    st.markdown(
        """
```
News appears early  →  Pros check: REAL? BIG? Volume? Sector?
        →  Enter BEFORE hype  →  Retail notices later  →  Pros exit into strength
```
"""
    )

    st.markdown("#### 3. The 5-layer pro rulebook")
    st.markdown(
        """
**LAYER 1 — News quality**

| ❌ Bad to trade | ✅ Good to trade |
|-----------------|------------------|
| Rumors | Government policy |
| Influencer tweets | Big order wins |
| "Upper circuit coming" | Strong quarterly earnings |
| Pump channels | New contracts |
| | Promoter buying |
| | Sector-wide momentum |

**LAYER 2 — Volume = truth**

| Signal | Meaning |
|--------|---------|
| Price ↑ + Volume **low** | Weak move — suspect |
| Price ↑ + Volume **high** | Strong move — pros care |

Watch: delivery %, institutional activity, sudden volume expansion.

**LAYER 3 — Sector sentiment**

- **All railway stocks up** → sector strong → higher continuation odds  
- **One tiny name alone** → possible operator play → higher risk

**LAYER 4 — Timing**

| Beginners | Pros |
|-----------|------|
| Buy after big candle | Early breakout or healthy pullback |
| | High volume + positive Tier 1–2 news + market & sector supportive |

**LAYER 5 — Market sentiment cycle**

```
Fear → Smart money accumulates → Recovery → Pros enter
→ Excitement → Retail enters → Euphoria → Pros sell to retail → Crash
```

Buy in **fear / early recovery**. Avoid **extreme euphoria**.
"""
    )

    st.markdown("#### 4. Safe short-term setup (visual)")
    st.markdown(
        """
```
Positive Tier 1–2 News
        +
High Volume (≥ 2× avg)
        +
Breakout / healthy pullback
        +
Sector strong
        +
Nifty / market stable
        =  Higher probability setup
```
"""
    )

    st.markdown("#### 5. Red flags pros avoid 🚩")
    st.markdown(
        """
- Stock already **+25–40%** in a few days with no Tier 1–2 news  
- No credible source (only Tier 4 noise)  
- Very low cap pump · upper-circuit chains · fake multibagger hype  
- Buying panic FOMO after vertical candle  
"""
    )

    st.markdown("#### 6. The real secret")
    st.markdown(
        """
Professionals don't predict — they **react faster**, **control risk**, **exit earlier**, and follow **data, not emotion**.
"""
    )


def render_news_scanner_page() -> None:
    safe_set_page_config(page_title="News Scanner | StockSight", page_icon="📰", layout="wide")
    inject_css()

    st.markdown(
        """
<div class="main-title" style="font-family:'IBM Plex Mono',monospace;font-size:2rem;color:#25d366;font-weight:700;">
📰 News Scanner</div>
<div style="font-family:'IBM Plex Mono',monospace;font-size:0.8rem;color:#b8e7c7;letter-spacing:2px;text-transform:uppercase;">
News + sentiment · Tier 1–4 · Pro rulebook</div>
""",
        unsafe_allow_html=True,
    )

    page_audience_note(
        "Traders who want to know if a move is real news or noise before entering.",
        "Pulls headlines from **Yahoo Finance** and **Google News RSS**, classifies into **4 tiers**, "
        "and scores tradability. Pair **high news score** with **high Vol×** from the Intraday Screener.",
    )

    with st.expander("📡 News sources (why Yahoo alone looked empty)", expanded=False):
        st.markdown(
            """
| Source | Role |
|--------|------|
| **Yahoo Finance API** | Direct ticker feed (when available) |
| **Google News RSS** | Backup search by company name + symbol — usually fresher for NSE names |

If nothing appears in your chosen **News window**, the scanner automatically widens to **30 days** for context.

**Tip:** Use **7–14 day** window for swing context; **3–5 days** for intraday catalysts only.
"""
        )

    st.markdown("---")

    st.session_state.setdefault("news_scan_max_age", 7)
    st.slider(
        "News window (days) — all tabs",
        3,
        30,
        int(st.session_state.get("news_scan_max_age", 7)),
        key="news_scan_max_age",
    )

    universe = st.selectbox(
        "Market / suffix",
        ["Nifty 50 (NSE)", "Nifty 500 (NSE)", "S&P 500 (NYSE)"],
        key="news_scan_universe",
    )

    tab1, tab2, tab3, tab4 = st.tabs(
        ["🔍 Single stock", "📌 Watchlist scan", "🌐 Universe scan", "📚 Pro rulebook"]
    )

    with tab1:
        _render_single_stock_tab(universe)
    with tab2:
        _render_watchlist_tab(universe)
    with tab3:
        _render_universe_scan_tab(universe)
    with tab4:
        _render_rulebook_tab()

    st.markdown("---")
    render_tier_reference_card()

    st.caption(
        f"⚠️ Educational only · Yahoo Finance via yfinance · Not financial advice · "
        f"Updated {datetime.now().strftime('%d %b %Y %H:%M')}"
    )
