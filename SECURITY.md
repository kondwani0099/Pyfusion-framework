# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.6.x   | ✅ |
| 0.5.x   | ✅ (security fixes) |
| < 0.5   | ❌ (CSRF was not enforced and component state was not integrity-checked; please upgrade) |

## Reporting a vulnerability

**Please do not open public GitHub issues for security problems.**

Report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/kondwani0099/pyfusion-framework/security/advisories/new).
Include:

- affected version and component (e.g. `fusionlib/web_server.py`, RPC endpoint)
- reproduction steps or a proof of concept
- impact assessment, if known

We aim to acknowledge reports within **3 business days** and to ship a fix or mitigation for
confirmed high-severity issues within **30 days**. Reporters are credited in the release notes
unless they ask to remain anonymous.

## Security model (summary)

| Area | Mechanism |
|------|-----------|
| CSRF & CSWSH | Signed double-submit cookie (`pyfusion_csrf`) enforced on every POST/PUT/PATCH/DELETE and on the `/_pyfusion/ws` WebSocket handshake (alongside same-origin `Origin`/`Host` verification). Tokens are injected automatically into `<form method="post">`. |
| Component RPC | Only functions defined in the component are callable. State held by the browser is an HMAC-SHA256-signed snapshot. `locked` props cannot be changed by the client. `@local_only` / `restrict_to_localhost` actions run only for loopback clients in development mode. |
| Client runtime | CSP-safe `SafeExpr` AST evaluator (no `eval` / `new Function`); blocks `constructor`, `__proto__`, `prototype`, and unapproved globals. |
| Passwords | PBKDF2-HMAC-SHA256, 600,000 iterations (OWASP). Use `password_needs_rehash()` to upgrade legacy hashes. |
| Headers | `DEFAULT_CSP` enforces `script-src 'self'` (no `'unsafe-eval'`, no `'unsafe-inline'`, no script CDNs), plus X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, COOP, and optional HSTS. |
| Static files | Path-traversal guard; dotfiles, `.py`, `.fusion` and DB files are blocked; no directory listings. |
| Abuse | Per-IP sliding-window rate limit, 2 MB body/frame cap, keep-alive/socket timeouts. |

## Deployment checklist

1. Set `PYFUSION_ENV=production` (or `pyfusion run web --production`).
2. Set a strong `PYFUSION_SECRET_KEY` (`python -c "import secrets; print(secrets.token_hex(32))"`).
   The server refuses to start in production without one.
3. Terminate TLS at a reverse proxy (nginx, Caddy, Traefik) and pass `SecurityConfig(enable_hsts=True)`
   so cookies are marked `Secure`.
4. Run on the ASGI backend (`uvicorn`, selected automatically when installed, or multi-worker
   `gunicorn -k uvicorn.workers.UvicornWorker web.app:app.asgi`) behind your reverse proxy.
5. For untrusted rich HTML, install the `security` extra (`pip install pyfusion-framework[security]`)
   so `sanitize_html` uses the `nh3` allowlist sanitizer.
6. If you remove all inline `<style>` blocks from your components, you can switch from `DEFAULT_CSP`
   to `STRICT_CSP` (`style-src 'self'`).
