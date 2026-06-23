"""Local live dashboard server (stdlib only).

Serves dashboard.html and exposes POST /api/refresh, which re-runs the full
fetch → diff → regenerate pipeline so the dashboard's Refresh button pulls
genuinely fresh data. Intended for localhost use only.

    python3 serve.py            # http://127.0.0.1:8787
    python3 serve.py --port 9000
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG = ROOT / "config.json"
DASHBOARD = ROOT / "dashboard.html"

# Serialize refreshes so two button presses can't run the pipeline concurrently
# and clobber each other's snapshot writes.
_refresh_lock = threading.Lock()


def _run_pipeline() -> int:
    # Imported lazily so importing the server never pulls in the whole run stack.
    import run as runner
    return runner.run(CONFIG, DATA_DIR, seed=False)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html", "/dashboard.html"):
            if not DASHBOARD.exists():
                self._send(503, b"dashboard not generated yet; run python3 run.py",
                           "text/plain; charset=utf-8")
                return
            self._send(200, DASHBOARD.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/health":
            self._send(200, b'{"ok":true}', "application/json")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        if self.path != "/api/refresh":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        # If a refresh is already running, don't queue another — just report busy.
        if not _refresh_lock.acquire(blocking=False):
            self._send(409, b'{"ok":false,"error":"refresh already running"}',
                       "application/json")
            return
        try:
            self._run_and_respond()
        finally:
            _refresh_lock.release()

    def _run_and_respond(self):
        try:
            _run_pipeline()
            self._send(200, b'{"ok":true}', "application/json")
        except Exception as exc:  # report failure to the button instead of 500-ing silently
            body = json.dumps({"ok": False, "error": str(exc)}).encode()
            self._send(500, body, "application/json")

    def log_message(self, fmt, *args):  # quieter console
        print(f"[server] {self.address_string()} {fmt % args}")


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    from scraper.env import load_env
    load_env(ROOT / ".env")
    # Make sure there's something to serve on first launch.
    if not DASHBOARD.exists():
        from scraper.dashboard import build_dashboard
        build_dashboard(DATA_DIR, DASHBOARD, CONFIG)

    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"Job Tracker dashboard live at {url}")
    print("  • open that URL in your browser")
    print("  • the Refresh button now re-fetches all companies and updates live")
    print("  • Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        httpd.server_close()
