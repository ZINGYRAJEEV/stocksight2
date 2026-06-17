"""
Screener.in fundamentals for Indian (NSE/BSE) names — quarterly P&L QoQ and top ratios.

Used where Yahoo Finance quarterly / ROCE data is unreliable for NSE listings.
"""

from __future__ import annotations

import html as html_lib
import re
import time
from typing import Optional

try:
    from .valuation_model import _parse_screener_number
except ImportError:
    from valuation_model import _parse_screener_number


def _clean_cell(text: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(text or "").replace("\xa0", " ")).strip()


def fetch_screener_company_html(display_ticker: str) -> str:
    try:
        from screener_buyback import SCREENER_BASE, _http_get, resolve_screener_company_id

        _, _, slug = resolve_screener_company_id(display_ticker)
        slug = slug or display_ticker.replace(".NS", "").replace(".BO", "")
        return _http_get(f"{SCREENER_BASE}/company/{slug}/consolidated/") or ""
    except Exception:
        return ""


def _parse_section_table(
    html: str,
    section_id: str,
) -> tuple[list[str], dict[str, list[Optional[float]]]]:
    """Parse first data-table in a Screener section — column labels + row values."""
    m = re.search(rf'id=["\']{re.escape(section_id)}["\'][^>]*>(.*?)</section>', html, re.S | re.I)
    if not m:
        return [], {}

    tables = re.findall(r"<table[^>]*>(.*?)</table>", m.group(1), re.S | re.I)
    if not tables:
        return [], {}

    rows: list[list[str]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tables[0], re.S | re.I):
        cells = [
            _clean_cell(re.sub(r"<[^>]+>", "", c))
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S | re.I)
        ]
        if cells:
            rows.append(cells)
    if len(rows) < 2:
        return [], {}

    headers = [_clean_cell(h) for h in rows[0][1:]]
    if not headers:
        return [], {}

    data: dict[str, list[Optional[float]]] = {}
    for cells in rows[1:]:
        label = _clean_cell(cells[0]).lower()
        if not label or label == "raw pdf":
            continue
        vals: list[Optional[float]] = []
        for v in cells[1 : 1 + len(headers)]:
            vals.append(_parse_screener_number(v))
        data[label] = vals

    return headers, data


def _row_values(data: dict[str, list[Optional[float]]], *needles: str) -> list[Optional[float]]:
    for key, vals in data.items():
        if any(n in key for n in needles):
            return vals
    return []


def _qoq_pct(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    if current is None or prior is None:
        return None
    try:
        p = float(prior)
        c = float(current)
    except (TypeError, ValueError):
        return None
    if abs(p) < 1.0:
        return None
    return round((c - p) / abs(p) * 100.0, 1)


def _latest_two_quarters(
    headers: list[str],
    sales: list[Optional[float]],
    profit: list[Optional[float]],
) -> tuple[str, str, Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Return (latest_label, prior_label, sales0, sales1, profit0, profit1)."""
    pairs: list[tuple[str, Optional[float], Optional[float]]] = []
    for hdr, s, p in zip(headers, sales, profit):
        if not hdr:
            continue
        if s is None and p is None:
            continue
        pairs.append((hdr, s, p))

    if len(pairs) < 2:
        return "", "", None, None, None, None

    (lbl0, s0, p0), (lbl1, s1, p1) = pairs[-2], pairs[-1]
    return lbl1, lbl0, s1, s0, p1, p0


def fetch_screener_quarterly_qoq(display_ticker: str, *, html: str = "") -> dict:
    """
    Latest vs prior quarter Sales+ and Net Profit+ from Screener.in (Rs Cr).

    Returns keys compatible with earnings_surprise_screener.extract_quarterly_qoq.
    """
    page = html or fetch_screener_company_html(display_ticker)
    if not page:
        return {}

    headers, data = _parse_section_table(page, "quarters")
    if not headers:
        return {}

    sales = _row_values(data, "sales+", "sales +", "revenue")
    profit = _row_values(data, "net profit", "pat", "profit after tax")
    if not sales or not profit:
        return {}

    latest_q, prior_q, s0, s1, p0, p1 = _latest_two_quarters(headers, sales, profit)
    if not latest_q or not prior_q:
        return {}

    return {
        "latest_q": latest_q,
        "prior_q": prior_q,
        "qoq_sales_pct": _qoq_pct(s0, s1),
        "qoq_profit_pct": _qoq_pct(p0, p1),
        "latest_revenue_cr": round(float(s0), 1) if s0 is not None else None,
        "latest_profit_cr": round(float(p0), 1) if p0 is not None else None,
        "source": "Screener.in quarterly (consolidated, Rs Cr)",
    }


def _parse_ratio_block(html: str, label: str) -> Optional[float]:
    m = re.search(rf'id=["\']top-ratios["\'][^>]*>(.*?)</section>', html, re.S | re.I)
    if not m:
        return None
    block = m.group(1)
    pat = (
        rf'<span class="name">\s*{re.escape(label)}\s*</span>'
        rf'.*?<span class="number">([\d.]+)</span>'
    )
    hit = re.search(pat, block, re.S | re.I)
    if not hit:
        return None
    try:
        return round(float(hit.group(1)), 2)
    except (TypeError, ValueError):
        return None


def fetch_screener_top_ratios(display_ticker: str, *, html: str = "") -> dict:
    """ROCE / ROE from Screener.in top-ratios panel (latest reported)."""
    page = html or fetch_screener_company_html(display_ticker)
    if not page:
        return {}

    roce = _parse_ratio_block(page, "ROCE")
    roe = _parse_ratio_block(page, "ROE")
    if roce is None and roe is None:
        return {}

    return {
        "roce_pct": roce,
        "roe_pct": roe,
        "source": "Screener.in top ratios",
    }


def enrich_fundamentals_from_screener(
    display_ticker: str,
    fund: dict,
    *,
    html: str = "",
    delay_sec: float = 0.0,
) -> dict:
    """Overlay ROCE/ROE (and optional YoY qtr proxies) from Screener for NSE names."""
    page = html or fetch_screener_company_html(display_ticker)
    if delay_sec > 0:
        time.sleep(delay_sec)

    ratios = fetch_screener_top_ratios(display_ticker, html=page)
    if not ratios:
        return fund

    out = dict(fund)
    roce = ratios.get("roce_pct")
    roe = ratios.get("roe_pct")
    if roce is not None:
        out["roce_pct"] = roce
        out["roce_is_roe_proxy"] = False
    elif roe is not None:
        out["roce_pct"] = roe
        out["roce_is_roe_proxy"] = True
    if roe is not None:
        out["roe_pct"] = roe
    out["screener_fundamentals_source"] = ratios.get("source", "")
    return out
