"""
OWASP Top 10 Security Suite for PyFusion Framework.

Provides:
- OWASP Security Headers (CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, HSTS)
- CSRF Token generation & constant-time verification (signed double-submit cookie pattern)
- Sliding-window IP Rate Limiting & DoS payload size protection
- Password hashing & verification (PBKDF2-HMAC-SHA256 + salt, OWASP 2023+ iteration count)
- HMAC-SHA256 signed session tokens
- HMAC-SHA256 component state snapshot signing (tamper protection for client-held state)
- HTML / XSS sanitization & Path Traversal prevention
"""

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple

# OWASP Password Storage Cheat Sheet: PBKDF2-HMAC-SHA256 minimum 600,000 iterations.
PBKDF2_DEFAULT_ITERATIONS = 600_000

# Default Content-Security-Policy.
# Compatible with the bundled demo (Tailwind Play CDN, daisyUI, Google Fonts, inline handlers and the
# expression-evaluating client runtime). It still blocks plugins, base-tag hijacking, cross-origin
# form posts, clickjacking and cross-origin XHR/fetch exfiltration.
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "img-src 'self' data: blob: https:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'self'"
)

# Strict policy for apps that ship compiled CSS and no inline scripts/handlers.
STRICT_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


class SecurityConfig:
    """Centralized OWASP security configuration for a PyFusionApp."""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        csrf_enabled: bool = True,
        rate_limit_per_minute: int = 180,
        max_body_size: int = 2 * 1024 * 1024,  # 2 MB limit (DoS protection)
        frame_options: str = "SAMEORIGIN",
        enable_hsts: bool = False,
        cors_origins: str = "",
        content_security_policy: Optional[str] = DEFAULT_CSP,
        secure_cookies: Optional[bool] = None,
        state_signing: bool = True,
    ):
        provided_key = secret_key or os.environ.get("PYFUSION_SECRET_KEY")
        # When no key is provided an ephemeral key is generated. PyFusionApp replaces it with a persistent
        # development key in debug mode and refuses to start in production mode.
        self.secret_key_is_ephemeral = not provided_key
        self.secret_key = provided_key or secrets.token_hex(32)
        self.csrf_enabled = csrf_enabled
        self.rate_limit_per_minute = rate_limit_per_minute
        self.max_body_size = max_body_size
        self.frame_options = frame_options
        self.enable_hsts = enable_hsts
        self.cors_origins = cors_origins
        self.content_security_policy = content_security_policy
        # Secure cookies default to on whenever HSTS (i.e. HTTPS) is enabled.
        self.secure_cookies = enable_hsts if secure_cookies is None else secure_cookies
        self.state_signing = state_signing


class RateLimiter:
    """Thread-safe sliding-window in-memory rate limiter per client IP (OWASP A04/A07 Brute-Force & DoS protection).

    Memory is bounded: stale IP entries are purged periodically and the number of tracked IPs is capped.
    For multi-process deployments use a shared store (e.g. Redis) or a reverse-proxy rate limiter instead.
    """

    def __init__(self, max_requests: int = 180, window_seconds: int = 60, max_tracked_ips: int = 50_000):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_tracked_ips = max_tracked_ips
        self._hits: Dict[str, list] = {}
        self._lock = threading.Lock()
        self._last_purge = time.time()

    def _purge(self, now: float):
        cutoff = now - self.window_seconds
        stale = [ip for ip, ts in self._hits.items() if not ts or ts[-1] <= cutoff]
        for ip in stale:
            del self._hits[ip]
        self._last_purge = now

    def is_allowed(self, client_ip: str) -> Tuple[bool, int]:
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            if now - self._last_purge > self.window_seconds or len(self._hits) > self.max_tracked_ips:
                self._purge(now)

            timestamps = [t for t in self._hits.get(client_ip, []) if t > cutoff]

            if len(timestamps) >= self.max_requests:
                retry_after = int(self.window_seconds - (now - timestamps[0])) + 1
                self._hits[client_ip] = timestamps
                return False, max(1, retry_after)

            timestamps.append(now)
            self._hits[client_ip] = timestamps
            return True, 0


# --- OWASP A02: Cryptographic Password Hashing & Signed Tokens ---

def hash_password(password: str, iterations: int = PBKDF2_DEFAULT_ITERATIONS) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a cryptographic random salt."""
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    hash_b64 = base64.b64encode(dk).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt}${hash_b64}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a PBKDF2-HMAC-SHA256 hash using constant-time comparison.

    Hashes created with older (lower) iteration counts still verify; use ``password_needs_rehash``
    after a successful login to upgrade them.
    """
    try:
        algorithm, iterations_str, salt, hash_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
        candidate_b64 = base64.b64encode(dk).decode("ascii")
        return hmac.compare_digest(candidate_b64, hash_b64)
    except Exception:
        return False


def password_needs_rehash(stored_hash: str, iterations: int = PBKDF2_DEFAULT_ITERATIONS) -> bool:
    """Return True if a stored hash uses an outdated algorithm or fewer iterations than the current policy."""
    try:
        algorithm, iterations_str, _salt, _hash = stored_hash.split("$", 3)
        return algorithm != "pbkdf2_sha256" or int(iterations_str) < iterations
    except Exception:
        return True


