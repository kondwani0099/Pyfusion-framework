import os
import tkinter as tk
from PIL import Image, ImageTk


class AppBar(tk.Frame):
    """Top application bar for PyFusion desktop windows with custom project icon and title."""

    def __init__(self, master=None, app_name="PyFusion", app_color="#10b981", icon_path=None, **kwargs):
        bg_color = kwargs.pop("bg", "#0f172a")
        super().__init__(master, bg=bg_color, height=58, **kwargs)

        self._logo_img = self._load_logo(icon_path, size=(28, 28))
        if self._logo_img:
            self.icon_lbl = tk.Label(self, image=self._logo_img, bg=bg_color)
            self.icon_lbl.image = self._logo_img
            self.icon_lbl.pack(side=tk.LEFT, padx=(16, 8), pady=10)
        else:
            self.dot = tk.Label(
                self,
                text="●",
                font=("Segoe UI", 14, "bold"),
                foreground=app_color or "#10b981",
                bg=bg_color,
            )
            self.dot.pack(side=tk.LEFT, padx=(16, 6), pady=12)

        self.label = tk.Label(
            self,
            text=app_name or "PyFusion Desktop",
            font=("Segoe UI", 14, "bold"),
            foreground="#f8fafc",
            bg=bg_color,
        )
        self.label.pack(side=tk.LEFT, padx=4, pady=12)

        self.badge = tk.Label(
            self,
            text="v0.4.0 • OWASP Safe • SQLite ORM",
            font=("Segoe UI", 9, "bold"),
            foreground=app_color or "#10b981",
            bg="#1e293b",
            padx=10,
            pady=4,
        )
        self.badge.pack(side=tk.RIGHT, padx=16, pady=12)

    def _load_logo(self, icon_path=None, size=(28, 28)):
        candidates = []
        if icon_path:
            candidates.append(icon_path)
        candidates.extend(["web/logo.png", "assets/icon.ico"])
        for path in candidates:
            abs_p = path if os.path.isabs(path) else os.path.abspath(path)
            if os.path.exists(abs_p):
                try:
                    img = Image.open(abs_p).convert("RGBA")
                    resample = getattr(Image, "Resampling", Image).LANCZOS
                    img = img.resize(size, resample)
                    return ImageTk.PhotoImage(img)
                except Exception:
                    pass
        return None

    def set_title(self, title):
        self.label.config(text=title)

    def set_icon(self, icon_path):
        new_img = self._load_logo(icon_path, size=(28, 28))
        if new_img and hasattr(self, "icon_lbl"):
            self.icon_lbl.config(image=new_img)
            self.icon_lbl.image = new_img


class BottomNavigation(tk.Frame):
    """Bottom navigation bar supporting icon/text buttons and NavigationManager integration."""

    def __init__(self, master=None, navigation_manager=None, **kwargs):
        bg_color = kwargs.pop("bg", "#0f172a")
        super().__init__(master, bg=bg_color, **kwargs)
        self.navigation_manager = navigation_manager
        self._active_route = "index"

        self.canvas = tk.Canvas(self, bg=bg_color, highlightthickness=0, width=600, height=2)
        self.canvas.pack(side=tk.TOP, fill=tk.X)
        self.canvas.create_rectangle(0, 0, 2000, 2, fill="#1e293b", outline="")

        self.button_container = tk.Frame(self, bg=bg_color)
        self.button_container.pack(side=tk.TOP, pady=8)

        self.buttons = {}
        nav_items = [
            ("index", "🏠 Overview"),
            ("counter", "⚡ Reactive Counter"),
            ("form", "🗄️ Database & Form"),
            ("settings", "⚙️ App Name, Icon & Save"),
            ("security", "🛡️ OWASP Security"),
        ]

        for route_key, label_text in nav_items:
            btn = tk.Button(
                self.button_container,
                text=label_text,
                font=("Segoe UI", 9, "bold"),
                relief=tk.FLAT,
                bd=0,
                padx=14,
                pady=6,
                cursor="hand2",
                command=lambda r=route_key: self._navigate(r),
            )
            btn.pack(side=tk.LEFT, padx=6)
            self.buttons[route_key] = btn

        self._update_button_styles("index")

    def _update_button_styles(self, active_route):
        self._active_route = active_route
        for route_key, btn in self.buttons.items():
            if route_key == active_route:
                btn.config(bg="#10b981", fg="#ffffff", activebackground="#059669", activeforeground="#ffffff")
            else:
                btn.config(bg="#1e293b", fg="#cbd5e1", activebackground="#334155", activeforeground="#ffffff")

    def _navigate(self, route):
        self._update_button_styles(route)
        if self.navigation_manager:
            self.navigation_manager.navigate(route)

    def load_icon(self, file_name, size=(24, 24)):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = file_name if os.path.isabs(file_name) else os.path.join(script_dir, "icons", file_name)

        if not os.path.exists(file_path):
            return None

        try:
            icon = Image.open(file_path)
            resample_filter = getattr(Image, "Resampling", Image).LANCZOS
            icon = icon.resize(size, resample_filter)
            return ImageTk.PhotoImage(icon)
        except Exception:
            return None

    def show_home(self):
        self._navigate("index")

    def show_settings(self):
        self._navigate("settings")
