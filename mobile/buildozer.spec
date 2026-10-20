[app]
title = Uniplexity AI - PyFusion
package.name = pyfusionstudio
package.domain = org.pyfusion
source.dir = ..
source.include_exts = py,png,jpg,ico,html,css,js,fusion,json
source.exclude_dirs = env,venv,.git,__pycache__,desktop/dist,desktop/shortcuts,mobile/dist
version = 0.4.0
requirements = python3,sqlite3,pyjnius,android
icon.filename = %(source.dir)s/web/assets/logo.png
orientation = portrait
fullscreen = 0

# Android WebView bootstrap & Artifact Formats (.apk and .aab)
p4a.bootstrap = webview
p4a.port = 5000
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.release_artifact = aab
android.debug_artifact = aab

[buildozer]
log_level = 2
warn_on_root = 1
bin_dir = ./dist
