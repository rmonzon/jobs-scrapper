"""Local live dashboard server (stdlib only).

Serves the dashboard/ directory and exposes POST /api/refresh, which re-runs the full
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
DASHBOARD_DIR = ROOT / "dashboard"
DASHBOARD_DATA = DASHBOARD_DIR / "data.js"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}

# Serialize refreshes so two button presses can't run the pipeline concurrently
# and clobber each other's snapshot writes.
_refresh_lock = threading.Lock()
# Serialize preference writes so concurrent tabs can't corrupt the file.
_prefs_lock = threading.Lock()

# Reject absurd preference payloads outright (the real thing is a few KB).
_MAX_PREFS_BYTES = 5_000_000


def _run_pipeline() -> int:
    # Imported lazily so importing the server never pulls in the whole run stack.
    import run as runner
    return runner.run(CONFIG, DATA_DIR, seed=False)


def _static_file(url_path: str) -> Path | None:
    """Map a URL path to a file inside DASHBOARD_DIR, or None.

    The dashboard directory is served at the site root, the same layout GitHub
    Pages gets, so the page's relative asset URLs work in both places. Anything
    that resolves outside the directory (``/../.env``) is refused.
    """
    if url_path in ("/", "/dashboard.html"):  # dashboard.html: old bookmark
        url_path = "/index.html"
    base = DASHBOARD_DIR.resolve()
    try:
        fp = (base / url_path.lstrip("/")).resolve()
    except (OSError, ValueError):
        return None
    if not fp.is_relative_to(base) or not fp.is_file():
        return None
    return fp


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/health":
            self._send(200, b'{"ok":true}', "application/json")
        elif path == "/api/prefs":
            from scraper import prefs as prefs_store
            with _prefs_lock:
                data = prefs_store.load_prefs(DATA_DIR)
            self._send(200, json.dumps(data).encode(), "application/json")
        elif path in ("/", "/index.html", "/data.js") and not DASHBOARD_DATA.exists():
            self._send(503, b"dashboard not generated yet; run python3 run.py",
                       "text/plain; charset=utf-8")
        elif (fp := _static_file(path)) is not None:
            ctype = _CONTENT_TYPES.get(fp.suffix, "application/octet-stream")
            self._send(200, fp.read_bytes(), ctype)
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/prefs":
            self._save_prefs()
            return
        if path != "/api/refresh":
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

    def _save_prefs(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > _MAX_PREFS_BYTES:
            self._send(400, b'{"ok":false,"error":"bad payload size"}',
                       "application/json")
            return
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            self._send(400, b'{"ok":false,"error":"invalid json"}',
                       "application/json")
            return
        from scraper import prefs as prefs_store
        with _prefs_lock:
            saved = prefs_store.save_prefs(DATA_DIR, body)
        self._send(200, json.dumps({"ok": True, **saved}).encode(),
                   "application/json")

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
    if not DASHBOARD_DATA.exists():
        from scraper.dashboard import build_dashboard
        build_dashboard(DATA_DIR, DASHBOARD_DIR, CONFIG)

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
