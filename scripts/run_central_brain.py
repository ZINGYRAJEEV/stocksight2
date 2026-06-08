#!/usr/bin/env python3
"""
Run Central Brain webhook API (TradingView → validation → exchange).

Local:  python scripts/run_central_brain.py
Railway: Procfile runs this on $PORT.

Endpoints:
  GET  /health
  GET  /checklist
  POST /webhook/tradingview
  POST /webhook/test
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_STOCKSIGHT = _REPO / "stocksight"
for p in (_REPO, _STOCKSIGHT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

if __name__ == "__main__":
    import uvicorn

    from central_brain.api import app

    port = int(os.environ.get("PORT", os.environ.get("CENTRAL_BRAIN_PORT", "8080")))
    host = os.environ.get("CENTRAL_BRAIN_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port, log_level="info")
