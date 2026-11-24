# Quota board: one static page plus /api/subs, served on 127.0.0.1:9181 by default.
#
# Serves one static page and /api/subs, which only reads the cache that subs.py refreshes
# in the background (Claude, Antigravity, Codex). It reads no databases and
# serves only an allow-list of files, so none of this source is reachable over HTTP.
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import subs

BASE = Path(__file__).resolve().parent
PORT = int(os.environ.get("USAGE_DAEMON_PORT", "9181"))
HOST = os.environ.get("USAGE_DAEMON_HOST", "127.0.0.1")

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/subs":
            self._send(200, json.dumps(subs.get(), separators=(",", ":")).encode(), "application/json; charset=utf-8")
        elif path in STATIC:
            name, ctype = STATIC[path]
            try:
                self._send(200, (BASE / name).read_bytes(), ctype)
            except OSError as e:
                self._send(500, str(e).encode(), "text/plain; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    subs.start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"subscription page: {BASE} on {HOST}:{PORT}")
    srv.serve_forever()
