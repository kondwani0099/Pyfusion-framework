"""
PyFusion Web Application Entry Point (web/app.py).
Mounts Vue-style Single-File Components from web/components/, serves static assets from web/assets/,
and connects to the root SQLite database with OWASP Top 10 security.
"""

import os
import sys

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(WEB_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fusionlib import (
    Field,
    FusionDB,
    Model,
    create_app,
    escape_html,
    hash_password,
)

# 1. Connect Database (SQLite out of the box, or set DATABASE_URL)
db = FusionDB("sqlite:///pyfusion.db")


# 2. Define Declarative Database ORM Model (100% Parameterized SQL / OWASP A03 Safe)
class UserSubmission(Model):
    table_name = "user_submissions"

    username = Field("TEXT", nullable=False)
    role = Field("TEXT", default="Developer")
    password_hash = Field("TEXT", nullable=False)
    ip_address = Field("TEXT", default="127.0.0.1")


# 3. Create Vue-style PyFusion app & install Database plugin
app = create_app(
    web_dir=WEB_DIR,
    components_dir=os.path.join(WEB_DIR, "components"),
).use(db)

# 4. Mount the Single-File Component (web/components/Counter.fusion) at /counter
if "Counter" in app.components:
    app.mount("/counter", app.components["Counter"], title="PyFusion Reactive Counter")


# 5. Database CRUD Endpoints for Submissions
@app.get("/api/submissions")
def list_submissions(request):
    records = [r.to_dict() for r in UserSubmission.all(limit=25)]
    return {"status": "ok", "count": len(records), "submissions": records}


@app.delete("/api/submissions/<id>")
def delete_submission(request):
    rec_id = request.route_params.get("id")
    deleted = UserSubmission.delete_by_id(rec_id)
    return {"status": "ok", "deleted": deleted, "id": rec_id}


# 6. Handle Form Submissions (PBKDF2 Password Hashing + SQLite Persistence)
@app.post("/submit_form")
def handle_form_submission(request):
    raw_username = (request.form.get("username") or "Guest").strip()
    raw_password = request.form.get("password") or "default_pass"
    safe_username = escape_html(raw_username)

    # OWASP A02: Hash password with PBKDF2-HMAC-SHA256 + cryptographic salt before saving
    pw_hash = hash_password(raw_password)

    # OWASP A03: Save using parameterized ORM query
    record = UserSubmission.create(
        username=safe_username,
        password_hash=pw_hash,
        ip_address=request.client_ip,
    )
    total_records = len(UserSubmission.all(limit=500))
    print(f"[{record.created_at}] Saved UserSubmission #{record.id} for user '{safe_username}'")

    if "application/json" in request.headers.get("Accept", ""):
        return {
            "status": "success",
            "message": f"Saved '{safe_username}' to SQLite database (id #{record.id})",
            "record": record.to_dict(),
            "total_records_in_db": total_records,
            "security": {
                "password_storage": "PBKDF2-HMAC-SHA256 (600,000 iterations)",
                "sql_protection": "Parameterized Prepared Statement",
                "xss_escaped": True,
            },
        }

    return (
        f"<!DOCTYPE html><html data-theme='dark'><head><meta charset='utf-8'>"
        f"<title>Saved to Database — PyFusion</title>"
        f"<link rel='stylesheet' href='/assets/app.css'>"
        f"</head><body class='min-h-screen flex items-center justify-center bg-base-300 text-base-content p-6'>"
        f"<div class='card bg-base-100 border border-base-content/10 shadow-2xl p-8 text-center max-w-md w-full'>"
        f"<div class='w-12 h-12 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center mx-auto mb-4 text-2xl'>✓</div>"
        f"<h2 class='text-2xl font-bold mb-2'>Welcome, {safe_username}!</h2>"
        f"<p class='opacity-75 text-sm mb-2'>Saved as Record <strong>#{record.id}</strong> in <code>pyfusion.db</code>.</p>"
        f"<p class='text-xs font-mono opacity-60 break-all mb-6'>{pw_hash[:48]}...</p>"
        f"<div class='flex justify-center gap-3'>"
        f"<a href='/form' class='btn btn-outline btn-sm'>Back to Form</a>"
        f"<a href='/' class='btn bg-emerald-600 hover:bg-emerald-500 text-white border-none btn-sm'>Return Home</a>"
        f"</div></div>"
        f"<script src='/_pyfusion/client.js'></script></body></html>"
    )


if __name__ == "__main__":
    app.run(host="localhost", port=5000)
