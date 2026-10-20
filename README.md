# PyFusion Framework

[![CI](https://github.com/kondwani0099/pyfusion-framework/actions/workflows/ci.yml/badge.svg)](https://github.com/kondwani0099/pyfusion-framework/actions/workflows/ci.yml)
[![CodeQL](https://github.com/kondwani0099/pyfusion-framework/actions/workflows/codeql.yml/badge.svg)](https://github.com/kondwani0099/pyfusion-framework/actions/workflows/codeql.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Description:
PyFusion is an open-source, **Vue.js-inspired** Python framework designed for the seamless development of both reactive web and desktop applications. Combining Python's simplicity with Vue-style **Single-File Components (`.fusion`)**, reactive state (`ref`, `reactive`, `define_store`), and an extensible plugin architecture (`app.use()`), PyFusion empowers developers to build and share components, stores, and plugins on top of the framework.

## Key Features

- **Vue-Style Single-File Components (`.fusion`):** Write `<template>`, `<script>`, and `<style scoped>` in a single `.fusion` file or define Python `Component` classes.
- **Reactive Directives & Two-Way Binding:** Built-in support for `{{ expr }}`, `f-model` / `v-model`, `@click` / `@submit.prevent`, `f-if` / `v-if`, `f-for` / `v-for`, and `:attr` bindings synced automatically between the browser and Python backend via RPC.
- **Extensible Plugin & Store Ecosystem:** Build on top of PyFusion using `create_app()`, `app.use(plugin)`, `app.component(name, Comp)`, and Pinia-like `define_store()`.
- **Tkinter Desktop GUI:** Leveraging Python's standard GUI library, PyFusion enables the creation of desktop applications with integrated navigation.
- **CLI Tool (`pyfusion`):** Scaffold projects, components, stores, plugins, and pages, or run live-reload servers directly from the terminal.

## Screenshots 
![Alt Text](screenshots/pyfusion.png)


## Folder Structure
```text
pyfusion-framework/
├── pyfusion.json             # Root Project Config (name, title, icon, folder paths)
├── pyproject.toml            # Package & CLI configuration
├── requirements.txt          # Python dependencies
├── pyfusion.py               # CLI entry script
├── desktop/                  # Desktop Application Folder
│   ├── app.py                # Desktop GUI entry point
│   ├── icons/                # Compiled Windows .ico & desktop icons
│   │   ├── icon.ico
│   │   └── logo.png
│   └── shortcuts/            # Generated .lnk shortcuts & windowless .vbs launchers
├── web/                      # Web Application Folder
│   ├── app.py                # Web server & routes entry point
│   ├── index.html            # Main web landing page
│   ├── form.html             # Form / demo page
│   ├── assets/               # Static web assets (logo.png, styles.css, images)
│   │   ├── logo.png
│   │   └── styles.css
│   ├── components/           # Vue-style Single-File Components (.fusion)
│   │   └── Counter.fusion
│   ├── models/               # SQLite ORM models
│   ├── stores/               # Reactive state stores
│   └── plugins/              # Reusable plugins
└── fusionlib/                # Core PyFusion Framework engine
    ├── __init__.py
    ├── __main__.py
    ├── cli.py
    ├── component.py
    ├── config.py
    ├── database.py
    ├── gui_framework.py
    ├── modern_ui.py
    ├── navigation_manager.py
    ├── reactivity.py
    ├── security.py
    ├── ui_components.py
    └── web_server.py
```

## Getting Started

### Setup

1. Clone the repository and navigate into it:
   ```bash
   git clone https://github.com/kondwani0099/pyfusion-framework.git
   cd pyfusion-framework
   ```

2. Install dependencies and the `pyfusion` CLI (Python 3.10+):
   ```bash
   pip install -r requirements.txt
   pip install -e ".[dev]"
   ```

3. Run the test suite:
   ```bash
   pytest
   ```

---

## CLI Commands (`pyfusion`)

Run commands with `pyfusion` (or `python pyfusion.py` / `python -m fusionlib`):

```bash
# Scaffold a Vue-style Single-File Component (web/components/UserCard.fusion)
pyfusion create component UserCard

# Scaffold a Database ORM Model (web/models/product_model.py)
pyfusion create model Product

# Scaffold a Pinia/Vuex-style reactive store (web/stores/cart_store.py)
pyfusion create store cart

# Scaffold a reusable PyFusion plugin (web/plugins/auth_plugin.py)
pyfusion create plugin auth

# Scaffold a static web page (web/dashboard.html & web/assets/dashboard.css)
pyfusion create page dashboard

# Configure project name, desktop title, and custom icon in root pyfusion.json
pyfusion config --name "MyProject" --title "My Desktop App" --icon "web/assets/logo.png"

# Save a windowless Desktop App shortcut (.lnk) in desktop/shortcuts/ & Windows Desktop
pyfusion build shortcut

# Run the web server with live-reload (watches .py, .fusion, .html, .css)
pyfusion run web --port 5000 --reload --open

# Run the windowless desktop GUI application (desktop/app.py)
pyfusion run desktop

# Inspect all registered routes, reactive components, and static pages
pyfusion routes
```

---

## Building on Top of PyFusion (Vue.js Style)

### 1. Single-File Components (`web/components/Counter.fusion`)
Just like `.vue` files in Vue.js, `.fusion` files encapsulate HTML template, Python reactive logic, and scoped CSS:

```html
<template>
  <div class="card bg-base-100 shadow-xl p-6">
    <h2>{{ title }}: {{ count }} (Doubled: {{ doubled }})</h2>
    <input type="text" f-model="greeting" class="input input-bordered" />
    <p>{{ greeting }}</p>
    <button @click="increment" class="btn btn-primary">+1</button>
  </div>
</template>

<script>
props = {"title": "Reactive Counter"}

def data(self):
    return {"count": 0, "greeting": "Hello PyFusion!"}

def computed(self):
    return {"doubled": lambda state: int(state["count"]) * 2}

def increment(self):
    self.state.count = int(self.state.count) + 1
</script>

<style scoped>
.card { border-radius: 12px; }
</style>
```

### 2. Python Class Components, Stores & Plugins (`webapp.py`)
```python
from fusionlib import create_app, Component, define_store, FusionPlugin

# Define a Pinia-style reactive store
counter_store = define_store(
    "counter",
    state=lambda: {"count": 0},
    getters={"doubled": lambda s: s["count"] * 2},
    actions={"increment": lambda s: s.__setitem__("count", s["count"] + 1)},
)

# Define a reusable Plugin
class LoggerPlugin(FusionPlugin):
    name = "logger"
    def install(self, app, **options):
        @app.get("/api/logs")
        def get_logs(request):
            return {"plugin": self.name, "status": "enabled"}

# Create and configure the application (just like Vue's createApp)
app = (
    create_app()
    .use(LoggerPlugin())
    .store(counter_store)
    .mount("/counter", "components/Counter.fusion", title="Counter")
)

if __name__ == "__main__":
    app.run(host="localhost", port=5000, open_browser=True)
```

---

## Security Model

PyFusion components run on the server, and their state round-trips through the browser. The framework
protects that round-trip by default:

| Protection | How |
|---|---|
| **CSRF** | Signed double-submit cookie enforced on every POST/PUT/PATCH/DELETE. Tokens are auto-injected into `<form method="post">`, and `fetch()` gets `X-CSRF-Token` automatically. |
| **State integrity** | Component state is an HMAC-SHA256-signed snapshot. Tampered snapshots are rejected. |
| **Action allowlist** | Only functions you define in the component are callable from the browser. |
| **Locked props** | `locked = {"balance", "is_admin"}`: the browser can never change these. |
| **Local-only actions** | `@local_only` or `restrict_to_localhost = True` for actions that touch the machine. |
| **Passwords** | PBKDF2-HMAC-SHA256 at 600k iterations, plus `password_needs_rehash()`. |
| **Headers** | CSP, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, optional HSTS. |

```html
<script>
locked = {"count"}            # server-owned state

def increment(self):          # callable from @click="increment"
    self.state.count += 1

@local_only                   # only from localhost in development mode
def rebuild_icons(self):
    ...
</script>
```

See [SECURITY.md](SECURITY.md) for the full model and how to report vulnerabilities.

## Production Deployment

```bash
export PYFUSION_ENV=production
export PYFUSION_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
pyfusion run web --production --host 127.0.0.1 --port 5000
```

- Production mode disables live reload, hides error details and internal health data, and refuses to
  start without `PYFUSION_SECRET_KEY`.
- Put it behind a TLS reverse proxy (nginx, Caddy) and use `SecurityConfig(enable_hsts=True)` so cookies
  are marked `Secure`.

## Docker Support
To build and run your Docker image:
```bash
docker build -t pyfusion-app .
docker run -p 5000:5000 -e PYFUSION_SECRET_KEY=change-me pyfusion-app
```

## Contributing
Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) and our
[Code of Conduct](CODE_OF_CONDUCT.md). Release notes live in [CHANGELOG.md](CHANGELOG.md).

## License
This project is licensed under the [MIT License](LICENSE).
