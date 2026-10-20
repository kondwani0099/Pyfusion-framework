"""
Project configuration, icon generator, and windowless desktop packaging utilities for PyFusion Framework.
Root configuration lives in `pyfusion.json` outside `desktop/` and `web/`.
"""

import json
import os
import subprocess
import sys
from typing import Any, Dict, Optional

CONFIG_FILENAME = "pyfusion.json"

DEFAULT_PATHS: Dict[str, str] = {
    "desktop_dir": "desktop",
    "desktop_entry": "desktop/app.py",
    "desktop_icons_dir": "desktop/icons",
    "desktop_shortcuts_dir": "desktop/shortcuts",
    "mobile_dir": "mobile",
    "mobile_entry": "mobile/app.py",
    "web_dir": "web",
    "web_entry": "web/app.py",
    "assets_dir": "web/assets",
    "components_dir": "web/components",
    "models_dir": "web/models",
    "stores_dir": "web/stores",
    "plugins_dir": "web/plugins",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "project_name": "PyFusion-Studio",
    "app_title": "Uniplexity AI - PyFusion",
    "author": "Kondwani Nyirenda",
    "version": "0.4.0",
    "icon": "web/assets/logo.png",
    "ico_path": "desktop/icons/icon.ico",
    "theme_color": "#10b981",
    "engine": "tk",
    "host": "localhost",
    "port": 5000,
    "width": 1120,
    "height": 760,
    "paths": dict(DEFAULT_PATHS),
}


def get_config_path(base_dir: str = None) -> str:
    root = base_dir or os.getcwd()
    return os.path.join(root, CONFIG_FILENAME)


def load_project_config(base_dir: str = None) -> Dict[str, Any]:
    """Load root pyfusion.json merged with default settings and folder paths."""
    cfg = dict(DEFAULT_CONFIG)
    cfg["paths"] = dict(DEFAULT_PATHS)
    path = get_config_path(base_dir)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                user_paths = user_cfg.get("paths")
                cfg.update(user_cfg)
                merged_paths = dict(DEFAULT_PATHS)
                if isinstance(user_paths, dict):
                    merged_paths.update(user_paths)
                cfg["paths"] = merged_paths
        except Exception:
            pass
    return cfg