def create_signed_token(payload: Dict[str, Any], secret_key: str, expires_in: int = 3600) -> str:
    """Create an HMAC-SHA256 signed token (similar to JWT) without external dependencies."""
    data = dict(payload)
    data["exp"] = int(time.time()) + expires_in
    raw_json = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
    sig = hmac.new(secret_key.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{body_b64}.{sig_b64}"


def verify_signed_token(token: str, secret_key: str) -> Optional[Dict[str, Any]]:
    """Verify an HMAC-SHA256 signed token and check expiration."""
    try:
        body_b64, sig_b64 = token.split(".", 1)
        expected_sig = hmac.new(secret_key.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
        expected_b64 = base64.urlsafe_b64encode(expected_sig).decode("ascii").rstrip("=")
        if not hmac.compare_digest(sig_b64, expected_b64):
            return None
        padding = "=" * (-len(body_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body_b64 + padding).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


# --- Component state integrity (Livewire-style snapshot checksums) ---

def sign_state(component_id: str, snapshot_json: str, secret_key: str) -> str:
    """Compute an HMAC-SHA256 checksum binding a serialized state snapshot to its component."""
    msg = f"pyfusion-state:{component_id}\n{snapshot_json}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_state(component_id: str, snapshot_json: str, checksum: str, secret_key: str) -> bool:
    """Verify a state snapshot checksum in constant time."""
    if not isinstance(snapshot_json, str) or not isinstance(checksum, str) or not checksum:
        return False
    expected = sign_state(component_id, snapshot_json, secret_key)
    return hmac.compare_digest(expected, checksum)


# --- OWASP A01 / A07: CSRF Protection ---

def generate_csrf_token(secret_key: str, session_id: str = "default") -> str:
    """Generate an HMAC-signed CSRF token."""
    nonce = secrets.token_hex(16)
    msg = f"{session_id}:{nonce}".encode("utf-8")
    sig = hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{nonce}.{sig}"


def verify_csrf_token(token: str, secret_key: str, session_id: str = "default") -> bool:
    """Verify an HMAC-signed CSRF token in constant time."""
    if not token or not isinstance(token, str) or "." not in token:
        return False
    try:
        nonce, sig = token.split(".", 1)
        msg = f"{session_id}:{nonce}".encode("utf-8")
        expected_sig = hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False


def csrf_tokens_match(cookie_token: Optional[str], submitted_token: Optional[str], secret_key: str) -> bool:
    """Signed double-submit cookie check (OWASP CSRF Prevention Cheat Sheet).

    The token submitted in the header/form must equal the cookie value AND carry a valid server signature.
    """
    if not cookie_token or not submitted_token:
        return False
    if not hmac.compare_digest(str(cookie_token), str(submitted_token)):
        return False
    return verify_csrf_token(str(cookie_token), secret_key)


# --- OWASP A03: XSS Sanitization & Path Traversal Prevention ---

def escape_html(value: Any) -> str:
    """Escape HTML special characters (<, >, &, ", ') to prevent Reflected/Stored XSS."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


_DANGEROUS_TAGS_RE = re.compile(r"<\s*/?\s*(script|iframe|object|embed|applet|meta|link|style)[^>]*>", re.IGNORECASE)
_EVENT_ATTR_RE = re.compile(r"\son[a-z]+\s*=\s*(['\"].*?['\"]|[^\s>]+)", re.IGNORECASE)
_JS_PROTO_RE = re.compile(r"javascript\s*:", re.IGNORECASE)


def sanitize_html(raw_html: str) -> str:
    """Strip dangerous XSS vectors (<script>,<iframe>, inline on* handlers, javascript: URLs).

    Note: regex-based sanitizing is a best-effort fallback. For untrusted rich HTML prefer an
    allowlist parser such as ``nh3``; when installed it is used automatically.
    """
    if not raw_html:
        return ""
    try:  # pragma: no cover - optional dependency
        import nh3  # type: ignore

        return nh3.clean(str(raw_html))
    except ImportError:
        pass
    cleaned = _DANGEROUS_TAGS_RE.sub("", str(raw_html))
    cleaned = _EVENT_ATTR_RE.sub("", cleaned)
    cleaned = _JS_PROTO_RE.sub("", cleaned)
    return cleaned


def is_safe_static_path(base_dir: str, requested_path: str) -> Tuple[bool, str]:
    """
    Prevent Path Traversal (OWASP A01) and sensitive file exposure.
    Ensures the resolved file stays strictly inside base_dir and blocks dotfiles / .py files.
    """
    real_base = os.path.realpath(base_dir)
    clean_rel = requested_path.lstrip("/\\")
    candidate = os.path.realpath(os.path.join(real_base, clean_rel))

    # Must reside inside real_base
    if not (candidate == real_base or candidate.startswith(real_base + os.sep)):
        return False, candidate

    # Block hidden dotfiles (.env, .git, etc.) and backend source files (.py, .db, .sqlite)
    parts = os.path.relpath(candidate, real_base).split(os.sep)
    for part in parts:
        if part.startswith(".") and part != ".":
            return False, candidate

    blocked_exts = (".py", ".pyc", ".db", ".sqlite", ".sqlite3", ".env", ".fusion")
    if candidate.lower().endswith(blocked_exts):
        return False, candidate

    return True, candidate


def is_loopback(client_ip: Optional[str]) -> bool:
    """Return True if the client address is a loopback address (127.0.0.0/8 or ::1)."""
    if not client_ip:
        return False
    try:
        return ipaddress.ip_address(client_ip.split("%", 1)[0]).is_loopback
    except ValueError:
        return client_ip == "localhost"


def get_owasp_security_headers(config: SecurityConfig) -> Dict[str, str]:
    """Return standard OWASP recommended HTTP security headers."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": config.frame_options,
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "X-Permitted-Cross-Domain-Policies": "none",
    }
    csp = getattr(config, "content_security_policy", None)
    if csp:
        headers["Content-Security-Policy"] = csp
    if config.enable_hsts:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if config.cors_origins:
        headers["Access-Control-Allow-Origin"] = config.cors_origins
        headers["Vary"] = "Origin"
    return headers
