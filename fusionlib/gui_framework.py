import os
import re
import socket
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
from tkhtmlview import HTMLLabel

from .config import (
    create_desktop_shortcut,
    ensure_project_ico,
    generate_android_project,
    launch_mobile_detached,
    load_project_config,
    resolve_web_entry,
    save_project_config,
)
from .modern_ui import WebBadge, WebButton, WebCard, WebInput, WebStatCard, WebTheme, apply_ttk_web_styles
from .navigation_manager import NavigationManager
from .ui_components import AppBar, BottomNavigation


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def clean_html_for_tk(raw_html: str) -> str:
    if not raw_html:
        return ""
    cleaned = re.sub(r"<head\b[^>]*>.*?</head>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<svg\b[^>]*>.*?</svg>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


class FusionHTMLLabel(HTMLLabel):
    """Extended HTMLLabel supporting set_html_content and set_css_styles for PyFusion."""

    def __init__(self, master=None, html="", **kwargs):
        super().__init__(master, html=clean_html_for_tk(html), **kwargs)

    def set_html_content(self, html_content):
        self.set_html(clean_html_for_tk(html_content))

    def set_css_styles(self, css_styles):
        if not css_styles:
            return
        for style in css_styles:
            name = style.get("name")
            props = style.get("properties", {})
            valid_props = {k: v for k, v in props.items() if k in ("font", "foreground", "background", "justify")}
            if name and valid_props:
                try:
                    self.tag_configure(name, **valid_props)
                except tk.TclError:
                    pass


class DesktopBridgeAPI:
    """Python-to-JS Native Desktop Bridge exposed as window.pywebview.api in WebView2."""

    def get_framework_info(self):
        cfg = load_project_config()
        return {"framework": "PyFusion Desktop", "config": cfg, "engine": "WebView2 + Python"}

    def save_desktop_shortcut(self):
        return create_desktop_shortcut()

    def update_project_config(self, project_name: str, app_title: str, icon: str):
        cfg = save_project_config({"project_name": project_name, "app_title": app_title, "icon": icon})
        ensure_project_ico(icon)
        return cfg


class HTMLAppWindow:
    """
    Hybrid Web-Grade Desktop Application Window for PyFusion with custom Project Name,
    Window/Taskbar Icon (.ico / .png), and one-click Desktop App saving.
    """

    def __init__(
        self,
        app_name=None,
        app_color=None,
        icon_path=None,
        html_content=None,
        css_styles=None,
        web_dir="web",
        width=None,
        height=None,
        port=None,
        engine=None,
        auto_start=True,
    ):
        cfg = load_project_config()
        self.project_name = cfg.get("project_name", "PyFusion-Studio")
        self.app_name = app_name or cfg.get("app_title") or self.project_name
        self.app_color = app_color or cfg.get("theme_color", "#10b981")
        self.icon_path = icon_path or cfg.get("icon", "web/assets/logo.png")
        self.web_dir = web_dir or cfg.get("paths", {}).get("web_dir", "web")
        self.width = width or int(cfg.get("width", 1120))
        self.height = height or int(cfg.get("height", 760))
        self.port = port or int(cfg.get("port", 5000))
        self.engine = engine or cfg.get("engine", "tk")
        self._custom_html = html_content
        self._css_styles = css_styles

        # Ensure multi-size Windows .ico exists from project icon
        self.ico_path = ensure_project_ico(self.icon_path)

        if auto_start:
            self.run()

    def _can_use_webview(self) -> bool:
        if self.engine != "webview":
            return False
        try:
            import webview  # noqa: F401
            return True
        except ImportError:
            return False

    def _apply_tk_window_icon(self):
        """Apply the project icon to the Tkinter window titlebar and Windows taskbar."""
        if self.ico_path and os.path.exists(self.ico_path):
            try:
                self.root.iconbitmap(self.ico_path)
            except Exception:
                pass
        abs_icon = self.icon_path if os.path.isabs(self.icon_path) else os.path.abspath(self.icon_path)
        if os.path.exists(abs_icon):
            try:
                img = Image.open(abs_icon).convert("RGBA")
                resample = getattr(Image, "Resampling", Image).LANCZOS
                img = img.resize((64, 64), resample)
                self._window_photo = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, self._window_photo)
            except Exception:
                pass

    def _run_webview_window(self):
        import sys
        import time
        import webview
        from .web_server import default_app, run_web_server

        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w")

        host = "localhost"
        if not _is_port_open(host, self.port):
            app = default_app
            web_entry = resolve_web_entry()
            if os.path.exists(web_entry):
                try:
                    import importlib.util

                    spec = importlib.util.spec_from_file_location("web_app", web_entry)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    if hasattr(mod, "app"):
                        app = mod.app
                except Exception:
                    pass
            run_web_server(port=self.port, host=host, app=app, in_thread=True)
            for _ in range(25):
                if _is_port_open(host, self.port):
                    break
                time.sleep(0.1)

        target_url = f"http://{host}:{self.port}"
        win = webview.create_window(
            title=self.app_name,
            url=target_url,
            width=self.width,
            height=self.height,
            min_size=(840, 580),
            background_color="#0b1120",
            js_api=DesktopBridgeAPI(),
        )

        ico_file = self.ico_path if self.ico_path and os.path.exists(self.ico_path) else None

        def _apply_native_icon():
            if ico_file and os.name == "nt":
                try:
                    import System.Drawing  # type: ignore

                    if hasattr(win, "native") and win.native is not None:
                        win.native.Icon = System.Drawing.Icon(ico_file)
                except Exception:
                    pass

        win.events.shown += _apply_native_icon
        storage_dir = os.path.abspath(os.path.join("desktop", ".webview_data"))
        os.makedirs(storage_dir, exist_ok=True)
        webview.start(private_mode=False, storage_path=storage_dir)

    def open_native_webview_app(self):
        """Launch the full TailwindCSS/DaisyUI PyFusion app inside a chromeless Edge/Chrome WebView2 OS window."""
        import shutil
        import subprocess
        import time
        from .web_server import default_app, run_web_server

        host = "localhost"
        if not _is_port_open(host, self.port):
            app = default_app
            web_entry = resolve_web_entry()
            if os.path.exists(web_entry):
                try:
                    import importlib.util

                    spec = importlib.util.spec_from_file_location("web_app", web_entry)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    if hasattr(mod, "app"):
                        app = mod.app
                except Exception:
                    pass
            run_web_server(port=self.port, host=host, app=app, in_thread=True)
            for _ in range(25):
                if _is_port_open(host, self.port):
                    break
                time.sleep(0.1)

        target_url = f"http://{host}:{self.port}"
        candidates = [
            shutil.which("msedge"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            shutil.which("chrome"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        ]
        browser_bin = next((c for c in candidates if c and os.path.exists(c)), None)
        if browser_bin:
            subprocess.Popen(
                [browser_bin, f"--app={target_url}", f"--window-size={self.width},{self.height}"],
                close_fds=True,
            )
            return True
        return False

    def _run_modern_tk_window(self):
        self.navigation = NavigationManager(initial_route="index")
        self.navigation.on_navigate(self._on_route_changed)

        self.root = tk.Tk()
        self.root.title(self.app_name)
        self.root.geometry(f"{self.width}x{self.height}")
        self.root.configure(bg=WebTheme.BG_BASE_300)
        self._apply_tk_window_icon()
        apply_ttk_web_styles(self.root)
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

        # Top Navbar with Project Icon & Title
        self.app_bar = AppBar(
            self.root,
            app_name=self.app_name,
            app_color=self.app_color,
            icon_path=self.icon_path,
        )
        self.app_bar.pack(fill=tk.X, side=tk.TOP)

        # Bottom Navigation
        self.bottom_navigation = BottomNavigation(self.root, navigation_manager=self.navigation)
        self.bottom_navigation.pack(fill=tk.X, side=tk.BOTTOM)

        # Main Dark Web Canvas
        self.workspace = tk.Frame(self.root, bg=WebTheme.BG_BASE_300)
        self.workspace.pack(expand=tk.YES, fill=tk.BOTH, padx=28, pady=20)

        self.html_label = FusionHTMLLabel(self.workspace, html="")

        self.change_page("index")
        self.root.mainloop()

    def _clear_workspace(self):
        for child in self.workspace.winfo_children():
            if child is not self.html_label:
                child.destroy()
        self.html_label.pack_forget()

    def _render_overview_view(self):
        self._clear_workspace()
        cfg = load_project_config()

        hero = WebCard(self.workspace, bg=WebTheme.BG_BASE_200, pad_x=28, pad_y=22)
        hero.pack(fill=tk.X, pady=(0, 18))

        top_row = tk.Frame(hero.body, bg=WebTheme.BG_BASE_200)
        top_row.pack(fill=tk.X)

        # Display Project Icon in Hero Banner
        abs_icon = self.icon_path if os.path.isabs(self.icon_path) else os.path.abspath(self.icon_path)
        if os.path.exists(abs_icon):
            try:
                img = Image.open(abs_icon).convert("RGBA")
                resample = getattr(Image, "Resampling", Image).LANCZOS
                img = img.resize((68, 68), resample)
                self._hero_logo = ImageTk.PhotoImage(img)
                logo_lbl = tk.Label(top_row, image=self._hero_logo, bg=WebTheme.BG_BASE_200)
                logo_lbl.pack(side=tk.LEFT, padx=(0, 18))
            except Exception:
                pass

        title_col = tk.Frame(top_row, bg=WebTheme.BG_BASE_200)
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)

        badge_row = tk.Frame(title_col, bg=WebTheme.BG_BASE_200)
        badge_row.pack(anchor="w", pady=(0, 6))
        WebBadge(badge_row, text=f"📦 {cfg.get('project_name', 'PyFusion-Studio')}", variant="emerald").pack(side=tk.LEFT, padx=(0, 8))
        WebBadge(badge_row, text="🗄️ SQLite ORM", variant="indigo").pack(side=tk.LEFT, padx=(0, 8))
        WebBadge(badge_row, text="🛡️ OWASP Hardened", variant="amber").pack(side=tk.LEFT)

        tk.Label(
            title_col,
            text=cfg.get("app_title", self.app_name),
            font=(WebTheme.FONT_SANS, 22, "bold"),
            bg=WebTheme.BG_BASE_200,
            fg=WebTheme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill=tk.X)

        tk.Label(
            title_col,
            text=f"AUTHOR: {cfg.get('author', 'Kondwani Nyirenda').upper()}   •   DESKTOP: desktop/app.py   •   WEB: web/app.py",
            font=(WebTheme.FONT_SANS, 9, "bold"),
            bg=WebTheme.BG_BASE_200,
            fg=WebTheme.EMERALD,
            anchor="w",
        ).pack(fill=tk.X, pady=(2, 8))

        cta_row = tk.Frame(hero.body, bg=WebTheme.BG_BASE_200)
        cta_row.pack(anchor="w", pady=(10, 0))
        WebButton(cta_row, text="🌐 WebView2 App Mode", variant="primary", command=self.open_native_webview_app).pack(side=tk.LEFT, padx=(0, 8))
        WebButton(cta_row, text="⚙️ Name, Icon & Save", variant="outline", command=lambda: self.bottom_navigation._navigate("settings")).pack(side=tk.LEFT, padx=(0, 8))
        WebButton(cta_row, text="📱 Android Simulator", variant="indigo", command=lambda: launch_mobile_detached()).pack(side=tk.LEFT, padx=(0, 8))
        WebButton(cta_row, text="⚡ Reactive Counter", variant="outline", command=lambda: self.bottom_navigation._navigate("counter")).pack(side=tk.LEFT, padx=(0, 8))
        WebButton(cta_row, text="🗄️ Database Explorer", variant="ghost", command=lambda: self.bottom_navigation._navigate("form")).pack(side=tk.LEFT)

        # Feature Grid
        grid = tk.Frame(self.workspace, bg=WebTheme.BG_BASE_300)
        grid.pack(fill=tk.BOTH, expand=True)
        for i in range(3):
            grid.columnconfigure(i, weight=1, uniform="col")

        features = [
            ("⚙️ Custom Name, Icon & Save", "Configure your project name & icon in pyfusion.json, create a Desktop Shortcut (.lnk), or build a standalone .exe!", "emerald"),
            ("🧩 Single-File Components", "Write <template>, Python <script>, and <style scoped> in .fusion files with two-way binding.", "indigo"),
            ("🗄️ Zero-Config SQLite ORM", "Connect with FusionDB('sqlite:///pyfusion.db') and run 100% parameterized queries.", "amber"),
        ]
        for idx, (title, desc, variant) in enumerate(features):
            card = WebCard(grid, bg=WebTheme.BG_BASE_100, pad_x=18, pad_y=16)
            card.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0 if idx == 2 else 8))
            WebBadge(card.body, text=variant.upper(), variant=variant).pack(anchor="w", pady=(0, 8))
            tk.Label(card.body, text=title, font=(WebTheme.FONT_SANS, 12, "bold"), bg=WebTheme.BG_BASE_100, fg=WebTheme.TEXT_PRIMARY, anchor="w").pack(fill=tk.X, pady=(0, 6))
            tk.Label(card.body, text=desc, font=(WebTheme.FONT_SANS, 9), bg=WebTheme.BG_BASE_100, fg=WebTheme.TEXT_SECONDARY, wraplength=280, justify=tk.LEFT, anchor="w").pack(fill=tk.X)

    def _render_settings_view(self):
        """Render the Project Name, Custom Icon & Save Desktop App studio tab."""
        self._clear_workspace()
        cfg = load_project_config()

        card = WebCard(self.workspace, bg=WebTheme.BG_BASE_100, pad_x=26, pad_y=22)
        card.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(card.body, bg=WebTheme.BG_BASE_100)
        header.pack(fill=tk.X, pady=(0, 14))
        tk.Label(
            header,
            text="⚙️ Project Name, Icon & Save Desktop Application",
            font=(WebTheme.FONT_SANS, 15, "bold"),
            bg=WebTheme.BG_BASE_100,
            fg=WebTheme.TEXT_PRIMARY,
        ).pack(side=tk.LEFT)
        status_badge = WebBadge(header, text="Saved in pyfusion.json", variant="emerald")
        status_badge.pack(side=tk.RIGHT)

        form_grid = tk.Frame(card.body, bg=WebTheme.BG_BASE_100)
        form_grid.pack(fill=tk.X, pady=(0, 14))
        form_grid.columnconfigure(0, weight=1)
        form_grid.columnconfigure(1, weight=1)

        proj_name_inp = WebInput(form_grid, label="Project Name (used for .exe & package)", default_value=cfg.get("project_name", "PyFusion-Studio"))
        proj_name_inp.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=6)

        app_title_inp = WebInput(form_grid, label="Desktop Window Title & Shortcut Name", default_value=cfg.get("app_title", "Lapansi Industries - PyFusion"))
        app_title_inp.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=6)

        author_inp = WebInput(form_grid, label="Author / Organization", default_value=cfg.get("author", "Kondwani Nyirenda"))
        author_inp.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=6)

        icon_inp = WebInput(form_grid, label="App Icon Path (.png or .ico — auto-converts to desktop/icons/icon.ico)", default_value=cfg.get("icon", "web/assets/logo.png"))
        icon_inp.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=6)

        def browse_icon():
            chosen = filedialog.askopenfilename(
                title="Select Project Icon (.png, .ico, .jpg)",
                filetypes=[("Image & Icon files", "*.png *.ico *.jpg *.jpeg"), ("All files", "*.*")],
            )
            if chosen:
                try:
                    rel = os.path.relpath(chosen, os.getcwd())
                    icon_inp.set(rel if not rel.startswith("..") else chosen)
                except ValueError:
                    icon_inp.set(chosen)

        log_var = tk.StringVar(value=f"Current Icon: {cfg.get('icon')}  ->  Generated Windows Icon: {self.ico_path or 'desktop/icons/icon.ico'}")
        log_lbl = tk.Label(card.body, textvariable=log_var, font=(WebTheme.FONT_MONO, 9), bg=WebTheme.BG_BASE_200, fg=WebTheme.EMERALD, padx=12, pady=10, anchor="w")
        log_lbl.pack(fill=tk.X, pady=(6, 16))

        def apply_and_save_config():
            new_cfg = save_project_config({
                "project_name": proj_name_inp.get().strip() or "PyFusion-App",
                "app_title": app_title_inp.get().strip() or "PyFusion Desktop",
                "author": author_inp.get().strip() or "Kondwani Nyirenda",
                "icon": icon_inp.get().strip() or "web/assets/logo.png",
            })
            self.project_name = new_cfg["project_name"]
            self.app_name = new_cfg["app_title"]
            self.icon_path = new_cfg["icon"]
            self.ico_path = ensure_project_ico(self.icon_path)

            # Live-update window title, taskbar icon, and AppBar
            self.root.title(self.app_name)
            self._apply_tk_window_icon()
            self.app_bar.set_title(self.app_name)
            self.app_bar.set_icon(self.icon_path)
            status_badge.configure(text="✓ Config & Icon Applied")
            log_var.set(f"✓ Saved pyfusion.json! Title='{self.app_name}', Icon='{self.ico_path}'")

        def save_desktop_app_shortcut():
            apply_and_save_config()
            res = create_desktop_shortcut()
            launcher_path = res.get("launcher_vbs", "")
            shortcuts_list = res.get("shortcuts", [])
            shortcuts_str = ", ".join(shortcuts_list) or launcher_path
            status_badge.configure(text="✓ Desktop Shortcut Saved!")
            log_var.set(f"✓ Created Desktop App Shortcut with custom icon: {shortcuts_str}")
            messagebox.showinfo(
                "Desktop App Saved!",
                f"Saved '{res.get('app_title', self.app_name)}' with custom icon!\n\n"
                f"• Windowless Launcher: {launcher_path}\n"
                f"• Desktop Shortcuts: {', '.join(shortcuts_list)}",
            )

        def build_android_config(fmt="both"):
            apply_and_save_config()
            res = generate_android_project(artifact_format=fmt)
            status_badge.configure(text=f"✓ Android {res['format']} Ready!")
            log_var.set(f"✓ Configured Android {res['format']} ({res['package_name']}): {res['buildozer_spec']}")
            messagebox.showinfo(
                f"Android {res['format']} Synced!",
                f"Configured Android {res['format']} for '{res['app_title']}':\n\n"
                f"• Debug Format: .{res['debug_artifact'].lower()} (Direct Phone Install)\n"
                f"• Release Format: .{res['release_artifact'].lower()} (Google Play Store)\n"
                f"• Buildozer Spec: {res['buildozer_spec']}\n"
                f"• Docker Builder: {res['dockerfile_android']}\n"
                f"• GitHub Actions CI: {res['github_workflow']}",
            )

        btn_row = tk.Frame(card.body, bg=WebTheme.BG_BASE_100)
        btn_row.pack(fill=tk.X)

        WebButton(btn_row, text="📁 Browse Icon...", variant="outline", command=browse_icon).pack(side=tk.LEFT, padx=(0, 6))
        WebButton(btn_row, text="💾 Save Name & Icon", variant="indigo", command=apply_and_save_config).pack(side=tk.LEFT, padx=(0, 6))
        WebButton(btn_row, text="🖥️ Save Desktop (.lnk)", variant="primary", command=save_desktop_app_shortcut).pack(side=tk.LEFT, padx=(0, 6))
        WebButton(btn_row, text="📦 Build .APK", variant="outline", command=lambda: build_android_config("apk")).pack(side=tk.LEFT, padx=(0, 6))
        WebButton(btn_row, text="🏪 Build .AAB", variant="outline", command=lambda: build_android_config("aab")).pack(side=tk.LEFT, padx=(0, 6))
        WebButton(btn_row, text="🤖 Android Simulator", variant="ghost", command=lambda: launch_mobile_detached()).pack(side=tk.LEFT)

    def _render_counter_view(self):
        self._clear_workspace()
        from .component import load_sfc

        sfc_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../web/components/Counter.fusion"))
        if not os.path.exists(sfc_path):
            sfc_path = os.path.abspath("web/components/Counter.fusion")
        comp_cls = load_sfc(sfc_path, "Counter") if os.path.exists(sfc_path) else None
        instance = comp_cls() if comp_cls else None

        card = WebCard(self.workspace, bg=WebTheme.BG_BASE_100, pad_x=28, pad_y=24)
        card.pack(fill=tk.X)

        header = tk.Frame(card.body, bg=WebTheme.BG_BASE_100)
        header.pack(fill=tk.X, pady=(0, 14))
        tk.Label(header, text="PyFusion Reactive Counter (Counter.fusion)", font=(WebTheme.FONT_SANS, 16, "bold"), bg=WebTheme.BG_BASE_100, fg=WebTheme.TEXT_PRIMARY).pack(side=tk.LEFT)
        count_badge = WebBadge(header, text="Count: 0", variant="emerald")
        count_badge.pack(side=tk.RIGHT)

        stats_row = tk.Frame(card.body, bg=WebTheme.BG_BASE_100)
        stats_row.pack(fill=tk.X, pady=(0, 16))
        stats_row.columnconfigure(0, weight=1)
        stats_row.columnconfigure(1, weight=1)

        stat_count = WebStatCard(stats_row, title="Current State (count)", value="0", subtitle="Reactive Python state", accent=WebTheme.EMERALD)
        stat_count.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        stat_doubled = WebStatCard(stats_row, title="Computed (doubled)", value="0", subtitle="computed: count * 2", accent=WebTheme.INDIGO)
        stat_doubled.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        preview_var = tk.StringVar(value="Live Value: Hello from PyFusion SFC!")

        def on_greeting_type(val):
            preview_var.set(f"Live Value: {val}")

        greeting_input = WebInput(
            card.body,
            label='Two-Way Data Binding (f-model="greeting")',
            default_value="Hello from PyFusion SFC!",
            on_change=on_greeting_type,
        )
        greeting_input.pack(fill=tk.X, pady=(0, 6))

        tk.Label(card.body, textvariable=preview_var, font=(WebTheme.FONT_SANS, 10, "bold"), bg=WebTheme.BG_BASE_100, fg=WebTheme.EMERALD, anchor="w").pack(fill=tk.X, pady=(0, 16))

        def trigger(method_name):
            if not instance:
                return
            state = instance.invoke_method(method_name)
            stat_count.set_value(state["count"])
            stat_doubled.set_value(state["doubled"])
            count_badge.configure(text=f"Count: {state['count']}")

        btn_row = tk.Frame(card.body, bg=WebTheme.BG_BASE_100)
        btn_row.pack(anchor="e")
        WebButton(btn_row, text="-1 (Decrement)", variant="outline", command=lambda: trigger("decrement")).pack(side=tk.LEFT, padx=6)
        WebButton(btn_row, text="+1 (Increment)", variant="primary", command=lambda: trigger("increment")).pack(side=tk.LEFT, padx=6)
        WebButton(btn_row, text="Reset", variant="ghost", command=lambda: trigger("reset")).pack(side=tk.LEFT, padx=(6, 0))

    def _render_database_view(self):
        self._clear_workspace()
        from .database import Field, FusionDB, Model
        from .security import hash_password

        db = FusionDB("sqlite:///pyfusion.db")

        class DesktopSubmission(Model):
            table_name = "user_submissions"
            username = Field("TEXT", nullable=False)
            password_hash = Field("TEXT", nullable=False)
            ip_address = Field("TEXT", default="desktop-ui")

        db.register_model(DesktopSubmission)
        DesktopSubmission.create_table()

        form_card = WebCard(self.workspace, bg=WebTheme.BG_BASE_100, pad_x=22, pad_y=16)
        form_card.pack(fill=tk.X, pady=(0, 14))

        top_bar = tk.Frame(form_card.body, bg=WebTheme.BG_BASE_100)
        top_bar.pack(fill=tk.X, pady=(0, 10))
        tk.Label(top_bar, text="SQLite Database Explorer (pyfusion.db)", font=(WebTheme.FONT_SANS, 14, "bold"), bg=WebTheme.BG_BASE_100, fg=WebTheme.TEXT_PRIMARY).pack(side=tk.LEFT)
        status_badge = WebBadge(top_bar, text=f"{len(DesktopSubmission.all())} Records in DB", variant="emerald")
        status_badge.pack(side=tk.RIGHT)

        inputs_row = tk.Frame(form_card.body, bg=WebTheme.BG_BASE_100)
        inputs_row.pack(fill=tk.X)
        inputs_row.columnconfigure(0, weight=1)
        inputs_row.columnconfigure(1, weight=1)

        user_inp = WebInput(inputs_row, label="Username", default_value="kondwani")
        user_inp.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        pw_inp = WebInput(inputs_row, label="Password (PBKDF2-HMAC-SHA256)", default_value="pyfusion2026", show="*")
        pw_inp.grid(row=0, column=1, sticky="ew", padx=(10, 14))

        table_card = WebCard(self.workspace, bg=WebTheme.BG_BASE_100, pad_x=18, pad_y=14)
        table_card.pack(fill=tk.BOTH, expand=True)

        columns = ("id", "username", "password_hash", "ip_address", "created_at")
        tree = ttk.Treeview(table_card.body, columns=columns, show="headings", style="Web.Treeview")
        tree.heading("id", text="ID")
        tree.heading("username", text="USERNAME")
        tree.heading("password_hash", text="PBKDF2-SHA256 PASSWORD HASH")
        tree.heading("ip_address", text="CLIENT IP")
        tree.heading("created_at", text="CREATED AT")

        tree.column("id", width=60, anchor="w")
        tree.column("username", width=150, anchor="w")
        tree.column("password_hash", width=380, anchor="w")
        tree.column("ip_address", width=110, anchor="w")
        tree.column("created_at", width=150, anchor="w")
        tree.pack(fill=tk.BOTH, expand=True)

        def refresh_table():
            for item in tree.get_children():
                tree.delete(item)
            rows = DesktopSubmission.all(limit=25)
            status_badge.configure(text=f"{len(rows)} Records in DB")
            for r in rows:
                tree.insert(
                    "",
                    tk.END,
                    values=(f"#{r.id}", r.username, str(r.password_hash)[:48] + "...", r.ip_address, r.created_at),
                )

        def save_to_db():
            uname = user_inp.get().strip() or "Guest"
            raw_pw = pw_inp.get() or "secret"
            DesktopSubmission.create(username=uname, password_hash=hash_password(raw_pw), ip_address="desktop-app")
            refresh_table()

        WebButton(inputs_row, text="Save to SQLite DB", variant="primary", command=save_to_db, padx=18, pady=9).grid(row=0, column=2, sticky="s")
        refresh_table()

    def _render_security_view(self):
        self._clear_workspace()
        card = WebCard(self.workspace, bg=WebTheme.BG_BASE_100, pad_x=24, pad_y=20)
        card.pack(fill=tk.BOTH, expand=True)

        tk.Label(card.body, text="🛡️ Active OWASP Top 10 Security Controls", font=(WebTheme.FONT_SANS, 15, "bold"), bg=WebTheme.BG_BASE_100, fg=WebTheme.TEXT_PRIMARY, anchor="w").pack(fill=tk.X, pady=(0, 14))

        grid = tk.Frame(card.body, bg=WebTheme.BG_BASE_100)
        grid.pack(fill=tk.BOTH, expand=True)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        items = [
            ("A01: Access Control & Path Traversal", "Blocks ../ traversal, .env/.py/.db exposure, and enforces RPC method allowlists."),
            ("A02: Cryptographic Failures", "Passwords hashed with PBKDF2-HMAC-SHA256 (260,000 iterations) + cryptographic salt."),
            ("A03: SQLi & XSS Injection", "100% parameterized SQL statements in FusionDB + automatic HTML escaping."),
            ("A04: Rate Limiting & DoS", "Sliding-window IP rate limiter (180 req/min) + 2MB max request body cap."),
            ("A05: Security Headers", "X-Content-Type-Options: nosniff, X-Frame-Options: SAMEORIGIN, Referrer-Policy."),
            ("A07: CSRF Protection", "HMAC-SHA256 signed CSRF tokens with constant-time verification."),
        ]
        for idx, (title, desc) in enumerate(items):
            r, c = divmod(idx, 2)
            box = WebCard(grid, bg=WebTheme.BG_BASE_200, pad_x=14, pad_y=12)
            box.grid(row=r, column=c, sticky="nsew", padx=6, pady=6)
            tk.Label(box.body, text=title, font=(WebTheme.FONT_SANS, 10, "bold"), bg=WebTheme.BG_BASE_200, fg=WebTheme.EMERALD, anchor="w").pack(fill=tk.X, pady=(0, 4))
            tk.Label(box.body, text=desc, font=(WebTheme.FONT_SANS, 9), bg=WebTheme.BG_BASE_200, fg=WebTheme.TEXT_SECONDARY, wraplength=380, justify=tk.LEFT, anchor="w").pack(fill=tk.X)

    def _on_route_changed(self, route, params=None):
        self.change_page(route)

    def change_page(self, page_name):
        if page_name == "index":
            self._render_overview_view()
        elif page_name == "counter":
            self._render_counter_view()
        elif page_name == "form":
            self._render_database_view()
        elif page_name == "settings":
            self._render_settings_view()
        elif page_name == "security":
            self._render_security_view()
        else:
            self._clear_workspace()
            self.html_label.pack(expand=tk.YES, fill=tk.BOTH)
            html_file = os.path.join(self.web_dir, f"{page_name}.html")
            if os.path.exists(html_file):
                with open(html_file, "r", encoding="utf-8") as f:
                    self.html_label.set_html_content(f.read())

    def apply_styles(self, css_styles):
        if hasattr(self, "html_label"):
            self.html_label.set_css_styles(css_styles)

    def run(self):
        if self._can_use_webview():
            try:
                self._run_webview_window()
                return
            except Exception as exc:
                print(f"[PyFusion Desktop] WebView fallback to Modern UI ({exc})")
        self._run_modern_tk_window()
