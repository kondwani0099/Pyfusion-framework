"""Vue.js-inspired Component system and Single-File Component (.fusion) compiler for PyFusion."""

import hashlib
import json
import os
import re
from typing import Any, Callable, Dict, Optional, Set, Type
from .reactivity import ReactiveDict, reactive
from .security import escape_html

_PROTECTED_COMPONENT_METHODS: Set[str] = {
    "data",
    "computed",
    "watch",
    "created",
    "before_mount",
    "mounted",
    "updated",
    "unmounted",
    "get_full_state",
    "invoke_method",
    "render_fragment",
    "render_page",
}


CLIENT_RUNTIME_JS = r"""
(function () {
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content') || '';
    const match = document.cookie.match(/(?:^|;\s*)pyfusion_csrf=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  class PyFusionInstance {
    constructor(rootEl, componentId, initialState, computedKeys) {
      this.root = rootEl;
      this.componentId = componentId;
      this.computedKeys = new Set(computedKeys || []);
      this.templateEls = [];
      this._initForTemplates();
      this.state = this._createReactiveProxy(initialState || {});
      this._bindEvents();
      this.render();
    }

    _createReactiveProxy(target) {
      const self = this;
      return new Proxy(target, {
        set(obj, prop, value) {
          if (obj[prop] !== value) {
            obj[prop] = value;
            self.render();
          }
          return true;
        },
        get(obj, prop) {
          return obj[prop];
        }
      });
    }

    _initForTemplates() {
      const forNodes = this.root.querySelectorAll('[f-for], [v-for]');
      forNodes.forEach((node) => {
        const expr = node.getAttribute('f-for') || node.getAttribute('v-for');
        node.removeAttribute('f-for');
        node.removeAttribute('v-for');
        const anchor = document.createComment(`pyfusion-for: ${expr}`);
        node.parentNode.insertBefore(anchor, node);
        node.parentNode.removeChild(node);
        this.templateEls.push({ anchor, template: node, expr, rendered: [] });
      });
    }

    _evalInScope(expr, extraScope) {
      try {
        const scope = Object.assign({}, this.state, extraScope || {});
        const trimmed = String(expr || '').trim();
        if (Object.prototype.hasOwnProperty.call(scope, trimmed)) {
          return scope[trimmed];
        }
        const keys = Object.keys(scope);
        const vals = keys.map((k) => scope[k]);
        const fn = new Function(...keys, `return (${trimmed});`);
        return fn(...vals);
      } catch (e) {
        return '';
      }
    }

    async callServer(methodName, args, eventPayload) {
      try {
        const rawState = Object.assign({}, this.state);
        const headers = { 'Content-Type': 'application/json' };
        const csrf = getCsrfToken();
        if (csrf) headers['X-CSRF-Token'] = csrf;

        const res = await fetch('/_pyfusion/rpc', {
          method: 'POST',
          headers,
          body: JSON.stringify({
            component_id: this.componentId,
            method: methodName,
            args: args || [],
            state: rawState,
            event: eventPayload || {}
          })
        });
        if (!res.ok) return;
        const data = await res.json();
        if (data && data.state) {
          Object.assign(this.state, data.state);
          this.render();
        }
      } catch (err) {
        console.error('[PyFusion RPC Error]', err);
      }
    }

    _bindNodeEvents(rootNode, extraScope) {
      const allEls = [rootNode, ...rootNode.querySelectorAll('*')];
      allEls.forEach((el) => {
        if (!el.attributes) return;
        if (el.__pyfusion_bound) return;
        const ownerComp = el.closest('[data-pyfusion-component]');
        if (ownerComp && ownerComp !== this.root) return;

        // Two-way data binding: f-model / v-model
        const modelProp = el.getAttribute('f-model') || el.getAttribute('v-model');
        if (modelProp) {
          const propName = modelProp.trim();
          el.addEventListener('input', (e) => {
            const val = el.type === 'checkbox' ? el.checked : (el.type === 'number' ? Number(e.target.value) : e.target.value);
            this.state[propName] = val;
          });
        }

        // Event bindings: @click, @submit.prevent, f-on:click, v-on:click
        Array.from(el.attributes).forEach((attr) => {
          let eventName = null;
          let modifiers = [];
          if (attr.name.startsWith('@')) {
            const parts = attr.name.slice(1).split('.');
            eventName = parts[0];
            modifiers = parts.slice(1);
          } else if (attr.name.startsWith('f-on:') || attr.name.startsWith('v-on:')) {
            const parts = attr.name.slice(5).split('.');
            eventName = parts[0];
            modifiers = parts.slice(1);
          }

          if (eventName) {
            const handlerExpr = attr.value.trim();
            el.addEventListener(eventName, (e) => {
              if (modifiers.includes('prevent')) e.preventDefault();
              if (modifiers.includes('stop')) e.stopPropagation();

              const match = handlerExpr.match(/^([a-zA-Z_][a-zA-Z0-9_]*)(?:\((.*)\))?$/);
              if (match) {
                const methodName = match[1];
                const rawArgs = match[2] ? match[2].split(',').map((a) => this._evalInScope(a.trim(), extraScope)) : [];
                this.callServer(methodName, rawArgs, { value: e.target ? e.target.value : null });
              } else {
                this._evalInScope(handlerExpr, extraScope);
                this.render();
              }
            });
          }
        });

        el.__pyfusion_bound = true;
      });
    }

    _bindEvents() {
      this._bindNodeEvents(this.root, {});
    }

    _renderInterpolation(node, extraScope) {
      const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
      let textNode;
      while ((textNode = walker.nextNode())) {
        const parentEl = textNode.parentElement;
        if (parentEl) {
          if (parentEl.closest('[f-pre], [v-pre]')) continue;
          const ownerComp = parentEl.closest('[data-pyfusion-component]');
          if (ownerComp && ownerComp !== this.root) continue;
        }
        if (textNode.__pyfusion_tpl === undefined) {
          if (/\{\{.+?\}\}/.test(textNode.nodeValue)) {
            textNode.__pyfusion_tpl = textNode.nodeValue;
          } else {
            textNode.__pyfusion_tpl = null;
          }
        }
        if (textNode.__pyfusion_tpl) {
          textNode.nodeValue = textNode.__pyfusion_tpl.replace(/\{\{\s*(.+?)\s*\}\}/g, (_, expr) => {
            const val = this._evalInScope(expr, extraScope);
            return val === undefined || val === null ? '' : String(val);
          });
        }
      }
    }

    _renderDirectives(container, extraScope) {
      const els = [container, ...container.querySelectorAll('*')];
      els.forEach((el) => {
        if (!el.attributes) return;
        if (el.closest('[f-pre], [v-pre]')) return;
        const ownerComp = el.closest('[data-pyfusion-component]');
        if (ownerComp && ownerComp !== this.root) return;

        // f-if / v-if
        const ifExpr = el.getAttribute('f-if') || el.getAttribute('v-if');
        if (ifExpr !== null) {
          const show = Boolean(this._evalInScope(ifExpr, extraScope));
          el.style.display = show ? '' : 'none';
        }

        // f-show / v-show
        const showExpr = el.getAttribute('f-show') || el.getAttribute('v-show');
        if (showExpr !== null) {
          const show = Boolean(this._evalInScope(showExpr, extraScope));
          el.style.display = show ? '' : 'none';
        }

        // f-text / v-text (XSS-safe via textContent)
        const textExpr = el.getAttribute('f-text') || el.getAttribute('v-text');
        if (textExpr !== null) {
          const val = this._evalInScope(textExpr, extraScope);
          el.textContent = val === undefined || val === null ? '' : String(val);
        }

        // f-model / v-model sync
        const modelProp = el.getAttribute('f-model') || el.getAttribute('v-model');
        if (modelProp) {
          const val = this.state[modelProp.trim()];
          if (el.type === 'checkbox') {
            el.checked = Boolean(val);
          } else if (document.activeElement !== el && val !== undefined) {
            el.value = val;
          }
        }

        // Dynamic attribute bindings (:class, :disabled, f-bind:href, etc.)
        Array.from(el.attributes).forEach((attr) => {
          let bindAttr = null;
          if (attr.name.startsWith(':')) {
            bindAttr = attr.name.slice(1);
          } else if (attr.name.startsWith('f-bind:') || attr.name.startsWith('v-bind:')) {
            bindAttr = attr.name.slice(7);
          }
          if (bindAttr) {
            const val = this._evalInScope(attr.value, extraScope);
            if (bindAttr === 'disabled' || bindAttr === 'hidden' || bindAttr === 'checked') {
              if (val) el.setAttribute(bindAttr, '');
              else el.removeAttribute(bindAttr);
            } else if (val !== undefined && val !== null) {
              const strVal = String(val);
              if (/^javascript:/i.test(strVal.trim())) return; // Block XSS javascript: URIs
              el.setAttribute(bindAttr, strVal);
            }
          }
        });
      });
    }

    render() {
      this.templateEls.forEach((item) => {
        item.rendered.forEach((n) => n.parentNode && n.parentNode.removeChild(n));
        item.rendered = [];

        const match = item.expr.match(/^\s*(?:\(([^,]+),\s*([^)]+)\)|([a-zA-Z0-9_]+))\s+in\s+(.+)$/);
        if (!match) return;
        const itemVar = (match[1] || match[3]).trim();
        const indexVar = match[2] ? match[2].trim() : 'index';
        const listExpr = match[4].trim();
        const listVal = this._evalInScope(listExpr) || [];

        if (Array.isArray(listVal)) {
          listVal.forEach((entry, idx) => {
            const clone = item.template.cloneNode(true);
            const scope = { [itemVar]: entry, [indexVar]: idx };
            this._renderDirectives(clone, scope);
            this._renderInterpolation(clone, scope);
            this._bindNodeEvents(clone, scope);
            item.anchor.parentNode.insertBefore(clone, item.anchor);
            item.rendered.push(clone);
          });
        }
      });

      this._renderDirectives(this.root, {});
      this._renderInterpolation(this.root, {});
    }
  }

  // --- Browser Live-Reload Watcher ---
  function startLiveReloadWatcher() {
    let lastHash = null;
    setInterval(async () => {
      try {
        const res = await fetch('/_pyfusion/livereload', { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (lastHash === null) {
          lastHash = data.hash;
        } else if (data.hash && data.hash !== lastHash) {
          lastHash = data.hash;
          console.log('[PyFusion] File change detected! Reloading page...');
          window.location.reload();
        }
      } catch (_) {
        // Server may be restarting; next tick will reconnect and reload
      }
    }, 1200);
  }

  window.PyFusion = {
    instances: {},
    getCsrfToken,
    mountAll() {
      document.querySelectorAll('[data-pyfusion-component]').forEach((el) => {
        const id = el.getAttribute('data-pyfusion-component');
        if (this.instances[id]) return;
        const rawState = el.getAttribute('data-pyfusion-state') || '{}';
        const rawComputed = el.getAttribute('data-pyfusion-computed') || '[]';
        const state = JSON.parse(rawState);
        const computedKeys = JSON.parse(rawComputed);
        this.instances[id] = new PyFusionInstance(el, id, state, computedKeys);
      });
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      window.PyFusion.mountAll();
      startLiveReloadWatcher();
    });
  } else {
    window.PyFusion.mountAll();
    startLiveReloadWatcher();
  }
})();
"""


