"""The Example Scores site, small enough to read, for the guide's extensions to talk to.

Standard library only. Run it with `python practice_site.py` and it answers on
127.0.0.1:8790. It accepts the key `practice-key` in an `X-API-Key` header and keeps its
scores in memory, so stopping it forgets what was posted.

    GET  /status   open to anyone: {"open": true}
    GET  /check    200 with the right key, 401 without
    GET  /top      the scores, best first, with the right key
    POST /scores   {"player", "table", "score"}, with the right key; 201

A test starts it with `make_server(0)` and reads the port the system chose.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HOST = "127.0.0.1"
PORT = 8790
KEY = "practice-key"

SCORES: list[dict[str, Any]] = [
    {"player": "AAA", "table": "Medieval Madness", "score": 1_240_000_000},
    {"player": "BEE", "table": "Attack from Mars", "score": 980_500_000},
    {"player": "CJ", "table": "The Addams Family", "score": 310_000_000},
]


def _handler(scores: list[dict[str, Any]]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass

        def _send(self, status: int, body: Any) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _signed_in(self) -> bool:
            if self.headers.get("X-API-Key") == KEY:
                return True
            self._send(401, {"error": "The key was not accepted"})
            return False

        def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
            if self.path == "/status":
                self._send(200, {"open": True})
            elif self.path == "/check" and self._signed_in():
                self._send(200, {"ok": True})
            elif self.path == "/top" and self._signed_in():
                self._send(200, sorted(scores, key=lambda one: -one["score"]))
            elif self.path not in ("/check", "/top"):
                self._send(404, {"error": "No such page"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/scores":
                self._send(404, {"error": "No such page"})
            elif self._signed_in():
                size = int(self.headers.get("Content-Length") or 0)
                try:
                    posted = json.loads(self.rfile.read(size) or b"{}")
                    scores.append({"player": str(posted["player"]),
                                   "table": str(posted["table"]),
                                   "score": int(posted["score"])})
                except (ValueError, KeyError):
                    self._send(400, {"error": "A score needs player, table and score"})
                else:
                    self._send(201, {"ok": True})

    return Handler


def make_server(port: int = PORT) -> ThreadingHTTPServer:
    """A server on `port` (0 for any free one) with its own copy of the sample scores."""
    return ThreadingHTTPServer((HOST, port), _handler([dict(one) for one in SCORES]))


def serve_in_background(port: int = 0) -> ThreadingHTTPServer:
    """`make_server`, answering on a thread of its own. `shutdown()` and `server_close()`
    end it."""
    server = make_server(port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    print(f"Example Scores on http://{HOST}:{PORT}  (key: {KEY})")
    make_server().serve_forever()
