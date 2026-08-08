"""
Screener.in fundamentals for Indian (NSE/BSE) names — quarterly P&L QoQ and top ratios.

Used where Yahoo Finance quarterly / ROCE data is unreliable for NSE listings.
"""

from __future__ import annotations

import html as html_lib
import re
import time
from datetime import date, datetime, timedelta
from typing import Optional

try:
    from .valuation_model import _parse_screener_number
except ImportError:
    from valuation_model import _parse_screener_number

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


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


def parse_quarter_label_date(label: str) -> Optional[date]:
    """Convert Screener quarter header like 'Jun 2025' to quarter-end date."""
    if not label:
        return None
    m = re.search(r"([A-Za-z]{3,9})\s*(20\d{2})", label.strip())
    if not m:
        return None
    mon = _MONTH_MAP.get(m.group(1).lower()[:3])
    if not mon:
        return None
    year = int(m.group(2))
    if mon == 12:
        return date(year, 12, 31)
    nxt = date(year, mon + 1, 1)
    return nxt - timedelta(days=1)


def estimate_results_announcement_date(quarter_end: date, *, lag_days: int = 45) -> date:
    """Proxy announcement date when exact filing date is unknown."""
    return quarter_end + timedelta(days=lag_days)


def fetch_screener_quarterly_series(display_ticker: str, *, html: str = "") -> list[dict]:
    """
    Quarterly Sales+ / Net Profit+ series from Screener #quarters (oldest → newest).

    Each item: {label, sales_cr, profit_cr, quarter_end, est_announce_date}.
    """
    page = html or fetch_screener_company_html(display_ticker)
    if not page:
        return []

    headers, data = _parse_section_table(page, "quarters")
    if not headers:
        return []

    sales = _row_values(data, "sales+", "sales +", "revenue")
    profit = _row_values(data, "net profit", "pat", "profit after tax")
    if not sales or not profit:
        return []

    out: list[dict] = []
    for hdr, s, p in zip(headers, sales, profit):
        if not hdr or (s is None and p is None):
            continue
        q_end = parse_quarter_label_date(hdr)
        out.append({
            "label": hdr,
            "sales_cr": s,
            "profit_cr": p,
            "quarter_end": q_end,
            "est_announce_date": estimate_results_announcement_date(q_end) if q_end else None,
        })
    return out


def fetch_screener_results_latest(*, max_rows: int = 200) -> list[dict]:
    """
    Recent quarterly result reporters from Screener.in /results/latest/.

    Returns [{symbol, company, slug, url}, ...].
    """
    try:
        from screener_buyback import SCREENER_BASE, _http_get
    except ImportError:
        return []

    html = _http_get(f"{SCREENER_BASE}/results/latest/") or ""
    if not html:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(
        r'href="(/company/([^/]+)/[^"]*)"[^>]*>\s*([^<]+?)\s*</a>',
        html,
        re.I,
    ):
        slug = m.group(2).strip().lower()
        if slug in seen:
            continue
        seen.add(slug)
        company = _clean_cell(m.group(3))
        symbol = slug.upper()
        out.append({
            "symbol": symbol,
            "company": company,
            "slug": slug,
            "url": f"{SCREENER_BASE}{m.group(1)}",
        })
        if len(out) >= max_rows:
            break
    return out


def _parse_ratio_block(html: str, label: str) -> Optional[float]:
    """Parse a top-ratios label; supports negatives and % values."""
    m = re.search(rf'id=["\']top-ratios["\'][^>]*>(.*?)</section>', html, re.S | re.I)
    if not m:
        return None
    block = m.group(1)
    hit = re.search(
        rf'<span class="name">\s*{re.escape(label)}\s*</span>(.*?)'
        rf'(?:<span class="name">|</ul>|</div>\s*</li>|</section>)',
        block,
        re.S | re.I,
    )
    chunk = hit.group(1) if hit else ""
    if not chunk:
        # Legacy: number span only (no negatives)
        pat = (
            rf'<span class="name">\s*{re.escape(label)}\s*</span>'
            rf'.*?<span class="number">(-?[\d,.]+)\s*%?</span>'
        )
        legacy = re.search(pat, block, re.S | re.I)
        if not legacy:
            return None
        return _parse_screener_number(legacy.group(1))

    num = re.search(r'<span class="number"[^>]*>(.*?)</span>', chunk, re.S | re.I)
    if num:
        parsed = _parse_screener_number(num.group(1))
        if parsed is not None:
            return round(float(parsed), 2)
    val = re.search(r'<span class="nowrap value"[^>]*>(.*?)</span>', chunk, re.S | re.I)
    if val:
        text = _clean_cell(re.sub(r"<[^>]+>", " ", val.group(1)))
        parsed = _parse_screener_number(text)
        if parsed is not None:
            return round(float(parsed), 2)
    return None


