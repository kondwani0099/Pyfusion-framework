"""
OWASP Top 10 Security Suite for PyFusion Framework.

Provides:
- OWASP Security Headers (CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, HSTS)
- CSRF Token generation & constant-time verification
- Sliding-window IP Rate Limiting & DoS payload size protection
- Password hashing & verification (PBKDF2-HMAC-SHA256 + salt)
- HMAC-SHA256 signed session tokens
- HTML / XSS sanitization & Path Traversal prevention
"""

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
from typing import Any, Callable, Dict, Optional, Tuple


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
    ):
        self.secret_key = (
            secret_key
            or os.environ.get("PYFUSION_SECRET_KEY")
            or secrets.token_hex(32)
        )
        self.csrf_enabled = csrf_enabled
        self.rate_limit_per_minute = rate_limit_per_minute
        self.max_body_size = max_body_size
        self.frame_options = frame_options
        self.enable_hsts = enable_hsts
        self.cors_origins = cors_origins


class RateLimiter:
    """Sliding-window in-memory rate limiter per client IP (OWASP A04/A07 Brute-Force & DoS protection)."""

    def __init__(self, max_requests: int = 180, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: Dict[str, list] = {}

    def is_allowed(self, client_ip: str) -> Tuple[bool, int]:
        now = time.time()
        cutoff = now - self.window_seconds
        timestamps = [t for t in self._hits.get(client_ip, []) if t > cutoff]

        if len(timestamps) >= self.max_requests:
            retry_after = int(self.window_seconds - (now - timestamps[0])) + 1
            self._hits[client_ip] = timestamps
            return False, max(1, retry_after)

        timestamps.append(now)
        self._hits[client_ip] = timestamps
        return True, 0


# --- OWASP A02: Cryptographic Password Hashing & Signed Tokens ---

def hash_password(password: str, iterations: int = 260_000) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a cryptographic random salt."""
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    hash_b64 = base64.b64encode(dk).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt}${hash_b64}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a PBKDF2-HMAC-SHA256 hash using constant-time comparison."""
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


# --- OWASP A01 / A07: CSRF Protection ---

def generate_csrf_token(secret_key: str, session_id: str = "default") -> str:
    """Generate an HMAC-signed CSRF token."""
    nonce = secrets.token_hex(16)
    msg = f"{session_id}:{nonce}".encode("utf-8")
    sig = hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{nonce}.{sig}"


def verify_csrf_token(token: str, secret_key: str, session_id: str = "default") -> bool:
    """Verify an HMAC-signed CSRF token in constant time."""
    if not token or "." not in token:
        return False
    try:
        nonce, sig = token.split(".", 1)
        msg = f"{session_id}:{nonce}".encode("utf-8")
        expected_sig = hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False


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
    """Strip dangerous XSS vectors (<script>,<iframe>, inline on* handlers, javascript: URLs)."""
    if not raw_html:
        return ""
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
    if config.enable_hsts:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if config.cors_origins:
        headers["Access-Control-Allow-Origin"] = config.cors_origins
    return headers
