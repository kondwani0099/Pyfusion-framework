"""ASGI adapter for PyFusion: run any PyFusionApp on uvicorn, hypercorn or gunicorn (uvicorn workers).

HTTP requests go through the same transport-agnostic core as the stdlib server
(:meth:`PyFusionApp.handle_request`), so routing, CSRF, rate limiting and security headers are identical.

On top of that the ASGI transport adds a WebSocket channel at ``/_pyfusion/ws`` used for:

* component RPC (lower latency than one HTTP POST per action), and
* push-based live reload in development mode (no polling).

WebSocket security (Cross-Site WebSocket Hijacking protection):

* the ``Origin`` header must match the ``Host`` the browser connected to,
* the handshake must carry the CSRF token (``?csrf=``) matching the signed ``pyfusion_csrf`` cookie,
* handshakes and RPC messages count against the per-IP rate limiter,
* message size is capped by ``SecurityConfig.max_body_size``.

Usage::

    # web/app.py
    app = create_app()
    asgi_app = app.asgi        # or: from fusionlib.asgi import create_asgi_app

    $ uvicorn web.app:asgi_app --host 0.0.0.0 --port 8000 --proxy-headers
"""

import asyncio
import functools
import json
import logging
from urllib.parse import parse_qs, urlparse

from .security import csrf_tokens_match
from .web_server import (
    CSRF_COOKIE_NAME,
    WEBSOCKET_PATH,
    Headers,
    RawResponse,
    _parse_cookies,
)

logger = logging.getLogger("pyfusion")

LIVERELOAD_INTERVAL_SECONDS = 1.0


def _decode_headers(raw_headers):
    return Headers((k.decode("latin-1"), v.decode("latin-1")) for k, v in raw_headers or [])


def _client_ip(scope) -> str:
    client = scope.get("client")
    return client[0] if client else "127.0.0.1"


def origin_allowed(headers: Headers) -> bool:
    """Same-origin check for WebSocket handshakes. Non-browser clients (no Origin) still need the CSRF token."""
    origin = headers.get("origin")
    if not origin:
        return True
    netloc = urlparse(origin).netloc.lower()
    if not netloc:
        return False
    allowed = {h.strip().lower() for h in (headers.get("host", ""), headers.get("x-forwarded-host", "")) if h}
    return netloc in allowed