def _parse_top_ratio_text(html: str, label: str) -> str:
    """Raw text block after a top-ratio label (price, mcap units, etc.)."""
    m = re.search(rf'id=["\']top-ratios["\'][^>]*>(.*?)</section>', html, re.S | re.I)
    if not m:
        return ""
    pat = (
        rf'<span class="name">\s*{re.escape(label)}\s*</span>'
        rf'.*?<span class="nowrap value">(.*?)</span>'
    )
    hit = re.search(pat, m.group(1), re.S | re.I)
    if not hit:
        return ""
    return _clean_cell(re.sub(r"<[^>]+>", " ", hit.group(1)))


def _parse_market_cap_cr(html: str) -> Optional[float]:
    raw = _parse_top_ratio_text(html, "Market Cap")
    if not raw:
        val = _parse_ratio_block(html, "Market Cap")
        return round(val, 1) if val is not None else None
    num = _parse_screener_number(raw)
    if num is None:
        return None
    low = raw.lower()
    if "lakh" in low and "cr" in low:
        return round(float(num) * 100_000.0, 1)
    if "cr" in low:
        return round(float(num), 1)
    return round(float(num), 1)


def _parse_compounded_table(html: str, title: str) -> dict[str, Optional[float]]:
    """Parse Screener ranges-table blocks like Compounded Profit Growth."""
    out: dict[str, Optional[float]] = {}
    for table_html in re.findall(r'<table class="ranges-table">(.*?)</table>', html, re.S | re.I):
        if title.lower() not in table_html.lower():
            continue
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S | re.I):
            cells = [
                _clean_cell(re.sub(r"<[^>]+>", "", c))
                for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S | re.I)
            ]
            if len(cells) < 2:
                continue
            label = cells[0].rstrip(":").strip().lower()
            val = _parse_screener_number(cells[1])
            if "10 year" in label:
                out["y10"] = val
            elif "5 year" in label:
                out["y5"] = val
            elif "3 year" in label:
                out["y3"] = val
            elif label == "ttm":
                out["ttm"] = val
        break
    return out


def _parse_trailing_eps(html: str) -> tuple[Optional[float], Optional[int]]:
    """Latest Mar FY EPS in Rs from consolidated P&L."""
    series = _parse_eps_history(html)
    if not series:
        return None, None
    fy, _lbl, eps = series[-1]
    return eps, fy


def _parse_eps_history(html: str) -> list[tuple[int, str, float]]:
    """Mar FY EPS in Rs from consolidated P&L — oldest to newest."""
    headers, data = _parse_section_table(html, "profit-loss")
    eps_vals = _row_values(data, "eps in rs", "eps")
    if not eps_vals or not headers:
        return []
    out: list[tuple[int, str, float]] = []
    for hdr, val in zip(headers, eps_vals):
        if val is None or float(val) <= 0:
            continue
        year = None
        m = re.search(r"(20\d{2})", hdr or "")
        if m:
            year = int(m.group(1))
        if year is None:
            continue
        out.append((year, (hdr or str(year)).strip(), round(float(val), 2)))
    out.sort(key=lambda x: x[0])
    return out


def fetch_screener_eps_history(display_ticker: str, *, html: str = "") -> list[tuple[int, str, float]]:
    """[(fy_year, header_label, eps_rs), ...] from Screener.in consolidated P&L."""
    page = html or fetch_screener_company_html(display_ticker)
    if not page:
        return []
    return _parse_eps_history(page)


