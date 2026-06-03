"""IntraBot orchestrator — one tick per market or position monitor."""

from __future__ import annotations

from typing import Any, Callable, Optional

try:
    from intraday import compute_intraday_quality_gate, resolve_universe
except ImportError:
    from ..intraday import compute_intraday_quality_gate, resolve_universe  # type: ignore

from intrabot.alerts import emit
from intrabot.config import IntraBotConfig
from intrabot.executor import execute_buy, square_off_market
from intrabot.risk_manager import count_open, daily_loss_halted, update_trailing_stops
from intrabot.scheduler import PhaseSpec, resolve_phase
from intrabot.store import load_state, save_state, set_runtime
from intrabot.strategies import build_shortlist, run_gap_scan, run_strategy_scan


def _data_source(market: str, cfg: IntraBotConfig) -> str:
    return "yahoo" if market.upper() == "US" else (cfg.data_source_nse or "auto")


def _rank_results(results: list, regime: str, min_score: int) -> list[tuple[float, Any, dict]]:
    ranked: list[tuple[float, Any, dict]] = []
    for r in results:
        pack = compute_intraday_quality_gate(
            {
                "Score /120": getattr(r, "score_120", 0),
                "Tier": getattr(r, "rank_tier", ""),
                "Prediction": getattr(r, "prediction", ""),
                "Strategy": getattr(r, "strategy", ""),
                "R:R": getattr(r, "rr_ratio", None),
            },
            strategies_on_ticker=[getattr(r, "strategy", "")],
        )
        score = int(pack.get("score", 0))
        if score < min_score:
            continue
        if getattr(r, "rr_ratio", None) is not None and float(r.rr_ratio) < 1.0:
            continue
        ranked.append((float(score), r, pack))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def run_position_monitor(
    cfg: IntraBotConfig,
    state: dict[str, Any],
    *,
    progress_cb: Optional[Callable[..., None]] = None,
) -> dict[str, Any]:
    """Trailing stops + stop/target checks (run every ~60s)."""
    out: dict[str, Any] = {"type": "monitor"}
    if state.get("kill_switch") or cfg.kill_switch:
        emit(state, "kill_switch", "Monitor skipped", level="warn")
        save_state(state)
        return out
    if daily_loss_halted(state, cfg.risk):
        emit(state, "daily_halt", "Daily loss limit — no new risk", level="warn")
        state["halted"] = True
        save_state(state)
        return out

    all_msgs: list[str] = []
    for mkt in cfg.markets:
        msgs = update_trailing_stops(state, mkt, cfg.risk)
        for m in msgs:
            emit(state, "trail_stop", m, market=mkt, level="info")
        all_msgs.extend(msgs)
    out["trail_updates"] = all_msgs
    save_state(state)
    return out


