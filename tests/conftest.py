import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Deterministic secret for tests (avoids writing .pyfusion/dev_secret).
os.environ.setdefault("PYFUSION_SECRET_KEY", "test-secret-key-" + "x" * 48)


COUNTER_SFC = """<template>
  <div>
    <p>{{ count }}</p>
    <input f-model="greeting" />
    <button @click="increment">+1</button>
  </div>
</template>

<script>
props = {"title": "Counter"}
locked = {"count"}

def data(self):
    return {"count": 0, "greeting": "hi", "role": "user"}

def computed(self):
    return {"doubled": lambda s: int(s.get("count", 0)) * 2}

def increment(self):
    self.state.count = int(self.state.count) + 1

def echo_greeting(self):
    self.state.role = "echo:" + str(self.state.greeting)

def _private_helper(self):
    self.state.count = 999

helper_imported = os.path.join
</script>
"""

FORM_PAGE = """<!DOCTYPE html><html><body>
<form action="/submit_form" method="post"><input name="username"></form>
<Counter />
<script src="/_pyfusion/client.js"></script>
</body></html>"""


@pytest.fixture()
def project_dir(tmp_path):
    web = tmp_path / "web"
    comps = web / "components"
    comps.mkdir(parents=True)
    (comps / "Counter.fusion").write_text(COUNTER_SFC, encoding="utf-8")
    (web / "index.html").write_text(FORM_PAGE, encoding="utf-8")
    (web / "secret.py").write_text("SECRET = 1", encoding="utf-8")
    (web / "assets").mkdir()
    (web / "assets" / "styles.css").write_text("body{}", encoding="utf-8")
    return tmp_path