def fetch_screener_value_profile(display_ticker: str, *, html: str = "") -> dict:
    """
    Value / GARP fields from Screener.in consolidated page:
    P/E, price, trailing EPS, compounded profit growth (3Y/5Y/TTM), ROCE/ROE.
    """
    page = html or fetch_screener_company_html(display_ticker)
    if not page:
        return {}

    pe = _parse_ratio_block(page, "Stock P/E")
    price = _parse_ratio_block(page, "Current Price")
    mcap_cr = _parse_market_cap_cr(page)
    eps, eps_year = _parse_trailing_eps(page)
    profit_g = _parse_compounded_table(page, "Compounded Profit Growth")
    sales_g = _parse_compounded_table(page, "Compounded Sales Growth")
    roce = _parse_ratio_block(page, "ROCE")
    roe = _parse_ratio_block(page, "ROE")

    slug = display_ticker.replace(".NS", "").replace(".BO", "").strip().lower()
    return {
        "pe": pe,
        "price": price,
        "market_cap_cr": mcap_cr,
        "trailing_eps": eps,
        "eps_fy": eps_year,
        "profit_growth_3y_pct": profit_g.get("y3"),
        "profit_growth_5y_pct": profit_g.get("y5"),
        "profit_growth_ttm_pct": profit_g.get("ttm"),
        "sales_growth_3y_pct": sales_g.get("y3"),
        "sales_growth_ttm_pct": sales_g.get("ttm"),
        "roce_pct": roce,
        "roe_pct": roe,
        "screener_url": f"https://www.screener.in/company/{slug}/consolidated/",
        "source": "Screener.in consolidated",
    }


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


def _last_non_null(vals: list[Optional[float]]) -> Optional[float]:
    for v in reversed(vals or []):
        if v is not None:
            try:
                return round(float(v), 2)
            except (TypeError, ValueError):
                continue
    return None


def _parse_shareholding_governance(html: str) -> dict[str, Optional[float]]:
    """Promoter holding / pledge / QoQ change from Screener shareholding section."""
    out: dict[str, Optional[float]] = {
        "promoter_holding_pct": None,
        "promoter_change_pct": None,
        "pledged_pct": None,
    }
    headers, data = _parse_section_table(html, "shareholding")
    if not data:
        return out

    promoter_vals: list[Optional[float]] = []
    pledged_vals: list[Optional[float]] = []
    for key, vals in data.items():
        k = (key or "").lower()
        if "pledge" in k:
            pledged_vals = vals
        elif "promoter" in k and "non" not in k:
            promoter_vals = vals

    out["promoter_holding_pct"] = _last_non_null(promoter_vals)
    out["pledged_pct"] = _last_non_null(pledged_vals)
    # Change = latest − prior reported column
    cleaned = [v for v in promoter_vals if v is not None]
    if len(cleaned) >= 2:
        try:
            out["promoter_change_pct"] = round(float(cleaned[-1]) - float(cleaned[-2]), 2)
        except (TypeError, ValueError):
            pass
    return out


def _parse_latest_opm_pct(html: str) -> Optional[float]:
    headers, data = _parse_section_table(html, "profit-loss")
    if not data:
        return None
    vals = _row_values(data, "opm %", "operating profit margin")
    return _last_non_null(vals)


