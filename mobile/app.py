"""
PyFusion Mobile & Android Entry Point (mobile/app.py).
- When running on Android (Buildozer / python-for-android), starts the embedded PyFusion
  HTTP + SQLite server on 127.0.0.1 and opens a full-screen native Android WebView.
- When running on a Desktop OS (`pyfusion run mobile` or `python mobile/app.py`),
  opens the windowless Android Pixel Phone Simulator.
"""

import argparse
import os
import sys

MOBILE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MOBILE_DIR)
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--title", default=None)
    parser.add_argument("--icon", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--android-webview", action="store_true")
    args, _ = parser.parse_known_args()

    from fusionlib.mobile_simulator import AndroidSimulatorWindow, run_native_android_webview

    if args.android_webview:
        run_native_android_webview(port=args.port or 5000)
    else:
        AndroidSimulatorWindow(
            app_name=args.title,
            icon_path=args.icon,
            port=args.port,
        )


if __name__ == "__main__":
    main()
