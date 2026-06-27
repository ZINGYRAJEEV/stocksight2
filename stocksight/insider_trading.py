"""
Insider trading tracker — SEC Edgar Form 4 (US) + Yahoo insider feed (NSE/US universe).

Educational transparency tool — not investment advice. Form 4 data is public SEC record;
illegal insider trading is separate from these legal disclosure filings.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests

try:
    from screener import get_stock_links, hist_series
except ImportError:
    from .screener import get_stock_links, hist_series

ET_TZ = ZoneInfo("America/New_York")

META = {
    "id": "insider_trading",
    "title": "Insider Trading Tracker",
    "emoji": "🕵️",
    "nav_title": "Insider Trading",
    "audience": (
        "Investors monitoring **legal** insider buys/sells — SEC Form 4 (US) and "
        "Yahoo insider history (NSE/US watchlists). Free public data, ranked by size."
    ),
    "purpose": (
        "Surfaces CEO/CFO transactions, cluster buying (3+ buyers in 48h), and "
        "high-conviction dollar flags — without paid terminal gatekeeping."
    ),
}

ProgressCb = Callable[[int, int, str], None]

_CIK_TICKER_CACHE: dict[str, str] = {}
_COMPANY_TICKERS_PATH = Path(__file__).resolve().parent / ".sec_company_tickers.json"
_COMPANY_TICKERS_TTL_SEC = 86400 * 7

CEO_CFO_PATTERNS = (
    r"\bceo\b",
    r"\bcfo\b",
    r"chief executive",
    r"chief financial",
    r"president",
    r"chairman",
    r"chair\b",
)

HIGH_VALUE_USD = 500_000
ALERT_VALUE_USD = 100_000


@dataclass
class InsiderTrade:
    ticker: str
    company: str
    insider_name: str
    role: str
    side: str  # Buy | Sell | Other
    shares: float
    price: float
    value_usd: float
    filing_date: str
    trade_date: str
    source: str  # SEC | Yahoo
    sec_url: str
    cluster_id: str = ""
    is_cluster: bool = False
    high_conviction: bool = False
    links: dict = field(default_factory=dict)
    raw_cik: str = ""


@dataclass
class InsiderScanStats:
    source: str
    filings_fetched: int = 0
    trades_parsed: int = 0
    parse_errors: int = 0
    cluster_count: int = 0
    buy_count: int = 0
    sell_count: int = 0
    scan_elapsed_sec: float = 0.0


def get_sec_user_agent() -> str:
    try:
        import streamlit as st

        sec = getattr(st, "secrets", None)
        if sec is not None:
            block = sec.get("sec", {})
            ua = (block.get("user_agent") or block.get("email") or "").strip()
            if ua:
                if "@" in ua and "StockSight" not in ua:
                    return f"StockSight {ua}"
                return ua
    except Exception:
        pass
    # SEC blocks noreply/github-style addresses; use a plain contact string.
    return "StockSight contact@stocksight.local"


def _sec_headers() -> dict[str, str]:
    return {"User-Agent": get_sec_user_agent()}


def _sec_get(url: str, *, params: Optional[dict] = None, timeout: int = 45) -> requests.Response:
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=_sec_headers(), timeout=timeout)
            if r.status_code == 403 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except Exception as exc:
            last_err = exc
            time.sleep(1.0)
    raise last_err or RuntimeError("SEC request failed")


def _load_company_tickers() -> dict[str, str]:
    """Map zero-padded CIK -> ticker symbol."""
    global _CIK_TICKER_CACHE
    if _CIK_TICKER_CACHE:
        return _CIK_TICKER_CACHE

    now = time.time()
    if _COMPANY_TICKERS_PATH.is_file():
        try:
            cached = json.loads(_COMPANY_TICKERS_PATH.read_text(encoding="utf-8"))
            if now - float(cached.get("_ts", 0)) < _COMPANY_TICKERS_TTL_SEC:
                _CIK_TICKER_CACHE = {str(k).zfill(10): v for k, v in cached.get("map", {}).items()}
                return _CIK_TICKER_CACHE
        except Exception:
            pass

    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": get_sec_user_agent()},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        mapping: dict[str, str] = {}
        for _idx, row in data.items():
            cik = str(row.get("cik_str", "")).zfill(10)
            ticker = str(row.get("ticker", "")).upper()
            if cik and ticker:
                mapping[cik] = ticker
        _CIK_TICKER_CACHE = mapping
        _COMPANY_TICKERS_PATH.write_text(
            json.dumps({"_ts": now, "map": mapping}, indent=0),
            encoding="utf-8",
        )
    except Exception:
        _CIK_TICKER_CACHE = {}
    return _CIK_TICKER_CACHE


def _issuer_cik_from_hit(src: dict[str, Any]) -> str:
    ciks = src.get("ciks") or []
    if len(ciks) >= 2:
        return str(ciks[1]).zfill(10)
    if ciks:
        return str(ciks[0]).zfill(10)
    return ""


def _issuer_name_from_hit(src: dict[str, Any]) -> str:
    names = src.get("display_names") or []
    if len(names) >= 2:
        return re.sub(r"\s*\(CIK.*", "", names[1]).strip()
    if names:
        return re.sub(r"\s*\(CIK.*", "", names[0]).strip()
    return "—"


def _insider_name_from_hit(src: dict[str, Any]) -> str:
    names = src.get("display_names") or []
    if names:
        return re.sub(r"\s*\(CIK.*", "", names[0]).strip()
    return "—"


def fetch_form4_hits(*, days: int = 7, max_hits: int = 100) -> list[dict[str, Any]]:
    end = datetime.now(tz=ET_TZ).strftime("%Y-%m-%d")
    start = (datetime.now(tz=ET_TZ) - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    r = _sec_get(
        "https://efts.sec.gov/LATEST/search-index",
        params={
            "q": "",
            "forms": "4",
            "dateRange": "custom",
            "startdt": start,
            "enddt": end,
        },
    )
    hits = r.json().get("hits", {}).get("hits", [])
    return [h.get("_source", {}) for h in hits[:max_hits] if h.get("_source")]


def _strip_xml_ns(root: ET.Element) -> None:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _parse_form4_xml(
    content: bytes,
    *,
    hit: dict[str, Any],
    ticker: str,
    company: str,
) -> list[InsiderTrade]:
    trades: list[InsiderTrade] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return trades
    _strip_xml_ns(root)

    insider_name = ""
    role = ""
    owner = root.find(".//reportingOwner")
    if owner is not None:
        name_el = owner.find(".//rptOwnerName")
        if name_el is not None and name_el.text:
            insider_name = name_el.text.strip()
        for tag, label in (
            ("officerTitle", None),
            ("director", "Director"),
            ("isTenPercentOwner", "10% Owner"),
        ):
            el = owner.find(f".//{tag}")
            if el is not None:
                role = (el.text or label or tag).strip() if el.text or label else tag
                break
    if not insider_name:
        insider_name = _insider_name_from_hit(hit)

    filing_date = str(hit.get("file_date") or "")
    adsh = str(hit.get("adsh") or "")
    issuer_cik = _issuer_cik_from_hit(hit)
    cik_path = issuer_cik.lstrip("0") or issuer_cik
    ac = adsh.replace("-", "")
    sec_url = f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{ac}/"

    for tx in root.findall(".//nonDerivativeTransaction"):
        code_el = tx.find(".//transactionAcquiredDisposedCode/value")
        sh_el = tx.find(".//transactionShares/value")
        pr_el = tx.find(".//transactionPricePerShare/value")
        dt_el = tx.find(".//transactionDate/value")
        code = (code_el.text or "").strip().upper() if code_el is not None else ""
        try:
            shares = float(sh_el.text) if sh_el is not None and sh_el.text else 0.0
        except (TypeError, ValueError):
            shares = 0.0
        try:
            price = float(pr_el.text) if pr_el is not None and pr_el.text else 0.0
        except (TypeError, ValueError):
            price = 0.0
        value = round(shares * price, 2)
        side = "Buy" if code == "A" else ("Sell" if code == "D" else "Other")
        trade_date = (dt_el.text or filing_date) if dt_el is not None else filing_date
        if shares <= 0 and value <= 0:
            continue
        raw = f"{ticker}" if ticker else company[:12]
        yahoo_sym = raw if "." in raw else raw
        trades.append(
            InsiderTrade(
                ticker=ticker or raw,
                company=company,
                insider_name=insider_name,
                role=role or "—",
                side=side,
                shares=shares,
                price=round(price, 4),
                value_usd=value,
                filing_date=filing_date,
                trade_date=str(trade_date)[:10],
                source="SEC Form 4",
                sec_url=sec_url,
                high_conviction=value >= HIGH_VALUE_USD,
                links=get_stock_links(yahoo_sym) if ticker else {},
                raw_cik=issuer_cik,
            )
        )
    return trades


def parse_form4_hit(hit: dict[str, Any], *, ticker_map: Optional[dict[str, str]] = None) -> list[InsiderTrade]:
    ticker_map = ticker_map or _load_company_tickers()
    issuer_cik = _issuer_cik_from_hit(hit)
    ticker = ticker_map.get(issuer_cik, "")
    company = _issuer_name_from_hit(hit)
    adsh = str(hit.get("adsh") or "")
    if not adsh or not issuer_cik:
        return []

    cik_path = issuer_cik.lstrip("0") or issuer_cik
    ac = adsh.replace("-", "")
    idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{ac}/index.json"
    try:
        ir = requests.get(idx_url, headers={"User-Agent": get_sec_user_agent()}, timeout=25)
        if not ir.ok:
            return []
        items = ir.json().get("directory", {}).get("item", [])
        xml_name = next(
            (x["name"] for x in items if str(x.get("name", "")).endswith(".xml")),
            None,
        )
        if not xml_name:
            return []
        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{ac}/{xml_name}"
        dr = requests.get(doc_url, headers={"User-Agent": get_sec_user_agent()}, timeout=25)
        if not dr.ok:
            return []
        return _parse_form4_xml(dr.content, hit=hit, ticker=ticker, company=company)
    except Exception:
        return []


def is_ceo_cfo_role(role: str) -> bool:
    blob = (role or "").lower()
    return any(re.search(p, blob) for p in CEO_CFO_PATTERNS)


def apply_cluster_flags(trades: list[InsiderTrade], *, window_hours: int = 48) -> list[InsiderTrade]:
    """Mark cluster buying: 3+ distinct insiders buying same issuer within window."""
    buys = [t for t in trades if t.side == "Buy" and t.raw_cik]
    by_cik: dict[str, list[InsiderTrade]] = {}
    for t in buys:
        by_cik.setdefault(t.raw_cik, []).append(t)

    for cik, group in by_cik.items():
        group.sort(key=lambda x: x.trade_date or x.filing_date)
        for i, t in enumerate(group):
            window_start = _parse_date(t.trade_date or t.filing_date)
            if not window_start:
                continue
            insiders: set[str] = set()
            for u in group:
                ud = _parse_date(u.trade_date or u.filing_date)
                if not ud:
                    continue
                if abs((ud - window_start).total_seconds()) <= window_hours * 3600:
                    insiders.add(u.insider_name.lower())
            if len(insiders) >= 3:
                cid = f"cluster-{cik}-{t.trade_date}"
                for u in group:
                    ud = _parse_date(u.trade_date or u.filing_date)
                    if ud and abs((ud - window_start).total_seconds()) <= window_hours * 3600:
                        u.is_cluster = True
                        u.cluster_id = cid
    return trades


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def scan_sec_form4(
    *,
    days: int = 7,
    max_filings: int = 80,
    min_value_usd: float = 0.0,
    ceo_cfo_only: bool = False,
    buys_only: bool = False,
    progress_cb: Optional[ProgressCb] = None,
) -> tuple[list[InsiderTrade], InsiderScanStats]:
    t0 = time.time()
    stats = InsiderScanStats(source="SEC Form 4")
    hits = fetch_form4_hits(days=days, max_hits=max_filings)
    stats.filings_fetched = len(hits)
    ticker_map = _load_company_tickers()
    all_trades: list[InsiderTrade] = []
    total = len(hits)

    for i, hit in enumerate(hits, start=1):
        sym = ticker_map.get(_issuer_cik_from_hit(hit), _issuer_name_from_hit(hit)[:12])
        if progress_cb:
            progress_cb(i, total, sym)
        parsed = parse_form4_hit(hit, ticker_map=ticker_map)
        if not parsed:
            stats.parse_errors += 1
        else:
            all_trades.extend(parsed)
        time.sleep(0.12)  # SEC fair-access pacing

    all_trades = apply_cluster_flags(all_trades)
    filtered: list[InsiderTrade] = []
    for t in all_trades:
        if t.value_usd < min_value_usd:
            continue
        if ceo_cfo_only and not is_ceo_cfo_role(t.role):
            continue
        if buys_only and t.side != "Buy":
            continue
        filtered.append(t)
        if t.side == "Buy":
            stats.buy_count += 1
        elif t.side == "Sell":
            stats.sell_count += 1

    stats.trades_parsed = len(filtered)
    stats.cluster_count = len({t.cluster_id for t in filtered if t.is_cluster})
    filtered.sort(key=lambda x: (-x.value_usd, x.filing_date))
    stats.scan_elapsed_sec = round(time.time() - t0, 1)
    return filtered, stats


def scan_yahoo_insider_universe(
    tickers: list[str],
    *,
    days: int = 90,
    min_value_usd: float = 50_000,
    progress_cb: Optional[ProgressCb] = None,
) -> tuple[list[InsiderTrade], InsiderScanStats]:
    """Universe scan via Yahoo insider_transactions (NSE + US)."""
    import yfinance as yf

    t0 = time.time()
    stats = InsiderScanStats(source="Yahoo insider")
    cutoff = datetime.now() - timedelta(days=days)
    results: list[InsiderTrade] = []
    total = len(tickers)

    for i, raw in enumerate(tickers, start=1):
        raw = (raw or "").strip()
        if progress_cb:
            progress_cb(i, total, raw.replace(".NS", "").replace(".BO", ""))
        try:
            df = yf.Ticker(raw).insider_transactions
            if df is None or df.empty:
                continue
            disp = raw.replace(".NS", "").replace(".BO", "")
            for _, row in df.iterrows():
                dt_s = str(row.get("Start Date") or row.get("startDate") or "")[:10]
                td = _parse_date(dt_s)
                if td and td < cutoff:
                    continue
                shares = float(row.get("Shares") or 0)
                value = row.get("Value")
                try:
                    value_f = float(value) if value is not None and str(value) != "nan" else 0.0
                except (TypeError, ValueError):
                    value_f = 0.0
                own = str(row.get("Ownership") or row.get("Transaction") or "").upper()
                text = str(row.get("Text") or "")
                if "purchase" in text.lower() or "buy" in text.lower() or own == "P":
                    side = "Buy"
                elif "sale" in text.lower() or "sell" in text.lower() or own == "D":
                    side = "Sell"
                else:
                    side = "Other"
                if value_f < min_value_usd and shares <= 0:
                    continue
                price = round(value_f / shares, 4) if shares > 0 and value_f > 0 else 0.0
                role = str(row.get("Position") or "—")
                results.append(
                    InsiderTrade(
                        ticker=disp,
                        company=disp,
                        insider_name=str(row.get("Insider") or "—"),
                        role=role,
                        side=side,
                        shares=shares,
                        price=price,
                        value_usd=round(value_f, 2),
                        filing_date=dt_s,
                        trade_date=dt_s,
                        source="Yahoo",
                        sec_url="",
                        high_conviction=value_f >= HIGH_VALUE_USD,
                        links=get_stock_links(raw),
                    )
                )
        except Exception:
            stats.parse_errors += 1
        time.sleep(0.08)

    results.sort(key=lambda x: -x.value_usd)
    stats.trades_parsed = len(results)
    stats.buy_count = sum(1 for t in results if t.side == "Buy")
    stats.sell_count = sum(1 for t in results if t.side == "Sell")
    stats.scan_elapsed_sec = round(time.time() - t0, 1)
    return results, stats


def market_intelligence_summary(trades: list[InsiderTrade]) -> dict[str, Any]:
    if not trades:
        return {
            "total_trades": 0,
            "buy_value": 0.0,
            "sell_value": 0.0,
            "net_sentiment": "Neutral",
            "clusters": 0,
            "high_conviction": 0,
            "ceo_cfo_buys": 0,
            "alert_count": 0,
        }
    buys = [t for t in trades if t.side == "Buy"]
    sells = [t for t in trades if t.side == "Sell"]
    buy_val = sum(t.value_usd for t in buys)
    sell_val = sum(t.value_usd for t in sells)
    if buy_val > sell_val * 1.5:
        sentiment = "Bullish insider flow"
    elif sell_val > buy_val * 1.5:
        sentiment = "Bearish insider flow"
    else:
        sentiment = "Mixed / neutral"
    return {
        "total_trades": len(trades),
        "buy_value": round(buy_val, 0),
        "sell_value": round(sell_val, 0),
        "net_sentiment": sentiment,
        "clusters": len({t.cluster_id for t in trades if t.is_cluster}),
        "high_conviction": sum(1 for t in trades if t.high_conviction),
        "ceo_cfo_buys": sum(1 for t in buys if is_ceo_cfo_role(t.role)),
        "alert_count": sum(1 for t in trades if t.value_usd >= ALERT_VALUE_USD),
    }


def trades_to_dataframe(trades: list[InsiderTrade]) -> pd.DataFrame:
    rows = []
    for i, t in enumerate(trades, start=1):
        rows.append(
            {
                "Rank": i,
                "Ticker": t.ticker,
                "Company": t.company,
                "Insider": t.insider_name,
                "Role": t.role,
                "Side": t.side,
                "Value ($)": t.value_usd,
                "Shares": t.shares,
                "Price": t.price,
                "Trade date": t.trade_date,
                "Filed": t.filing_date,
                "Cluster": "🔥 Yes" if t.is_cluster else "—",
                "Source": t.source,
                "SEC ↗": t.sec_url if t.sec_url else "—",
                **{k: v for k, v in t.links.items()},
            }
        )
    return pd.DataFrame(rows)
