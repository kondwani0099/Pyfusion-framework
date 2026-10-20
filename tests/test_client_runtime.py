"""The client runtime must work under a strict CSP: no eval / new Function, and a sandboxed evaluator."""

import json
import shutil
import subprocess

import pytest

from fusionlib.component import get_client_runtime_js

NODE = shutil.which("node")

HARNESS = r"""
const S = globalThis.PyFusionSafeExpr;
const out = {};
const state = { count: 3, name: 'Ada', items: [1, 2, 3], rec: { id: 7, tags: ['a'] }, flag: false, nil: null };
const cases = {
  ident: 'count',
  arith: 'count * 2 + 1',
  pow: '2 ** 3 ** 2',
  compare: 'count >= 3 && count < 10',
  ternary: "count > 5 ? 'big' : count > 2 ? 'mid' : 'small'",
  member: 'rec.id',
  index: 'items[1]',
  optional: 'nil?.foo',
  nullish: "nil ?? 'fallback'",
  length: 'items.length',
  method: "name.toUpperCase()",
  join: "items.map(String).join('-')",
  math: 'Math.max(count, 10)',
  json: 'JSON.stringify(rec)',
  objlit: "({ a: count, name }).name",
  arrlit: '[count, 1][0]',
  typeofMissing: 'typeof missing',
  not: '!flag',
  neg: '-count',
  str: '"a\\"b" + \'c\'',
  loopvar: 'item * 10',
  missing: 'nothere',
};
for (const [k, src] of Object.entries(cases)) {
  try { out[k] = S.run(src, state, { item: 4 }); } catch (e) { out[k] = 'ERR:' + e.message; }
}
const st = { count: 1, todo: { done: false } };
S.run('count += 2; todo.done = !todo.done', st);
S.run('count++', st);
out.assigned = st;
const blocked = [
  'constructor', "rec.constructor", "rec['constructor']", "name.constructor.constructor('return 1')()",
  "rec.__proto__", "items['__proto__']", "Math.max.constructor", 'Function', 'window', 'globalThis.process',
  'this', "rec.prototype", "rec.toString.constructor", "items.map.__proto__",
];
out.blocked = blocked.map((src) => {
  try { const v = S.run(src, state); return v === undefined ? 'undefined' : (typeof v === 'function' ? 'FUNCTION' : 'value'); }
  catch (e) { return 'blocked'; }
});
out.syntax = ['count +', 'a b', '`${x}`'].map((src) => { try { S.parse(src); return 'parsed'; } catch (e) { return 'error'; } });
console.log(JSON.stringify(out));
"""


def test_runtime_has_no_dynamic_code_evaluation():
    js = get_client_runtime_js(livereload=False, websocket=True)
    assert "new Function" not in js
    assert "eval(" not in js
    assert "const WEBSOCKET_ENABLED = true" in js
    assert "__PYFUSION_" not in js


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_safe_expression_evaluator(tmp_path):
    script = tmp_path / "harness.js"
    script.write_text(get_client_runtime_js() + "\n" + HARNESS, encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    assert out["ident"] == 3
    assert out["arith"] == 7
    assert out["pow"] == 512
    assert out["compare"] is True
    assert out["ternary"] == "mid"
    assert out["member"] == 7
    assert out["index"] == 2
    assert out.get("optional") is None
    assert out["nullish"] == "fallback"
    assert out["length"] == 3
    assert out["method"] == "ADA"
    assert out["join"] == "1-2-3"
    assert out["math"] == 10
    assert json.loads(out["json"]) == {"id": 7, "tags": ["a"]}
    assert out["objlit"] == "Ada"
    assert out["arrlit"] == 3
    assert out["typeofMissing"] == "undefined"
    assert out["not"] is True
    assert out["neg"] == -3
    assert out["str"] == 'a"bc'
    assert out["loopvar"] == 40
    assert out.get("missing") is None
    assert out["assigned"] == {"count": 4, "todo": {"done": True}}
    # Nothing in the sandbox may yield the Function constructor or reach real globals
    for verdict in out["blocked"]:
        assert verdict in ("blocked", "undefined"), out["blocked"]
    assert out["syntax"] == ["error", "error", "error"]
