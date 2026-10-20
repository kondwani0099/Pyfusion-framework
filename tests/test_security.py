import threading

from fusionlib.security import (
    PBKDF2_DEFAULT_ITERATIONS,
    RateLimiter,
    SecurityConfig,
    csrf_tokens_match,
    escape_html,
    generate_csrf_token,
    get_owasp_security_headers,
    hash_password,
    is_loopback,
    is_safe_static_path,
    password_needs_rehash,
    sign_state,
    verify_csrf_token,
    verify_password,
    verify_state,
)

SECRET = "unit-test-secret"


def test_password_hash_roundtrip_and_policy():
    hashed = hash_password("correct horse")
    assert hashed.startswith(f"pbkdf2_sha256${PBKDF2_DEFAULT_ITERATIONS}$")
    assert PBKDF2_DEFAULT_ITERATIONS >= 600_000  # OWASP Password Storage Cheat Sheet
    assert verify_password("correct horse", hashed)
    assert not verify_password("wrong", hashed)
    assert not password_needs_rehash(hashed)


def test_legacy_hash_still_verifies_but_needs_rehash():
    legacy = hash_password("pw", iterations=1000)
    assert verify_password("pw", legacy)
    assert password_needs_rehash(legacy)
    assert password_needs_rehash("garbage")


def test_csrf_double_submit():
    token = generate_csrf_token(SECRET)
    assert verify_csrf_token(token, SECRET)
    assert csrf_tokens_match(token, token, SECRET)
    assert not csrf_tokens_match(token, None, SECRET)
    assert not csrf_tokens_match(token, generate_csrf_token(SECRET), SECRET)
    forged = token.split(".")[0] + ".deadbeef"
    assert not csrf_tokens_match(forged, forged, SECRET)
    assert not verify_csrf_token(token, "other-secret")


def test_state_signature_detects_tampering():
    snap = '{"count":1,"is_admin":false}'
    sig = sign_state("Counter", snap, SECRET)
    assert verify_state("Counter", snap, sig, SECRET)
    assert not verify_state("Counter", snap.replace("false", "true"), sig, SECRET)
    assert not verify_state("Other", snap, sig, SECRET)
    assert not verify_state("Counter", snap, "", SECRET)
    assert not verify_state("Counter", None, sig, SECRET)


def test_path_traversal_and_sensitive_files(tmp_path):
    (tmp_path / "ok.css").write_text("x")
    assert is_safe_static_path(str(tmp_path), "/ok.css")[0]
    assert not is_safe_static_path(str(tmp_path), "../etc/passwd")[0]
    assert not is_safe_static_path(str(tmp_path), "/.env")[0]
    assert not is_safe_static_path(str(tmp_path), "/app.py")[0]
    assert not is_safe_static_path(str(tmp_path), "/components/X.fusion")[0]


def test_security_headers_include_csp():
    headers = get_owasp_security_headers(SecurityConfig(secret_key=SECRET))
    assert "Content-Security-Policy" in headers
    assert "object-src 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    hsts = get_owasp_security_headers(SecurityConfig(secret_key=SECRET, enable_hsts=True))
    assert "Strict-Transport-Security" in hsts


def test_secure_cookies_follow_hsts():
    assert SecurityConfig(secret_key=SECRET, enable_hsts=True).secure_cookies is True
    assert SecurityConfig(secret_key=SECRET).secure_cookies is False


def test_rate_limiter_blocks_and_is_thread_safe():
    limiter = RateLimiter(max_requests=50, window_seconds=60)
    results = []

    def hit():
        for _ in range(10):
            results.append(limiter.is_allowed("1.2.3.4")[0])

    threads = [threading.Thread(target=hit) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 50
    assert results.count(False) == 50


def test_rate_limiter_memory_is_bounded():
    limiter = RateLimiter(max_requests=5, window_seconds=0, max_tracked_ips=10)
    for i in range(100):
        limiter.is_allowed(f"10.0.0.{i}")
    assert len(limiter._hits) <= 11


def test_escape_html_and_loopback():
    assert escape_html("<script>") == "&lt;script&gt;"
    assert is_loopback("127.0.0.1") and is_loopback("::1")
    assert not is_loopback("192.168.1.10")
    assert not is_loopback(None)
