"""
Project configuration, icon generator, and windowless desktop packaging utilities for PyFusion Framework.
"""

import json
import os
import subprocess
import sys
from typing import Any, Dict, Optional

CONFIG_FILENAME = "pyfusion.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "project_name": "PyFusion-Studio",
    "app_title": "Lapansi Industries - PyFusion",
    "author": "Kondwani Nyirenda",
    "version": "0.4.0",
    "icon": "web/logo.png",
    "ico_path": "assets/icon.ico",
    "theme_color": "#10b981",
    "engine": "tk",
    "host": "localhost",
    "port": 5000,
    "width": 1120,
    "height": 760,
}


def get_config_path(base_dir: str = None) -> str:
    root = base_dir or os.getcwd()
    return os.path.join(root, CONFIG_FILENAME)


def load_project_config(base_dir: str = None) -> Dict[str, Any]:
    """Load pyfusion.json merged with default settings."""
    cfg = dict(DEFAULT_CONFIG)
    path = get_config_path(base_dir)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                cfg.update(user_cfg)
        except Exception:
            pass
    return cfg


def save_project_config(updates: Dict[str, Any], base_dir: str = None) -> Dict[str, Any]:
    """Update and persist project configuration to pyfusion.json."""
    cfg = load_project_config(base_dir)
    for k, v in updates.items():
        if v is not None:
            cfg[k] = v

    path = get_config_path(base_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def ensure_project_ico(icon_source: str = None, output_ico: str = None) -> Optional[str]:
    """
    Convert a PNG/JPG logo into a multi-size Windows .ico file (assets/icon.ico) using Pillow,
    so desktop windows, shortcuts, and standalone .exe builds use the custom project icon.
    """
    cfg = load_project_config()
    src = icon_source or cfg.get("icon", "web/logo.png")
    dst = output_ico or cfg.get("ico_path", "assets/icon.ico")

    if not os.path.isabs(src):
        src = os.path.abspath(src)
    if not os.path.isabs(dst):
        dst = os.path.abspath(dst)

    if src.lower().endswith(".ico") and os.path.exists(src):
        return src

    if not os.path.exists(src):
        fallback = os.path.abspath("web/logo.png")
        if os.path.exists(fallback):
            src = fallback
        else:
            return None

    try:
        from PIL import Image

        os.makedirs(os.path.dirname(dst), exist_ok=True)
        img = Image.open(src).convert("RGBA")
        img.save(dst, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return dst
    except Exception:
        return None


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
    Spawn the PyFusion Desktop GUI using pythonw.exe (a Windows GUI subsystem binary)
    without CREATE_NO_WINDOW so the GUI window is visible while no console window is created.
    """
    pythonw = get_windowless_python()
    script_path = os.path.abspath("desktop_app.py")
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
    Create a Desktop App shortcut (.lnk) pointing directly to pythonw.exe + desktop_app.py
    with WindowStyle = 1 (Normal GUI Window) and custom .ico icon.
    Because pythonw.exe is a GUI-subsystem executable, Windows opens ONLY the GUI window and NEVER opens a terminal.
    """
    cfg = load_project_config()
    project_name = cfg.get("project_name", "PyFusion-Studio")
    app_title = cfg.get("app_title", project_name)
    safe_filename = "".join(c if c.isalnum() or c in ("-", "_", " ") else "" for c in app_title).strip() or "PyFusion App"

    ico_path = ensure_project_ico()
    cwd = os.getcwd()
    pythonw_exe = get_windowless_python()
    desktop_script = os.path.join(cwd, "desktop_app.py")

    # Clean up old .bat or .vbs launchers
    for fname in os.listdir(cwd):
        if fname.startswith("Launch ") and (fname.endswith(".bat") or fname.endswith(".vbs")):
            try:
                os.remove(os.path.join(cwd, fname))
            except OSError:
                pass

    # Create a clean VBScript launcher with window style 1 (Normal GUI window, pythonw has no console)
    launcher_vbs = os.path.join(cwd, f"Launch {safe_filename}.vbs")
    vbs_content = (
        f'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.CurrentDirectory = "{cwd}"\r\n'
        f'WshShell.Run """{pythonw_exe}"" ""{desktop_script}""", 1, False\r\n'
    )
    with open(launcher_vbs, "w", encoding="utf-8") as f:
        f.write(vbs_content)

    # Create Windows .lnk shortcuts pointing directly to pythonw.exe + desktop_app.py
    shortcut_locations = [os.path.join(cwd, f"{safe_filename}.lnk")]
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


def build_standalone_exe(onefile: bool = True) -> Optional[str]:
    """
    Package the PyFusion desktop app into a standalone windowless Windows .exe in dist/ using PyInstaller,
    embedding web/, components/, assets/, and the custom .ico icon and project name.
    """
    cfg = load_project_config()
    project_name = cfg.get("project_name", "PyFusionApp").replace(" ", "-")
    ico_path = ensure_project_ico()

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
        f"--name={project_name}",
    ]
    if onefile:
        cmd.append("--onefile")
    if ico_path and os.path.exists(ico_path):
        cmd.append(f"--icon={ico_path}")

    for folder in ("web", "components", "assets"):
        if os.path.exists(folder):
            cmd.append(f"--add-data={folder}{sep}{folder}")

    cmd.append("desktop_app.py")

    subprocess.run(cmd, check=True)
    exe_ext = ".exe" if os.name == "nt" else ""
    dist_path = os.path.abspath(os.path.join("dist", f"{project_name}{exe_ext}"))
    return dist_path if os.path.exists(dist_path) else os.path.abspath("dist")
