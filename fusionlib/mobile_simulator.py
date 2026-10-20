"""
Android Mobile Simulator & Native Android WebView Runtime for PyFusion Framework.
- On Android devices (python-for-android / Buildozer): Starts the PyFusion server on 127.0.0.1
  and attaches to the native Android WebView.
- On Desktop (Windows/macOS/Linux): Opens a sleek Android Pixel Phone Simulator window (420x820)
  styled with Material 3 Dark Web aesthetics, live .fusion Counter, SQLite DB, and APK builder.
"""

import os
import socket
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk

from .config import ensure_project_ico, generate_android_project, load_project_config
from .modern_ui import WebBadge, WebButton, WebCard, WebInput, WebStatCard, WebTheme, apply_ttk_web_styles


def get_lan_ip() -> str:
    """Detect local Wi-Fi/LAN IP so users can test the app on a physical Android phone."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def is_running_on_android() -> bool:
    return "ANDROID_ARGUMENT" in os.environ or "ANDROID_BOOTLOGO" in os.environ


def run_native_android_webview(port: int = 5000):
    """
    Entry point when packaged as a native Android APK via Buildozer / python-for-android.
    Starts PyFusion's pure-Python HTTP + SQLite server on 127.0.0.1 and loads it in Android WebView.
    """
    from .config import resolve_web_entry
    from .web_server import default_app, run_web_server

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

    run_web_server(port=port, host="127.0.0.1", app=app, in_thread=True)
    target_url = f"http://127.0.0.1:{port}"

    try:
        # python-for-android WebView bootstrap
        from jnius import autoclass  # type: ignore
        from android.runnable import run_on_ui_thread  # type: ignore

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        WebView = autoclass("android.webkit.WebView")
        WebViewClient = autoclass("android.webkit.WebViewClient")
        activity = PythonActivity.mActivity

        @run_on_ui_thread
        def create_webview():
            webview = WebView(activity)
            settings = webview.getSettings()
            settings.setJavaScriptEnabled(True)
            settings.setDomStorageEnabled(True)
            webview.setWebViewClient(WebViewClient())
            activity.setContentView(webview)
            webview.loadUrl(target_url)

        create_webview()
        import time

        while True:
            time.sleep(1)
    except Exception:
        import webbrowser

        webbrowser.open(target_url)


class AndroidSimulatorWindow:
    """
    Material-3 / Dark Web Android Phone Simulator (430x820) for previewing and packaging
    PyFusion apps for Android (.apk / PWA).
    """

    def __init__(self, app_name=None, icon_path=None, port=None, auto_start=True):
        cfg = load_project_config()
        self.project_name = cfg.get("project_name", "PyFusion-Studio")
        self.app_name = app_name or cfg.get("app_title") or self.project_name
        self.icon_path = icon_path or cfg.get("icon", "web/assets/logo.png")
        self.port = port or int(cfg.get("port", 5000))
        self.ico_path = ensure_project_ico(self.icon_path)
        self.active_tab = "home"

        if auto_start:
            self.run()

    def _apply_icon(self):
        if self.ico_path and os.path.exists(self.ico_path):
            try:
                self.root.iconbitmap(self.ico_path)
            except Exception:
                pass

    def run(self):
        if is_running_on_android():
            run_native_android_webview(self.port)
            return

        self.root = tk.Tk()
        self.root.title(f"📱 {self.app_name} — Android Simulator")
        self.root.geometry("430x820")
        self.root.minsize(390, 720)
        self.root.configure(bg="#020617")
        self._apply_icon()
        apply_ttk_web_styles(self.root)

        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

        # Phone Outer Bezel Frame
        self.phone_bezel = tk.Frame(
            self.root,
            bg=WebTheme.BG_BASE_300,
            highlightbackground="#334155",
            highlightcolor="#10b981",
            highlightthickness=2,
        )
        self.phone_bezel.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 1. Android Status Bar (Top)
        status_bar = tk.Frame(self.phone_bezel, bg="#090d16", height=28)
        status_bar.pack(fill=tk.X, side=tk.TOP)
        tk.Label(status_bar, text="5G • PyFusion Android", font=(WebTheme.FONT_SANS, 8, "bold"), bg="#090d16", fg="#94a3b8").pack(side=tk.LEFT, padx=14, pady=4)
        tk.Label(status_bar, text="●", font=(WebTheme.FONT_SANS, 10), bg="#090d16", fg="#1e293b").pack(side=tk.LEFT, expand=True)
        tk.Label(status_bar, text="Wi-Fi  100% 🔋", font=(WebTheme.FONT_SANS, 8, "bold"), bg="#090d16", fg="#10b981").pack(side=tk.RIGHT, padx=14, pady=4)

        # 2. Mobile App Top Bar
        app_header = tk.Frame(self.phone_bezel, bg=WebTheme.BG_BASE_200, height=54)
        app_header.pack(fill=tk.X, side=tk.TOP)

        abs_icon = self.icon_path if os.path.isabs(self.icon_path) else os.path.abspath(self.icon_path)
        if os.path.exists(abs_icon):
            try:
                img = Image.open(abs_icon).convert("RGBA")
                resample = getattr(Image, "Resampling", Image).LANCZOS
                img = img.resize((26, 26), resample)
                self._top_logo = ImageTk.PhotoImage(img)
                tk.Label(app_header, image=self._top_logo, bg=WebTheme.BG_BASE_200).pack(side=tk.LEFT, padx=(14, 8), pady=12)
            except Exception:
                pass

        tk.Label(
            app_header,
            text=self.app_name,
            font=(WebTheme.FONT_SANS, 11, "bold"),
            bg=WebTheme.BG_BASE_200,
            fg=WebTheme.TEXT_PRIMARY,
        ).pack(side=tk.LEFT, pady=12)

        WebBadge(app_header, text="ANDROID", variant="emerald").pack(side=tk.RIGHT, padx=12)

        # 3. Bottom Android Gesture Pill & Material Navigation Bar
        gesture_bar = tk.Frame(self.phone_bezel, bg="#090d16", height=18)
        gesture_bar.pack(fill=tk.X, side=tk.BOTTOM)
        pill = tk.Frame(gesture_bar, bg="#475569", width=110, height=4)
        pill.pack(pady=7)

        self.nav_bar = tk.Frame(self.phone_bezel, bg=WebTheme.BG_BASE_200, height=56)
        self.nav_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self.nav_buttons = {}
        tabs = [
            ("home", "📱 Home"),
            ("counter", "⚡ Counter"),
            ("db", "🗄️ SQLite"),
            ("build", "📦 APK Build"),
        ]
        for key, label in tabs:
            btn = tk.Button(
                self.nav_bar,
                text=label,
                font=(WebTheme.FONT_SANS, 9, "bold"),
                relief=tk.FLAT,
                bd=0,
                padx=10,
                pady=10,
                cursor="hand2",
                command=lambda k=key: self.switch_tab(k),
            )
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3, pady=6)
            self.nav_buttons[key] = btn

        # 4. Main Mobile Viewport
        self.viewport = tk.Frame(self.phone_bezel, bg=WebTheme.BG_BASE_300)
        self.viewport.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

        self.switch_tab("home")
        self.root.mainloop()

    def _clear_viewport(self):
        for child in self.viewport.winfo_children():
            child.destroy()

    def switch_tab(self, tab_key: str):
        self.active_tab = tab_key
        for k, btn in self.nav_buttons.items():
            if k == tab_key:
                btn.config(bg=WebTheme.EMERALD, fg="#ffffff", activebackground=WebTheme.EMERALD_HOVER)
            else:
                btn.config(bg=WebTheme.BG_BASE_100, fg=WebTheme.TEXT_SECONDARY, activebackground=WebTheme.BG_ELEVATED)

        if tab_key == "home":
            self._render_home()
        elif tab_key == "counter":
            self._render_counter()
        elif tab_key == "db":
            self._render_db()
        elif tab_key == "build":
            self._render_build()

    def _render_home(self):
        self._clear_viewport()
        cfg = load_project_config()
        lan_ip = get_lan_ip()

        hero = WebCard(self.viewport, bg=WebTheme.BG_BASE_200, pad_x=16, pad_y=16)
        hero.pack(fill=tk.X, pady=(0, 12))

        WebBadge(hero.body, text=f"📦 {cfg.get('project_name')}", variant="emerald").pack(anchor="w", pady=(0, 6))
        tk.Label(
            hero.body,
            text=self.app_name,
            font=(WebTheme.FONT_SANS, 15, "bold"),
            bg=WebTheme.BG_BASE_200,
            fg=WebTheme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            hero.body,
            text="Hybrid Android WebView + Pure Python SQLite Runtime",
            font=(WebTheme.FONT_SANS, 9),
            bg=WebTheme.BG_BASE_200,
            fg=WebTheme.TEXT_SECONDARY,
            anchor="w",
        ).pack(fill=tk.X, pady=(2, 10))

        WebButton(
            hero.body,
            text="📦 Build / Configure Android APK",
            variant="primary",
            command=lambda: self.switch_tab("build"),
        ).pack(fill=tk.X, pady=(0, 6))

        pwa_card = WebCard(self.viewport, bg=WebTheme.BG_BASE_100, pad_x=16, pad_y=14)
        pwa_card.pack(fill=tk.X, pady=(0, 12))
        WebBadge(pwa_card.body, text="INSTANT WI-FI TEST ON PHONE", variant="indigo").pack(anchor="w", pady=(0, 6))
        tk.Label(
            pwa_card.body,
            text="Test on Your Physical Android Phone:",
            font=(WebTheme.FONT_SANS, 11, "bold"),
            bg=WebTheme.BG_BASE_100,
            fg=WebTheme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            pwa_card.body,
            text=f"1. Run: pyfusion run web --host 0.0.0.0\n2. Open on Android Chrome:\n   http://{lan_ip}:{self.port}\n3. Tap 'Add to Home Screen' to install as PWA!",
            font=(WebTheme.FONT_MONO, 8),
            bg=WebTheme.BG_BASE_200,
            fg=WebTheme.EMERALD,
            justify=tk.LEFT,
            anchor="w",
            padx=10,
            pady=8,
        ).pack(fill=tk.X, pady=(6, 0))

        arch_card = WebCard(self.viewport, bg=WebTheme.BG_BASE_100, pad_x=16, pad_y=14)
        arch_card.pack(fill=tk.BOTH, expand=True)
        WebBadge(arch_card.body, text="OFFLINE APK ARCHITECTURE", variant="amber").pack(anchor="w", pady=(0, 6))
        tk.Label(
            arch_card.body,
            text="• Embedded Python 3.12 + SQLite 3 on Android\n• Renders web/components/*.fusion in Android WebView\n• OWASP CSRF + PBKDF2 security active offline\n• Packaged via mobile/buildozer.spec or Capacitor",
            font=(WebTheme.FONT_SANS, 9),
            bg=WebTheme.BG_BASE_100,
            fg=WebTheme.TEXT_SECONDARY,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X)

    def _render_counter(self):
        self._clear_viewport()
        from .component import load_sfc

        sfc_path = os.path.abspath("web/components/Counter.fusion")
        comp_cls = load_sfc(sfc_path, "Counter") if os.path.exists(sfc_path) else None
        instance = comp_cls() if comp_cls else None

        card = WebCard(self.viewport, bg=WebTheme.BG_BASE_100, pad_x=16, pad_y=16)
        card.pack(fill=tk.BOTH, expand=True)

        WebBadge(card.body, text="web/components/Counter.fusion", variant="emerald").pack(anchor="w", pady=(0, 8))
        tk.Label(
            card.body,
            text="Mobile Reactive Counter",
            font=(WebTheme.FONT_SANS, 14, "bold"),
            bg=WebTheme.BG_BASE_100,
            fg=WebTheme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 12))

        stat_count = WebStatCard(card.body, title="State (count)", value="0", subtitle="Python mobile state", accent=WebTheme.EMERALD)
        stat_count.pack(fill=tk.X, pady=(0, 8))

        stat_doubled = WebStatCard(card.body, title="Computed (doubled)", value="0", subtitle="count * 2", accent=WebTheme.INDIGO)
        stat_doubled.pack(fill=tk.X, pady=(0, 14))

        def trigger(method_name):
            if not instance:
                return
            state = instance.invoke_method(method_name)
            stat_count.set_value(state["count"])
            stat_doubled.set_value(state["doubled"])

        btn_row = tk.Frame(card.body, bg=WebTheme.BG_BASE_100)
        btn_row.pack(fill=tk.X, pady=(6, 0))
        WebButton(btn_row, text="-1", variant="outline", command=lambda: trigger("decrement")).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))
        WebButton(btn_row, text="+1", variant="primary", command=lambda: trigger("increment")).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=4)
        WebButton(btn_row, text="Reset", variant="ghost", command=lambda: trigger("reset")).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

    def _render_db(self):
        self._clear_viewport()
        from .database import Field, FusionDB, Model
        from .security import hash_password

        db = FusionDB("sqlite:///pyfusion.db")

        class MobileSubmission(Model):
            table_name = "user_submissions"
            username = Field("TEXT", nullable=False)
            password_hash = Field("TEXT", nullable=False)
            ip_address = Field("TEXT", default="android-app")

        db.register_model(MobileSubmission)
        MobileSubmission.create_table()

        card = WebCard(self.viewport, bg=WebTheme.BG_BASE_100, pad_x=16, pad_y=14)
        card.pack(fill=tk.BOTH, expand=True)

        tk.Label(card.body, text="🗄️ Mobile SQLite ORM", font=(WebTheme.FONT_SANS, 13, "bold"), bg=WebTheme.BG_BASE_100, fg=WebTheme.TEXT_PRIMARY, anchor="w").pack(fill=tk.X, pady=(0, 8))

        user_inp = WebInput(card.body, label="Username", default_value="android_user")
        user_inp.pack(fill=tk.X, pady=(0, 8))

        pw_inp = WebInput(card.body, label="Password (PBKDF2)", default_value="mobile2026", show="*")
        pw_inp.pack(fill=tk.X, pady=(0, 10))

        records_box = tk.Frame(card.body, bg=WebTheme.BG_BASE_200, padx=10, pady=8)
        records_box.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        def refresh_list():
            for child in records_box.winfo_children():
                child.destroy()
            rows = MobileSubmission.all(limit=6)
            tk.Label(records_box, text=f"Latest Records ({len(rows)}):", font=(WebTheme.FONT_SANS, 9, "bold"), bg=WebTheme.BG_BASE_200, fg=WebTheme.EMERALD, anchor="w").pack(fill=tk.X, pady=(0, 4))
            for r in rows:
                tk.Label(
                    records_box,
                    text=f"#{r.id} • {r.username} ({r.ip_address})",
                    font=(WebTheme.FONT_MONO, 8),
                    bg=WebTheme.BG_BASE_200,
                    fg=WebTheme.TEXT_PRIMARY,
                    anchor="w",
                ).pack(fill=tk.X, pady=1)

        def add_record():
            MobileSubmission.create(
                username=user_inp.get().strip() or "android_user",
                password_hash=hash_password(pw_inp.get() or "secret"),
                ip_address="android-apk",
            )
            refresh_list()

        WebButton(card.body, text="💾 Save to On-Device SQLite", variant="primary", command=add_record).pack(fill=tk.X)
        refresh_list()

    def _render_build(self):
        self._clear_viewport()
        card = WebCard(self.viewport, bg=WebTheme.BG_BASE_100, pad_x=16, pad_y=16)
        card.pack(fill=tk.BOTH, expand=True)

        WebBadge(card.body, text="ANDROID .APK & .AAB BUILDER", variant="emerald").pack(anchor="w", pady=(0, 6))
        tk.Label(
            card.body,
            text="Build .APK or .AAB Package",
            font=(WebTheme.FONT_SANS, 14, "bold"),
            bg=WebTheme.BG_BASE_100,
            fg=WebTheme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 6))

        tk.Label(
            card.body,
            text="• .APK — Direct sideload install on any Android phone\n• .AAB — Official Android App Bundle for Google Play Store",
            font=(WebTheme.FONT_SANS, 8),
            bg=WebTheme.BG_BASE_100,
            fg=WebTheme.TEXT_SECONDARY,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 10))

        status_var = tk.StringVar(value="Select .APK (Direct Install), .AAB (Google Play), or Both below.")
        tk.Label(
            card.body,
            textvariable=status_var,
            font=(WebTheme.FONT_MONO, 8),
            bg=WebTheme.BG_BASE_200,
            fg=WebTheme.EMERALD,
            wraplength=340,
            justify=tk.LEFT,
            anchor="w",
            padx=10,
            pady=10,
        ).pack(fill=tk.X, pady=(0, 10))

        def run_generate(fmt: str):
            res = generate_android_project(artifact_format=fmt)
            status_var.set(
                f"✓ Configured Android {res['format']} ({res['package_name']})!\n"
                f"• Debug: .{res['debug_artifact'].lower()}  |  Release: .{res['release_artifact'].lower()}\n"
                f"• Spec: mobile/buildozer.spec\n"
                f"• CI/CD: .github/workflows/android-apk-aab.yml"
            )
            messagebox.showinfo(
                f"Android {res['format']} Ready!",
                f"Configured Android {res['format']} for '{res['app_title']}':\n\n"
                f"• Debug Format: .{res['debug_artifact'].lower()} (Direct Phone Install)\n"
                f"• Release Format: .{res['release_artifact'].lower()} (Google Play Store)\n"
                f"• Buildozer Spec: {res['buildozer_spec']}\n"
                f"• Capacitor Config: {res['capacitor_config']}\n"
                f"• Docker Builder: {res['dockerfile_android']}\n"
                f"• GitHub Actions CI: {res['github_workflow']}",
            )

        btn_row = tk.Frame(card.body, bg=WebTheme.BG_BASE_100)
        btn_row.pack(fill=tk.X, pady=(0, 6))
        WebButton(btn_row, text="📦 Build .APK (Install)", variant="primary", command=lambda: run_generate("apk")).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))
        WebButton(btn_row, text="🏪 Build .AAB (Play Store)", variant="indigo", command=lambda: run_generate("aab")).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

        WebButton(card.body, text="⚡ Configure Both (.APK + .AAB + GitHub CI)", variant="outline", command=lambda: run_generate("both")).pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            card.body,
            text="CLI Commands:\n• pyfusion build apk\n• pyfusion build aab\n• pyfusion build android --format both",
            font=(WebTheme.FONT_MONO, 8),
            bg=WebTheme.BG_BASE_100,
            fg=WebTheme.TEXT_SECONDARY,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 0))

