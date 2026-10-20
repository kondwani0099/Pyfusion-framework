import argparse
import os
import subprocess
import sys
import time
from .web_server import default_app, run_web_server

VERSION = "0.4.0"

PAGE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - PyFusion</title>
    <link href="https://cdn.jsdelivr.net/npm/daisyui@4.5.0/dist/full.min.css" rel="stylesheet" type="text/css" />
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="/assets/styles.css">
    <link rel="stylesheet" href="/assets/{name}.css">
</head>
<body class="bg-base-300 text-base-content min-h-screen flex flex-col">
    <div class="navbar bg-base-100 shadow-sm">
        <div class="flex-1">
            <a href="/" class="btn btn-ghost text-xl">PyFusion</a>
        </div>
        <div class="flex-none gap-2">
            <a href="/" class="btn btn-sm btn-ghost">Home</a>
            <a href="/{name}" class="btn btn-sm btn-primary">{title}</a>
        </div>
    </div>

    <main class="flex-1 container mx-auto p-8">
        <div class="card bg-base-100 shadow-xl max-w-xl mx-auto">
            <div class="card-body">
                <h1 class="card-title text-2xl">{title} Page</h1>
                <p>Created with <code>pyfusion create page {name}</code>.</p>
            </div>
        </div>
    </main>
    <script src="/_pyfusion/client.js"></script>
</body>
</html>
"""

PAGE_CSS_TEMPLATE = """/* web/assets/{name}.css */
h1 {{
    color: #10b981;
}}
"""

SFC_COMPONENT_TEMPLATE = """<template>
  <div class="card bg-base-100 shadow-lg border border-base-300 max-w-md mx-auto my-6">
    <div class="card-body">
      <h2 class="card-title text-xl font-bold">{{ title }}</h2>
      <p class="text-sm opacity-80">Count: <strong>{{ count }}</strong> (Doubled: {{ doubled }})</p>

      <div class="form-control mt-2">
        <input type="text" f-model="message" class="input input-bordered input-sm" placeholder="Two-way bound input..." />
        <span class="text-xs mt-1 opacity-75">You typed: {{ message }}</span>
      </div>

      <div class="card-actions justify-end mt-4">
        <button @click="decrement" class="btn btn-outline btn-sm">-1</button>
        <button @click="increment" class="btn btn-primary btn-sm">+1</button>
      </div>
    </div>
  </div>
</template>

<script>
props = {{
    "title": "{component_name} Component"
}}

def data(self):
    return {{
        "count": 0,
        "message": "Hello PyFusion!"
    }}

def computed(self):
    return {{
        "doubled": lambda state: int(state.get("count", 0)) * 2
    }}

def increment(self):
    self.state.count = int(self.state.count) + 1

def decrement(self):
    self.state.count = int(self.state.count) - 1
</script>

<style scoped>
.card {{
    border-radius: 0.75rem;
}}
</style>
"""

STORE_TEMPLATE = """\"\"\"Reactive state store '{name}' (Pinia / Vuex style) for PyFusion.\"\"\"
from fusionlib import define_store

{name}_store = define_store(
    "{name}",
    state=lambda: {{
        "items": [],
        "count": 0,
    }},
    getters={{
        "total_items": lambda state: len(state["items"]),
    }},
    actions={{
        "increment": lambda state: state.__setitem__("count", state["count"] + 1),
        "add_item": lambda state, item: state["items"].append(item),
    }},
)
"""

MODEL_TEMPLATE = """\"\"\"Database ORM Model '{class_name}' (100% Parameterized SQL / OWASP A03 Safe).\"\"\"
from fusionlib import Field, Model


class {class_name}(Model):
    table_name = "{table_name}"

    name = Field("TEXT", nullable=False)
    description = Field("TEXT", default="")
"""

PLUGIN_TEMPLATE = """\"\"\"Reusable PyFusion plugin '{class_name}'.\"\"\"
from fusionlib import FusionPlugin


class {class_name}(FusionPlugin):
    name = "{name}"

    def install(self, app, **options):
        \"\"\"Called when app.use({class_name}(), **options) is invoked.\"\"\"
        prefix = options.get("prefix", "/api/{name}")

        @app.get(prefix)
        def plugin_info(request):
            return {{"plugin": self.name, "status": "active", "options": options}}
