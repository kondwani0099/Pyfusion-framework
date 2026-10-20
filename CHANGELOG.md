# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.6.0] - 2026-10-20

### Added
- **ASGI transport (`fusionlib.asgi.PyFusionASGI`) & uvicorn integration:** `pyfusion run web` and
  `app.run()` automatically use `uvicorn` (ASGI 3, HTTP/1.1 keep-alive, WebSockets) when installed,
  falling back to the zero-dependency stdlib server (`--server stdlib`). Any app can also be served
  directly via `uvicorn web.app:app.asgi` or `gunicorn -k uvicorn.workers.UvicornWorker web.app:app.asgi`.
- **WebSocket channel (`/_pyfusion/ws`):** low-latency component RPC over a persistent socket plus
  push-based live reload in development mode (no polling), with automatic HTTP fallback.
- **Cross-Site WebSocket Hijacking (CSWSH) protection:** WebSocket handshakes verify same-origin
  `Origin`/`Host` headers, require the `?csrf=` query parameter to match the signed `pyfusion_csrf`
  cookie, and enforce per-IP rate limiting and message size caps.
- **CSP-safe client expression evaluator (`SafeExpr`):** replaced `new Function` in the browser runtime
  with a sandboxed Pratt-parser AST evaluator supporting member/optional chaining (`?.`), nullish
  coalescing (`??`), ternaries, calls, array/object literals, and assignment/update operators (`+=`, `++`)
  while blocking `constructor`, `__proto__`, `prototype`, and arbitrary globals.
- **Precompiled Tailwind CSS + daisyUI bundle:** shipped precompiled CSS (`web/assets/app.css` and
  packaged `fusionlib/static/pyfusion.css` served at `/_pyfusion/pyfusion.css`) and added
  `pyfusion build css [--watch]`. Python-only users do not need Node.js installed.

### Security
- **Tightened default `Content-Security-Policy` (`DEFAULT_CSP`):** `script-src 'self'` with no
  `'unsafe-eval'`, no `'unsafe-inline'`, and no third-party script CDNs. Converted all demo inline
  `onclick` handlers to CSP-safe `data-*` event delegation. `LEGACY_CSP` remains available for apps
  that opt into CDN scripts.

## [0.5.0] - 2026-10-20

### Security
- **CSRF is now enforced** on every POST/PUT/PATCH/DELETE route, including `/_pyfusion/rpc`, using a
  signed double-submit cookie. Tokens are injected automatically into `<form method="post">`, and the
  client runtime attaches `X-CSRF-Token` to same-origin `fetch()` calls.
- **Component state integrity:** browser-held state is an HMAC-SHA256-signed snapshot. Tampered
  snapshots are rejected with `403 stale_state`.
- **RPC action allowlist:** only functions defined in a component (SFC top-level `def`s or class-body
  methods) are callable. Imported helpers, Model classes, private and lifecycle methods are blocked.
- New `locked = {...}` component attribute: listed props can never be modified by the client.
- New `@local_only` decorator and `restrict_to_localhost` attribute for actions with machine-level side
  effects. These run only for loopback clients in development mode.
- `/api/project/*` studio endpoints are restricted to localhost in development mode.
- PBKDF2-HMAC-SHA256 raised from 260k to **600k iterations** (OWASP). Added `password_needs_rehash()`.
- Added a `Content-Security-Policy` header (`DEFAULT_CSP`, with `STRICT_CSP` available).
- Directory listings disabled; 30 s socket timeout; Content-Length validation.
- The rate limiter is thread-safe and its memory is bounded.
- `SO_REUSEADDR` is disabled on Windows to prevent port hijacking.
- `/api/security/audit` now reports only protections that are actually enforced.
- `sanitize_html` uses `nh3` when installed (`pip install pyfusion-framework[security]`).

### Added
- Development/production modes (`PYFUSION_ENV`, `PYFUSION_DEBUG`, `pyfusion run web --production`).
  Production mode requires `PYFUSION_SECRET_KEY`, disables live reload and hides error details.
- A persistent development secret (`.pyfusion/dev_secret`) so sessions survive restarts.
- `app.put()`, `app.patch()` and `app.csrf_exempt()`.
- Test suite (`tests/`), CI matrix, CodeQL, Dependabot, `SECURITY.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`.

### Changed
- **Breaking:** requires Python **3.10+** (3.8 and 3.9 are end-of-life).
- **Breaking:** RPC payloads use `snapshot` + `checksum` + `updates` instead of `state`. Reload open
  pages after upgrading.
- Mounted pages accept only declared `props` from the query string.
- Unmatched POST requests now return `404` instead of echoing the body.
- The version is single-sourced in `fusionlib/_version.py`.

## [0.4.0]
- Vue-style Single-File Components, reactive stores, plugins, desktop and Android tooling.
