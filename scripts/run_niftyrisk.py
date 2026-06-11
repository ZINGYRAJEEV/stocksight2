#!/usr/bin/env python3
"""
Run NiftyRisk API (portfolio risk analysis).

Local:  python scripts/run_niftyrisk.py
Env:    NIFTYRISK_PORT=8090  NIFTYRISK_TIER=free|pro|elite

Endpoints:
  GET  /health
  GET  /tiers
  POST /analyze/csv
  POST /analyze/json
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

    from niftyrisk.api import app

    port = int(os.environ.get("PORT", os.environ.get("NIFTYRISK_PORT", "8090")))
    host = os.environ.get("NIFTYRISK_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port, log_level="info")
