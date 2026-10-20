# web_server.py
import asyncio
import hashlib
import inspect
import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
import webbrowser
from email.utils import formatdate
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer
from urllib.parse import parse_qs, unquote, urlparse

from .component import Component, get_client_runtime_js, load_sfc, serialize_state, set_default_state_secret
from .reactivity import FusionPlugin, FusionStore
from .security import (
    RateLimiter,
    SecurityConfig,
    csrf_tokens_match,
    escape_html,
    generate_csrf_token,
    get_owasp_security_headers,
    is_loopback,
    is_safe_static_path,
    sign_state,
    verify_csrf_token,
    verify_state,
)

logger = logging.getLogger("pyfusion")

CSRF_COOKIE_NAME = "pyfusion_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"
SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
WEBSOCKET_PATH = "/_pyfusion/ws"

_STATIC_MIME_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain",
    ".map": "application/json",
    ".wasm": "application/wasm",
}

_FORM_POST_RE = re.compile(r"(<form\b[^>]*\bmethod\s*=\s*[\"']?post[\"']?[^>]*>)", re.IGNORECASE)


def _resolve_debug(debug=None) -> bool:
    """Resolve development/production mode.

    Precedence: explicit argument > PYFUSION_DEBUG > PYFUSION_ENV ("production"/"prod" disables debug).
    Development mode is the default so `pyfusion run web` keeps hot reload out of the box.
    """
    if debug is not None:
        return bool(debug)
    flag = os.environ.get("PYFUSION_DEBUG", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return os.environ.get("PYFUSION_ENV", "").strip().lower() not in ("production", "prod")


def _load_or_create_dev_secret(base_dir: str) -> str:
    """Persist a per-project development secret (like Rails' tmp/local_secret.txt) so restarts keep sessions valid."""
    path = os.path.join(base_dir, ".pyfusion", "dev_secret")
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                value = f.read().strip()
            if len(value) >= 32:
                return value
        os.makedirs(os.path.dirname(path), exist_ok=True)
        value = secrets.token_hex(32)
        with open(path, "w", encoding="utf-8") as f:
            f.write(value)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return value
    except OSError:
        return secrets.token_hex(32)


def inject_csrf_into_forms(html_text: str, token: str) -> str:
    """Add a hidden csrf_token field to every <form method="post"> (Django/Rails-style automatic form protection)."""
    if not token or "<form" not in html_text.lower():
        return html_text
    hidden = f'<input type="hidden" name="{CSRF_FORM_FIELD}" value="{escape_html(token)}">'
    return _FORM_POST_RE.sub(lambda m: m.group(1) + hidden, html_text)


def _parse_cookies(raw_cookie: str) -> dict:
    cookies = {}
    if raw_cookie:
        cookie = SimpleCookie()
        try:
            cookie.load(raw_cookie)
            cookies = {k: v.value for k, v in cookie.items()}
        except Exception:
            pass
    return cookies


class Headers:
    """Case-insensitive, read-only mapping of request headers shared by every transport.

    Repeated headers are joined with ", " ("; " for Cookie), mirroring how HTTP folds them.
    """

    def __init__(self, items=None):
        self._data = {}
        if items is None:
            items = ()
        elif hasattr(items, "items"):
            items = items.items()
        for key, value in items:
            name = str(key).lower()
            value = str(value)
            if name in self._data:
                self._data[name] += ("; " if name == "cookie" else ", ") + value
            else:
                self._data[name] = value

    def get(self, name, default=None):
        return self._data.get(str(name).lower(), default)

    def __getitem__(self, name):
        return self._data[str(name).lower()]

    def __contains__(self, name):
        return str(name).lower() in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def items(self):
        return self._data.items()

    def keys(self):
        return self._data.keys()


class RawResponse:
    """Transport-level response produced by :meth:`PyFusionApp.handle_request` (status, header list, bytes)."""

    __slots__ = ("status", "headers", "body")

    def __init__(self, status=200, headers=None, body=b""):
        self.status = int(status)
        self.headers = list(headers or [])
        self.body = body or b""

    @classmethod
    def json(cls, status, payload, extra_headers=None):
        body = json.dumps(payload, default=str).encode("utf-8")
        headers = [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")]
        headers.extend(extra_headers or [])
        return cls(status, headers, body)

    def get_header(self, name, default=None):
        lname = name.lower()
        for k, v in self.headers:
            if k.lower() == lname:
                return v
        return default


class Request:
    """Represents an incoming HTTP request with parsed query, form, JSON, cookies, and client IP."""

    def __init__(
        self, method, path, headers, body_bytes=b"", route_params=None, client_ip="127.0.0.1", transport="stdlib"
    ):
        self.method = method.upper()
        parsed_url = urlparse(path)
        self.raw_path = path
        self.path = parsed_url.path
        self.headers = headers if isinstance(headers, Headers) else Headers(getattr(headers, "items", lambda: headers)())
        self.body = body_bytes
        self.route_params = route_params or {}
        self.client_ip = client_ip
        # "stdlib" (threaded http.server) or "asgi" (uvicorn / any ASGI server)
        self.transport = transport
        self.csrf_token = None
        self.db = None

        # Parse cookies
        self.cookies = _parse_cookies(self.headers.get("Cookie", ""))

        # Parse query parameters
        raw_query = parse_qs(parsed_url.query, keep_blank_values=True)
        self.query = {k: v[0] if len(v) == 1 else v for k, v in raw_query.items()}

        # Parse body into form or json
        self.form = {}
        self.json = None
        content_type = self.headers.get("Content-Type", "")
        text_body = body_bytes.decode("utf-8", errors="replace") if body_bytes else ""
        self.text = text_body

        if "application/json" in content_type and text_body:
            try:
                self.json = json.loads(text_body)
            except json.JSONDecodeError:
                self.json = None
        elif "application/x-www-form-urlencoded" in content_type or (self.method == "POST" and "=" in text_body):
            parsed_form = parse_qs(text_body, keep_blank_values=True)
            self.form = {k: v[0] if len(v) == 1 else v for k, v in parsed_form.items()}


class Response:
    """Represents an outgoing HTTP response."""

    def __init__(self, body="", status=200, headers=None, content_type="text/html; charset=utf-8"):
        self.status = status
        self.headers = headers or {}
        self.content_type = content_type

        if isinstance(body, (dict, list)):
            self.body = json.dumps(body, default=str).encode("utf-8")
            self.content_type = "application/json; charset=utf-8"
        elif isinstance(body, bytes):
            self.body = body
        else:
            self.body = str(body).encode("utf-8")


def render_template(template_name, web_dir=None, **context):
    """
    Render an HTML template from the web directory with OWASP XSS-safe {{ variable }} interpolation.
    Use {{{ raw_html }}} only for explicitly trusted HTML strings.
    """
    if web_dir is None:
        web_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../web"))
        if not os.path.exists(web_dir):
            web_dir = os.path.abspath("web")

    is_safe, template_path = is_safe_static_path(web_dir, template_name)
    if not is_safe or not os.path.exists(template_path):
        raise FileNotFoundError(f"Template not found or blocked: {template_name}")

    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Raw unescaped interpolation: {{{ var }}}
    def replace_raw(match):
        key = match.group(1).strip()
        return str(context.get(key, ""))

    content = re.sub(r"\{\{\{\s*([a-zA-Z0-9_]+)\s*\}\}\}", replace_raw, content)

    # Escaped XSS-safe interpolation: {{ var }}
    def replace_escaped(match):
        key = match.group(1).strip()
        if key not in context:
            return match.group(0)
        return escape_html(context[key])

    return re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", replace_escaped, content)


class PyFusionApp:
    """
    Vue.js-inspired application container with built-in OWASP Top 10 Security,
    Database plugin integration, and Browser Live-Reload (development mode).
    """

    def __init__(self, root_component=None, web_dir=None, components_dir=None, security_config=None, debug=None):
        if web_dir is None:
            default_web = os.path.abspath(os.path.join(os.path.dirname(__file__), "../web"))
            self.web_dir = default_web if os.path.exists(default_web) else os.path.abspath("web")
        else:
            self.web_dir = os.path.abspath(web_dir)

        if components_dir is None:
            web_comp = os.path.join(self.web_dir, "components")
            legacy_comp = os.path.abspath(os.path.join(os.path.dirname(__file__), "../components"))
            if os.path.exists(web_comp):
                self.components_dir = web_comp
            elif os.path.exists(legacy_comp):
                self.components_dir = legacy_comp
            else:
                self.components_dir = web_comp
        else:
            self.components_dir = os.path.abspath(components_dir)

        self.debug = _resolve_debug(debug)
        self.security = security_config or SecurityConfig()
        self.rate_limiter = RateLimiter(max_requests=self.security.rate_limit_per_minute, window_seconds=60)
        set_default_state_secret(self.security.secret_key)

        self.routes = []
        self.components = {}
        self.stores = {}
        self.plugins = []
        self.config = {}
        self.db = None
        self.csrf_exempt_paths = set()
        self._prepared = False

        self._discover_sfc_components()
        self._register_default_routes()

        if root_component is not None:
            self.mount("/", root_component)

    # --- Lifecycle ---

    def prepare_for_serving(self, host: str = "localhost"):
        """Validate configuration before accepting traffic (fail fast on insecure production setups)."""
        if self._prepared:
            return
        if self.security.secret_key_is_ephemeral:
            if self.debug:
                self.security.secret_key = _load_or_create_dev_secret(os.getcwd())
                self.security.secret_key_is_ephemeral = False
            else:
                raise RuntimeError(
                    "PYFUSION_SECRET_KEY must be set in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
        set_default_state_secret(self.security.secret_key)

        if not self.debug and not is_loopback(host) and host != "localhost" and not self.security.enable_hsts:
            logger.warning(
                "PyFusion is serving on %s without HSTS. Terminate TLS at a reverse proxy and pass "
                "SecurityConfig(enable_hsts=True) so cookies are marked Secure.",
                host,
            )
        self._prepared = True

    def _compute_livereload_hash(self) -> str:
        """Compute a digest of modification times across web/, components/, and .py files for instant browser reload."""
        hasher = hashlib.md5(usedforsecurity=False)
        watch_dirs = [self.web_dir, self.components_dir, os.getcwd()]
        seen = set()
        for d in watch_dirs:
            if not d or not os.path.exists(d):
                continue
            for root, dirs, files in os.walk(d):
                dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", "env", "venv", ".venv", "node_modules")]
                for f in sorted(files):
                    if f.endswith((".html", ".css", ".js", ".fusion", ".py")):
                        full = os.path.join(root, f)
                        if full in seen:
                            continue
                        seen.add(full)
                        try:
                            mtime = os.stat(full).st_mtime_ns
                            hasher.update(f"{full}:{mtime};".encode("utf-8"))
                        except OSError:
                            pass
                if d == os.getcwd():
                    # Don't recurse deeply from cwd if we already walk web_dir and components_dir
                    break
        return hasher.hexdigest()[:12]

    def _discover_sfc_components(self):
        """Auto-register or hot-reload any .fusion Single-File Components inside components/."""
        if os.path.exists(self.components_dir):
            for fname in os.listdir(self.components_dir):
                if fname.endswith(".fusion"):
                    comp_name = os.path.splitext(fname)[0]
                    full_path = os.path.join(self.components_dir, fname)
                    try:
                        existing = self.components.get(comp_name)
                        mtime = os.path.getmtime(full_path)
                        if existing is None or getattr(existing, "_sfc_mtime", None) != mtime:
                            self.component(comp_name, full_path)
                    except Exception as exc:
                        logger.warning("[PyFusion] Failed to compile %s: %s", fname, exc)

    def _hot_reload_components(self):
        """Re-scan .fusion files on each request in development mode only (production compiles once)."""
        if self.debug:
            self._discover_sfc_components()

    def render_html_with_components(self, html_content: str) -> str:
        """Expand any registered <ComponentName /> or <ComponentName></ComponentName> tags inside HTML."""
        self._hot_reload_components()
        if not self.components:
            return html_content

        rendered = html_content
        secret = self.security.secret_key
        for _ in range(4):
            changed = False
            for tag_name, comp_cls in list(self.components.items()):
                pattern = re.compile(
                    rf"<{tag_name}(\s+[^/>]*?)?\s*(?:/>|></{tag_name}>)",
                    re.IGNORECASE | re.DOTALL,
                )
                if pattern.search(rendered):
                    def replace_tag(match, cls=comp_cls):
                        attr_str = match.group(1) or ""
                        parsed_props = dict(re.findall(r'([a-zA-Z0-9_-]+)=["\']([^"\']*)["\']', attr_str))
                        instance = cls(**parsed_props)
                        return instance.render_fragment(registry=self.components, secret=secret)

                    rendered = pattern.sub(replace_tag, rendered)
                    changed = True
            if not changed:
                break
        return rendered

    # --- Vue.js-style Extensibility API ---

    def component(self, name: str, component_or_path):
        """Register a global component (class or .fusion Single-File Component path)."""
        if isinstance(component_or_path, str):
            comp_cls = load_sfc(component_or_path, component_name=name)
        else:
            comp_cls = component_or_path
            comp_cls.name = name

        self.components[name] = comp_cls
        return self

    def use(self, plugin, **options):
        """Install a PyFusion plugin (like Vue's app.use(plugin, options))."""
        if isinstance(plugin, FusionPlugin) or hasattr(plugin, "install"):
            plugin.install(self, **options)
        elif callable(plugin):
            plugin(self, **options)
        else:
            raise TypeError("Plugin must have an install(app, **options) method or be callable.")
        self.plugins.append(plugin)
        return self

    def store(self, store_instance: FusionStore):
        """Register a reactive store (Pinia/Vuex style)."""
        self.stores[store_instance.id] = store_instance
        return self

    def mount(self, route_path: str, component_or_path, title: str = None):
        """Mount a Component or .fusion file directly onto a URL route."""
        if isinstance(component_or_path, str):
            comp_name = os.path.splitext(os.path.basename(component_or_path))[0]
            comp_cls = load_sfc(component_or_path, component_name=comp_name)
        elif isinstance(component_or_path, Component):
            comp_cls = component_or_path.__class__
        else:
            comp_cls = component_or_path

        comp_name = getattr(comp_cls, "name", None) or comp_cls.__name__
        self.components[comp_name] = comp_cls

        @self.route(route_path, methods=["GET"])
        def mounted_component_view(request: Request):
            self._hot_reload_components()
            latest_cls = self.components.get(comp_name, comp_cls)
            # Only declared props may be set from the query string (mass-assignment protection)
            instance = latest_cls(**latest_cls.declared_props(request.query))
            csrf_tok = request.csrf_token or generate_csrf_token(self.security.secret_key)
            return instance.render_page(
                title=title or comp_name,
                registry=self.components,
                csrf_token=csrf_tok,
                secret=self.security.secret_key,
            )

        mounted_component_view.__name__ = f"mount_{comp_name}"
        return self

    def csrf_exempt(self, path_or_func=None):
        """Exempt a route path from CSRF checks (e.g. signed third-party webhooks).

        Usage: ``app.csrf_exempt("/webhooks/stripe")`` or as a decorator placed *above* ``@app.post(...)``.
        """
        if isinstance(path_or_func, str):
            self.csrf_exempt_paths.add(path_or_func)
            return path_or_func

        def decorator(func):
            for r in self.routes:
                if r["handler"] is func:
                    self.csrf_exempt_paths.add(r["path"])
            return func

        return decorator(path_or_func) if callable(path_or_func) else decorator

    def is_csrf_exempt(self, path: str) -> bool:
        for r in self.routes:
            if r["path"] in self.csrf_exempt_paths and r["regex"].match(path):
                return True
        return path in self.csrf_exempt_paths

    def _dev_tools_guard(self, request: Request):
        """Developer-studio endpoints mutate the local machine; allow them only on localhost in development mode."""
        if self.debug and is_loopback(request.client_ip):
            return None
        return Response(
            {"error": "Developer tools are only available on localhost in development mode.", "code": "dev_only"},
            status=403,
        )

    def _register_default_routes(self):
        @self.route("/_pyfusion/client.js", methods=["GET"])
        def serve_client_runtime(request: Request):
            return Response(
                body=get_client_runtime_js(livereload=self.debug, websocket=request.transport == "asgi"),
                status=200,
                headers={"Cache-Control": "no-cache"},
                content_type="application/javascript; charset=utf-8",
            )

        @self.route("/_pyfusion/pyfusion.css", methods=["GET"])
        def serve_bundled_css(request: Request):
            # Precompiled Tailwind + daisyUI bundle used by Component.render_page (no CDN, CSP-friendly).
            css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "pyfusion.css")
            try:
                with open(css_path, "rb") as f:
                    css = f.read()
            except OSError:
                return Response({"error": "Not found"}, status=404)
            return Response(
                body=css,
                status=200,
                headers={"Cache-Control": "public, max-age=86400"},
                content_type="text/css; charset=utf-8",
            )

        @self.route("/_pyfusion/livereload", methods=["GET"])
        def serve_livereload_hash(request: Request):
            if not self.debug:
                return Response({"error": "Not found"}, status=404)
            self._discover_sfc_components()
            return {
                "hash": self._compute_livereload_hash(),
                "components": list(self.components.keys()),
            }

        @self.route("/_pyfusion/rpc", methods=["POST"])
        def handle_component_rpc(request: Request):
            payload = request.json if isinstance(request.json, dict) else {}
            status, body = self.execute_rpc(payload, request.client_ip)
            return Response(body, status=status)

        @self.route("/api/security/audit", methods=["GET"])
        def security_audit(request: Request):
            sec = self.security
            return {
                "status": "ok",
                "mode": "development" if self.debug else "production",
                "standard": "OWASP Top 10 (2021)",
                "protections": {
                    "A01_Broken_Access_Control": "Path traversal blocking, no directory listing, RPC action allowlist, "
                    "locked props, localhost-only developer tools",
                    "A02_Cryptographic_Failures": "PBKDF2-HMAC-SHA256 (600k iterations), HMAC-SHA256 signed tokens "
                    "and component state snapshots",
                    "A03_Injection": "Parameterized SQL, SQL identifier validation, automatic HTML escaping"
                    + (", Content-Security-Policy" if sec.content_security_policy else ""),
                    "A04_Insecure_Design": f"Sliding-window IP rate limiter ({sec.rate_limit_per_minute} req/min), "
                    f"{sec.max_body_size // 1024} KB body cap, 30s socket timeout",
                    "A05_Security_Misconfiguration": "OWASP HTTP headers, server version hidden, generic error messages "
                    "in production",
                    "A07_Identification_And_Auth": "CSRF signed double-submit cookie "
                    + ("(enforced)" if sec.csrf_enabled else "(DISABLED)"),
                    "A08_Software_And_Data_Integrity": "State snapshot checksums "
                    + ("(enforced)" if sec.state_signing else "(DISABLED)"),
                },
                "headers_active": list(get_owasp_security_headers(sec).keys()),
                "secure_cookies": sec.secure_cookies,
            }

        @self.route("/submit_form", methods=["POST"])
        def default_submit_form(request: Request):
            username = escape_html(request.form.get("username", "Guest"))
            accept = request.headers.get("Accept", "")
            if "application/json" in accept:
                safe_form = {k: v for k, v in request.form.items() if k != CSRF_FORM_FIELD}
                return {"status": "success", "message": f"Form submitted by {username}", "data": safe_form}
            return (
                f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<title>Form Submitted</title>"
                f"<link rel='stylesheet' href='/styles.css'></head>"
                f"<body style='font-family: sans-serif; text-align: center; padding: 40px;'>"
                f"<h2>Thank you, {username}!</h2>"
                f"<p>Your form data was received safely by PyFusion Server.</p>"
                f"<a href='/'>Return Home</a></body></html>"
            )

        @self.route("/api/project/config", methods=["GET", "POST"])
        def project_config_route(request: Request):
            denied = self._dev_tools_guard(request)
            if denied:
                return denied
            from .config import ensure_project_ico, load_project_config, save_project_config

            if request.method == "POST":
                data = request.json or request.form or {}
                updates = {}
                for k in ("project_name", "app_title", "author", "icon", "theme_color", "engine"):
                    if k in data and str(data[k]).strip():
                        updates[k] = str(data[k]).strip()
                cfg = save_project_config(updates)
                ico = ensure_project_ico(cfg.get("icon"))
                return {"status": "saved", "config": cfg, "ico_path": ico}

            return {"status": "ok", "config": load_project_config()}

        @self.route("/api/project/save-desktop", methods=["POST"])
        def save_desktop_route(request: Request):
            denied = self._dev_tools_guard(request)
            if denied:
                return denied
            from .config import create_desktop_shortcut, ensure_project_ico, save_project_config

            data = request.json or request.form or {}
            updates = {}
            for k in ("project_name", "app_title", "author", "icon"):
                if k in data and str(data[k]).strip():
                    updates[k] = str(data[k]).strip()
            if updates:
                save_project_config(updates)
            ensure_project_ico()
            result = create_desktop_shortcut()
            return {"status": "saved", "shortcut_info": result}

        @self.route("/api/project/build-android", methods=["POST"])
        def build_android_route(request: Request):
            denied = self._dev_tools_guard(request)
            if denied:
                return denied
            from .config import generate_android_project, save_project_config

            data = request.json or request.form or {}
            updates = {}
            for k in ("project_name", "app_title", "author", "icon"):
                if k in data and str(data[k]).strip():
                    updates[k] = str(data[k]).strip()
            if updates:
                save_project_config(updates)
            fmt = str(data.get("format", "both")).strip().lower()
            android_info = generate_android_project(artifact_format=fmt)
            return {"status": "generated", "android_info": android_info}

        @self.route("/api/project/launch-mobile", methods=["POST"])
        def launch_mobile_route(request: Request):
            denied = self._dev_tools_guard(request)
            if denied:
                return denied
            from .config import launch_mobile_detached

            pid = launch_mobile_detached()
            return {"status": "launched", "pid": pid}

        @self.route("/manifest.json", methods=["GET"])
        def pwa_manifest(request: Request):
            from .config import load_project_config

            cfg = load_project_config()
            return {
                "name": cfg.get("app_title", "PyFusion App"),
                "short_name": cfg.get("project_name", "PyFusion"),
                "start_url": "/",
                "display": "standalone",
                "orientation": "portrait",
                "background_color": "#0b1120",
                "theme_color": cfg.get("theme_color", "#10b981"),
                "icons": [
                    {"src": "/assets/logo.png", "sizes": "192x192", "type": "image/png"},
                    {"src": "/assets/logo.png", "sizes": "512x512", "type": "image/png"},
                ],
            }

        @self.route("/sw.js", methods=["GET"])
        def pwa_service_worker(request: Request):
            # Only handle same-origin GETs. Cross-origin assets (CDNs) go straight to the network; proxying them
            # through the worker would subject them to the worker's own CSP (connect-src 'self') and break them.
            sw_code = (
                "self.addEventListener('install', e => self.skipWaiting());\n"
                "self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));\n"
                "self.addEventListener('fetch', e => {\n"
                "  if (e.request.method !== 'GET') return;\n"
                "  if (new URL(e.request.url).origin !== self.location.origin) return;\n"
                "  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));\n"
                "});\n"
            )
            return Response(
                body=sw_code,
                status=200,
                headers={"Cache-Control": "no-cache"},
                content_type="application/javascript; charset=utf-8",
            )

        @self.route("/api/health", methods=["GET"])
        def health_check(request: Request):
            if not self.debug:
                # Liveness probe only: do not disclose internals in production (OWASP A05)
                return {"status": "ok"}

            from .config import load_project_config
            from .mobile_simulator import get_lan_ip

            cfg = load_project_config()
            return {
                "status": "ok",
                "framework": "PyFusion",
                "mode": "development",
                "project_name": cfg.get("project_name", "PyFusion-Studio"),
                "app_title": cfg.get("app_title", "Uniplexity AI - PyFusion"),
                "icon": cfg.get("icon", "web/assets/logo.png"),
                "paths": cfg.get("paths", {}),
                "lan_url": f"http://{get_lan_ip()}:{cfg.get('port', 5000)}",
                "live_reload": True,
                "owasp_hardened": True,
                "android_ready": True,
                "database_connected": self.db is not None,
                "components": list(self.components.keys()),
                "stores": list(self.stores.keys()),
            }

    def route(self, path, methods=None):
        """Decorator to register a URL route handler."""
        if methods is None:
            methods = ["GET"]
        methods = [m.upper() for m in methods]

        pattern_str = re.sub(r"<([a-zA-Z_][a-zA-Z0-9_]*)>", r"(?P<\1>[^/]+)", path)
        regex = re.compile(f"^{pattern_str}$")

        def decorator(func):
            self.routes = [r for r in self.routes if not (r["path"] == path and r["methods"] == methods)]
            self.routes.append({
                "path": path,
                "regex": regex,
                "methods": methods,
                "handler": func,
            })
            return func

        return decorator

    def get(self, path):
        return self.route(path, methods=["GET"])

    def post(self, path):
        return self.route(path, methods=["POST"])

    def put(self, path):
        return self.route(path, methods=["PUT"])

    def patch(self, path):
        return self.route(path, methods=["PATCH"])

    def delete(self, path):
        return self.route(path, methods=["DELETE"])

    def match_route(self, path, method):
        method = method.upper()
        for route in self.routes:
            match = route["regex"].match(path)
            if match and method in route["methods"]:
                return route["handler"], match.groupdict()
        return None, {}

    # --- Component RPC (shared by HTTP POST /_pyfusion/rpc and the WebSocket transport) ---

    def execute_rpc(self, payload, client_ip: str = "127.0.0.1"):
        """Verify a component action request and run it. Returns ``(status_code, json_body)``.

        Transport security (CSRF for HTTP, Origin + CSRF handshake for WebSockets) is enforced by the caller.
        """
        self._hot_reload_components()
        if not isinstance(payload, dict):
            return 400, {"error": "Invalid request", "code": "bad_request"}
        comp_id = payload.get("component_id")
        method_name = payload.get("method")
        args = payload.get("args", [])
        secret = self.security.secret_key

        if not isinstance(comp_id, str) or comp_id not in self.components:
            return 404, {"error": "Unknown component", "code": "unknown_component"}

        snapshot = None
        if self.security.state_signing:
            snapshot_raw = payload.get("snapshot")
            if not verify_state(comp_id, snapshot_raw, payload.get("checksum"), secret):
                return 403, {
                    "error": "Component state failed its integrity check. Please reload the page.",
                    "code": "stale_state",
                }
            try:
                snapshot = json.loads(snapshot_raw)
            except (TypeError, ValueError):
                return 400, {"error": "Malformed state snapshot", "code": "bad_request"}
            updates = payload.get("updates") or {}
        else:
            updates = payload.get("updates") or payload.get("state") or {}

        comp_cls = self.components[comp_id]
        instance = comp_cls()

        if isinstance(method_name, str) and instance.is_local_only_action(method_name):
            if not (self.debug and is_loopback(client_ip)):
                return 403, {
                    "error": "This action is only available on localhost in development mode.",
                    "code": "local_only",
                }

        try:
            new_state = instance.invoke_method(method_name, args=args, client_state=updates, snapshot=snapshot)
        except PermissionError as exc:
            return 403, {"error": str(exc), "code": "forbidden"}
        except ValueError as exc:
            return 400, {"error": str(exc) if self.debug else "Invalid request", "code": "bad_request"}
        except Exception as exc:
            logger.exception("[PyFusion RPC Error] %s.%s", comp_id, method_name)
            return 500, {"error": str(exc) if self.debug else "Internal server error", "code": "server_error"}

        snapshot_json = serialize_state(new_state)
        return 200, {
            "status": "ok",
            "component": comp_id,
            "state": new_state,
            "snapshot": snapshot_json,
            "checksum": sign_state(comp_id, snapshot_json, secret),
        }

    # --- Transport-agnostic HTTP core (used by the stdlib server and the ASGI adapter) ---

    def resolve_csrf_token(self, cookies: dict):
        """Return (token, is_new). Invalid or foreign cookies (e.g. after a secret rotation) are replaced."""
        secret = self.security.secret_key
        existing = cookies.get(CSRF_COOKIE_NAME)
        if existing and verify_csrf_token(existing, secret):
            return existing, False
        return generate_csrf_token(secret), True

    def csrf_cookie_header(self, token: str) -> str:
        parts = [f"{CSRF_COOKIE_NAME}={token}", "Path=/", "SameSite=Lax"]
        if self.security.secure_cookies:
            parts.append("Secure")
        return "; ".join(parts)

    def finalize_response(self, resp: RawResponse, method: str = "GET") -> RawResponse:
        """Attach OWASP security headers and Content-Length; strip the body for HEAD requests."""
        present = {k.lower() for k, _ in resp.headers}
        for k, v in get_owasp_security_headers(self.security).items():
            if k.lower() not in present:
                resp.headers.append((k, v))
        if "content-length" not in present and resp.status not in (204, 304):
            resp.headers.append(("Content-Length", str(len(resp.body))))
        if method.upper() == "HEAD" or resp.status in (204, 304):
            resp.body = b""
        return resp

    def handle_request(
        self,
        method: str,
        raw_path: str,
        headers=None,
        body: bytes = b"",
        client_ip: str = "127.0.0.1",
        transport: str = "stdlib",
        loop=None,
    ) -> RawResponse:
        """Process one HTTP request end-to-end: rate limit, routing, CSRF, handlers, static files, headers.

        ``loop`` is the ASGI server's event loop; async route handlers are scheduled on it.
        """
        method = (method or "GET").upper()
        if not isinstance(headers, Headers):
            headers = Headers(headers)
        body = body or b""
        path = urlparse(raw_path).path or "/"

        # Livereload polling is exempt from the rate limit counter
        if path != "/_pyfusion/livereload":
            allowed, retry_after = self.rate_limiter.is_allowed(client_ip)
            if not allowed:
                resp = RawResponse.json(
                    429,
                    {"error": "Too many requests. Please slow down.", "retry_after": retry_after},
                    [("Retry-After", str(retry_after))],
                )
                return self.finalize_response(resp, method)

        if len(body) > self.security.max_body_size:
            return self.finalize_response(RawResponse.json(413, {"error": "Payload too large"}), method)

        effective = "GET" if method == "HEAD" else method
        try:
            handler, route_params = self.match_route(path, effective)
            if handler is not None:
                resp = self._dispatch(handler, route_params, effective, raw_path, path, headers, body, client_ip, transport, loop)
            elif effective == "GET":
                resp = self._serve_static(path, headers)
            elif effective == "OPTIONS":
                resp = RawResponse(204, [("Allow", "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS")])
            else:
                resp = RawResponse.json(404, {"error": "Route not found"})
        except Exception as exc:
            logger.exception("[PyFusion Request Error] %s %s", method, raw_path)
            resp = RawResponse.json(500, {"error": str(exc) if self.debug else "Internal server error"})
        return self.finalize_response(resp, method)

    @staticmethod
    def _resolve_awaitable(awaitable, loop=None):
        """Run an async route handler from the worker thread that is processing the request."""

        async def _wrap():
            return await awaitable

        if loop is not None and loop.is_running():
            return asyncio.run_coroutine_threadsafe(_wrap(), loop).result()
        return asyncio.run(_wrap())

    def _dispatch(self, handler, route_params, method, raw_path, path, headers, body, client_ip, transport, loop):
        req = Request(
            method=method,
            path=raw_path,
            headers=headers,
            body_bytes=body,
            route_params=route_params,
            client_ip=client_ip,
            transport=transport,
        )
        req.db = getattr(self, "db", None)
        csrf_token, csrf_is_new = self.resolve_csrf_token(req.cookies)
        req.csrf_token = csrf_token
        cookie_headers = [("Set-Cookie", self.csrf_cookie_header(csrf_token))] if csrf_is_new else []

        # OWASP CSRF Prevention: signed double-submit cookie on every state-changing request
        if method not in SAFE_HTTP_METHODS and self.security.csrf_enabled and not self.is_csrf_exempt(path):
            submitted = headers.get(CSRF_HEADER_NAME)
            if not submitted and isinstance(req.form, dict):
                submitted = req.form.get(CSRF_FORM_FIELD)
            if not submitted and isinstance(req.json, dict):
                submitted = req.json.get(CSRF_FORM_FIELD)
            if isinstance(submitted, list):
                submitted = submitted[0] if submitted else None
            if not csrf_tokens_match(req.cookies.get(CSRF_COOKIE_NAME), submitted, self.security.secret_key):
                return RawResponse.json(
                    403,
                    {"error": "CSRF token missing or invalid. Reload the page and try again.", "code": "csrf_failed"},
                    cookie_headers,
                )

        try:
            result = handler(req)
            if inspect.isawaitable(result):
                result = self._resolve_awaitable(result, loop)
            if isinstance(result, Response):
                resp = result
            elif isinstance(result, Component):
                resp = Response(
                    body=result.render_page(
                        registry=self.components,
                        csrf_token=csrf_token,
                        secret=self.security.secret_key,
                    )
                )
            elif isinstance(result, tuple):
                body_val, status = result[0], result[1]
                extra = result[2] if len(result) > 2 else None
                resp = Response(body=body_val, status=status, headers=extra)
            else:
                resp = Response(body=result)
        except Exception as exc:
            logger.exception("[PyFusion Route Error] %s %s", method, raw_path)
            resp = Response(body={"error": str(exc) if self.debug else "Internal server error"}, status=500)

        body_out = resp.body
        if resp.content_type.startswith("text/html"):
            try:
                body_out = inject_csrf_into_forms(body_out.decode("utf-8"), csrf_token).encode("utf-8")
            except UnicodeDecodeError:
                pass

        out_headers = [("Content-Type", resp.content_type)] + cookie_headers + list(resp.headers.items())
        if resp.content_type.startswith("application/json") and not any(
            k.lower() == "cache-control" for k in resp.headers
        ):
            out_headers.append(("Cache-Control", "no-store"))
        return RawResponse(resp.status, out_headers, body_out)

    def _serve_static(self, path: str, headers: Headers) -> RawResponse:
        """Serve files from web_dir with clean URLs, .fusion expansion in HTML, ETag/304 and traversal protection."""
        base = self.web_dir
        rel = unquote(path)

        # Support clean URLs (e.g., /form -> /form.html)
        if rel != "/" and "." not in os.path.basename(rel):
            candidate = os.path.join(base, rel.lstrip("/") + ".html")
            if os.path.isfile(candidate):
                rel = rel + ".html"
        elif rel != "/" and not rel.startswith("/assets/"):
            # Fallback to web/assets/<file> when requesting /logo.png, /styles.css, etc.
            direct_candidate = os.path.join(base, rel.lstrip("/"))
            assets_candidate = os.path.join(base, "assets", rel.lstrip("/"))
            if not os.path.isfile(direct_candidate) and os.path.isfile(assets_candidate):
                rel = "/assets/" + rel.lstrip("/")

        # OWASP A01 Path Traversal & Sensitive File Protection
        rel_target = "index.html" if rel == "/" else rel
        is_safe, target = is_safe_static_path(base, rel_target)
        if not is_safe:
            return RawResponse.json(403, {"error": "Forbidden path"})

        if os.path.isdir(target):
            index_file = os.path.join(target, "index.html")
            if not os.path.isfile(index_file):
                # Never expose directory listings (OWASP A01 / A05)
                return RawResponse.json(404, {"error": "Not found"})
            target = index_file
        if not os.path.isfile(target):
            return RawResponse.json(404, {"error": "Not found"})

        # Automatically expand Vue-style .fusion components inside .html pages (e.g., web/index.html)
        if target.endswith(".html"):
            try:
                with open(target, "r", encoding="utf-8") as f:
                    raw_html = f.read()
                csrf_token, csrf_is_new = self.resolve_csrf_token(_parse_cookies(headers.get("Cookie", "")))
                compiled = inject_csrf_into_forms(self.render_html_with_components(raw_html), csrf_token)
                out_headers = [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-cache")]
                if csrf_is_new:
                    out_headers.append(("Set-Cookie", self.csrf_cookie_header(csrf_token)))
                return RawResponse(200, out_headers, compiled.encode("utf-8"))
            except Exception:
                logger.exception("[PyFusion HTML Component Render Error] %s", rel_target)

        st = os.stat(target)
        etag = f'W/"{st.st_mtime_ns:x}-{st.st_size:x}"'
        ext = os.path.splitext(target)[1].lower()
        ctype = _STATIC_MIME_TYPES.get(ext)
        if ctype is None:
            guessed, encoding = mimetypes.guess_type(target)
            # Never send Content-Encoding for pre-compressed files; serve them as opaque downloads.
            ctype = "application/octet-stream" if encoding or not guessed else guessed
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        out_headers = [
            ("Content-Type", ctype),
            ("ETag", etag),
            ("Last-Modified", formatdate(st.st_mtime, usegmt=True)),
            ("Cache-Control", "no-cache"),
        ]
        if etag in [t.strip() for t in headers.get("If-None-Match", "").split(",")]:
            return RawResponse(304, out_headers)
        with open(target, "rb") as f:
            data = f.read()
        return RawResponse(200, out_headers, data)

    @property
    def asgi(self):
        """ASGI application for uvicorn / hypercorn / gunicorn (``uvicorn web.app:app.asgi``)."""
        cached = getattr(self, "_asgi_app", None)
        if cached is None:
            from .asgi import PyFusionASGI

            cached = self._asgi_app = PyFusionASGI(self)
        return cached

    def run(self, host="localhost", port=5000, in_thread=False, open_browser=False, server="auto"):
        return run_web_server(
            port=port, host=host, app=self, in_thread=in_thread, open_browser=open_browser, server=server
        )


def create_app(root_component=None, **kwargs) -> PyFusionApp:
    """Vue.js-style factory function: create_app(App).use(db).component('Card', Card).run()"""
    return PyFusionApp(root_component=root_component, **kwargs)


# Default global app instance
default_app = PyFusionApp()


class CustomHandler(BaseHTTPRequestHandler):
    """Thin stdlib (http.server) adapter around :meth:`PyFusionApp.handle_request`.

    Used as a zero-dependency fallback when uvicorn is not installed (``server="stdlib"``).
    """

    app = default_app
    # Drop idle/slow connections (mitigates slowloris-style resource exhaustion)
    timeout = 30

    def version_string(self):
        # Hide underlying Python/OS version details (OWASP A05 Security Misconfiguration)
        return "PyFusion"

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "127.0.0.1"

    def _handle(self, method: str):
        try:
            content_length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            content_length = -1
        if content_length < 0:
            resp = self.app.finalize_response(RawResponse.json(400, {"error": "Invalid Content-Length"}), method)
        elif content_length > self.app.security.max_body_size:
            # Reject before reading the body (DoS protection)
            resp = self.app.finalize_response(RawResponse.json(413, {"error": "Payload too large"}), method)
        else:
            body = self.rfile.read(content_length) if content_length > 0 else b""
            resp = self.app.handle_request(
                method,
                self.path,
                Headers(self.headers.items()),
                body,
                client_ip=self._client_ip(),
                transport="stdlib",
            )
        self._write(resp)

    def _write(self, resp: RawResponse):
        try:
            self.send_response(resp.status)
            for k, v in resp.headers:
                self.send_header(k, v)
            self.end_headers()
            if resp.body:
                self.wfile.write(resp.body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        self._handle("OPTIONS")

    def log_message(self, format, *args):
        # Suppress noisy livereload polling logs in terminal
        if args and isinstance(args[0], str) and "/_pyfusion/livereload" in args[0]:
            return
        super().log_message(format, *args)


class ReusableTCPServer(ThreadingTCPServer):
    # SO_REUSEADDR on Windows allows a second process to bind the same port (port hijacking), so only enable it on POSIX.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


class UvicornServerHandle:
    """Handle for a uvicorn server running in a background thread (mirrors the socketserver API used by callers)."""

    def __init__(self, server, thread, server_address):
        self._server = server
        self._thread = thread
        self.server_address = server_address

    def shutdown(self):
        self._server.should_exit = True
        self._thread.join(timeout=10)

    def server_close(self):
        # Sockets are closed by uvicorn during shutdown; kept for API compatibility.
        pass

    def serve_forever(self):
        self._thread.join()


def resolve_server_backend(server: str = "auto") -> str:
    """Pick the HTTP backend: ``uvicorn`` (ASGI + WebSockets) when installed, otherwise the stdlib server."""
    choice = (server or os.environ.get("PYFUSION_SERVER") or "auto").strip().lower()
    if choice == "auto" and os.environ.get("PYFUSION_SERVER"):
        choice = os.environ["PYFUSION_SERVER"].strip().lower()
    if choice not in ("auto", "uvicorn", "stdlib"):
        raise ValueError(f"Unknown server backend '{server}'. Use 'auto', 'uvicorn' or 'stdlib'.")
    if choice in ("auto", "uvicorn"):
        try:
            import uvicorn  # noqa: F401

            return "uvicorn"
        except ImportError:
            if choice == "uvicorn":
                raise RuntimeError("The uvicorn backend requires: pip install \"uvicorn[standard]\"") from None
    return "stdlib"


def _print_banner(active_app, url, backend):
    mode = "development (live-reload on)" if active_app.debug else "production"
    transport = "ASGI/uvicorn + WebSockets" if backend == "uvicorn" else "stdlib http.server"
    print(f"PyFusion Server running at {url} [{mode}] [{transport}]")
    print(f"Serving web directory: {active_app.web_dir}")
    if active_app.debug:
        print("  Development mode. For deployments set PYFUSION_ENV=production and PYFUSION_SECRET_KEY.")
    if active_app.components:
        print(f"Registered Components: {', '.join(active_app.components.keys())}")


def _run_uvicorn(active_app, host, port, in_thread, open_browser):
    import uvicorn

    from .asgi import PyFusionASGI

    config = uvicorn.Config(
        PyFusionASGI(active_app, host=host),
        host=host,
        port=port,
        log_level="info" if active_app.debug else "warning",
        access_log=active_app.debug,
        server_header=False,  # OWASP A05: do not advertise server software
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        lifespan="on",
        ws_max_size=active_app.security.max_body_size,
        timeout_keep_alive=5,
    )
    server = uvicorn.Server(config)

    if in_thread:
        thread = threading.Thread(target=server.run, daemon=True, name="pyfusion-uvicorn")
        thread.start()
        deadline = time.time() + 15
        while not server.started and thread.is_alive() and time.time() < deadline:
            time.sleep(0.02)
        if not server.started:
            raise RuntimeError(f"PyFusion (uvicorn) failed to start on {host}:{port}")
        bound_port = port
        try:
            bound_port = server.servers[0].sockets[0].getsockname()[1]
        except (AttributeError, IndexError, OSError):
            pass
        url = f"http://{host}:{bound_port}"
        _print_banner(active_app, url, "uvicorn")
        if open_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        return UvicornServerHandle(server, thread, (host, bound_port))

    url = f"http://{host}:{port}"
    _print_banner(active_app, url, "uvicorn")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    print("\nServer stopped.")
    return server


def run_web_server(port=5000, host="localhost", app=None, in_thread=False, open_browser=False, server="auto"):
    """Start the OWASP-hardened PyFusion server.

    ``server="auto"`` (default) uses uvicorn (ASGI, HTTP/1.1 keep-alive, WebSockets) when installed and falls
    back to the zero-dependency stdlib server otherwise. Force a backend with ``server="uvicorn"|"stdlib"``
    or the ``PYFUSION_SERVER`` environment variable.
    """
    active_app = app or default_app
    active_app.prepare_for_serving(host)
    mimetypes.init()

    backend = resolve_server_backend(server)
    if backend == "uvicorn":
        return _run_uvicorn(active_app, host, port, in_thread, open_browser)

    class BoundHandler(CustomHandler):
        pass

    BoundHandler.app = active_app

    httpd = ReusableTCPServer((host, port), BoundHandler)
    bound_port = httpd.server_address[1]
    url = f"http://{host}:{bound_port}"
    _print_banner(active_app, url, "stdlib")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    if in_thread:
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        return httpd

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        httpd.server_close()
    return httpd


if __name__ == "__main__":
    run_web_server()
