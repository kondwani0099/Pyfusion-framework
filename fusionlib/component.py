"""Vue.js-inspired Component system and Single-File Component (.fusion) compiler for PyFusion."""

import ast
import hashlib
import inspect
import json
import os
import re
from typing import Any, Callable, Dict, FrozenSet, Optional, Set, Type
from .reactivity import ReactiveDict, Ref, reactive
from .security import escape_html, sign_state

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
    "hydrate",
    "apply_client_updates",
    "is_local_only_action",
}

# Maximum number of positional arguments accepted from the browser for a single RPC call.
MAX_RPC_ARGS = 32

# Fallback secret used to sign state snapshots when render functions are called without an explicit
# secret (e.g. rendering a component outside of a PyFusionApp). Set by PyFusionApp on creation.
_DEFAULT_STATE_SECRET: Optional[str] = None


def set_default_state_secret(secret_key: Optional[str]):
    """Configure the fallback HMAC secret used to sign component state snapshots."""
    global _DEFAULT_STATE_SECRET
    _DEFAULT_STATE_SECRET = secret_key


def serialize_state(state: Dict[str, Any]) -> str:
    """Canonical JSON serialization of a component state snapshot (stable key order)."""
    return json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)


def local_only(fn: Callable) -> Callable:
    """Mark a component action as callable only from localhost in development mode.

    Use for actions with machine-level side effects (writing project files, spawning processes).
    """
    fn.__pyfusion_local_only__ = True
    return fn


