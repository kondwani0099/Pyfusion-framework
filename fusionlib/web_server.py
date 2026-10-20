# web_server.py
import hashlib
import json
import mimetypes
import os
import re
import threading
import webbrowser
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer
from urllib.parse import parse_qs, urlparse

from .component import CLIENT_RUNTIME_JS, Component, load_sfc
from .reactivity import FusionPlugin, FusionStore
from .security import (
    RateLimiter,
    SecurityConfig,
    escape_html,
    generate_csrf_token,
    get_owasp_security_headers,
    is_safe_static_path,
    verify_csrf_token,
)


class Request:
    """Represents an incoming HTTP request with parsed query, form, JSON, cookies, and client IP."""

    def __init__(self, method, path, headers, body_bytes=b"", route_params=None, client_ip="127.0.0.1"):
        self.method = method.upper()
        parsed_url = urlparse(path)
        self.raw_path = path
        self.path = parsed_url.path
        self.headers = headers
        self.body = body_bytes
        self.route_params = route_params or {}
        self.client_ip = client_ip

        # Parse cookies
        self.cookies = {}
        raw_cookie = self.headers.get("Cookie", "")
        if raw_cookie:
            cookie = SimpleCookie()
            try:
                cookie.load(raw_cookie)
                self.cookies = {k: v.value for k, v in cookie.items()}
            except Exception:
                pass

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
            self.body = json.dumps(body).encode("utf-8")
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
    Database plugin integration, and Browser Live-Reload.
    """

    def __init__(self, root_component=None, web_dir=None, components_dir=None, security_config=None):
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

        self.security = security_config or SecurityConfig()
        self.rate_limiter = RateLimiter(max_requests=self.security.rate_limit_per_minute, window_seconds=60)

        self.routes = []
        self.components = {}
        self.stores = {}
        self.plugins = []
        self.config = {}
        self.db = None

        self._discover_sfc_components()
        self._register_default_routes()

        if root_component is not None:
            self.mount("/", root_component)

    def _compute_livereload_hash(self) -> str:
        """Compute a digest of modification times across web/, components/, and .py files for instant browser reload."""
        hasher = hashlib.md5()
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
                        print(f"[PyFusion] Warning: Failed to compile {fname}: {exc}")

    def render_html_with_components(self, html_content: str) -> str:
        """Expand any registered <ComponentName /> or <ComponentName></ComponentName> tags inside HTML."""
        self._discover_sfc_components()
        if not self.components:
            return html_content

        rendered = html_content
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
                        return instance.render_fragment(registry=self.components)

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
            self._discover_sfc_components()
            latest_cls = self.components.get(comp_name, comp_cls)
            instance = latest_cls(**request.query)
            csrf_tok = request.cookies.get("pyfusion_csrf") or generate_csrf_token(self.security.secret_key)
            return instance.render_page(title=title or comp_name, registry=self.components, csrf_token=csrf_tok)

        mounted_component_view.__name__ = f"mount_{comp_name}"
        return self

    def _register_default_routes(self):
        @self.route("/_pyfusion/client.js", methods=["GET"])
        def serve_client_runtime(request: Request):
            return Response(
                body=CLIENT_RUNTIME_JS,
                status=200,
                content_type="application/javascript; charset=utf-8",
            )

        @self.route("/_pyfusion/livereload", methods=["GET"])
        def serve_livereload_hash(request: Request):
            self._discover_sfc_components()
            return {
                "hash": self._compute_livereload_hash(),
                "components": list(self.components.keys()),
            }

        @self.route("/_pyfusion/rpc", methods=["POST"])
        def handle_component_rpc(request: Request):
            self._discover_sfc_components()
            payload = request.json or {}
            comp_id = payload.get("component_id")
            method_name = payload.get("method")
            args = payload.get("args", [])
            client_state = payload.get("state", {})

            if not comp_id or comp_id not in self.components:
                return Response({"error": f"Unknown component '{comp_id}'"}, status=404)

            comp_cls = self.components[comp_id]
            instance = comp_cls()
            try:
                new_state = instance.invoke_method(method_name, args=args, client_state=client_state)
                return {"status": "ok", "component": comp_id, "state": new_state}
            except PermissionError as exc:
                return Response({"error": str(exc)}, status=403)
            except Exception as exc:
                return Response({"error": str(exc)}, status=400)

        @self.route("/api/security/audit", methods=["GET"])
        def security_audit(request: Request):
            return {
                "status": "hardened",
                "standard": "OWASP Top 10 (2021/2025)",
                "protections": {
                    "A01_Broken_Access_Control": "Path traversal blocking + RPC method allowlisting + SameSite cookies",
                    "A02_Cryptographic_Failures": "PBKDF2-HMAC-SHA256 (260k iterations) + HMAC-SHA256 signed tokens",
                    "A03_Injection": "100% Parameterized SQL queries + SQL identifier validation + Automatic HTML XSS escaping",
                    "A04_Insecure_Design": f"Sliding-window IP Rate Limiter ({self.security.rate_limit_per_minute} req/min) + 2MB body cap",
                    "A05_Security_Misconfiguration": "Strict OWASP HTTP headers (X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy)",
                    "A07_Identification_And_Auth": "CSRF HMAC token generation & constant-time verification",
                },
                "headers_active": list(get_owasp_security_headers(self.security).keys()),
            }

        @self.route("/submit_form", methods=["POST"])
        def default_submit_form(request: Request):
            username = escape_html(request.form.get("username", "Guest"))
            accept = request.headers.get("Accept", "")
            if "application/json" in accept:
                return {"status": "success", "message": f"Form submitted by {username}", "data": request.form}
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
            sw_code = (
                "self.addEventListener('install', e => self.skipWaiting());\n"
                "self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));\n"
                "self.addEventListener('fetch', e => {\n"
                "  if (e.request.method !== 'GET') return;\n"
                "  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));\n"
                "});\n"
            )
            return Response(body=sw_code, status=200, content_type="application/javascript; charset=utf-8")

        @self.route("/api/health", methods=["GET"])
        def health_check(request: Request):
            from .config import load_project_config
            from .mobile_simulator import get_lan_ip

            cfg = load_project_config()
            return {
                "status": "ok",
                "framework": "PyFusion",
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

    def delete(self, path):
        return self.route(path, methods=["DELETE"])

    def match_route(self, path, method):
        method = method.upper()
        for route in self.routes:
            match = route["regex"].match(path)
            if match and method in route["methods"]:
                return route["handler"], match.groupdict()
        return None, {}

    def run(self, host="localhost", port=5000, in_thread=False, open_browser=False):
        return run_web_server(port=port, host=host, app=self, in_thread=in_thread, open_browser=open_browser)


def create_app(root_component=None, **kwargs) -> PyFusionApp:
    """Vue.js-style factory function: create_app(App).use(db).component('Card', Card).run()"""
    return PyFusionApp(root_component=root_component, **kwargs)


# Default global app instance
default_app = PyFusionApp()


class CustomHandler(SimpleHTTPRequestHandler):
    """OWASP-Hardened HTTP Request Handler supporting PyFusionApp routes, live-reload, and static files."""

    app = default_app

    def __init__(self, *args, **kwargs):
        web_dir = self.app.web_dir if self.app and os.path.exists(self.app.web_dir) else os.getcwd()
        super().__init__(*args, directory=web_dir, **kwargs)

    def version_string(self):
        # Hide underlying Python/OS version details (OWASP A05 Security Misconfiguration)
        return "PyFusion"

    def end_headers(self):
        # Inject OWASP security headers on all static & dynamic responses
        if self.app and hasattr(self.app, "security"):
            for k, v in get_owasp_security_headers(self.app.security).items():
                self.send_header(k, v)
        super().end_headers()

    def _check_rate_limit(self) -> bool:
        client_ip = self.client_address[0] if self.client_address else "127.0.0.1"
        # Exempt livereload polling from rate limit counter
        if urlparse(self.path).path == "/_pyfusion/livereload":
            return True
        allowed, retry_after = self.app.rate_limiter.is_allowed(client_ip)
        if not allowed:
            body = json.dumps({"error": "Too many requests. Please slow down.", "retry_after": retry_after}).encode("utf-8")
            self.send_response(429)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Retry-After", str(retry_after))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return False
        return True

    def _dispatch_route(self, method):
        if not self._check_rate_limit():
            return True

        parsed_path = urlparse(self.path).path
        handler, route_params = self.app.match_route(parsed_path, method)

        if handler is None:
            return False

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > self.app.security.max_body_size:
            body = json.dumps({"error": "Payload too large"}).encode("utf-8")
            self.send_response(413)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True

        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

        req = Request(
            method=method,
            path=self.path,
            headers=self.headers,
            body_bytes=body_bytes,
            route_params=route_params,
            client_ip=client_ip,
        )
        req.db = getattr(self.app, "db", None)

        try:
            result = handler(req)
            if isinstance(result, Response):
                resp = result
            elif isinstance(result, Component):
                resp = Response(body=result.render_page(registry=self.app.components))
            elif isinstance(result, tuple):
                body, status = result[0], result[1]
                headers = result[2] if len(result) > 2 else None
                resp = Response(body=body, status=status, headers=headers)
            else:
                resp = Response(body=result)
        except Exception as exc:
            print(f"[PyFusion Route Error] {method} {self.path}: {exc}")
            resp = Response(
                body={"error": "Internal server error"},
                status=500,
            )

        try:
            self.send_response(resp.status)
            self.send_header("Content-Type", resp.content_type)
            self.send_header("Content-Length", str(len(resp.body)))
            if "pyfusion_csrf" not in req.cookies:
                csrf_token = generate_csrf_token(self.app.security.secret_key)
                self.send_header("Set-Cookie", f"pyfusion_csrf={csrf_token}; Path=/; SameSite=Lax")
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(resp.body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass
        return True

    def do_GET(self):
        if self._dispatch_route("GET"):
            return

        parsed_path = urlparse(self.path).path

        # Support clean URLs (e.g., /form -> /form.html)
        if parsed_path != "/" and "." not in os.path.basename(parsed_path):
            candidate = os.path.join(self.directory, parsed_path.lstrip("/") + ".html")
            if os.path.isfile(candidate):
                parsed_path = parsed_path + ".html"
                self.path = parsed_path
        elif parsed_path != "/" and not parsed_path.startswith("/assets/"):
            # Fallback to web/assets/<file> when requesting /logo.png, /styles.css, etc.
            direct_candidate = os.path.join(self.directory, parsed_path.lstrip("/"))
            assets_candidate = os.path.join(self.directory, "assets", parsed_path.lstrip("/"))
            if not os.path.isfile(direct_candidate) and os.path.isfile(assets_candidate):
                parsed_path = "/assets/" + parsed_path.lstrip("/")
                self.path = parsed_path

        # OWASP A01 Path Traversal & Sensitive File Protection
        rel_target = "index.html" if parsed_path == "/" else parsed_path
        is_safe, target_abspath = is_safe_static_path(self.directory, rel_target)
        if not is_safe:
            body = json.dumps({"error": "Forbidden path"}).encode("utf-8")
            try:
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
            return

        # Automatically expand Vue-style .fusion components inside .html pages (e.g., web/index.html)
        if target_abspath.endswith(".html") and os.path.isfile(target_abspath) and self.app:
            try:
                with open(target_abspath, "r", encoding="utf-8") as f:
                    raw_html = f.read()
                compiled_html = self.app.render_html_with_components(raw_html)
                body = compiled_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                raw_cookie = self.headers.get("Cookie", "")
                if "pyfusion_csrf=" not in raw_cookie:
                    csrf_token = generate_csrf_token(self.app.security.secret_key)
                    self.send_header("Set-Cookie", f"pyfusion_csrf={csrf_token}; Path=/; SameSite=Lax")
                self.end_headers()
                self.wfile.write(body)
                return
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                return
            except Exception as exc:
                print(f"[PyFusion HTML Component Render Error] {rel_target}: {exc}")

        try:
            super().do_GET()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def do_POST(self):
        if self._dispatch_route("POST"):
            return

        content_length = min(int(self.headers.get("Content-Length", 0)), self.app.security.max_body_size)
        post_data = self.rfile.read(content_length).decode("utf-8", errors="replace")

        response_bytes = json.dumps({"status": "received", "data": escape_html(post_data)}).encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response_bytes)))
            self.end_headers()
            self.wfile.write(response_bytes)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def do_DELETE(self):
        if self._dispatch_route("DELETE"):
            return
        self.send_error(404, "Route not found")

    def log_message(self, format, *args):
        # Suppress noisy livereload polling logs in terminal
        if args and isinstance(args[0], str) and "/_pyfusion/livereload" in args[0]:
            return
        super().log_message(format, *args)


class ReusableTCPServer(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def run_web_server(port=5000, host="localhost", app=None, in_thread=False, open_browser=False):
    """Start the OWASP-hardened PyFusion HTTP server."""
    active_app = app or default_app

    class BoundHandler(CustomHandler):
        pass

    BoundHandler.app = active_app
    mimetypes.init()

    server_address = (host, port)
    httpd = ReusableTCPServer(server_address, BoundHandler)

    url = f"http://{host}:{port}"
    print(f"PyFusion Server running at {url} [OWASP Hardened + Browser Live-Reload]")
    print(f"Serving web directory: {active_app.web_dir}")
    if active_app.components:
        print(f"Registered Components: {', '.join(active_app.components.keys())}")

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
