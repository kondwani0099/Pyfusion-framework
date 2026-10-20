"""End-to-end tests against real PyFusion HTTP & WebSocket servers (both stdlib and uvicorn ASGI backends)."""

import asyncio
import html
import json
import re
import urllib.error
import urllib.request

import pytest

from fusionlib.security import DEFAULT_CSP, STRICT_CSP, SecurityConfig
from fusionlib.web_server import create_app, run_web_server


class Client:
    def __init__(self, base):
        self.base = base
        self.cookies = {}

    def request(self, method, path, body=None, headers=None, json_body=None):
        headers = dict(headers or {})
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        elif body is not None:
            data = body.encode() if isinstance(body, str) else body
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            status, resp_headers, payload = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            status, resp_headers, payload = err.code, err.headers, err.read()
        for cookie in resp_headers.get_all("Set-Cookie") or []:
            name, _, rest = cookie.partition("=")
            self.cookies[name] = rest.split(";", 1)[0]
        return status, resp_headers, payload


def _start(project_dir, debug=True, backend="stdlib", security_config=None):
    app = create_app(
        web_dir=str(project_dir / "web"),
        components_dir=str(project_dir / "web" / "components"),
        debug=debug,
        security_config=security_config,
    )
    httpd = run_web_server(port=0, host="127.0.0.1", app=app, in_thread=True, server=backend)
    return app, httpd, Client(f"http://127.0.0.1:{httpd.server_address[1]}")


@pytest.fixture(params=["stdlib", "uvicorn"])
def server(project_dir, request):
    app, httpd, client = _start(project_dir, backend=request.param)
    yield app, client
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture()
def asgi_server(project_dir):
    app, httpd, client = _start(project_dir, backend="uvicorn")
    yield app, httpd, client
    httpd.shutdown()
    httpd.server_close()


def _component_snapshot(page_html):
    m = re.search(r'data-pyfusion-state="([^"]*)"\s+data-pyfusion-checksum="([^"]*)"', page_html)
    assert m, "component snapshot not rendered"
    return html.unescape(m.group(1)), html.unescape(m.group(2))


def _load_index(client):
    status, headers, body = client.request("GET", "/")
    assert status == 200
    return headers, body.decode()


def test_security_headers_and_csrf_cookie(server):
    _, client = server
    headers, page = _load_index(client)
    assert "Content-Security-Policy" in headers
    csp = headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "'unsafe-eval'" not in csp
    assert "'unsafe-inline'" not in csp.split("style-src")[0]
    assert headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "pyfusion_csrf" in client.cookies
    # Hidden token auto-injected into POST forms, matching the cookie
    assert f'name="csrf_token" value="{client.cookies["pyfusion_csrf"]}"' in page


def test_strict_csp_policy():
    assert "'unsafe-eval'" not in DEFAULT_CSP
    assert "'unsafe-eval'" not in STRICT_CSP
    assert "'unsafe-inline'" not in STRICT_CSP


def test_post_without_csrf_is_rejected(server):
    _, client = server
    _load_index(client)
    status, _, body = client.request("POST", "/submit_form", body="username=bob")
    assert status == 403
    assert json.loads(body)["code"] == "csrf_failed"


def test_post_with_form_token_succeeds(server):
    _, client = server
    _load_index(client)
    token = client.cookies["pyfusion_csrf"]
    status, _, body = client.request(
        "POST", "/submit_form", body=f"username=bob&csrf_token={token}", headers={"Accept": "application/json"}
    )
    assert status == 200
    assert "csrf_token" not in json.loads(body)["data"]


def test_rpc_happy_path_and_snapshot_rotation(server):
    _, client = server
    _, page = _load_index(client)
    snapshot, checksum = _component_snapshot(page)
    token = client.cookies["pyfusion_csrf"]
    payload = {
        "component_id": "Counter",
        "method": "increment",
        "args": [],
        "snapshot": snapshot,
        "checksum": checksum,
        "updates": {},
    }
    status, _, body = client.request("POST", "/_pyfusion/rpc", json_body=payload, headers={"X-CSRF-Token": token})
    assert status == 200, body
    data = json.loads(body)
    assert data["state"]["count"] == 1
    # Chained call using the server-issued snapshot
    payload.update(snapshot=data["snapshot"], checksum=data["checksum"])
    status, _, body = client.request("POST", "/_pyfusion/rpc", json_body=payload, headers={"X-CSRF-Token": token})
    assert json.loads(body)["state"]["count"] == 2


def test_rpc_rejects_tampered_snapshot(server):
    _, client = server
    _, page = _load_index(client)
    snapshot, checksum = _component_snapshot(page)
    tampered = snapshot.replace('"count":0', '"count":1000000')
    assert tampered != snapshot
    status, _, body = client.request(
        "POST",
        "/_pyfusion/rpc",
        json_body={"component_id": "Counter", "method": "increment", "snapshot": tampered, "checksum": checksum},
        headers={"X-CSRF-Token": client.cookies["pyfusion_csrf"]},
    )
    assert status == 403
    assert json.loads(body)["code"] == "stale_state"


