#!/usr/bin/env python3
"""IntraBot CLI — paper by default.  python scripts/run_intrabot.py --loop --interval 60"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "stocksight"))

from intrabot.config import IntraBotConfig, PAPER_TRADE  # noqa: E402
from intrabot.engine import run_intrabot_tick  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="IntraBot intraday automation")
    p.add_argument("--once", action="store_true", default=True)
    p.add_argument("--loop", action="store_true")
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--mode", choices=("auto", "scan", "monitor"), default="auto")
    p.add_argument("--markets", default="NSE,US")
    p.add_argument("--paper", action="store_true", default=PAPER_TRADE)
    p.add_argument("--live", action="store_true")
    p.add_argument("--data-source-nse", default="auto", choices=("auto", "breeze", "yahoo"))
    args = p.parse_args()

    cfg = IntraBotConfig(
        paper_trade=not args.live,
        markets=tuple(x.strip().upper() for x in args.markets.split(",") if x.strip()),
        data_source_nse=args.data_source_nse,
    )

    def tick() -> None:
        out = run_intrabot_tick(cfg, mode=args.mode)
        print(json.dumps(out, indent=2, default=str))

    if args.loop:
        while True:
            tick()
            time.sleep(max(30, args.interval))
    else:
        tick()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
