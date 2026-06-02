"""
Intraday trading autopilot — scheduled phases, unified scoring, paper/live execution.

Default: PAPER + dry-run safe. Live Breeze orders require explicit env + kill-switch off.

Schedule aligns with CEST/IST routine (NSE) and ET (US) in user playbook.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from intraday import (
    STRATEGIES,
    STRATEGY_LABEL,
    GapResult,
    IntradayFilters,
    IntradayResult,
    compute_intraday_quality_gate,
    compute_market_mood,
    market_session_window,
    resolve_universe,
    scan_gaps,
    scan_intraday,
    compute_market_mood as _compute_mood_from_gaps,
)
from intraday_autopilot_store import append_log, load_state, save_state


@dataclass
class AutopilotConfig:
    """Runtime limits — conservative defaults."""
    mode: str = "paper"  # paper | live | dry_run
    markets: tuple[str, ...] = ("NSE", "US")
    universe_nse: str = "Nifty 50 (fast)"
    universe_us: str = "Liquid US shortlist (~35)"
    max_intraday_tickers: int = 60
    max_open_positions: int = 3
    max_trades_per_market_per_day: int = 5
    max_daily_loss_pct: float = 2.0
    min_gate_score: int = 58
    risk_pct_per_trade: float = 1.0
    gap_min_pct: float = 0.5
    priority_watchlist_size: int = 5
    min_rr: float = 1.2
    live_orders_enabled: bool = False


@dataclass
class PhaseSpec:
    id: str
    label: str
    start_mins: int
    end_mins: int
    strategies: tuple[str, ...]
    allow_new_entries: bool = True
    manage_only: bool = False
    force_square_off: bool = False
    run_eod_report: bool = False


# NSE schedule (IST, minutes from midnight)
NSE_PHASES: list[PhaseSpec] = [
    PhaseSpec("pre_open", "Market context", 8 * 60, 9 * 60 + 15, (), allow_new_entries=False),
    PhaseSpec("gap_scan", "Gap scanner", 9 * 60 + 15, 9 * 60 + 20, ("GAP",), allow_new_entries=False),
    PhaseSpec("mood_shortlist", "Mood + shortlist", 9 * 60 + 20, 9 * 60 + 30, ("GAP",), allow_new_entries=False),
    PhaseSpec("opening", "Opening drive", 9 * 60 + 30, 9 * 60 + 45, ("GAP", "MOMENTUM", "BROAD")),
    PhaseSpec("orb", "ORB window", 9 * 60 + 45, 10 * 60 + 15, ("ORB", "MOMENTUM")),
    PhaseSpec("trend_ath", "Trend & ATH", 10 * 60, 12 * 60 + 30, ("MOMENTUM", "ATH", "BROAD")),
    PhaseSpec("vwap", "VWAP pullback", 10 * 60 + 30, 13 * 60, ("VWAP",)),
    PhaseSpec("lunch", "Lunch manage-only", 12 * 60 + 30, 14 * 60, (), allow_new_entries=False, manage_only=True),
    PhaseSpec("afternoon", "Afternoon momentum", 14 * 60 + 30, 15 * 60 + 15, ("MOMENTUM", "BROAD")),
    PhaseSpec("square_off", "Square-off", 15 * 60 + 15, 15 * 60 + 25, (), allow_new_entries=False, force_square_off=True),
    PhaseSpec("eod", "EOD report", 15 * 60 + 30, 16 * 60, (), allow_new_entries=False, run_eod_report=True),
]

# US schedule (ET, minutes from midnight)
US_PHASES: list[PhaseSpec] = [
    PhaseSpec("pre_open", "Pre-market context", 7 * 60, 9 * 60 + 30, (), allow_new_entries=False),
    PhaseSpec("gap_scan", "Premarket gaps", 9 * 60 + 30, 9 * 60 + 45, ("GAP",), allow_new_entries=False),
    PhaseSpec("opening", "US open", 9 * 60 + 30, 9 * 60 + 45, ("GAP", "MOMENTUM", "BROAD")),
    PhaseSpec("orb", "ORB window", 9 * 60 + 45, 10 * 60 + 15, ("ORB", "MOMENTUM")),
    PhaseSpec("trend_ath", "Trend & ATH", 10 * 60, 13 * 60 + 30, ("MOMENTUM", "ATH", "BROAD")),
    PhaseSpec("vwap", "VWAP pullback", 11 * 60, 13 * 60 + 30, ("VWAP",)),
    PhaseSpec("lunch", "Mid-day chop", 13 * 60 + 30, 15 * 60, (), allow_new_entries=False, manage_only=True),
    PhaseSpec("afternoon", "Power hour", 15 * 60, 15 * 60 + 55, ("MOMENTUM", "BROAD")),
    PhaseSpec("square_off", "Square-off", 15 * 60 + 55, 16 * 60, (), allow_new_entries=False, force_square_off=True),
    PhaseSpec("eod", "EOD report", 16 * 60, 17 * 60, (), allow_new_entries=False, run_eod_report=True),
]


def _market_now_mins(market: str) -> int:
    from intraday import US_TZ, NSE_TZ, _now_tz

    tz = US_TZ if market.upper() == "US" else NSE_TZ
    now = _now_tz(tz)
    return now.hour * 60 + now.minute


def resolve_phase(market: str, phase_id: Optional[str] = None) -> PhaseSpec:
    phases = US_PHASES if market.upper() == "US" else NSE_PHASES
    if phase_id:
        for p in phases:
            if p.id == phase_id:
                return p
        return phases[0]
    mins = _market_now_mins(market)
    matched = [p for p in phases if p.start_mins <= mins < p.end_mins]
    if not matched:
        sess = market_session_window(market)
        if not sess.get("is_open"):
            return phases[-1] if phases[-1].id == "eod" else PhaseSpec(
                "closed", "Market closed", 0, 0, (), allow_new_entries=False,
            )
        return PhaseSpec("off_schedule", "Off schedule", 0, 0, ("BROAD",), allow_new_entries=False)
    return matched[-1]


def regime_from_gaps(gaps: list[GapResult]) -> tuple[str, str]:
    mood, note = _compute_mood_from_gaps(gaps)
    code = "risk_on" if "bull" in mood.lower() else "risk_off" if "bear" in mood.lower() else "neutral"
    if "mixed" in mood.lower():
        code = "range_bound"
    return code, f"{mood} — {note}"


def _build_priority_watchlist(gaps: list[GapResult], n: int) -> list[str]:
    scored: list[tuple[float, str]] = []
    for g in gaps:
        if g.direction != "UP":
            continue
        s = abs(g.gap_pct) * 10
        if g.holding:
            s += 15
        if g.vol_ratio and g.vol_ratio >= 1.2:
            s += 10
        if g.size_band in ("Medium", "Large"):
            s += 8
        scored.append((s, g.raw_ticker))
    scored.sort(reverse=True)
    out: list[str] = []
    for _, raw in scored:
        if raw not in out:
            out.append(raw)
        if len(out) >= n:
            break
    return out


def _score_candidates(
    results: list[IntradayResult],
    *,
    regime: str,
    confluence_map: dict[str, list[str]],
    min_score: int,
) -> list[tuple[float, IntradayResult, dict[str, Any]]]:
    ranked: list[tuple[float, IntradayResult, dict[str, Any]]] = []
    for r in results:
        pack = compute_intraday_quality_gate(
            {
                "Score /120": r.score_120,
                "Tier": r.rank_tier,
                "Prediction": r.prediction,
                "Strategy": STRATEGY_LABEL.get(r.strategy, r.strategy),
                "R:R": r.rr_ratio,
            },
            strategies_on_ticker=confluence_map.get(r.raw_ticker, [r.strategy]),
        )
        score = int(pack["score"])
        if regime == "risk_off":
            score -= 12
        if "avoid" in (r.rank_tier or "").lower():
            continue
        if score < min_score:
            continue
        if r.rr_ratio is not None and float(r.rr_ratio) < 1.0:
            continue
        ranked.append((float(score), r, pack))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def _confluence_map(results: list[IntradayResult]) -> dict[str, list[str]]:
    m: dict[str, list[str]] = {}
    for r in results:
        m.setdefault(r.raw_ticker, [])
        if r.strategy not in m[r.raw_ticker]:
            m[r.raw_ticker].append(r.strategy)
    return m


def _count_open_autopilot_positions(market: str) -> int:
    try:
        from paper_trading_store import load_paper_account
    except ImportError:
        return 0
    acc = load_paper_account()
    tag = f"autopilot_{market.lower()}"
    return sum(
        1 for p in acc.get("positions", [])
        if str(p.get("source", "")).startswith("autopilot") and str(p.get("horizon", "")) == market
    )


def _execute_entry(
    r: IntradayResult,
    *,
    market: str,
    cfg: AutopilotConfig,
    pack: dict[str, Any],
) -> tuple[bool, str]:
    from paper_trading import fetch_last_price, paper_buy, suggest_quantity
    from paper_trading_store import load_paper_account  # noqa: PLC0415

    entry = float(r.entry or r.price or 0)
    stop = float(r.stop or 0)
    if entry <= 0:
        return False, "No entry price"
    if stop <= 0 or stop >= entry:
        stop = round(entry * 0.985, 2)

    if cfg.mode == "dry_run":
        return True, f"DRY-RUN BUY {r.ticker} @ {entry} stop {stop} gate {pack.get('label', '')}"

    if cfg.mode == "paper":
        acc = load_paper_account()
        qty = suggest_quantity(
            cash=float(acc["cash"]),
            entry=entry,
            stop=stop,
            risk_pct=cfg.risk_pct_per_trade,
        )
        px = fetch_last_price(r.raw_ticker) or entry
        return paper_buy(
            raw_ticker=r.raw_ticker,
            ticker_display=r.ticker,
            quantity=qty,
            price=px,
            horizon=market,
            strategy=STRATEGY_LABEL.get(r.strategy, r.strategy),
            pattern=pack.get("label", ""),
            stop=stop,
            target=r.target,
            gate_band=pack.get("label", ""),
            source=f"autopilot_{market}",
            note=(r.setup_note or "")[:100],
        )

    if cfg.mode == "live" and cfg.live_orders_enabled:
        try:
            from breeze_data import place_buy_order, place_stoploss_sell
        except ImportError:
            return False, "Breeze not available"
        if os.environ.get("AUTOPILOT_LIVE_CONFIRM", "").upper() != "YES":
            return False, "Set AUTOPILOT_LIVE_CONFIRM=YES for live autopilot orders"
        from paper_trading import suggest_quantity

        qty = max(1, suggest_quantity(cash=500_000, entry=entry, stop=stop, risk_pct=cfg.risk_pct_per_trade))
        ok, msg, _ = place_buy_order(r.raw_ticker, qty, order_type="market", product="margin")
        if ok:
            place_stoploss_sell(r.raw_ticker, qty, trigger_price=stop, product="margin")
        return ok, msg

    return False, f"Unknown mode {cfg.mode}"


def _square_off_market(market: str, cfg: AutopilotConfig) -> list[str]:
    msgs: list[str] = []
    if cfg.mode == "paper":
        from paper_trading import load_paper_account, paper_sell, fetch_last_price

        acc = load_paper_account()
        for p in list(acc.get("positions", [])):
            if str(p.get("horizon", "")) != market:
                continue
            if not str(p.get("source", "")).startswith("autopilot"):
                continue
            raw = str(p.get("raw_ticker", ""))
            ok, msg = paper_sell(raw, price=fetch_last_price(raw))
            msgs.append(msg if ok else f"{raw}: {msg}")
        return msgs

    if cfg.mode == "live" and cfg.live_orders_enabled:
        try:
            from breeze_data import get_positions, place_sell_order
        except ImportError:
            return ["Breeze unavailable"]
        rows, err = get_positions()
        if err:
            return [err]
        for row in rows or []:
            action = str(row.get("action", "")).lower()
            if action and action != "buy":
                continue
            code = str(row.get("stock_code", ""))
            qty = int(float(row.get("quantity", 0) or 0))
            if qty > 0 and code:
                raw = f"{code}.NS"
                ok, msg, _ = place_sell_order(raw, qty, order_type="market", product="margin")
                msgs.append(msg if ok else f"{raw}: {msg}")
        return msgs

    return ["DRY-RUN square-off (no positions closed)"]


def run_market_tick(
    market: str,
    cfg: AutopilotConfig,
    state: dict[str, Any],
    *,
    phase_override: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """One autopilot cycle for a single market. Updates and saves state."""
    mkt = market.upper()
    phase = resolve_phase(mkt, phase_override)
    mstate = state["markets"].setdefault(mkt, {})
    state["last_phase"][mkt] = phase.id

    if state.get("kill_switch"):
        append_log(state, "kill_switch_active", market=mkt)
        save_state(state)
        return {"market": mkt, "phase": phase.id, "skipped": "kill_switch"}

    uni = cfg.universe_us if mkt == "US" else cfg.universe_nse
    tickers = resolve_universe(uni, mkt)[: cfg.max_intraday_tickers]

    if progress_cb:
        progress_cb(f"{mkt} · {phase.label}")

    tick_out: dict[str, Any] = {"market": mkt, "phase": phase.id, "phase_label": phase.label}

    # Pre-open / gap / mood
    if phase.id in ("pre_open", "gap_scan", "mood_shortlist"):
        gaps = scan_gaps(tickers, min_gap_abs_pct=cfg.gap_min_pct)
        reg, note = regime_from_gaps(gaps)
        mstate["regime"] = reg
        mstate["regime_note"] = note
        if phase.id in ("gap_scan", "mood_shortlist"):
            mstate["priority_watchlist"] = _build_priority_watchlist(gaps, cfg.priority_watchlist_size)
        tick_out["regime"] = reg
        tick_out["gaps"] = len(gaps)
        tick_out["watchlist"] = mstate.get("priority_watchlist", [])
        append_log(state, phase.id, market=mkt, **tick_out)
        save_state(state)
        return tick_out

    if phase.force_square_off:
        msgs = _square_off_market(mkt, cfg)
        tick_out["square_off"] = msgs
        append_log(state, "square_off", market=mkt, messages=msgs)
        save_state(state)
        return tick_out

    if phase.run_eod_report:
        try:
            from paper_trading import account_summary
            summ = account_summary()
            tick_out["eod"] = summ
            append_log(state, "eod_report", market=mkt, summary=summ)
        except ImportError:
            tick_out["eod"] = {}
        save_state(state)
        return tick_out

    sess = market_session_window(mkt)
    if not sess.get("is_open") and phase.allow_new_entries:
        tick_out["skipped"] = "session_closed"
        save_state(state)
        return tick_out

    if phase.manage_only:
        tick_out["mode"] = "manage_only"
        append_log(state, "manage_only", market=mkt)
        save_state(state)
        return tick_out

    # Active strategies for this phase
    strats = tuple(s for s in phase.strategies if s in STRATEGIES)
    if not strats:
        strats = ("BROAD",)

    watch = mstate.get("priority_watchlist") or []
    scan_list = list(dict.fromkeys(watch + tickers))[: cfg.max_intraday_tickers]

    results, stats = scan_intraday(
        scan_list,
        strats,
        IntradayFilters(),
        market=mkt,
        data_source="yahoo" if cfg.mode != "live" else "auto",
    )
    conf = _confluence_map(results)
    regime = mstate.get("regime", "neutral")
    ranked = _score_candidates(
        results, regime=regime, confluence_map=conf, min_score=cfg.min_gate_score,
    )

    open_pos = _count_open_autopilot_positions(mkt)
    trades_today = int(mstate.get("trades_today", 0))

    executed: list[str] = []
    for score, r, pack in ranked:
        if open_pos >= cfg.max_open_positions:
            break
        if trades_today >= cfg.max_trades_per_market_per_day:
            break
        if r.rr_ratio is not None and float(r.rr_ratio) < cfg.min_rr:
            continue
        ok, msg = _execute_entry(r, market=mkt, cfg=cfg, pack=pack)
        executed.append(msg)
        if ok and not msg.startswith("DRY-RUN"):
            trades_today += 1
            open_pos += 1
            mstate["trades_today"] = trades_today

    tick_out.update(
        {
            "scanned": stats.total_scanned,
            "matches": len(results),
            "candidates": len(ranked),
            "executed": executed,
            "open_positions": open_pos,
            "trades_today": trades_today,
            "session": sess.get("window"),
        }
    )
    append_log(state, "scan_execute", market=mkt, **{k: v for k, v in tick_out.items() if k != "executed"})
    save_state(state)
    return tick_out


def run_autopilot_tick(
    cfg: Optional[AutopilotConfig] = None,
    *,
    phase_override: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Run one tick for all configured markets."""
    cfg = cfg or AutopilotConfig()
    cfg.live_orders_enabled = (
        cfg.mode == "live"
        and os.environ.get("AUTOPILOT_ENABLED", "").lower() in ("1", "true", "yes")
    )
    state = load_state()
    out: dict[str, Any] = {"markets": {}, "mode": cfg.mode}
    for m in cfg.markets:
        out["markets"][m] = run_market_tick(
            m, cfg, state, phase_override=phase_override, progress_cb=progress_cb,
        )
    out["kill_switch"] = state.get("kill_switch", False)
    return out


def set_kill_switch(on: bool) -> None:
    st = load_state()
    st["kill_switch"] = bool(on)
    append_log(st, "kill_switch", enabled=on)
    save_state(st)
