"""Kleine webserver voor het dashboard (alleen standaardbibliotheek)."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DASHBOARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard", "index.html")


def make_server(app, host, port):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                with open(DASHBOARD, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._send(200, json.dumps(app.snapshot()), "application/json")
            else:
                self._send(404, "niet gevonden", "text/plain")

        def do_POST(self):
            parts = self.path.strip("/").split("/")  # api/bots/BTCUSDT/pause
            if len(parts) == 4 and parts[:2] == ["api", "bots"] and app.command(parts[2], parts[3]):
                self._send(200, json.dumps({"ok": True}), "application/json")
            else:
                self._send(400, json.dumps({"ok": False}), "application/json")

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)
