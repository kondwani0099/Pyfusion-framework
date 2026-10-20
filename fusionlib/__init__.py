from .component import Component, load_sfc
from .database import Field, FusionDB, Model
from .navigation_manager import NavigationManager
from .reactivity import FusionPlugin, FusionStore, ReactiveDict, Ref, define_store, reactive, ref
from .security import (
    SecurityConfig,
    create_signed_token,
    escape_html,
    generate_csrf_token,
    hash_password,
    sanitize_html,
    verify_csrf_token,
    verify_password,
    verify_signed_token,
)
from .web_server import PyFusionApp, Request, Response, create_app, default_app, render_template, run_web_server

__version__ = "0.4.0"

__all__ = [
    "PyFusionApp",
    "create_app",
    "Component",
    "load_sfc",
    "FusionDB",
    "Model",
    "Field",
    "SecurityConfig",
    "hash_password",
    "verify_password",
    "create_signed_token",
    "verify_signed_token",
    "generate_csrf_token",
    "verify_csrf_token",
    "escape_html",
    "sanitize_html",
    "ref",
    "reactive",
    "define_store",
    "FusionStore",
    "FusionPlugin",
    "Ref",
    "ReactiveDict",
    "Request",
    "Response",
    "default_app",
    "render_template",
    "run_web_server",
    "HTMLAppWindow",
    "AppBar",
    "BottomNavigation",
    "NavigationManager",
]


def __getattr__(name):
    if name == "HTMLAppWindow":
        from .gui_framework import HTMLAppWindow

        return HTMLAppWindow
    if name in ("AppBar", "BottomNavigation"):
        from . import ui_components

        return getattr(ui_components, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
