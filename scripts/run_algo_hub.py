#!/usr/bin/env python3
"""Headless multi-horizon algo selection (same engine as Algo Strategy Hub UI)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "stocksight"))

from algo_selector import HORIZONS, picks_to_dataframe, run_algo_selection  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="StockSight Algo Strategy Hub (CLI)")
    p.add_argument("--universe", default="Nifty 50 (fast)")
    p.add_argument("--market", default="NSE", choices=("NSE", "US"))
    p.add_argument("--horizons", default=",".join(HORIZONS))
    p.add_argument("--top-n", type=int, default=8)
    p.add_argument("--max-intraday", type=int, default=80)
    p.add_argument("--data-source", default="yahoo", choices=("auto", "yahoo", "breeze"))
    p.add_argument("--out-dir", default="")
    p.add_argument(
        "--email",
        action="store_true",
        help="Email summary if SMTP is configured (secrets.toml or env)",
    )
    args = p.parse_args()

    horizons = tuple(h.strip() for h in args.horizons.split(",") if h.strip())
    out = Path(args.out_dir) if args.out_dir else _ROOT / "output" / "algo_hub"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")

    def prog(phase: str, cur: int, tot: int) -> None:
        print(f"  [{cur}/{tot}] {phase}")

    report = run_algo_selection(
        args.universe,
        market=args.market,
        horizons=horizons,
        top_n=args.top_n,
        max_intraday_tickers=args.max_intraday,
        data_source=args.data_source,
        progress_cb=prog,
    )

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "universe": report.universe,
        "regime": report.regime.code,
        "regime_label": report.regime.label,
        "session_note": report.session_note,
        "stats": report.stats,
        "files": {},
    }

    for h, picks in report.picks_by_horizon.items():
        df = picks_to_dataframe(picks)
        if not df.empty:
            path = out / f"algo_{h}_{stamp}.csv"
            df.to_csv(path, index=False)
            summary["files"][h] = str(path)
            print(f"{h}: {len(picks)} picks -> {path}")

    sp = out / f"summary_{stamp}.json"
    sp.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Summary: {sp}")

    if args.email:
        try:
            from email_alerts import send_plain_email  # noqa: E402
        except ImportError:
            print("Email skipped — email_alerts not available.")
            return 0
        lines = [
            f"StockSight Algo Strategy Hub — {args.universe}",
            f"Regime: {report.regime.label} ({report.regime.code})",
            f"Session: {report.session_note}",
            "",
        ]
        for h, picks in report.picks_by_horizon.items():
            lines.append(f"--- {h.upper()} (top {len(picks)}) ---")
            for p in picks[: args.top_n]:
                lines.append(
                    f"#{p.rank} {p.ticker} | {p.gate_band} | score {p.score} | {p.algo_style}"
                )
            lines.append("")
        lines.append("Research only — not exchange-approved algo. Review before trading.")
        ok, msg = send_plain_email(
            subject=f"[StockSight] Algo Hub — {report.regime.label} — {stamp}",
            body="\n".join(lines),
        )
        print(f"Email: {msg}" if ok else f"Email failed: {msg}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