class PyFusionASGI:
    """ASGI 3 application wrapping a :class:`~fusionlib.web_server.PyFusionApp`."""

    def __init__(self, app, host: str = "localhost"):
        self.app = app
        self.host = host
        self._clients = set()
        self._watch_task = None

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind == "http":
            await self._http(scope, receive, send)
        elif kind == "websocket":
            await self._websocket(scope, receive, send)
        elif kind == "lifespan":
            await self._lifespan(receive, send)

    # --- lifespan ---

    async def _lifespan(self, receive, send):
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    self.app.prepare_for_serving(self.host)
                except Exception as exc:  # fail fast on insecure production configuration
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                    return
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                if self._watch_task is not None:
                    self._watch_task.cancel()
                await send({"type": "lifespan.shutdown.complete"})
                return

    # --- HTTP ---

    async def _send_raw(self, send, resp: RawResponse):
        await send({
            "type": "http.response.start",
            "status": resp.status,
            "headers": [(k.lower().encode("latin-1"), str(v).encode("latin-1")) for k, v in resp.headers],
        })
        await send({"type": "http.response.body", "body": resp.body})

    async def _http(self, scope, receive, send):
        if not self.app._prepared:
            # Lifespan disabled by the server: still refuse to serve with an insecure configuration.
            self.app.prepare_for_serving(self.host)

        method = scope.get("method", "GET")
        headers = _decode_headers(scope.get("headers"))
        limit = self.app.security.max_body_size

        try:
            declared = int(headers.get("content-length", "0") or 0)
        except ValueError:
            declared = -1
        if declared < 0:
            await self._send_raw(send, self.app.finalize_response(RawResponse.json(400, {"error": "Invalid Content-Length"}), method))
            return
        if declared > limit:
            await self._send_raw(send, self.app.finalize_response(RawResponse.json(413, {"error": "Payload too large"}), method))
            return

        body = bytearray()
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                await self._send_raw(send, self.app.finalize_response(RawResponse.json(413, {"error": "Payload too large"}), method))
                return
            more = message.get("more_body", False)

        raw_path = scope.get("raw_path") or scope.get("path", "/").encode("utf-8")
        raw_path = raw_path.decode("latin-1") if isinstance(raw_path, bytes) else raw_path
        query = scope.get("query_string", b"")
        if query:
            raw_path += "?" + query.decode("latin-1")

        loop = asyncio.get_running_loop()
        # Route handlers are synchronous (DB access, file IO); run them off the event loop.
        resp = await loop.run_in_executor(
            None,
            functools.partial(
                self.app.handle_request,
                method,
                raw_path,
                headers,
                bytes(body),
                _client_ip(scope),
                "asgi",
                loop,
            ),
        )
        await self._send_raw(send, resp)

    # --- WebSocket ---

    async def _websocket(self, scope, receive, send):
        message = await receive()
        if message["type"] != "websocket.connect":
            return
        if scope.get("path") != WEBSOCKET_PATH:
            await send({"type": "websocket.close", "code": 4404})
            return

        app = self.app
        headers = _decode_headers(scope.get("headers"))
        client_ip = _client_ip(scope)

        allowed, _ = app.rate_limiter.is_allowed(client_ip)
        if not allowed:
            await send({"type": "websocket.close", "code": 4429})
            return
        if not origin_allowed(headers):
            logger.warning("[PyFusion WS] Rejected cross-origin handshake from %s", headers.get("origin"))
            await send({"type": "websocket.close", "code": 4403})
            return
        if app.security.csrf_enabled:
            query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            token = (query.get("csrf") or [None])[0]
            cookies = _parse_cookies(headers.get("cookie", ""))
            if not csrf_tokens_match(cookies.get(CSRF_COOKIE_NAME), token, app.security.secret_key):
                await send({"type": "websocket.close", "code": 4403})
                return

        await send({"type": "websocket.accept"})
        lock = asyncio.Lock()
        closed = False

        async def send_json(payload):
            nonlocal closed
            if closed:
                return
            async with lock:
                try:
                    await send({"type": "websocket.send", "text": json.dumps(payload, default=str)})
                except Exception:
                    closed = True

        self._clients.add(send_json)
        if app.debug:
            self._ensure_watcher()

        loop = asyncio.get_running_loop()
        try:
            while True:
                message = await receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message["type"] != "websocket.receive":
                    continue
                text = message.get("text")
                if text is None:
                    text = (message.get("bytes") or b"").decode("utf-8", errors="replace")
                if len(text) > app.security.max_body_size:
                    await send_json({"type": "error", "error": "Payload too large"})
                    continue
                try:
                    data = json.loads(text)
                except ValueError:
                    await send_json({"type": "error", "error": "Malformed JSON"})
                    continue
                if not isinstance(data, dict):
                    continue

                kind = data.get("type")
                if kind == "ping":
                    await send_json({"type": "pong"})
                elif kind == "rpc":
                    msg_id = data.get("id")
                    ok, retry_after = app.rate_limiter.is_allowed(client_ip)
                    if not ok:
                        await send_json({
                            "type": "rpc_result",
                            "id": msg_id,
                            "status": 429,
                            "body": {"error": "Too many requests. Please slow down.", "retry_after": retry_after},
                        })
                        continue
                    status, body = await loop.run_in_executor(None, app.execute_rpc, data, client_ip)
                    await send_json({"type": "rpc_result", "id": msg_id, "status": status, "body": body})
        finally:
            closed = True
            self._clients.discard(send_json)

    # --- Development live reload (push) ---

    def _ensure_watcher(self):
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = asyncio.get_running_loop().create_task(self._watch_files())

    async def _watch_files(self):
        loop = asyncio.get_running_loop()
        last = await loop.run_in_executor(None, self.app._compute_livereload_hash)
        while True:
            await asyncio.sleep(LIVERELOAD_INTERVAL_SECONDS)
            if not self._clients:
                continue
            try:
                current = await loop.run_in_executor(None, self.app._compute_livereload_hash)
            except Exception:
                continue
            if current != last:
                last = current
                await self.broadcast({"type": "reload", "hash": current})

    async def broadcast(self, payload):
        """Send a JSON message to every connected browser (e.g. a server-initiated refresh)."""
        for client in list(self._clients):
            await client(payload)


def create_asgi_app(app=None, host: str = "localhost") -> PyFusionASGI:
    """Return an ASGI application for ``app`` (defaults to the global ``default_app``)."""
    if app is None:
        from .web_server import default_app

        app = default_app
    return PyFusionASGI(app, host=host)
