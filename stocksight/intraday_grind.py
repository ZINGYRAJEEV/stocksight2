"""
Sector steady-grind pattern — slow institutional accumulation intraday.

Detects names like ZENTEC / MIDHANI: themed sector, volume confirmation,
price holding above VWAP with higher highs and no violent 5m spikes.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def _hist_series(hist: pd.DataFrame, col: str) -> pd.Series:
    try:
        from intraday import hist_series
    except ImportError:
        from .intraday import hist_series  # type: ignore[no-redef]
    return hist_series(hist, col)


def _compute_vwap(bars: pd.DataFrame):
    try:
        from intraday import compute_vwap
    except ImportError:
        from .intraday import compute_vwap  # type: ignore[no-redef]
    return compute_vwap(bars)

# Yahoo sector/industry text + known NSE defence/aerospace names (sector tags are often vague).
SECTOR_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Defence & Aerospace": (
        "defence",
        "defense",
        "aerospace",
        "military",
        "ordnance",
        "anti-drone",
        "drone",
        "simulator",
        "munition",
        "missile",
        "radar",
        "shipbuilding",
        "shipyard",
        "artillery",
        "tank",
        "combat",
        "aeronaut",
        "superalloy",
        "titanium",
        "psu",
        "ministry of defence",
    ),
}

NSE_THEME_TICKERS: dict[str, frozenset[str]] = {
    "Defence & Aerospace": frozenset(
        {
            "ZENTEC.NS",
            "MIDHANI.NS",
            "HAL.NS",
            "BEL.NS",
            "BDL.NS",
            "COCHINSHIP.NS",
            "GRSE.NS",
            "MAZDOCK.NS",
            "BEML.NS",
            "DATAPATTNS.NS",
            "MTARTECH.NS",
            "APOLLO.NS",
            "IDEAFORGE.NS",
            "PARAS.NS",
            "ASTRAMICRO.NS",
            "SOLARINDS.NS",
            "TEJASNET.NS",
            "RVNL.NS",
            "IRCON.NS",
        }
    ),
}

US_THEME_TICKERS: dict[str, frozenset[str]] = {
    "Defence & Aerospace": frozenset({"LMT", "NOC", "RTX", "GD", "LHX", "BA", "HII", "TXT"}),
}


def _norm_ticker(raw: str) -> str:
    return (raw or "").strip().upper()


def match_sector_theme(
    sector: str,
    industry: str,
    *,
    raw_ticker: str = "",
    market: str = "NSE",
) -> Optional[str]:
    """Return theme label (e.g. Defence & Aerospace) or None."""
    raw = _norm_ticker(raw_ticker)
    mkt = (market or "NSE").upper()
    ticker_maps = US_THEME_TICKERS if mkt == "US" else NSE_THEME_TICKERS
    for theme, tickers in ticker_maps.items():
        if raw in tickers:
            return theme

    blob = f"{sector or ''} {industry or ''}".lower()
    if not blob.strip():
        return None
    for theme, keys in SECTOR_THEME_KEYWORDS.items():
        if any(k in blob for k in keys):
            return theme
    return None


def _to_15m_bars(session: pd.DataFrame, bar_interval: str) -> pd.DataFrame:
    if session is None or session.empty:
        return session
    if (bar_interval or "5m") == "15m":
        return session
    try:
        o = _hist_series(session, "Open").astype(float)
        h = _hist_series(session, "High").astype(float)
        lo = _hist_series(session, "Low").astype(float)
        c = _hist_series(session, "Close").astype(float)
        v = _hist_series(session, "Volume").astype(float)
        df = pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": v}, index=session.index)
        agg = df.resample("15min").agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
        )
        return agg.dropna(how="all")
    except Exception:
        return session


def analyze_steady_grind(ctx: dict) -> dict:
    """
    Session structure metrics for slow grind-up pattern.

    Populates keys used by GRIND strategy: pct_vs_open, session_above_vwap,
    grind_hh_score, grind_max_bar_pct, grind_body_ratio, grind_smooth.
    """
    defaults = {
        "pct_vs_open": 0.0,
        "session_above_vwap": 0.0,
        "grind_hh_score": 0.0,
        "grind_higher_highs": False,
        "grind_max_bar_pct": 0.0,
        "grind_body_ratio": 0.0,
        "grind_smooth": False,
    }
    session = ctx.get("session")
    if session is None or getattr(session, "empty", True) or len(session) < 6:
        return defaults

    open_px = float(ctx.get("open_px") or 0.0)
    price = float(ctx.get("price") or 0.0)
    if open_px <= 0:
        return defaults
    pct_vs_open = round((price - open_px) / open_px * 100.0, 2)

    vwap_s = _compute_vwap(session)
    closes = _hist_series(session, "Close").astype(float)
    above = 0
    n = 0
    if vwap_s is not None and not vwap_s.empty:
        aligned = vwap_s.reindex(closes.index).ffill()
        for i in range(len(closes)):
            if i < len(aligned) and pd.notna(aligned.iloc[i]):
                n += 1
                if closes.iloc[i] >= float(aligned.iloc[i]) * 0.998:
                    above += 1
    session_above_vwap = round(above / n, 2) if n else 0.0

    bars_15 = _to_15m_bars(session, str(ctx.get("bar_interval") or "5m"))
    hh_score = 0.0
    if bars_15 is not None and len(bars_15) >= 3:
        highs = _hist_series(bars_15, "High").astype(float)
        ups = sum(1 for i in range(1, len(highs)) if highs.iloc[i] > highs.iloc[i - 1])
        hh_score = round(ups / max(len(highs) - 1, 1), 2)

    highs = _hist_series(session, "High").astype(float)
    lows = _hist_series(session, "Low").astype(float)
    opens = _hist_series(session, "Open").astype(float)
    max_bar = 0.0
    bodies: list[float] = []
    for i in range(1, len(closes)):
        prev = float(closes.iloc[i - 1])
        if prev > 0:
            max_bar = max(max_bar, abs((float(closes.iloc[i]) - prev) / prev * 100.0))
        rng = float(highs.iloc[i]) - float(lows.iloc[i])
        if rng > 0:
            bodies.append(abs(float(closes.iloc[i]) - float(opens.iloc[i])) / rng)
    max_bar = round(max_bar, 2)
    body_ratio = round(float(sum(bodies) / len(bodies)), 2) if bodies else 0.0
    grind_smooth = max_bar <= 2.8 and body_ratio >= 0.32

    return {
        "pct_vs_open": pct_vs_open,
        "session_above_vwap": session_above_vwap,
        "grind_hh_score": hh_score,
        "grind_higher_highs": hh_score >= 0.5,
        "grind_max_bar_pct": max_bar,
        "grind_body_ratio": body_ratio,
        "grind_smooth": grind_smooth,
    }


def enrich_ctx_for_grind(
    ctx: dict,
    raw_ticker: str,
    *,
    sector: str = "",
    industry: str = "",
    market: str = "NSE",
) -> tuple[str, str, Optional[str]]:
    """Attach sector theme + grind metrics to context. Returns (sector, industry, theme)."""
    sec = sector or ctx.get("sector_name") or ""
    ind = industry or ctx.get("industry") or ""
    theme = match_sector_theme(sec, ind, raw_ticker=raw_ticker, market=market)
    ctx["sector_name"] = sec
    ctx["industry"] = ind
    ctx["sector_theme"] = theme
    ctx.update(analyze_steady_grind(ctx))
    return sec, ind, theme
