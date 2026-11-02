from __future__ import annotations

import hmac
import json
import queue
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .secrets import get_secret, set_secret


MAX_BODY = 16_384


def companion_token() -> str:
    token = get_secret("companion_token")
    if token:
        return token
    token = secrets.token_urlsafe(32)
    set_secret("companion_token", token)
    if get_secret("companion_token") != token:
        raise RuntimeError("Windows Credential Manager could not store the companion token.")
    return token


@dataclass(frozen=True)
class CompanionCommand:
    request_id: str
    text: str
    source: str = "phone"


class CompanionServer:
    """Authenticated local command inbox; it never executes actions itself."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, token: str | None = None):
        self.host = str(host)
        self.port = int(port)
        self.token = token or companion_token()
        self.commands: queue.Queue[CompanionCommand] = queue.Queue(maxsize=50)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int] | None:
        return self._server.server_address if self._server else None

    def _handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "JARVIS-V6-Companion"

            def log_message(self, _format, *_args):
                return

            def _json(self, status: int, payload: dict):
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

            def _authorized(self) -> bool:
                supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                return bool(supplied) and hmac.compare_digest(supplied, owner.token)

            def do_GET(self):
                if self.path != "/v1/status": self._json(404, {"error": "not_found"}); return
                if not self._authorized(): self._json(401, {"error": "unauthorized"}); return
                self._json(200, {"application": "JARVIS V6", "status": "ready",
                                 "execution": "plan_then_execute"})

            def do_POST(self):
                if self.path != "/v1/commands": self._json(404, {"error": "not_found"}); return
                if not self._authorized(): self._json(401, {"error": "unauthorized"}); return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length < 1 or length > MAX_BODY:
                    self._json(413, {"error": "invalid_body_size"}); return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    text = " ".join(str(payload.get("text", "")).strip().split())
                    request_id = str(payload.get("requestId", "")).strip() or secrets.token_hex(8)
                except Exception:
                    self._json(400, {"error": "invalid_json"}); return
                if not text or len(text) > 2_000:
                    self._json(400, {"error": "invalid_command"}); return
                try:
                    owner.commands.put_nowait(CompanionCommand(request_id[:100], text))
                except queue.Full:
                    self._json(503, {"error": "queue_full"}); return
                self._json(202, {"requestId": request_id[:100], "status": "queued"})

        return Handler

    def start(self) -> tuple[str, int]:
        if self._server:
            return self._server.server_address
        self._server = ThreadingHTTPServer((self.host, self.port), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="jarvis-companion", daemon=True)
        self._thread.start()
        return self._server.server_address

    def stop(self) -> None:
        server, self._server = self._server, None
        if server:
            server.shutdown(); server.server_close()
        if self._thread:
            self._thread.join(timeout=2); self._thread = None

    def next_command(self) -> CompanionCommand | None:
        try:
            return self.commands.get_nowait()
        except queue.Empty:
            return None
