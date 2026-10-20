"""Buildozer / python-for-android entry point."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from fusionlib.mobile_simulator import run_native_android_webview

if __name__ == "__main__":
    run_native_android_webview(port=5000)