def run_market_tick(
    market: str,
    cfg: IntraBotConfig,
    state: dict[str, Any],
    *,
    progress_cb: Optional[Callable[..., None]] = None,
) -> dict[str, Any]:
    mkt = market.upper()
    phase = resolve_phase(mkt, cfg.force_phase)
    mstate = state["markets"].setdefault(mkt, {})
    ds = _data_source(mkt, cfg)
    tick_out: dict[str, Any] = {
        "market": mkt,
        "phase": phase.id,
        "phase_label": phase.label,
        "data_source": ds,
    }

    set_runtime(
        state,
        status="phase",
        market=mkt,
        phase_id=phase.id,
        phase_label=phase.label,
        message=phase.label,
    )

    if state.get("kill_switch") or cfg.kill_switch:
        emit(state, "kill_switch", "Tick blocked", market=mkt, level="warn")
        save_state(state)
        return {**tick_out, "skipped": "kill_switch"}

    if daily_loss_halted(state, cfg.risk):
        emit(state, "daily_halt", "Daily loss halt active", market=mkt, level="warn")
        save_state(state)
        return {**tick_out, "skipped": "daily_halt"}

    uni = cfg.universe_us if mkt == "US" else cfg.universe_nse
    tickers = resolve_universe(uni, mkt)[: cfg.max_scan_tickers]

    if phase.force_square_off:
        msgs = square_off_market(mkt, cfg)
        for m in msgs:
            emit(state, "square_off", m, market=mkt, level="trade")
        tick_out["square_off"] = msgs
        save_state(state)
        return tick_out

    if phase.manage_only:
        msgs = update_trailing_stops(state, mkt, cfg.risk)
        tick_out["monitor"] = msgs
        emit(state, "manage_only", f"Monitor {len(msgs)} update(s)", market=mkt)
        save_state(state)
        return tick_out

    if phase.id in ("wake", "pre_us", "off_hours"):
        emit(state, phase.id, "Context only — no scan", market=mkt)
        save_state(state)
        return {**tick_out, "skipped": phase.id}

    if phase.id in ("gap_scan", "mood", "us_gap") or phase.scan_only:
        emit(state, "gap_scan_start", f"Scanning {len(tickers)} tickers", market=mkt)
        gaps = run_gap_scan(tickers, data_source=ds, progress_cb=progress_cb)
        wl = build_shortlist(gaps, cfg.mood_shortlist_size)
        mstate["watchlist"] = wl
        tick_out["gaps"] = len(gaps)
        tick_out["watchlist"] = wl
        emit(state, "gap_scan_done", f"{len(gaps)} gaps · watchlist {wl}", market=mkt)
        save_state(state)
        return tick_out

    strats = tuple(s for s in phase.strategies if s)
    if not strats:
        save_state(state)
        return {**tick_out, "skipped": "no_strategies"}

    watch = mstate.get("watchlist") or []
    scan_list = list(dict.fromkeys(watch + tickers))[: cfg.max_scan_tickers]
    emit(
        state,
        "scan_start",
        f"{phase.label} · {','.join(strats)} · {len(scan_list)} tickers",
        market=mkt,
    )

    results, stats = run_strategy_scan(
        scan_list, strats, market=mkt, data_source=ds, progress_cb=progress_cb,
    )
    ranked = _rank_results(results, mstate.get("regime", ""), cfg.risk.min_gate_score)

    open_pos = count_open(state, mkt)
    trades = int(mstate.get("trades_today", 0))
    executed: list[str] = []

    if phase.allow_new_entries and not phase.scan_only:
        for _score, r, pack in ranked:
            if open_pos >= cfg.risk.max_open_positions:
                break
            if trades >= cfg.risk.max_open_positions:
                break
            if getattr(r, "rr_ratio", None) is not None and float(r.rr_ratio) < cfg.risk.min_rr:
                continue
            ok, msg = execute_buy(r, market=mkt, cfg=cfg, pack=pack)
            executed.append(msg)
            emit(state, "order", msg, market=mkt, level="trade" if ok else "warn")
            if ok:
                trades += 1
                open_pos += 1
                mstate["trades_today"] = trades

    tick_out.update(
        {
            "scanned": stats.total_scanned,
            "matches": len(results),
            "candidates": len(ranked),
            "executed": executed,
            "open_positions": open_pos,
        }
    )
    emit(
        state,
        "scan_done",
        f"matches={len(results)} candidates={len(ranked)} orders={len(executed)}",
        market=mkt,
    )
    save_state(state)
    return tick_out


def run_intrabot_tick(
    cfg: Optional[IntraBotConfig] = None,
    *,
    mode: str = "auto",
    progress_cb: Optional[Callable[..., None]] = None,
) -> dict[str, Any]:
    """
    Run one orchestrator tick.
    mode: auto | scan | monitor
    """
    cfg = cfg or IntraBotConfig()
    state = load_state()
    state["paper_trade"] = cfg.effective_paper()
    state["kill_switch"] = bool(cfg.kill_switch or state.get("kill_switch"))

    out: dict[str, Any] = {"markets": {}, "paper": cfg.effective_paper(), "mode": mode}

    if mode == "monitor":
        out["monitor"] = run_position_monitor(cfg, state, progress_cb=progress_cb)
        save_state(state)
        return out

    for m in cfg.markets:
        out["markets"][m] = run_market_tick(m, cfg, state, progress_cb=progress_cb)

    if mode == "auto":
        out["monitor"] = run_position_monitor(cfg, state, progress_cb=progress_cb)

    set_runtime(state, status="idle", message="Tick complete")
    save_state(state)
    return out