def _parse_interest_coverage_from_pl(html: str) -> Optional[float]:
    """Operating Profit / Interest from Screener P&L (latest column)."""
    headers, data = _parse_section_table(html, "profit-loss")
    if not data:
        return None
    op = _last_non_null(_row_values(data, "operating profit"))
    interest = _last_non_null(_row_values(data, "interest"))
    if op is None or interest is None:
        return None
    try:
        if abs(float(interest)) < 0.01:
            return 99.0 if float(op) > 0 else None
        return round(float(op) / abs(float(interest)), 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None



def _yoy_quarterly_growth(html: str) -> dict[str, Optional[float]]:
    """YoY growth: latest quarter vs same quarter ~1 year earlier (4 steps back)."""
    headers, data = _parse_section_table(html, "quarters")
    if not headers:
        return {"yoy_sales_pct": None, "yoy_profit_pct": None}
    sales = _row_values(data, "sales+", "sales +", "revenue")
    profit = _row_values(data, "net profit", "pat", "profit after tax")
    pairs: list[tuple[Optional[float], Optional[float]]] = []
    for s, p in zip(sales, profit):
        if s is None and p is None:
            continue
        pairs.append((s, p))
    if len(pairs) < 5:
        return {"yoy_sales_pct": None, "yoy_profit_pct": None}
    s_now, p_now = pairs[-1]
    s_yoy, p_yoy = pairs[-5]
    return {
        "yoy_sales_pct": _qoq_pct(s_now, s_yoy),
        "yoy_profit_pct": _qoq_pct(p_now, p_yoy),
    }


def fetch_screener_fundamental_profile(display_ticker: str, *, html: str = "") -> dict:
    """
    Fields for the 3-tier Fundamental Screener Framework.

    Prefer Screener.in top-ratios / tables; leave None when absent so callers
    can hard-fail governance gates or soft-skip valuation checks.
    """
    page = html or fetch_screener_company_html(display_ticker)
    if not page:
        return {}

    base = fetch_screener_value_profile(display_ticker, html=page)
    if not base:
        base = {}

    # Debt / liquidity / valuation — try several Screener label variants
    debt_eq = (
        _parse_ratio_block(page, "Debt to equity")
        or _parse_ratio_block(page, "Debt to Equity")
    )
    current_ratio = _parse_ratio_block(page, "Current ratio") or _parse_ratio_block(
        page, "Current Ratio"
    )
    interest_cov = (
        _parse_ratio_block(page, "Interest Coverage Ratio")
        or _parse_ratio_block(page, "Interest Coverage")
        or _parse_interest_coverage_from_pl(page)
    )
    roa = _parse_ratio_block(page, "ROA") or _parse_ratio_block(page, "Return on assets")
    industry_pe = _parse_ratio_block(page, "Industry PE") or _parse_ratio_block(
        page, "Industry P/E"
    )
    peg = _parse_ratio_block(page, "PEG Ratio") or _parse_ratio_block(page, "PEG")
    pb = (
        _parse_ratio_block(page, "Price to book value")
        or _parse_ratio_block(page, "Price to Book value")
        or _parse_ratio_block(page, "Book Value")
    )
    # Book Value on Screener is often ₹/share — Price to book is separate
    if pb is not None and pb > 50:
        # Likely book value per share, not P/B — drop and recompute later from Yahoo
        pb = None

    promoter_top = _parse_ratio_block(page, "Promoter holding")
    pledged_top = _parse_ratio_block(page, "Pledged percentage") or _parse_ratio_block(
        page, "Promoter pledging"
    )

    sh = _parse_shareholding_governance(page)
    promoter = promoter_top if promoter_top is not None else sh.get("promoter_holding_pct")
    pledged = pledged_top if pledged_top is not None else sh.get("pledged_pct")
    promoter_chg = sh.get("promoter_change_pct")

    roe_tbl = _parse_compounded_table(page, "Return on Equity")
    avg_roe_3y = roe_tbl.get("y3")

    opm = _parse_latest_opm_pct(page)
    yoy = _yoy_quarterly_growth(page)

    # PEG proxy when Screener PEG missing
    if peg is None:
        pe = base.get("pe")
        g = base.get("profit_growth_3y_pct") or base.get("profit_growth_ttm_pct")
        if pe is not None and g is not None and float(g) > 0:
            peg = round(float(pe) / float(g), 2)

    slug = display_ticker.replace(".NS", "").replace(".BO", "").strip().lower()
    out = dict(base)
    out.update(
        {
            "debt_equity": debt_eq,
            "current_ratio": current_ratio,
            "interest_coverage": interest_cov,
            "roa_pct": roa,
            "industry_pe": industry_pe,
            "peg": peg,
            "price_to_book": pb,
            "promoter_holding_pct": promoter,
            "promoter_change_pct": promoter_chg,
            "pledged_pct": pledged,
            "avg_roe_3y_pct": avg_roe_3y,
            "opm_pct": opm,
            "yoy_sales_pct": yoy.get("yoy_sales_pct"),
            "yoy_profit_pct": yoy.get("yoy_profit_pct"),
            "screener_url": f"https://www.screener.in/company/{slug}/consolidated/",
            "source": "Screener.in fundamental profile",
        }
    )
    return out
