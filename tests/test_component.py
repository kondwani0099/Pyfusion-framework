import json

import pytest

from fusionlib.component import Component, load_sfc, local_only


def _counter(project_dir):
    return load_sfc(str(project_dir / "web" / "components" / "Counter.fusion"))


def test_sfc_action_allowlist(project_dir):
    cls = _counter(project_dir)
    actions = cls.public_actions()
    assert {"increment", "echo_greeting"} <= actions
    # Lifecycle hooks, private helpers and imported callables are never exposed
    for forbidden in ("data", "computed", "_private_helper", "helper_imported", "render_page", "invoke_method"):
        assert forbidden not in actions


def test_invoke_rejects_non_actions(project_dir):
    comp = _counter(project_dir)()
    for name in ("_private_helper", "helper_imported", "render_page", "__init__", "nope"):
        with pytest.raises(PermissionError):
            comp.invoke_method(name)


def test_locked_props_cannot_be_modified(project_dir):
    comp = _counter(project_dir)()
    with pytest.raises(PermissionError):
        comp.invoke_method("increment", client_state={"count": 1000})


def test_unlocked_updates_and_hydration(project_dir):
    comp = _counter(project_dir)()
    state = comp.invoke_method(
        "echo_greeting",
        snapshot={"count": 7, "greeting": "hi", "role": "user", "doubled": 999},
        client_state={"greeting": "hello", "unknown_key": "x", "doubled": 5},
    )
    assert state["count"] == 7  # hydrated from signed snapshot
    assert state["role"] == "echo:hello"  # unlocked update applied
    assert state["doubled"] == 14  # computed recomputed, never client-controlled
    assert "unknown_key" not in state


def test_rpc_args_validated(project_dir):
    comp = _counter(project_dir)()
    with pytest.raises(ValueError):
        comp.invoke_method("increment", args="not-a-list")
    with pytest.raises(ValueError):
        comp.invoke_method("increment", args=list(range(100)))


def test_render_fragment_is_signed(project_dir):
    comp = _counter(project_dir)()
    html = comp.render_fragment(secret="s3cret")
    assert 'data-pyfusion-checksum="' in html
    assert 'data-pyfusion-checksum=""' not in html


def test_class_component_allowlist_excludes_imported_functions():
    def external(self):
        return "should not be callable"

    class Widget(Component):
        borrowed = external

        def data(self):
            return {"n": 0}

        def bump(self):
            self.state.n += 1

        @local_only
        def wipe_disk(self):
            pass

    assert Widget.public_actions() == frozenset({"bump", "wipe_disk"})
    w = Widget()
    assert w.is_local_only_action("wipe_disk")
    assert not w.is_local_only_action("bump")
    assert w.invoke_method("bump")["n"] == 1


def test_declared_props_filter(project_dir):
    cls = _counter(project_dir)
    assert cls.declared_props({"title": "x", "count": 99, "is_admin": True}) == {"title": "x"}


def test_state_serialization_is_json(project_dir):
    comp = _counter(project_dir)()
    from fusionlib.component import serialize_state

    raw = serialize_state(comp.get_full_state())
    assert json.loads(raw)["doubled"] == 0
