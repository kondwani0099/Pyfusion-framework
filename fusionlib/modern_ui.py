"""
fusionlib/modern_ui.py — Custom Web-Grade UI Component Library for PyFusion Desktop.

Provides Tailwind/DaisyUI-inspired dark/light theme tokens, rounded Canvas cards,
hover-animated pill buttons, modern bordered inputs, badges, stat cards, and data tables
so pure-Python desktop windows look and feel like a modern web application.
"""

import tkinter as tk
from tkinter import ttk


class WebTheme:
    """Tailwind Slate & Emerald Dark Mode Color Palette."""

    BG_BASE_300 = "#0b1120"      # Page backdrop
    BG_BASE_200 = "#0f172a"      # Secondary surface / navbar
    BG_BASE_100 = "#1e293b"      # Card surface
    BG_ELEVATED = "#334155"      # Hover / elevated surface
    BORDER = "#334155"           # Subtle card border

    TEXT_PRIMARY = "#f8fafc"     # Slate 50
    TEXT_SECONDARY = "#94a3b8"   # Slate 400
    TEXT_MUTED = "#64748b"       # Slate 500

    EMERALD = "#10b981"          # Primary accent
    EMERALD_HOVER = "#059669"
    EMERALD_SOFT = "#064e3b"

    INDIGO = "#6366f1"           # Secondary accent
    INDIGO_HOVER = "#4f46e5"

    AMBER = "#f59e0b"
    ROSE = "#f43f5e"
    SKY = "#0ea5e9"

    FONT_SANS = "Segoe UI"
    FONT_MONO = "Consolas"


