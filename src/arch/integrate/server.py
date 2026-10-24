"""The review page, served on this machine only.

Realizes arch.integrate.server. Binds 127.0.0.1 and nothing else. Writes are accepted only as JSON from
the page itself: requests need `Content-Type: application/json` (which a foreign page cannot send without
a CORS preflight this server never grants), a Host of this server (against DNS rebinding), and no foreign
Origin. Every verdict goes through the catalog.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NewType

from arch.integrate import catalog
from arch.integrate.catalog import Revision, VerdictInput, Workspace
from arch.model.ids import Text
from arch.review.page import Board
from arch.review.session import Anchor, Category, Decision, Weight
from arch.view.render import Count

Port = NewType("Port", int)
URL = NewType("URL", str)
LOOPBACK = "127.0.0.1"
MAX_BODY = 64 * 1024


class Reviewing:
    """The served review: the current board, rebuilt on request."""

    def __init__(self, ws: Workspace, base: Revision):
        self.ws, self.base = ws, base
        self.board: Board = catalog.review_board(ws, base).view

    def rebuild(self) -> None:
        self.board = catalog.review_board(self.ws, self.base).view

    def decide(self, raw: dict) -> Board:
        anchor = raw.get("anchor")
        verdict = VerdictInput(
            item=raw["item"], digest=raw["digest"], decision=Decision(raw["decision"]),
            comment=Text(raw["comment"]) if raw.get("comment") else None,
            category=Category(raw.get("category", "other")), weight=Weight(raw.get("weight", "blocking")),
            anchor=Anchor(Text(anchor["path"]), Count(int(anchor["line"]))) if isinstance(anchor, dict) else None)
        self.board = catalog.review_decide(self.ws, self.board, verdict).view
        return self.board


def make_server(reviewing: Reviewing, port: Port = Port(0)) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # quiet: the terminal belongs to the CLI
            pass

        def _send(self, status: int, body: str, kind: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _ours(self) -> bool:
            host = f"{LOOPBACK}:{self.server.server_address[1]}"
            origin = self.headers.get("Origin")
            return self.headers.get("Host") in (host, f"localhost:{self.server.server_address[1]}") and (
                origin is None or origin in (f"http://{host}", f"http://localhost:{self.server.server_address[1]}"))

        def do_GET(self) -> None:
            if not self._ours():
                return self._send(403, "forbidden", "text/plain")
            if self.path.split("?")[0] == "/":
                return self._send(200, reviewing.board.to_html(), "text/html; charset=utf-8")
            if self.path == "/api/state":
                return self._send(200, json.dumps(reviewing.board.to_json()), "application/json")
            self._send(404, "not found", "text/plain")

        def do_POST(self) -> None:
            if not self._ours() or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._send(403, "forbidden", "text/plain")
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send(413, "too large", "text/plain")
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                if self.path == "/api/verdict":
                    board = reviewing.decide(json.loads(raw))
                    return self._send(200, json.dumps(board.to_json()), "application/json")
                if self.path == "/api/rebuild":
                    reviewing.rebuild()
                    return self._send(200, json.dumps(reviewing.board.to_json()), "application/json")
            except (catalog.ReviewRejected, KeyError, ValueError, TypeError) as e:
                return self._send(409, str(e), "text/plain")
            self._send(404, "not found", "text/plain")

    return ThreadingHTTPServer((LOOPBACK, port), Handler)


def serve(ws: Workspace, base: Revision, port: Port, ready: Callable[[URL], None]) -> None:
    """Serve until interrupted; `ready` is told the address once the server is listening."""
    server = make_server(Reviewing(ws, base), port)
    ready(URL(f"http://{LOOPBACK}:{server.server_address[1]}/"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
