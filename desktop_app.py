import argparse
import os
import sys
import traceback

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure stdout/stderr exist when running windowless under pythonw.exe
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--title", default=None)
    parser.add_argument("--color", default=None)
    parser.add_argument("--icon", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--engine", default=None)
    args, _ = parser.parse_known_args()

    from fusionlib.gui_framework import HTMLAppWindow

    app_window = HTMLAppWindow(
        app_name=args.title,
        app_color=args.color,
        icon_path=args.icon,
        port=args.port,
        engine=args.engine,
    )

