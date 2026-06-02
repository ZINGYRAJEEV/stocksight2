#!/usr/bin/env bash
# StockSight — headless intraday cycle (gap + intraday + overlap CSV export)
# Usage: ./scripts/run_intraday_cycle.sh [--universe "Nifty 50 (fast)"] [--data-source yahoo]

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f stocksight/intraday.py ]]; then
  echo "ERROR: stocksight/intraday.py not found. Run from stocksight2 repo root." >&2
  exit 1
fi

echo "[$(date -Iseconds)] Starting intraday cycle..."
python3 scripts/intraday_cycle.py "$@"
echo "Outputs: ${ROOT}/output/intraday/"