def test_rpc_rejects_locked_update_and_private_method(server):
    _, client = server
    _, page = _load_index(client)
    snapshot, checksum = _component_snapshot(page)
    hdrs = {"X-CSRF-Token": client.cookies["pyfusion_csrf"]}
    base = {"component_id": "Counter", "snapshot": snapshot, "checksum": checksum}

    status, _, _ = client.request(
        "POST",
        "/_pyfusion/rpc",
        headers=hdrs,
        json_body={**base, "method": "increment", "updates": {"count": 500}},
    )
    assert status == 403
    for method in ("_private_helper", "helper_imported", "render_page"):
        status, _, _ = client.request("POST", "/_pyfusion/rpc", headers=hdrs, json_body={**base, "method": method})
        assert status == 403, method


def test_rpc_requires_csrf(server):
    _, client = server
    _, page = _load_index(client)
    snapshot, checksum = _component_snapshot(page)
    status, _, _ = client.request(
        "POST",
        "/_pyfusion/rpc",
        json_body={"component_id": "Counter", "method": "increment", "snapshot": snapshot, "checksum": checksum},
    )
    assert status == 403


def test_static_protection_and_bundled_css(server):
    _, client = server
    assert client.request("GET", "/secret.py")[0] == 403
    assert client.request("GET", "/components/Counter.fusion")[0] == 403
    assert client.request("GET", "/assets/")[0] == 404  # no directory listing
    assert client.request("GET", "/assets/styles.css")[0] == 200
    status, hdrs, css = client.request("GET", "/_pyfusion/pyfusion.css")
    assert status == 200
    assert "text/css" in hdrs["Content-Type"]
    assert len(css) > 10_000


def test_service_worker_skips_cross_origin(server):
    _, client = server
    status, _, js = client.request("GET", "/sw.js")
    assert status == 200
    assert b"self.location.origin" in js


def test_websocket_rpc_and_cswsh_protection(asgi_server):
    import websockets
    from websockets.exceptions import InvalidStatus

    _, httpd, client = asgi_server
    _, page = _load_index(client)
    snapshot, checksum = _component_snapshot(page)
    csrf = client.cookies["pyfusion_csrf"]
    host, port = httpd.server_address
    ws_base = f"ws://{host}:{port}/_pyfusion/ws"

    async def _exercise():
        # 1. Valid same-origin + CSRF handshake -> ping & RPC increment
        async with websockets.connect(
            f"{ws_base}?csrf={csrf}",
            origin=f"http://{host}:{port}",
            additional_headers={"Cookie": f"pyfusion_csrf={csrf}"},
        ) as ws:
            await ws.send(json.dumps({"type": "ping"}))
            pong = json.loads(await ws.recv())
            assert pong == {"type": "pong"}

            await ws.send(
                json.dumps(
                    {
                        "type": "rpc",
                        "id": 42,
                        "component_id": "Counter",
                        "method": "increment",
                        "args": [],
                        "snapshot": snapshot,
                        "checksum": checksum,
                        "updates": {},
                    }
                )
            )
            res = json.loads(await ws.recv())
            assert res["type"] == "rpc_result"
            assert res["id"] == 42
            assert res["status"] == 200
            assert res["body"]["state"]["count"] == 1

        # 2. Cross-origin Origin header must be rejected (CSWSH protection)
        with pytest.raises((InvalidStatus, Exception)):
            async with websockets.connect(
                f"{ws_base}?csrf={csrf}",
                origin="https://evil.example.com",
                additional_headers={"Cookie": f"pyfusion_csrf={csrf}"},
            ):
                pass

        # 3. Missing/mismatched CSRF token must be rejected
        with pytest.raises((InvalidStatus, Exception)):
            async with websockets.connect(
                f"{ws_base}?csrf=wrong-token",
                origin=f"http://{host}:{port}",
                additional_headers={"Cookie": f"pyfusion_csrf={csrf}"},
            ):
                pass

    asyncio.run(_exercise())


def test_production_mode_hardening(project_dir):
    app, httpd, client = _start(project_dir, debug=False, backend="uvicorn")
    try:
        assert client.request("GET", "/_pyfusion/livereload")[0] == 404
        status, _, body = client.request("GET", "/api/health")
        assert json.loads(body) == {"status": "ok"}
        status, _, js = client.request("GET", "/_pyfusion/client.js")
        assert b"const LIVERELOAD_ENABLED = false" in js
        assert b"const WEBSOCKET_ENABLED = true" in js
        _load_index(client)
        status, _, _ = client.request(
            "POST",
            "/api/project/launch-mobile",
            json_body={},
            headers={"X-CSRF-Token": client.cookies["pyfusion_csrf"]},
        )
        assert status == 403  # developer tools disabled in production
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_production_requires_secret_key(project_dir, monkeypatch):
    monkeypatch.delenv("PYFUSION_SECRET_KEY", raising=False)

    app = create_app(
        web_dir=str(project_dir / "web"),
        components_dir=str(project_dir / "web" / "components"),
        debug=False,
        security_config=SecurityConfig(),
    )
    with pytest.raises(RuntimeError):
        app.prepare_for_serving("0.0.0.0")