"""

INIT_APP_TEMPLATE = """from fusionlib import FusionDB, create_app

db = FusionDB("sqlite:///pyfusion.db")
app = create_app().use(db)

if "Counter" in app.components:
    app.mount("/counter", app.components["Counter"], title="Counter Demo")


@app.get("/api/status")
def status(request):
    return {{"project": "{project_name}", "status": "running", "components": list(app.components.keys())}}


if __name__ == "__main__":
    app.run(host="localhost", port=5000, open_browser=True)
"""


def _iter_watched_files(base_dir):
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "env", "venv", ".venv", "node_modules")]
        for f in files:
            if f.endswith((".py", ".html", ".css", ".js", ".fusion")):
                yield os.path.join(root, f)


def _run_with_reloader(host, port, open_browser):
    """Run web server in a subprocess and restart it whenever Python files change (HTML/CSS/.fusion reload live in browser)."""
    print(f"[PyFusion] Starting server with Browser + Backend Live-Reload on http://{host}:{port} ...")
    base_dir = os.getcwd()

    def snapshot_py():
        mtimes = {}
        for path in _iter_watched_files(base_dir):
            if path.endswith(".py"):
                try:
                    mtimes[path] = os.stat(path).st_mtime
                except OSError:
                    pass
        return mtimes

    cmd = [sys.executable, "-m", "fusionlib", "run", "web", "--host", host, "--port", str(port)]
    if open_browser:
        cmd.append("--open")

    last_mtimes = snapshot_py()
    proc = subprocess.Popen(cmd)

    # Only open browser on the first start
    cmd = [c for c in cmd if c != "--open"]

    try:
        while True:
            time.sleep(1.0)
            current_mtimes = snapshot_py()
            if current_mtimes != last_mtimes:
                print("\n[PyFusion] Python file change detected! Restarting backend & triggering browser reload...")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                last_mtimes = current_mtimes
                proc = subprocess.Popen(cmd)
    except KeyboardInterrupt:
        proc.terminate()
        print("\n[PyFusion] Live-reload server stopped.")


def _load_user_app():
    from .config import resolve_web_entry

    app = default_app
    web_entry = resolve_web_entry()
    if os.path.exists(web_entry):
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location("web_app", web_entry)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "app"):
                app = module.app
        except Exception as exc:
            print(f"[PyFusion] Note: Could not auto-import {web_entry} ({exc})")
    return app


def cmd_run(args):
    mode = args.mode
    if mode == "web":
        if args.reload:
            _run_with_reloader(args.host, args.port, args.open)
            return

        app = _load_user_app()
        run_web_server(port=args.port, host=args.host, app=app, open_browser=args.open)

    elif mode == "desktop":
        if not getattr(args, "foreground", False):
            from .config import launch_desktop_detached, load_project_config

            extra = []
            if args.title:
                extra.extend(["--title", args.title])
            if args.color:
                extra.extend(["--color", args.color])
            if getattr(args, "icon", None):
                extra.extend(["--icon", args.icon])
            if args.port:
                extra.extend(["--port", str(args.port)])
            if getattr(args, "engine", None):
                extra.extend(["--engine", args.engine])

            pid = launch_desktop_detached(extra)
            cfg = load_project_config()
            title = args.title or cfg.get("app_title", "PyFusion Desktop")
            print(f"[PyFusion] Launched '{title}' as a standalone desktop window (PID: {pid}).")
            return

        from .gui_framework import HTMLAppWindow

        html_content = None
        if args.page != "index":
            html_file = os.path.join("web", f"{args.page}.html")
            if os.path.exists(html_file):
                with open(html_file, "r", encoding="utf-8") as f:
                    html_content = f.read()

        HTMLAppWindow(
            app_name=args.title,
            app_color=args.color,
            icon_path=getattr(args, "icon", None),
            html_content=html_content,
            port=args.port,
            engine=getattr(args, "engine", "auto"),
        )

    elif mode == "mobile":
        if not getattr(args, "foreground", False):
            from .config import launch_mobile_detached, load_project_config

            extra = []
            if args.title:
                extra.extend(["--title", args.title])
            if getattr(args, "icon", None):
                extra.extend(["--icon", args.icon])
            if args.port:
                extra.extend(["--port", str(args.port)])

            pid = launch_mobile_detached(extra)
            cfg = load_project_config()
            title = args.title or cfg.get("app_title", "PyFusion Mobile")
            print(f"[PyFusion] Launched '{title}' Android Simulator window (PID: {pid}).")
            return

        from .mobile_simulator import AndroidSimulatorWindow

        AndroidSimulatorWindow(
            app_name=args.title,
            icon_path=getattr(args, "icon", None),
            port=args.port,
        )

    elif mode == "dev":
        from .gui_framework import HTMLAppWindow

        app = _load_user_app()
        print(f"[PyFusion] Starting background web server on http://{args.host}:{args.port} ...")
        run_web_server(port=args.port, host=args.host, app=app, in_thread=True, open_browser=args.open)

        html_content = None
        if args.page != "index":
            html_file = os.path.join("web", f"{args.page}.html")
            if os.path.exists(html_file):
                with open(html_file, "r", encoding="utf-8") as f:
                    html_content = f.read()

        print("[PyFusion] Launching desktop window...")
        HTMLAppWindow(
            app_name=args.title,
            app_color=args.color,
            icon_path=getattr(args, "icon", None),
            html_content=html_content,
            port=args.port,
            engine=getattr(args, "engine", "auto"),
        )


def cmd_create(args):
    from .config import load_project_config

    cfg = load_project_config()
    paths = cfg.get("paths", {})
    resource = args.resource
    raw_name = args.name.strip()

    if resource == "page":
        name = raw_name.lower().replace(".html", "")
        title = name.replace("_", " ").replace("-", " ").title()
        web_dir = os.path.abspath(paths.get("web_dir", "web"))
        assets_dir = os.path.abspath(paths.get("assets_dir", "web/assets"))
        os.makedirs(web_dir, exist_ok=True)
        os.makedirs(assets_dir, exist_ok=True)

        html_path = os.path.join(web_dir, f"{name}.html")
        css_path = os.path.join(assets_dir, f"{name}.css")

        if os.path.exists(html_path) and not args.force:
            print(f"[PyFusion] Error: Page '{html_path}' already exists. Use --force to overwrite.")
            sys.exit(1)

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(PAGE_HTML_TEMPLATE.format(name=name, title=title))

        if not os.path.exists(css_path) or args.force:
            with open(css_path, "w", encoding="utf-8") as f:
                f.write(PAGE_CSS_TEMPLATE.format(name=name))

        print(f"[PyFusion] Created page templates (with Browser Live-Reload):")
        print(f"  - {html_path}")
        print(f"  - {css_path}")

    elif resource == "component":
        comp_name = raw_name.replace(".fusion", "")
        comp_name = comp_name[0].upper() + comp_name[1:] if comp_name else "MyComponent"
        comp_dir = os.path.abspath(paths.get("components_dir", "web/components"))
        os.makedirs(comp_dir, exist_ok=True)

        comp_path = os.path.join(comp_dir, f"{comp_name}.fusion")
        if os.path.exists(comp_path) and not args.force:
            print(f"[PyFusion] Error: Component '{comp_path}' already exists. Use --force to overwrite.")
            sys.exit(1)

        with open(comp_path, "w", encoding="utf-8") as f:
            f.write(SFC_COMPONENT_TEMPLATE.format(component_name=comp_name))

        print(f"[PyFusion] Created Single-File Component (.fusion) in web/components/:")
        print(f"  - {comp_path}")

    elif resource == "model":
        clean = raw_name.replace("_model", "").replace(".py", "")
        class_name = "".join(part.capitalize() for part in clean.split("_"))
        table_name = clean.lower() + "s"
        models_dir = os.path.abspath(paths.get("models_dir", "web/models"))
        os.makedirs(models_dir, exist_ok=True)

        model_path = os.path.join(models_dir, f"{clean.lower()}_model.py")
        if os.path.exists(model_path) and not args.force:
            print(f"[PyFusion] Error: Model '{model_path}' already exists. Use --force to overwrite.")
            sys.exit(1)

        with open(model_path, "w", encoding="utf-8") as f:
            f.write(MODEL_TEMPLATE.format(class_name=class_name, table_name=table_name))

        print(f"[PyFusion] Created Database ORM Model in web/models/:")
        print(f"  - {model_path} (Table: '{table_name}')")

    elif resource == "store":
        store_name = raw_name.lower().replace("_store", "").replace(".py", "")
        stores_dir = os.path.abspath(paths.get("stores_dir", "web/stores"))
        os.makedirs(stores_dir, exist_ok=True)

        store_path = os.path.join(stores_dir, f"{store_name}_store.py")
        if os.path.exists(store_path) and not args.force:
            print(f"[PyFusion] Error: Store '{store_path}' already exists. Use --force to overwrite.")
            sys.exit(1)

        with open(store_path, "w", encoding="utf-8") as f:
            f.write(STORE_TEMPLATE.format(name=store_name))

        print(f"[PyFusion] Created reactive store in web/stores/:")
        print(f"  - {store_path}")

    elif resource == "plugin":
        plugin_name = raw_name.lower().replace("_plugin", "").replace(".py", "")
        class_name = "".join(part.capitalize() for part in plugin_name.split("_")) + "Plugin"
        plugins_dir = os.path.abspath(paths.get("plugins_dir", "web/plugins"))
        os.makedirs(plugins_dir, exist_ok=True)

        plugin_path = os.path.join(plugins_dir, f"{plugin_name}_plugin.py")
        if os.path.exists(plugin_path) and not args.force:
            print(f"[PyFusion] Error: Plugin '{plugin_path}' already exists. Use --force to overwrite.")
            sys.exit(1)

        with open(plugin_path, "w", encoding="utf-8") as f:
            f.write(PLUGIN_TEMPLATE.format(name=plugin_name, class_name=class_name))

        print(f"[PyFusion] Created plugin in web/plugins/:")
        print(f"  - {plugin_path}")


def cmd_db(args):
    app = _load_user_app()
    from .database import FusionDB

    db = getattr(app, "db", None) or FusionDB()
    if args.action == "migrate":
        db.create_all()
        print(f"[PyFusion DB] Migrated all registered models in {db.sqlite_path}")
    else:
        db.create_all()
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        print(f"[PyFusion DB] Connected to: {db.sqlite_path}")
        print(f"[PyFusion DB] Tables ({len(tables)}): {', '.join(t['name'] for t in tables) or 'None'}")


def cmd_init(args):
    from .config import save_project_config

    project_name = args.project_name.strip()
    target_dir = os.path.abspath(project_name)

    if os.path.exists(target_dir) and os.listdir(target_dir):
        print(f"[PyFusion] Error: Directory '{target_dir}' already exists and is not empty.")
        sys.exit(1)

    for folder in (
        "desktop/icons",
        "desktop/shortcuts",
        "mobile",
        "web/assets",
        "web/components",
        "web/models",
        "web/stores",
        "web/plugins",
    ):
        os.makedirs(os.path.join(target_dir, folder), exist_ok=True)

    # Root config outside folders
    save_project_config({"project_name": project_name, "app_title": project_name}, base_dir=target_dir)

    with open(os.path.join(target_dir, "web", "index.html"), "w", encoding="utf-8") as f:
        f.write(PAGE_HTML_TEMPLATE.format(name="index", title=project_name))

    with open(os.path.join(target_dir, "web", "assets", "styles.css"), "w", encoding="utf-8") as f:
        f.write("body { font-family: 'Poppins', sans-serif; }\n")

    with open(os.path.join(target_dir, "web", "components", "Counter.fusion"), "w", encoding="utf-8") as f:
        f.write(SFC_COMPONENT_TEMPLATE.format(component_name="Counter"))

    with open(os.path.join(target_dir, "web", "app.py"), "w", encoding="utf-8") as f:
        f.write(INIT_APP_TEMPLATE.format(project_name=project_name))

    with open(os.path.join(target_dir, "desktop", "app.py"), "w", encoding="utf-8") as f:
        f.write(
            'import os, sys\n'
            'PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n'
            'os.chdir(PROJECT_ROOT)\n'
            'if PROJECT_ROOT not in sys.path:\n'
            '    sys.path.insert(0, PROJECT_ROOT)\n'
            'from fusionlib.gui_framework import HTMLAppWindow\n\n'
            'if __name__ == "__main__":\n'
            '    HTMLAppWindow()\n'
        )

    with open(os.path.join(target_dir, "mobile", "app.py"), "w", encoding="utf-8") as f:
        f.write(
            'import os, sys\n'
            'PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n'
            'os.chdir(PROJECT_ROOT)\n'
            'if PROJECT_ROOT not in sys.path:\n'
            '    sys.path.insert(0, PROJECT_ROOT)\n'
            'from fusionlib.mobile_simulator import AndroidSimulatorWindow\n\n'
            'if __name__ == "__main__":\n'
            '    AndroidSimulatorWindow()\n'
        )

    print(f"[PyFusion] Initialized Vue-style PyFusion project in '{target_dir}'!")
    print("  - pyfusion.json         (Root Project Config)")
    print("  - desktop/app.py        (Desktop Application)")
    print("  - mobile/app.py         (Android & Mobile Application)")
    print("  - web/app.py            (Web Server & Routes)")
    print("  - web/assets/           (Static CSS, Images, Icons)")
    print("  - web/components/       (Single-File Components .fusion)")
    print(f"\nNext steps:")
    print(f"  cd {project_name}")
    print(f"  pyfusion run web --open --reload")
    print(f"  pyfusion run desktop")
    print(f"  pyfusion run mobile")


def cmd_routes(args):
    app = _load_user_app()

    print("Registered HTTP Routes:")
    print("-" * 60)
    print(f"{'METHODS':<15} {'PATH':<28} {'HANDLER'}")
    print("-" * 60)
    for route in app.routes:
        methods = ", ".join(route["methods"])
        handler_name = route["handler"].__name__
        print(f"{methods:<15} {route['path']:<28} {handler_name}")

    if app.components:
        print("\nRegistered Reactive Components (.fusion / Component):")
        for comp_name, comp_cls in app.components.items():
            props_keys = list(getattr(comp_cls, "props", {}).keys())
            print(f"  <{comp_name} />  (props: {props_keys or 'none'})")

    web_dir = app.web_dir
    if os.path.exists(web_dir):
        html_pages = [f for f in os.listdir(web_dir) if f.endswith(".html")]
        if html_pages:
            print("\nStatic Web Pages (web/):")
            for page in sorted(html_pages):
                clean_route = "/" if page == "index.html" else f"/{page[:-5]}"
                print(f"GET             {clean_route:<28} web/{page}")


def cmd_info(args):
    from .config import load_project_config

    app = _load_user_app()
    cfg = load_project_config()
    paths = cfg.get("paths", {})
    print(f"PyFusion Framework v{VERSION} (Vue-Reactive + OWASP Hardened + SQLite ORM)")
    print(f"Python Version : {sys.version.split()[0]}")
    print(f"Root Config    : {os.path.abspath('pyfusion.json')}")
    print(f"Desktop Folder : {os.path.abspath(paths.get('desktop_dir', 'desktop'))} (entry: {paths.get('desktop_entry', 'desktop/app.py')})")
    print(f"Mobile Folder  : {os.path.abspath(paths.get('mobile_dir', 'mobile'))} (entry: {paths.get('mobile_entry', 'mobile/app.py')})")
    print(f"Web Folder     : {os.path.abspath(paths.get('web_dir', 'web'))} (entry: {paths.get('web_entry', 'web/app.py')})")
    print(f"Web Assets     : {os.path.abspath(paths.get('assets_dir', 'web/assets'))}")
    print(f"Web Components : {os.path.abspath(paths.get('components_dir', 'web/components'))} ({', '.join(app.components.keys()) if app.components else 'None'})")
    print(f"Database       : {'Connected (' + app.db.db_url + ')' if getattr(app, 'db', None) else 'Ready (FusionDB)'}")
    web_dir = os.path.abspath(paths.get("web_dir", "web"))
    if os.path.exists(web_dir):
        pages = [f for f in os.listdir(web_dir) if f.endswith(".html")]
        print(f"Static Pages   : {', '.join(pages) if pages else 'None'}")


def cmd_config(args):
    from .config import ensure_project_ico, load_project_config, save_project_config

    updates = {}
    if args.name:
        updates["project_name"] = args.name.strip()
    if args.title:
        updates["app_title"] = args.title.strip()
    if args.author:
        updates["author"] = args.author.strip()
    if args.icon:
        updates["icon"] = args.icon.strip()
    if args.color:
        updates["theme_color"] = args.color.strip()

    if updates:
        cfg = save_project_config(updates)
        ico = ensure_project_ico(cfg.get("icon"))
        print("[PyFusion Config] Updated pyfusion.json:")
        for k, v in updates.items():
            print(f"  {k:<15}: {v}")
        if ico:
            print(f"  generated_ico  : {ico}")
    else:
        cfg = load_project_config()
        print("Current Project Configuration (pyfusion.json):")
        for k, v in cfg.items():
            print(f"  {k:<15}: {v}")


def cmd_build(args):
    from .config import (
        build_standalone_exe,
        create_desktop_shortcut,
        ensure_project_ico,
        generate_android_project,
        save_project_config,
    )

    updates = {}
    if args.name:
        updates["project_name"] = args.name.strip()
        if not args.title:
            updates["app_title"] = args.name.strip()
    if args.title:
        updates["app_title"] = args.title.strip()
    if args.icon:
        updates["icon"] = args.icon.strip()
    if updates:
        save_project_config(updates)

    ensure_project_ico()
    if args.target == "exe":
        dist_exe = build_standalone_exe(onefile=True)
        print(f"[PyFusion Build] Standalone executable saved at: {dist_exe}")
    elif args.target in ("android", "apk", "aab"):
        fmt = args.target if args.target in ("apk", "aab") else getattr(args, "format", "both")
        info = generate_android_project(artifact_format=fmt)
        print(f"[PyFusion Android] Synced Android {info['format']} project for '{info['app_title']}' ({info['package_name']})!")
        print(f"  - Debug Format     : .{info['debug_artifact'].lower()} (Direct Device Install)")
        print(f"  - Release Format   : .{info['release_artifact'].lower()} (Google Play Store Bundle)")
        print(f"  - Buildozer Spec   : {info['buildozer_spec']}")
        print(f"  - Capacitor Config : {info['capacitor_config']}")
        print(f"  - Docker Compiler  : {info['dockerfile_android']}")
        print(f"  - GitHub Actions   : {info['github_workflow']}")
        print(f"  - Mobile Simulator : Run `pyfusion run mobile` to preview on desktop")
    else:
        info = create_desktop_shortcut()
        print(f"[PyFusion Build] Saved Windowless Desktop Application '{info['app_title']}'!")
        print(f"  - Icon (.ico)  : {info['ico_path']}")
        print(f"  - Launcher     : {info.get('launcher_vbs', '')}")
        for s in info.get("shortcuts", []):
            print(f"  - Shortcut     : {s}")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pyfusion",
        description="PyFusion Framework CLI - Vue-inspired, OWASP-hardened Web, Desktop & Android framework for Python.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"PyFusion {VERSION}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # pyfusion run [web|desktop|mobile|dev]
    run_parser = subparsers.add_parser("run", help="Run the PyFusion web server, desktop app, Android mobile simulator, or dev")
    run_parser.add_argument(
        "mode",
        nargs="?",
        default="web",
        choices=["web", "desktop", "mobile", "dev"],
        help="Execution mode: 'web' (default), 'desktop', 'mobile' (Android simulator), or 'dev'",
    )
    run_parser.add_argument("--host", default="localhost", help="Host address (default: localhost)")
    run_parser.add_argument("-p", "--port", type=int, default=5000, help="Port number (default: 5000)")
    run_parser.add_argument("--open", action="store_true", help="Open web browser automatically")
    run_parser.add_argument("-r", "--reload", action="store_true", help="Enable live-reload on file changes (web mode)")
    run_parser.add_argument("--page", default="index", help="Initial HTML page name for desktop mode (default: index)")
    run_parser.add_argument("--title", default=None, help="Window title for desktop/mobile mode (defaults to pyfusion.json)")
    run_parser.add_argument("--color", default=None, help="AppBar accent color for desktop mode")
    run_parser.add_argument("--icon", default=None, help="Path to custom window icon (.png or .ico)")
    run_parser.add_argument(
        "--engine",
        default=None,
        choices=["auto", "webview", "tk"],
        help="Desktop UI engine: 'tk' (Dark Web-UI Engine, default) or 'webview' (WebView2 Chromium)",
    )
    run_parser.add_argument(
        "--foreground",
        action="store_true",
        help="Attach desktop/mobile app to current terminal instead of launching as a detached GUI process",
    )
    run_parser.set_defaults(func=cmd_run)

    # pyfusion config
    config_parser = subparsers.add_parser("config", help="View or set project name, window title, author, and icon")
    config_parser.add_argument("--name", help="Set project_name in pyfusion.json")
    config_parser.add_argument("--title", help="Set desktop window app_title in pyfusion.json")
    config_parser.add_argument("--author", help="Set author name in pyfusion.json")
    config_parser.add_argument("--icon", help="Set project icon path (.png or .ico) and generate desktop/icons/icon.ico")
    config_parser.add_argument("--color", help="Set theme accent color (e.g. #10b981)")
    config_parser.set_defaults(func=cmd_config)

    # pyfusion build [shortcut|exe|android|apk|aab]
    build_parser_sub = subparsers.add_parser(
        "build",
        help="Save Desktop shortcut (.lnk), build standalone Windows .exe, or build Android .apk / .aab",
    )
    build_parser_sub.add_argument(
        "target",
        nargs="?",
        default="shortcut",
        choices=["shortcut", "exe", "android", "apk", "aab"],
        help="'shortcut' (Desktop .lnk), 'exe' (Windows .exe), 'apk' (Android direct install), 'aab' (Google Play Store bundle), or 'android' (both)",
    )
    build_parser_sub.add_argument(
        "--format",
        default="both",
        choices=["apk", "aab", "both"],
        help="Android package format when target is 'android' (default: both)",
    )
    build_parser_sub.add_argument("--name", help="Override project name")
    build_parser_sub.add_argument("--title", help="Override desktop shortcut/window title")
    build_parser_sub.add_argument("--icon", help="Override icon path (.png or .ico)")
    build_parser_sub.set_defaults(func=cmd_build)

    # pyfusion create <component|model|store|plugin|page> <name>
    create_parser = subparsers.add_parser(
        "create",
        help="Scaffold a new component (.fusion), database model, store, plugin, or page",
    )
    create_parser.add_argument(
        "resource",
        choices=["component", "model", "store", "plugin", "page"],
        help="Resource type: 'component', 'model', 'store', 'plugin', or 'page'",
    )
    create_parser.add_argument("name", help="Name of the resource (e.g., UserCard, User, auth, dashboard)")
    create_parser.add_argument("-f", "--force", action="store_true", help="Overwrite existing files")
    create_parser.set_defaults(func=cmd_create)

    # pyfusion db <status|migrate>
    db_parser = subparsers.add_parser("db", help="Inspect or migrate the PyFusion SQLite/SQL database")
    db_parser.add_argument("action", nargs="?", default="status", choices=["status", "migrate"], help="DB action")
    db_parser.set_defaults(func=cmd_db)

    # pyfusion init <project_name>
    init_parser = subparsers.add_parser("init", help="Initialize a new Vue-style PyFusion project directory")
    init_parser.add_argument("project_name", help="Name of the new project folder")
    init_parser.set_defaults(func=cmd_init)

    # pyfusion routes
    routes_parser = subparsers.add_parser("routes", help="List all registered HTTP routes, components, and web pages")
    routes_parser.set_defaults(func=cmd_routes)

    # pyfusion info
    info_parser = subparsers.add_parser("info", help="Display framework and environment information")
    info_parser.set_defaults(func=cmd_info)

    return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    cleaned_argv = []
    for arg in argv:
        stripped = arg.strip("[]")
        if " " in stripped and stripped.startswith("-"):
            cleaned_argv.extend(stripped.split())
        elif stripped:
            cleaned_argv.append(stripped)

    parser = build_parser()
    args = parser.parse_args(cleaned_argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