def save_project_config(updates: Dict[str, Any], base_dir: str = None) -> Dict[str, Any]:
    """Update and persist project configuration to root pyfusion.json."""
    cfg = load_project_config(base_dir)
    for k, v in updates.items():
        if v is not None:
            cfg[k] = v

    path = get_config_path(base_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def resolve_desktop_entry(base_dir: str = None) -> str:
    """Resolve the desktop application entry script (defaults to desktop/app.py)."""
    root = base_dir or os.getcwd()
    cfg = load_project_config(root)
    entry_rel = cfg.get("paths", {}).get("desktop_entry", "desktop/app.py")
    candidate = os.path.abspath(os.path.join(root, entry_rel))
    if os.path.exists(candidate):
        return candidate
    fallback = os.path.abspath(os.path.join(root, "desktop_app.py"))
    return fallback if os.path.exists(fallback) else candidate


def resolve_mobile_entry(base_dir: str = None) -> str:
    """Resolve the mobile/Android application entry script (defaults to mobile/app.py)."""
    root = base_dir or os.getcwd()
    cfg = load_project_config(root)
    entry_rel = cfg.get("paths", {}).get("mobile_entry", "mobile/app.py")
    return os.path.abspath(os.path.join(root, entry_rel))


def resolve_web_entry(base_dir: str = None) -> str:
    """Resolve the web application entry script (defaults to web/app.py)."""
    root = base_dir or os.getcwd()
    cfg = load_project_config(root)
    entry_rel = cfg.get("paths", {}).get("web_entry", "web/app.py")
    candidate = os.path.abspath(os.path.join(root, entry_rel))
    if os.path.exists(candidate):
        return candidate
    fallback = os.path.abspath(os.path.join(root, "webapp.py"))
    return fallback if os.path.exists(fallback) else candidate


def ensure_project_ico(icon_source: str = None, output_ico: str = None) -> Optional[str]:
    """
    Convert a PNG/JPG logo into a multi-size Windows .ico file (desktop/icons/icon.ico) using Pillow,
    so desktop windows, shortcuts, and standalone .exe builds use the custom project icon.
    """
    cfg = load_project_config()
    src = icon_source or cfg.get("icon", "web/assets/logo.png")
    dst = output_ico or cfg.get("ico_path", "desktop/icons/icon.ico")

    if not os.path.isabs(src):
        src = os.path.abspath(src)
    if not os.path.isabs(dst):
        dst = os.path.abspath(dst)

    if src.lower().endswith(".ico") and os.path.exists(src):
        return src

    if not os.path.exists(src):
        for candidate in ("web/assets/logo.png", "desktop/icons/logo.png", "web/logo.png"):
            abs_cand = os.path.abspath(candidate)
            if os.path.exists(abs_cand):
                src = abs_cand
                break
        else:
            return dst if os.path.exists(dst) else None

    try:
        from PIL import Image

        os.makedirs(os.path.dirname(dst), exist_ok=True)
        img = Image.open(src).convert("RGBA")
        img.save(dst, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return dst
    except Exception:
        return dst if os.path.exists(dst) else None


def get_windowless_python() -> str:
    """Return pythonw.exe path on Windows so GUI processes never allocate a console window."""
    python_exe = sys.executable
    if os.name == "nt":
        venv_pythonw = os.path.join(os.getcwd(), "env", "Scripts", "pythonw.exe")
        if os.path.exists(venv_pythonw):
            return venv_pythonw
        pythonw_exe = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
        if os.path.exists(pythonw_exe):
            return pythonw_exe
    return python_exe


def launch_desktop_detached(extra_args=None) -> int:
    """
    Spawn the PyFusion Desktop GUI (desktop/app.py) using pythonw.exe (a Windows GUI subsystem binary)
    so the GUI window opens cleanly with zero console/terminal window.
    """
    pythonw = get_windowless_python()
    script_path = resolve_desktop_entry()
    cmd = [pythonw, script_path]
    if extra_args:
        cmd.extend(extra_args)

    proc = subprocess.Popen(
        cmd,
        cwd=os.getcwd(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return proc.pid


def launch_mobile_detached(extra_args=None) -> int:
    """
    Spawn the PyFusion Android Simulator GUI (mobile/app.py) using pythonw.exe
    so the mobile phone simulator opens cleanly with zero console/terminal window.
    """
    pythonw = get_windowless_python()
    script_path = resolve_mobile_entry()
    cmd = [pythonw, script_path]
    if extra_args:
        cmd.extend(extra_args)

    proc = subprocess.Popen(
        cmd,
        cwd=os.getcwd(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return proc.pid


def create_desktop_shortcut(target_dir: str = None) -> Dict[str, Any]:
    """
    Create a Desktop App shortcut (.lnk) and windowless launcher (.vbs) inside `desktop/shortcuts/`
    (and on the user's Windows Desktop) pointing to `pythonw.exe` + `desktop/app.py` with custom .ico icon.
    """
    cfg = load_project_config()
    project_name = cfg.get("project_name", "PyFusion-Studio")
    app_title = cfg.get("app_title", project_name)
    safe_filename = "".join(c if c.isalnum() or c in ("-", "_", " ") else "" for c in app_title).strip() or "PyFusion App"

    ico_path = ensure_project_ico()
    cwd = os.getcwd()
    pythonw_exe = get_windowless_python()
    desktop_script = resolve_desktop_entry(cwd)

    shortcuts_dir_rel = cfg.get("paths", {}).get("desktop_shortcuts_dir", "desktop/shortcuts")
    shortcuts_dir = os.path.abspath(os.path.join(cwd, shortcuts_dir_rel))
    os.makedirs(shortcuts_dir, exist_ok=True)

    # Clean up old launchers in desktop/shortcuts/ and root
    for folder in (shortcuts_dir, cwd):
        if not os.path.exists(folder):
            continue
        for fname in os.listdir(folder):
            if (fname.startswith("Launch ") and (fname.endswith(".bat") or fname.endswith(".vbs"))) or (
                folder == cwd and fname.endswith(".lnk")
            ):
                try:
                    os.remove(os.path.join(folder, fname))
                except OSError:
                    pass

    # Create a clean VBScript launcher inside desktop/shortcuts/
    launcher_vbs = os.path.join(shortcuts_dir, f"Launch {safe_filename}.vbs")
    vbs_content = (
        f'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.CurrentDirectory = "{cwd}"\r\n'
        f'WshShell.Run """{pythonw_exe}"" ""{desktop_script}""", 1, False\r\n'
    )
    with open(launcher_vbs, "w", encoding="utf-8") as f:
        f.write(vbs_content)

    # Create Windows .lnk shortcuts in desktop/shortcuts/ and on user's Desktop
    shortcut_locations = [os.path.join(shortcuts_dir, f"{safe_filename}.lnk")]
    user_desktop = target_dir or os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.exists(user_desktop):
        shortcut_locations.append(os.path.join(user_desktop, f"{safe_filename}.lnk"))

    created_shortcuts = []
    for lnk_path in shortcut_locations:
        ps_script = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{lnk_path}"); '
            f'$s.TargetPath = "{pythonw_exe}"; '
            f'$s.Arguments = \'"{desktop_script}"\'; '
            f'$s.WorkingDirectory = "{cwd}"; '
            f'$s.WindowStyle = 1; '
            f'$s.Description = "{app_title}"; '
        )
        if ico_path and os.path.exists(ico_path):
            ps_script += f'$s.IconLocation = "{ico_path},0"; '
        ps_script += "$s.Save()"

        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True, capture_output=True)
            created_shortcuts.append(lnk_path)
        except Exception:
            pass

    return {
        "launcher_vbs": launcher_vbs,
        "shortcuts": created_shortcuts,
        "ico_path": ico_path or "",
        "app_title": app_title,
    }


def generate_android_project(base_dir: str = None) -> Dict[str, Any]:
    """
    Generate & sync Android APK build configurations inside `mobile/` from root `pyfusion.json`:
      1. `mobile/buildozer.spec` — python-for-android WebView bootstrap bundling Python 3 + SQLite + PyFusion
      2. `mobile/capacitor.config.json` — Capacitor Android Studio hybrid wrapper config
      3. `mobile/main.py` — Android entry point required by Buildozer (`--android-webview`)
    """
    root = base_dir or os.getcwd()
    cfg = load_project_config(root)
    project_name = cfg.get("project_name", "PyFusionStudio")
    app_title = cfg.get("app_title", project_name)
    version = cfg.get("version", "0.4.0")
    icon_rel = cfg.get("icon", "web/assets/logo.png")
    pkg_slug = "".join(c.lower() for c in project_name if c.isalnum()) or "pyfusionapp"
    app_id = f"org.pyfusion.{pkg_slug}"

    mobile_dir = os.path.abspath(os.path.join(root, cfg.get("paths", {}).get("mobile_dir", "mobile")))
    os.makedirs(mobile_dir, exist_ok=True)

    # 1. Buildozer spec (python-for-android WebView bootstrap)
    buildozer_spec_path = os.path.join(mobile_dir, "buildozer.spec")
    buildozer_content = f"""[app]
title = {app_title}
package.name = {pkg_slug}
package.domain = org.pyfusion
source.dir = ..
source.include_exts = py,png,jpg,ico,html,css,js,fusion,json
source.exclude_dirs = env,venv,.git,__pycache__,desktop/dist,desktop/shortcuts
version = {version}
requirements = python3,sqlite3,pyjnius,android
icon.filename = %(source.dir)s/{icon_rel}
orientation = portrait
fullscreen = 0

# Android WebView bootstrap settings
p4a.bootstrap = webview
p4a.port = {cfg.get('port', 5000)}
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
"""
    with open(buildozer_spec_path, "w", encoding="utf-8") as f:
        f.write(buildozer_content)

    # 2. Capacitor config (for Android Studio / Gradle APK wrapper)
    cap_config_path = os.path.join(mobile_dir, "capacitor.config.json")
    cap_config = {
        "appId": app_id,
        "appName": app_title,
        "webDir": "../web",
        "bundledWebRuntime": False,
        "server": {
            "url": f"http://10.0.2.2:{cfg.get('port', 5000)}",
            "cleartext": True,
        },
        "android": {
            "backgroundColor": "#0b1120",
            "allowMixedContent": True,
        },
    }
    with open(cap_config_path, "w", encoding="utf-8") as f:
        json.dump(cap_config, f, indent=2)

    # 3. Android entry point shim in mobile/main.py for Buildozer
    android_main_path = os.path.join(mobile_dir, "main.py")
    with open(android_main_path, "w", encoding="utf-8") as f:
        f.write(
            '"""Buildozer / python-for-android entry point."""\n'
            "import os, sys\n"
            "ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
            "if ROOT not in sys.path:\n"
            "    sys.path.insert(0, ROOT)\n"
            "from fusionlib.mobile_simulator import run_native_android_webview\n\n"
            'if __name__ == "__main__":\n'
            f"    run_native_android_webview(port={cfg.get('port', 5000)})\n"
        )

    return {
        "app_title": app_title,
        "package_name": app_id,
        "buildozer_spec": buildozer_spec_path,
        "capacitor_config": cap_config_path,
        "android_main": android_main_path,
    }


def build_standalone_exe(onefile: bool = True) -> Optional[str]:
    """
    Package the PyFusion desktop app (`desktop/app.py`) into a standalone windowless Windows .exe
    in `desktop/dist/` using PyInstaller, embedding `web/` and `desktop/icons/` and custom .ico icon.
    """
    cfg = load_project_config()
    project_name = cfg.get("project_name", "PyFusionApp").replace(" ", "-")
    ico_path = ensure_project_ico()
    desktop_script = resolve_desktop_entry()
    dist_dir = os.path.abspath(os.path.join("desktop", "dist"))

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--noconsole",
        "--windowed",
        f"--distpath={dist_dir}",
        f"--name={project_name}",
    ]
    if onefile:
        cmd.append("--onefile")
    if ico_path and os.path.exists(ico_path):
        cmd.append(f"--icon={ico_path}")

    for folder in ("web", "desktop"):
        if os.path.exists(folder):
            cmd.append(f"--add-data={folder}{sep}{folder}")

    cmd.append(desktop_script)

    subprocess.run(cmd, check=True)
    exe_ext = ".exe" if os.name == "nt" else ""
    dist_path = os.path.join(dist_dir, f"{project_name}{exe_ext}")
    return dist_path if os.path.exists(dist_path) else dist_dir