CLIENT_RUNTIME_JS = r"""
(function () {
  if (window.PyFusion && window.PyFusion.__loaded) return;
  const LIVERELOAD_ENABLED = __PYFUSION_LIVERELOAD__;
  const SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS', 'TRACE'];

  function readCookie(name) {
    const match = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]+)'));
    return match ? decodeURIComponent(match[1]) : '';
  }

  function getCsrfToken() {
    // The cookie is authoritative (the server refreshes it); the meta tag is a fallback.
    const fromCookie = readCookie('pyfusion_csrf');
    if (fromCookie) return fromCookie;
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? (meta.getAttribute('content') || '') : '';
  }

  // Attach the CSRF header to same-origin state-changing fetch() calls automatically (axios-style XSRF).
  if (window.fetch && !window.fetch.__pyfusion_csrf) {
    const nativeFetch = window.fetch.bind(window);
    const patchedFetch = function (input, init) {
      try {
        init = init || {};
        const isRequestObj = typeof Request !== 'undefined' && input instanceof Request;
        const method = String(init.method || (isRequestObj ? input.method : 'GET')).toUpperCase();
        const rawUrl = typeof input === 'string' ? input : (input && input.url) || String(input);
        const url = new URL(rawUrl, window.location.href);
        if (!SAFE_METHODS.includes(method) && url.origin === window.location.origin) {
          const headers = new Headers(init.headers || (isRequestObj ? input.headers : undefined));
          if (!headers.has('X-CSRF-Token')) {
            const token = getCsrfToken();
            if (token) headers.set('X-CSRF-Token', token);
          }
          init = Object.assign({}, init, { headers, credentials: init.credentials || 'same-origin' });
        }
      } catch (_) {
        // Never block a request because of the CSRF helper
      }
      return nativeFetch(input, init);
    };
    patchedFetch.__pyfusion_csrf = true;
    window.fetch = patchedFetch;
  }

  function notify(message, type) {
    if (typeof window.showToast === 'function') window.showToast(message, type);
  }

  class PyFusionInstance {
    constructor(rootEl, componentId, snapshot, checksum, computedKeys, overrides) {
      this.root = rootEl;
      this.componentId = componentId;
      this.computedKeys = new Set(computedKeys || []);
      this.snapshot = snapshot || '{}';
      this.checksum = checksum || '';
      let initialState = {};
      try { initialState = JSON.parse(this.snapshot); } catch (_) { initialState = {}; }
      this._serverState = initialState;
      this.templateEls = [];
      this._initForTemplates();
      this.state = this._createReactiveProxy(Object.assign({}, initialState, overrides || {}));
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

    // Only fields the user changed locally (f-model etc.) are sent as "updates"; the server verifies the
    // signed snapshot and rejects updates to locked or computed properties.
    _collectUpdates() {
      const updates = {};
      Object.keys(this.state).forEach((k) => {
        if (this.computedKeys.has(k)) return;
        if (JSON.stringify(this.state[k]) !== JSON.stringify(this._serverState[k])) {
          updates[k] = this.state[k];
        }
      });
      return updates;
    }

    async callServer(methodName, args, eventPayload, isRetry) {
      try {
        const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
        const csrf = getCsrfToken();
        if (csrf) headers['X-CSRF-Token'] = csrf;

        const res = await fetch('/_pyfusion/rpc', {
          method: 'POST',
          headers,
          credentials: 'same-origin',
          body: JSON.stringify({
            component_id: this.componentId,
            method: methodName,
            args: args || [],
            snapshot: this.snapshot,
            checksum: this.checksum,
            updates: this._collectUpdates(),
            event: eventPayload || {}
          })
        });
        let data = null;
        try { data = await res.json(); } catch (_) { data = null; }

        if (!res.ok) {
          // The server rotates an invalid/expired CSRF cookie on failure; retry once with the fresh token.
          if (res.status === 403 && data && data.code === 'csrf_failed' && !isRetry) {
            return this.callServer(methodName, args, eventPayload, true);
          }
          console.warn('[PyFusion RPC]', res.status, data && data.error);
          if (data && data.error) notify(data.error, 'error');
          return;
        }

        if (data && typeof data.snapshot === 'string') {
          const prevToast = this.state.toast_message;
          let nextState = {};
          try { nextState = JSON.parse(data.snapshot); } catch (_) { nextState = data.state || {}; }
          this.snapshot = data.snapshot;
          this.checksum = data.checksum || '';
          this._serverState = JSON.parse(data.snapshot);
          Object.assign(this.state, nextState);
          this.render();
          if (nextState.toast_message && nextState.toast_message !== prevToast) {
            notify(nextState.toast_message);
          }
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
            // Never allow binding inline event handler attributes (XSS)
            if (/^on/i.test(bindAttr)) return;
            const val = this._evalInScope(attr.value, extraScope);
            if (bindAttr === 'disabled' || bindAttr === 'hidden' || bindAttr === 'checked') {
              if (val) el.setAttribute(bindAttr, '');
              else el.removeAttribute(bindAttr);
            } else if (val !== undefined && val !== null) {
              const strVal = String(val);
              if (/^\s*(javascript|vbscript|data:text\/html)/i.test(strVal)) return; // Block XSS URIs
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

  // --- Stateful Hot-Morph Live-Reload (HMR) Watcher (development mode only) ---
  async function hotMorphReload() {
    try {
      const activeSection = document.querySelector('.tab-section:not(.hidden)');
      const activeSectionId = activeSection ? activeSection.id : null;
      const scrollY = window.scrollY;

      const pageRes = await fetch(window.location.href, { cache: 'no-store' });
      if (!pageRes.ok) {
        window.location.reload();
        return;
      }
      const htmlText = await pageRes.text();
      const parser = new DOMParser();
      const nextDoc = parser.parseFromString(htmlText, 'text/html');

      nextDoc.querySelectorAll('[data-pyfusion-component]').forEach((nextEl) => {
        const id = nextEl.getAttribute('data-pyfusion-component');
        const curEl = document.querySelector(`[data-pyfusion-component="${id}"]`);
        if (!curEl) return;

        // Preserve active tab visibility across HMR morph
        if (activeSectionId) {
          nextEl.querySelectorAll('.tab-section').forEach((sec) => {
            sec.classList.toggle('hidden', sec.id !== activeSectionId);
          });
        }

        const prevInstance = window.PyFusion.instances[id];
        const modelKeys = [];
        curEl.querySelectorAll('[f-model], [v-model]').forEach((inp) => {
          const k = (inp.getAttribute('f-model') || inp.getAttribute('v-model') || '').trim();
          if (k) modelKeys.push(k);
        });
        const preservedModels = {};
        if (prevInstance && prevInstance.state) {
          modelKeys.forEach((k) => {
            if (prevInstance.state[k] !== undefined) preservedModels[k] = prevInstance.state[k];
          });
        }

        curEl.setAttribute('data-pyfusion-state', nextEl.getAttribute('data-pyfusion-state') || '{}');
        curEl.setAttribute('data-pyfusion-checksum', nextEl.getAttribute('data-pyfusion-checksum') || '');
        curEl.setAttribute('data-pyfusion-computed', nextEl.getAttribute('data-pyfusion-computed') || '[]');
        curEl.innerHTML = nextEl.innerHTML;

        const computedKeys = JSON.parse(curEl.getAttribute('data-pyfusion-computed') || '[]');
        window.PyFusion.instances[id] = new PyFusionInstance(
          curEl,
          id,
          curEl.getAttribute('data-pyfusion-state') || '{}',
          curEl.getAttribute('data-pyfusion-checksum') || '',
          computedKeys,
          preservedModels
        );
      });

      window.scrollTo({ top: scrollY, behavior: 'instant' });
      notify('⚡ Hot-reloaded components (state preserved)');
    } catch (err) {
      window.location.reload();
    }
  }

  function startLiveReloadWatcher() {
    if (!LIVERELOAD_ENABLED) return;
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
          console.log('[PyFusion HMR] File change detected! Hot-morphing components...');
          await hotMorphReload();
        }
      } catch (_) {
        // Server may be restarting; next tick will reconnect
      }
    }, 1200);
  }

  window.PyFusion = {
    __loaded: true,
    instances: {},
    getCsrfToken,
    hotMorphReload,
    mountAll() {
      document.querySelectorAll('[data-pyfusion-component]').forEach((el) => {
        const id = el.getAttribute('data-pyfusion-component');
        if (this.instances[id]) return;
        const snapshot = el.getAttribute('data-pyfusion-state') || '{}';
        const checksum = el.getAttribute('data-pyfusion-checksum') || '';
        const computedKeys = JSON.parse(el.getAttribute('data-pyfusion-computed') || '[]');
        this.instances[id] = new PyFusionInstance(el, id, snapshot, checksum, computedKeys);
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


def get_client_runtime_js(livereload: bool = False) -> str:
    """Return the browser runtime with live-reload enabled only when requested (development mode)."""
    return CLIENT_RUNTIME_JS.replace("__PYFUSION_LIVERELOAD__", "true" if livereload else "false")


class Component:
    """Vue.js-inspired Component base class for PyFusion.

    Security model (server-driven components):
    - Only public methods defined on the component itself are callable from the browser (allowlist).
    - State held by the browser is an HMAC-signed snapshot; tampered snapshots are rejected.
    - Keys listed in ``locked`` can never be modified by the browser (like Livewire's ``#[Locked]``).
    - Actions decorated with ``@local_only`` (or every action when ``restrict_to_localhost = True``)
      only run for loopback clients in development mode.
    """

    name: Optional[str] = None
    template: str = "<div></div>"
    template_file: Optional[str] = None
    style: str = ""
    scoped_style: bool = True
    props: Dict[str, Any] = {}
    components: Dict[str, Type["Component"]] = {}
    locked: Set[str] = set()
    actions: Optional[Set[str]] = None
    restrict_to_localhost: bool = False
    _sfc_path: Optional[str] = None
    _sfc_mtime: Optional[float] = None
    _sfc_actions: Optional[FrozenSet[str]] = None

    def __init__(self, **passed_props):
        self.component_name = self.name or self.__class__.__name__
        self.scope_id = "data-pf-" + hashlib.md5(self.component_name.encode(), usedforsecurity=False).hexdigest()[:6]

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

    @classmethod
    def declared_props(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Filter arbitrary input (e.g. query string) down to the component's declared props."""
        allowed = set((cls.props or {}).keys())
        return {k: v for k, v in (values or {}).items() if k in allowed}

    @classmethod
    def public_actions(cls) -> FrozenSet[str]:
        """Return the allowlist of method names the browser may invoke via RPC."""
        cached = cls.__dict__.get("_pyfusion_action_cache")
        if cached is not None:
            return cached

        if cls.actions is not None:
            names = set(cls.actions)
        else:
            names = set()
            for klass in cls.__mro__:
                if klass is Component or not (isinstance(klass, type) and issubclass(klass, Component)):
                    continue
                sfc_actions = klass.__dict__.get("_sfc_actions")
                if sfc_actions is not None:
                    names.update(sfc_actions)
                    continue
                for attr_name, val in klass.__dict__.items():
                    # Only functions *defined in the class body* count. Imported helpers or classes
                    # assigned as attributes are never exposed.
                    if inspect.isfunction(val) and val.__qualname__ == f"{klass.__qualname__}.{attr_name}":
                        names.add(attr_name)

        allowed = frozenset(
            n
            for n in names
            if isinstance(n, str)
            and n
            and not n.startswith("_")
            and n not in _PROTECTED_COMPONENT_METHODS
            and not hasattr(Component, n)
        )
        setattr(cls, "_pyfusion_action_cache", allowed)
        return allowed

    def is_local_only_action(self, method_name: str) -> bool:
        if self.restrict_to_localhost:
            return True
        fn = getattr(self.__class__, method_name, None)
        return bool(getattr(fn, "__pyfusion_local_only__", False))

    def _computed_keys(self) -> Set[str]:
        comp_map = self.computed() if callable(getattr(self, "computed", None)) else getattr(self, "computed", {})
        return set(comp_map.keys()) if isinstance(comp_map, dict) else set()

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

    def hydrate(self, snapshot: Dict[str, Any]):
        """Restore a verified (server-signed) state snapshot without triggering watchers."""
        if not isinstance(snapshot, dict):
            return
        comp_keys = self._computed_keys()
        for k, v in snapshot.items():
            if k in comp_keys or k not in self.state:
                continue
            current = dict.get(self.state, k)
            if isinstance(current, Ref):
                current._value = v
            else:
                dict.__setitem__(self.state, k, v)

    def apply_client_updates(self, updates: Dict[str, Any]):
        """Apply browser-side edits (f-model) to unlocked, non-computed state keys (OWASP A01 mass-assignment guard)."""
        if not updates:
            return
        if not isinstance(updates, dict):
            raise ValueError("Invalid state updates payload")
        comp_keys = self._computed_keys()
        locked = set(self.locked or ())
        for k, v in updates.items():
            if not isinstance(k, str) or k.startswith("_") or k in comp_keys or k not in self.state:
                continue
            if k in locked:
                raise PermissionError(f"Property '{k}' is locked and cannot be modified by the client")
            self.state[k] = v

    def invoke_method(
        self,
        method_name: str,
        args: list = None,
        client_state: dict = None,
        snapshot: dict = None,
    ) -> Dict[str, Any]:
        """Hydrate verified state, apply allowed client updates, check the action allowlist (OWASP A01/A03) and invoke."""
        if not isinstance(method_name, str) or method_name not in self.public_actions():
            raise PermissionError(f"Access denied or unknown public action method '{method_name}'")

        method = getattr(self, method_name, None)
        if not callable(method) or isinstance(method, type):
            raise PermissionError(f"Attribute '{method_name}' is not a callable action")

        if args is None:
            args = []
        if not isinstance(args, list) or len(args) > MAX_RPC_ARGS:
            raise ValueError("Invalid RPC arguments")

        if snapshot:
            self.hydrate(snapshot)
        if client_state:
            self.apply_client_updates(client_state)

        method(*args)
        return self.get_full_state()

    def _load_raw_template(self) -> str:
        if self.template_file and os.path.exists(self.template_file):
            with open(self.template_file, "r", encoding="utf-8") as f:
                return f.read()
        return self.template

    def _render_child_components(
        self, html: str, registry: Dict[str, Type["Component"]], secret: Optional[str] = None
    ) -> str:
        all_components = dict(registry or {})
        all_components.update(self.components or {})

        for tag_name, comp_cls in all_components.items():
            pattern = re.compile(
                rf"<{tag_name}(\s+[^/>]*?)?\s*(?:/>|></{tag_name}>)",
                re.IGNORECASE | re.DOTALL,
            )

            def replace_tag(match, cls=comp_cls):
                attr_str = match.group(1) or ""
                parsed_props = dict(re.findall(r'([a-zA-Z0-9_-]+)=["\']([^"\']*)["\']', attr_str))
                child_instance = cls(**parsed_props)
                return child_instance.render_fragment(registry=all_components, secret=secret)

            html = pattern.sub(replace_tag, html)

        return html

    def render_fragment(self, registry: Dict[str, Type["Component"]] = None, secret: Optional[str] = None) -> str:
        secret = secret or _DEFAULT_STATE_SECRET
        self.before_mount()
        raw_html = self._load_raw_template().strip()
        raw_html = self._render_child_components(raw_html, registry or {}, secret=secret)

        full_state = self.get_full_state()
        computed_keys = sorted(self._computed_keys())

        state_raw = serialize_state(full_state)
        checksum = sign_state(self.component_name, state_raw, secret) if secret else ""
        state_json = escape_html(state_raw)
        computed_json = escape_html(json.dumps(computed_keys))

        style_block = ""
        if self.style:
            style_block = f"<style>{self.style}</style>\n"

        wrapper = (
            f"{style_block}"
            f'<div data-pyfusion-component="{escape_html(self.component_name)}" '
            f'data-pyfusion-state="{state_json}" '
            f'data-pyfusion-checksum="{escape_html(checksum)}" '
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
        secret: Optional[str] = None,
    ) -> str:
        page_title = escape_html(title or self.component_name)
        fragment = self.render_fragment(registry=registry, secret=secret)
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


def _discover_sfc_actions(script_code: str, file_path: str) -> FrozenSet[str]:
    """Return names of top-level ``def`` functions in an SFC <script> block (the RPC allowlist)."""
    try:
        tree = ast.parse(script_code, filename=file_path)
    except SyntaxError:
        return frozenset()
    return frozenset(node.name for node in tree.body if isinstance(node, ast.FunctionDef))


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
        "_sfc_actions": frozenset(),
    }

    if script_code:
        from .database import Field, FusionDB, Model
        from .security import hash_password, verify_password

        sfc_globals = {
            "Component": Component,
            "Model": Model,
            "Field": Field,
            "FusionDB": FusionDB,
            "hash_password": hash_password,
            "verify_password": verify_password,
            "escape_html": escape_html,
            "local_only": local_only,
            "json": json,
            "os": os,
        }
        # SFC scripts are trusted, developer-authored source code (equivalent to a .py module).
        exec(compile(script_code, file_path, "exec"), sfc_globals, namespace)  # nosec B102
        sfc_globals.update(namespace)
        namespace["_sfc_actions"] = _discover_sfc_actions(script_code, file_path)

    if isinstance(namespace.get("locked"), (list, tuple, frozenset)):
        namespace["locked"] = set(namespace["locked"])

    return type(inferred_name, (Component,), namespace)