def apply_ttk_web_styles(root: tk.Tk):
    """Configure ttk Treeview and Scrollbar to match a dark Tailwind/DaisyUI web table."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(
        "Web.Treeview",
        background=WebTheme.BG_BASE_100,
        foreground=WebTheme.TEXT_PRIMARY,
        fieldbackground=WebTheme.BG_BASE_100,
        borderwidth=0,
        rowheight=36,
        font=(WebTheme.FONT_SANS, 10),
    )
    style.configure(
        "Web.Treeview.Heading",
        background=WebTheme.BG_BASE_200,
        foreground=WebTheme.TEXT_SECONDARY,
        borderwidth=0,
        relief="flat",
        padding=(12, 8),
        font=(WebTheme.FONT_SANS, 9, "bold"),
    )
    style.map(
        "Web.Treeview",
        background=[("selected", WebTheme.EMERALD_SOFT)],
        foreground=[("selected", "#ffffff")],
    )
    style.map(
        "Web.Treeview.Heading",
        background=[("active", WebTheme.BG_ELEVATED)],
    )


class WebCard(tk.Frame):
    """Tailwind/DaisyUI-style Card with subtle 1px border, dark slate surface, and internal padding."""

    def __init__(self, master, bg=WebTheme.BG_BASE_100, border_color=WebTheme.BORDER, pad_x=20, pad_y=18, **kwargs):
        super().__init__(
            master,
            bg=bg,
            highlightbackground=border_color,
            highlightcolor=border_color,
            highlightthickness=1,
            bd=0,
            **kwargs,
        )
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill=tk.BOTH, expand=True, padx=pad_x, pady=pad_y)


class WebBadge(tk.Label):
    """Pill-styled status badge like DaisyUI .badge."""

    VARIANTS = {
        "emerald": ("#064e3b", "#34d399"),
        "indigo": ("#1e1b4b", "#818cf8"),
        "amber": ("#451a03", "#fbbf24"),
        "rose": ("#4c0519", "#fb7185"),
        "slate": ("#1e293b", "#cbd5e1"),
    }

    def __init__(self, master, text="", variant="emerald", **kwargs):
        bg, fg = self.VARIANTS.get(variant, self.VARIANTS["emerald"])
        super().__init__(
            master,
            text=text,
            bg=bg,
            fg=fg,
            font=(WebTheme.FONT_SANS, 9, "bold"),
            padx=10,
            pady=3,
            **kwargs,
        )


class WebButton(tk.Label):
    """Web-styled button with smooth hover transitions, hand cursor, and DaisyUI color variants."""

    VARIANTS = {
        "primary": (WebTheme.EMERALD, WebTheme.EMERALD_HOVER, "#ffffff", WebTheme.EMERALD),
        "indigo": (WebTheme.INDIGO, WebTheme.INDIGO_HOVER, "#ffffff", WebTheme.INDIGO),
        "outline": (WebTheme.BG_BASE_100, WebTheme.BG_ELEVATED, WebTheme.TEXT_PRIMARY, WebTheme.BORDER),
        "ghost": (WebTheme.BG_BASE_200, WebTheme.BG_ELEVATED, WebTheme.TEXT_SECONDARY, WebTheme.BG_BASE_200),
        "danger": ("#881337", WebTheme.ROSE, "#ffffff", "#881337"),
    }

    def __init__(self, master, text="", command=None, variant="primary", padx=16, pady=8, font_size=10, **kwargs):
        bg, hover_bg, fg, border = self.VARIANTS.get(variant, self.VARIANTS["primary"])
        self._bg = bg
        self._hover_bg = hover_bg
        self._fg = fg
        self._command = command

        super().__init__(
            master,
            text=text,
            bg=bg,
            fg=fg,
            font=(WebTheme.FONT_SANS, font_size, "bold"),
            padx=padx,
            pady=pady,
            cursor="hand2",
            highlightbackground=border,
            highlightthickness=1,
            **kwargs,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _on_enter(self, _):
        self.configure(bg=self._hover_bg, fg="#ffffff")

    def _on_leave(self, _):
        self.configure(bg=self._bg, fg=self._fg)

    def _on_click(self, _):
        if callable(self._command):
            self._command()


class WebInput(tk.Frame):
    """Modern web-styled text input with focus ring border (like DaisyUI .input-bordered)."""

    def __init__(self, master, label="", placeholder="", default_value="", show=None, width=28, on_change=None, **kwargs):
        parent_bg = master.cget("bg")
        super().__init__(master, bg=parent_bg, **kwargs)
        self.var = tk.StringVar(value=default_value)

        if label:
            lbl = tk.Label(
                self,
                text=label,
                bg=parent_bg,
                fg=WebTheme.TEXT_SECONDARY,
                font=(WebTheme.FONT_SANS, 9, "bold"),
                anchor="w",
            )
            lbl.pack(fill=tk.X, pady=(0, 4))

        self.border_frame = tk.Frame(
            self,
            bg=WebTheme.BG_BASE_200,
            highlightbackground=WebTheme.BORDER,
            highlightcolor=WebTheme.EMERALD,
            highlightthickness=1,
            bd=0,
        )
        self.border_frame.pack(fill=tk.X)

        entry_kwargs = {"show": show} if show else {}
        self.entry = tk.Entry(
            self.border_frame,
            textvariable=self.var,
            bg=WebTheme.BG_BASE_200,
            fg=WebTheme.TEXT_PRIMARY,
            insertbackground=WebTheme.EMERALD,
            relief=tk.FLAT,
            bd=0,
            width=width,
            font=(WebTheme.FONT_SANS, 10),
            **entry_kwargs,
        )
        self.entry.pack(fill=tk.X, padx=12, pady=8)

        if callable(on_change):
            self.var.trace_add("write", lambda *_: on_change(self.var.get()))

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str):
        self.var.set(value)


class WebStatCard(WebCard):
    """DaisyUI-inspired Stat Card displaying a label, large metric value, and subtitle."""

    def __init__(self, master, title="", value="0", subtitle="", accent=WebTheme.EMERALD, **kwargs):
        super().__init__(master, bg=WebTheme.BG_BASE_200, pad_x=16, pad_y=12, **kwargs)
        self.title_lbl = tk.Label(
            self.body,
            text=title,
            bg=WebTheme.BG_BASE_200,
            fg=WebTheme.TEXT_SECONDARY,
            font=(WebTheme.FONT_SANS, 9),
            anchor="w",
        )
        self.title_lbl.pack(fill=tk.X)

        self.value_var = tk.StringVar(value=str(value))
        self.value_lbl = tk.Label(
            self.body,
            textvariable=self.value_var,
            bg=WebTheme.BG_BASE_200,
            fg=accent,
            font=(WebTheme.FONT_SANS, 22, "bold"),
            anchor="w",
        )
        self.value_lbl.pack(fill=tk.X, pady=(2, 2))

        if subtitle:
            self.sub_lbl = tk.Label(
                self.body,
                text=subtitle,
                bg=WebTheme.BG_BASE_200,
                fg=WebTheme.TEXT_MUTED,
                font=(WebTheme.FONT_SANS, 8),
                anchor="w",
            )
            self.sub_lbl.pack(fill=tk.X)

    def set_value(self, val):
        self.value_var.set(str(val))
