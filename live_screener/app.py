"""
Flask live NSE screener — Bloomberg-style dashboard with SSE scan progress.

Run from repo root:
    python run_live_screener.py
    # http://127.0.0.1:5000
"""
from __future__ import annotations

import json
import queue
import sys
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from live_screener.engine import (  # noqa: E402
    PRESETS,
    ScanConfig,
    get_scan_state,
    start_scan_async,
)

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)


@app.route("/")
def index():
    return render_template(
        "index.html",
        presets=PRESETS,
        default_preset="balanced",
    )


@app.route("/api/status")
def api_status():
    st = get_scan_state()
    return jsonify({**st.to_summary(), "rows": st.rows})


@app.route("/api/presets")
def api_presets():
    return jsonify(PRESETS)


@app.route("/api/scan", methods=["POST"])
def api_scan_start():
    body = request.get_json(silent=True) or {}
    preset = str(body.get("preset") or "nse_screener")
    universe = str(body.get("universe") or "").strip()
    explain = bool(body.get("explain_fall", True))

    st = get_scan_state()
    if st.running:
        return jsonify({"ok": False, "error": "Scan already running"}), 409

    cfg = ScanConfig(preset=preset, universe=universe, explain_fall=explain)
    start_scan_async(cfg)
    return jsonify({"ok": True, "preset": preset, "universe": cfg.resolved().get("universe")})


@app.route("/api/scan/stream")
def api_scan_stream():
    """SSE: client POSTs preset via query string, then receives progress + final rows."""
    preset = request.args.get("preset", "nse_screener")
    universe = request.args.get("universe", "")
    explain = request.args.get("explain_fall", "1") not in ("0", "false", "no")

    st = get_scan_state()
    if st.running:
        def busy():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Scan already running'})}\n\n"
        return Response(busy(), mimetype="text/event-stream")

    q: queue.Queue = queue.Queue()
    cfg = ScanConfig(preset=preset, universe=universe, explain_fall=explain)

    def on_event(evt: dict) -> None:
        q.put(evt)

    start_scan_async(cfg, on_event=on_event)

    def generate():
        while True:
            try:
                evt = q.get(timeout=600)
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Scan timed out'})}\n\n"
                break
            yield f"data: {json.dumps(evt, default=str)}\n\n"
            if evt.get("type") in ("done", "error"):
                break
            # Also poll global state for progress between events
            time.sleep(0.05)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def main() -> None:
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    main()