class Component:
    """Vue.js-inspired Component base class for PyFusion."""

    name: Optional[str] = None
    template: str = "<div></div>"
    template_file: Optional[str] = None
    style: str = ""
    scoped_style: bool = True
    props: Dict[str, Any] = {}
    components: Dict[str, Type["Component"]] = {}
    _sfc_path: Optional[str] = None
    _sfc_mtime: Optional[float] = None

    def __init__(self, **passed_props):
        self.component_name = self.name or self.__class__.__name__
        self.scope_id = "data-pf-" + hashlib.md5(self.component_name.encode()).hexdigest()[:6]

        merged_props = dict(self.props or {})
        merged_props.update(passed_props)
        self.props_data = merged_props

        initial_data = {}
        initial_data.update(merged_props)
        initial_data.update(self.data() or {})
        self.state: ReactiveDict = reactive(initial_data, on_change=self._on_state_change)

        for prop_name, watcher_fn in (self.watch() or {}).items():
            self.state.watch(prop_name, watcher_fn)

        self.created()

    def data(self) -> Dict[str, Any]:
        return {}

    def computed(self) -> Dict[str, Callable[[ReactiveDict], Any]]:
        return {}

    def watch(self) -> Dict[str, Callable[[Any, Any], None]]:
        return {}

    def created(self):
        pass

    def before_mount(self):
        pass

    def mounted(self):
        pass

    def updated(self, key: str = None, new_val: Any = None, old_val: Any = None):
        pass

    def unmounted(self):
        pass

    def _on_state_change(self, key: str, new_val: Any, old_val: Any):
        self.updated(key, new_val, old_val)

    def get_full_state(self) -> Dict[str, Any]:
        snapshot = self.state.to_dict()
        comp_map = self.computed() if callable(getattr(self, "computed", None)) else getattr(self, "computed", {})
        if isinstance(comp_map, dict):
            for k, fn in comp_map.items():
                try:
                    snapshot[k] = fn(self.state)
                except Exception:
                    snapshot[k] = None
        return snapshot

    def invoke_method(self, method_name: str, args: list = None, client_state: dict = None) -> Dict[str, Any]:
        """Synchronize client state, verify method allowlist (OWASP A01/A03), and invoke component method."""
        if (
            not method_name
            or method_name.startswith("_")
            or method_name in _PROTECTED_COMPONENT_METHODS
            or not hasattr(self, method_name)
        ):
            raise PermissionError(f"Access denied or unknown public action method '{method_name}'")

        method = getattr(self, method_name)
        if not callable(method):
            raise PermissionError(f"Attribute '{method_name}' is not a callable action")

        if client_state and isinstance(client_state, dict):
            comp_keys = set((self.computed() or {}).keys())
            allowed_keys = set(self.state.keys())
            for k, v in client_state.items():
                if k in allowed_keys and k not in comp_keys:
                    self.state[k] = v

        method(*(args or []))
        return self.get_full_state()

    def _load_raw_template(self) -> str:
        if self.template_file and os.path.exists(self.template_file):
            with open(self.template_file, "r", encoding="utf-8") as f:
                return f.read()
        return self.template

    def _render_child_components(self, html: str, registry: Dict[str, Type["Component"]]) -> str:
        all_components = dict(registry or {})
        all_components.update(self.components or {})

        for tag_name, comp_cls in all_components.items():
            pattern = re.compile(
                rf"<{tag_name}(\s+[^/>]*?)?\s*(?:/>|></{tag_name}>)",
                re.IGNORECASE | re.DOTALL,
            )

            def replace_tag(match):
                attr_str = match.group(1) or ""
                parsed_props = dict(re.findall(r'([a-zA-Z0-9_-]+)=["\']([^"\']*)["\']', attr_str))
                child_instance = comp_cls(**parsed_props)
                return child_instance.render_fragment(registry=all_components)

            html = pattern.sub(replace_tag, html)

        return html

    def render_fragment(self, registry: Dict[str, Type["Component"]] = None) -> str:
        self.before_mount()
        raw_html = self._load_raw_template().strip()
        raw_html = self._render_child_components(raw_html, registry or {})

        full_state = self.get_full_state()
        comp_map = self.computed() if callable(getattr(self, "computed", None)) else getattr(self, "computed", {})
        computed_keys = list(comp_map.keys()) if isinstance(comp_map, dict) else []

        state_json = escape_html(json.dumps(full_state))
        computed_json = escape_html(json.dumps(computed_keys))

        style_block = ""
        if self.style:
            style_block = f"<style>{self.style}</style>\n"

        wrapper = (
            f"{style_block}"
            f'<div data-pyfusion-component="{escape_html(self.component_name)}" '
            f'data-pyfusion-state="{state_json}" '
            f'data-pyfusion-computed="{computed_json}" '
            f"{self.scope_id}>"
            f"{raw_html}"
            f"</div>"
        )
        self.mounted()
        return wrapper

    def render_page(
        self,
        title: str = None,
        registry: Dict[str, Type["Component"]] = None,
        head_extra: str = "",
        csrf_token: str = "",
    ) -> str:
        page_title = escape_html(title or self.component_name)
        fragment = self.render_fragment(registry=registry)
        csrf_meta = f'<meta name="csrf-token" content="{escape_html(csrf_token)}">' if csrf_token else ""
        return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    {csrf_meta}
    <title>{page_title}</title>
    <link href="https://cdn.jsdelivr.net/npm/daisyui@4.5.0/dist/full.min.css" rel="stylesheet" type="text/css" />
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap">
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="/styles.css">
    {head_extra}
