"""Vue.js-inspired reactivity, state management (Pinia/Vuex style), and plugin architecture for PyFusion."""

from typing import Any, Callable, Dict, List


class Ref:
    """Reactive reference similar to Vue's ref()."""

    def __init__(self, value: Any = None):
        self._value = value
        self._subscribers: List[Callable[[Any, Any], None]] = []

    @property
    def value(self) -> Any:
        return self._value

    @value.setter
    def value(self, new_val: Any):
        old_val = self._value
        if old_val != new_val:
            self._value = new_val
            for sub in list(self._subscribers):
                sub(new_val, old_val)

    def subscribe(self, callback: Callable[[Any, Any], None]):
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def to_primitive(self):
        return self._value

    def __repr__(self):
        return f"Ref({self._value!r})"


def ref(initial_value: Any = None) -> Ref:
    """Create a reactive reference (like Vue's ref())."""
    return Ref(initial_value)


class ReactiveDict(dict):
    """Reactive dictionary that notifies watchers when keys are mutated (like Vue's reactive())."""

    def __init__(self, initial_data: Dict[str, Any] = None, on_change: Callable[[str, Any, Any], None] = None):
        super().__init__(initial_data or {})
        self._on_change = on_change
        self._watchers: Dict[str, List[Callable[[Any, Any], None]]] = {}

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            return super().__getattribute__(key)
        try:
            val = self[key]
            return val.value if isinstance(val, Ref) else val
        except KeyError:
            raise AttributeError(f"Reactive state has no property '{key}'")

    def __setattr__(self, key: str, value: Any):
        if key.startswith("_"):
            super().__setattr__(key, value)
        else:
            self[key] = value

    def __setitem__(self, key: str, value: Any):
        old_val = self.get(key, None)
        if isinstance(old_val, Ref) and not isinstance(value, Ref):
            old_raw = old_val.value
            old_val.value = value
            self._notify(key, value, old_raw)
            return

        super().__setitem__(key, value)
        if old_val != value:
            self._notify(key, value, old_val)

    def _notify(self, key: str, new_val: Any, old_val: Any):
        if self._on_change:
            self._on_change(key, new_val, old_val)
        for cb in self._watchers.get(key, []):
            cb(new_val, old_val)

    def watch(self, key: str, callback: Callable[[Any, Any], None]):
        self._watchers.setdefault(key, []).append(callback)

    def to_dict(self) -> Dict[str, Any]:
        result = {}
        for k, v in self.items():
            if isinstance(v, Ref):
                result[k] = v.value
            elif isinstance(v, ReactiveDict):
                result[k] = v.to_dict()
            else:
                result[k] = v
        return result


def reactive(data: Dict[str, Any], on_change: Callable[[str, Any, Any], None] = None) -> ReactiveDict:
    """Create a reactive state dictionary (like Vue's reactive())."""
    return ReactiveDict(data, on_change=on_change)


class FusionStore:
    """Pinia / Vuex-inspired reactive store that can be shared across components and pages."""

    def __init__(
        self,
        store_id: str,
        state: Callable[[], Dict[str, Any]] = None,
        getters: Dict[str, Callable[[ReactiveDict], Any]] = None,
        actions: Dict[str, Callable[..., Any]] = None,
    ):
        self.id = store_id
        initial_state = state() if callable(state) else (state or {})
        self.state = reactive(initial_state)
        self._getters = getters or {}
        self._actions = actions or {}

        for action_name, action_fn in self._actions.items():
            setattr(self, action_name, self._bind_action(action_fn))

    def _bind_action(self, fn):
        def bound(*args, **kwargs):
            return fn(self.state, *args, **kwargs)

        return bound

    def get(self, getter_name: str) -> Any:
        if getter_name in self._getters:
            return self._getters[getter_name](self.state)
        return self.state.get(getter_name)

    def snapshot(self) -> Dict[str, Any]:
        data = self.state.to_dict()
        for name, getter_fn in self._getters.items():
            try:
                data[name] = getter_fn(self.state)
            except Exception:
                pass
        return data


def define_store(
    store_id: str,
    state: Callable[[], Dict[str, Any]] = None,
    getters: Dict[str, Callable[[ReactiveDict], Any]] = None,
    actions: Dict[str, Callable[..., Any]] = None,
) -> FusionStore:
    """Define a reactive store (similar to Pinia's defineStore())."""
    return FusionStore(store_id=store_id, state=state, getters=getters, actions=actions)


class FusionPlugin:
    """Base class for building extensible plugins on top of PyFusion (used via app.use(plugin))."""

    name: str = "FusionPlugin"

    def install(self, app, **options):
        """Called when app.use(plugin, **options) is invoked."""
        raise NotImplementedError("Plugins must implement install(app, **options)")
