#!/usr/bin/env python3
"""
Intraday autopilot — continuous scheduled trading job (paper by default).

  python scripts/run_autopilot.py --once
  python scripts/run_autopilot.py --loop --interval 300
  python scripts/run_autopilot.py --once --mode dry_run --markets NSE

Live (DANGER): AUTOPILOT_ENABLED=true AUTOPILOT_LIVE_CONFIRM=YES python scripts/run_autopilot.py --once --mode live
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "stocksight"))

from intraday_autopilot import AutopilotConfig, run_autopilot_tick, set_kill_switch  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="StockSight intraday autopilot")
    p.add_argument("--once", action="store_true", help="Single tick (default)")
    p.add_argument("--loop", action="store_true", help="Run forever with sleep interval")
    p.add_argument("--interval", type=int, default=300, help="Seconds between ticks in loop mode")
    p.add_argument("--mode", choices=("dry_run", "paper", "live"), default="paper")
    p.add_argument("--markets", default="NSE,US", help="Comma-separated NSE,US")
    p.add_argument("--phase", default="", help="Force phase id (e.g. orb, square_off)")
    p.add_argument("--kill-switch-on", action="store_true")
    p.add_argument("--kill-switch-off", action="store_true")
    p.add_argument("--min-gate", type=int, default=58)
    args = p.parse_args()

    if args.kill_switch_on:
        set_kill_switch(True)
        print("Kill switch ON")
    if args.kill_switch_off:
        set_kill_switch(False)
        print("Kill switch OFF")

    cfg = AutopilotConfig(
        mode=args.mode,
        markets=tuple(m.strip().upper() for m in args.markets.split(",") if m.strip()),
        min_gate_score=args.min_gate,
    )
    phase = args.phase.strip() or None

    def prog(msg: str) -> None:
        print(msg)

    def tick() -> None:
        print(f"\n--- Autopilot tick mode={cfg.mode} ---")
        out = run_autopilot_tick(cfg, phase_override=phase, progress_cb=prog)
        print(json.dumps(out, indent=2, default=str))

    if args.loop:
        while True:
            tick()
            time.sleep(max(60, args.interval))
    else:
        tick()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