</head>
<body class="bg-base-300 min-h-screen">
    <div id="app">
        {fragment}
    </div>
    <script src="/_pyfusion/client.js"></script>
</body>
</html>"""


def load_sfc(file_path: str, component_name: str = None) -> Type[Component]:
    """Compile a Vue-like Single-File Component (.fusion) into a PyFusion Component class."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Single-File Component not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()

    tpl_match = re.search(r"<template>(.*?)</template>", source, re.DOTALL | re.IGNORECASE)
    script_match = re.search(r"<script(?:\s+[^>]*)?>(.*?)</script>", source, re.DOTALL | re.IGNORECASE)
    style_match = re.search(r"<style(\s+scoped)?>(.*?)</style>", source, re.DOTALL | re.IGNORECASE)

    template_html = tpl_match.group(1).strip() if tpl_match else "<div></div>"
    script_code = script_match.group(1).strip() if script_match else ""
    style_css = style_match.group(2).strip() if style_match else ""
    is_scoped = bool(style_match and style_match.group(1))

    inferred_name = component_name or os.path.splitext(os.path.basename(file_path))[0]

    namespace: Dict[str, Any] = {
        "name": inferred_name,
        "template": template_html,
        "style": style_css,
        "scoped_style": is_scoped,
        "_sfc_path": os.path.abspath(file_path),
        "_sfc_mtime": os.path.getmtime(file_path),
    }

    if script_code:
        exec(compile(script_code, file_path, "exec"), {"Component": Component}, namespace)

    return type(inferred_name, (Component,), namespace)
