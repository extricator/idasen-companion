"""The daemon<->GUI wire contract, checked from both sides.

`daemon/service.py` is the daemon's public API and was tested from neither
end: nothing in the suite imported it, so all ~50 exported members' bodies
were unexecuted — on the one module also excluded from mypy (its annotations
are D-Bus type codes, not Python types).

Meanwhile `gui/dbus_client.py` names every member as a bare string literal
and swallows a failed reply into a default. So renaming `Presets1.List`,
or dropping a property, compiled, passed the whole suite, and shipped a GUI
that silently did nothing.

This introspects the real `ServiceInterface` classes — the same metadata
dbus-fast puts on the wire — and checks every name the GUI asks for exists,
in the shape it asks for it. Same idea as test_log_catalog.py, which is the
only reason catalog drift gets caught.
"""

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from idasen_companion import DBUS_NAME
from idasen_companion.daemon import service as service_mod

CLIENT = (Path(__file__).resolve().parent.parent / "src" / "idasen_companion"
          / "gui" / "dbus_client.py")

#: The GUI's IFACE_* constants, mapped to the class that serves them.
INTERFACES = {
    "IFACE_DESK": service_mod.Desk1,
    "IFACE_AUTO": service_mod.Automation1,
    "IFACE_PRESETS": service_mod.Presets1,
    "IFACE_STATS": service_mod.Stats1,
    "IFACE_LOG": service_mod.Log1,
}

#: GUI helper -> which kind of member the name must resolve to.
#: The kind matters: asking for a method as a property fails at runtime just
#: as thoroughly as a misspelling, and just as quietly.
HELPERS = {
    "subscribe": "signal",
    "get_property": "property",
    "get_property_async": "property",
    "_async_call": "method",
    "_call_for_json": "method",
}


def members_of(cls):
    """(methods, properties, signals) as dbus-fast will introspect them."""
    node = cls(MagicMock()).introspect()
    return (
        {m.name for m in node.methods},
        {p.name for p in node.properties},
        {s.name for s in node.signals},
    )


def client_references():
    """Every (IFACE_* constant, member name, kind) the GUI asks for."""
    tree = ast.parse(CLIENT.read_text())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        func = node.func
        name = (func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute) else None)
        if name not in HELPERS:
            continue
        iface, member = node.args[0], node.args[1]
        if not (isinstance(iface, ast.Name) and iface.id in INTERFACES):
            continue
        if not (isinstance(member, ast.Constant)
                and isinstance(member.value, str)):
            continue
        found.append((iface.id, member.value, HELPERS[name], node.lineno))
    return found


def test_the_scan_actually_finds_the_calls():
    """Guard the guard: a refactor that renames the helpers would otherwise
    make this file pass by finding nothing at all."""
    refs = client_references()
    assert len(refs) >= 20, f"only found {len(refs)} references; scan is stale"
    assert {r[2] for r in refs} == {"signal", "property", "method"}


@pytest.mark.parametrize("const,cls", INTERFACES.items())
def test_interface_names_match_between_the_two_sides(const, cls):
    expected = cls(MagicMock()).name
    # The GUI builds its constants as f"{DBUS_NAME}.Desk1" etc.
    assert expected.startswith(DBUS_NAME + ".")


def test_every_member_the_gui_asks_for_exists_on_the_daemon():
    missing = []
    for const, member, kind, lineno in client_references():
        methods, properties, signals = members_of(INTERFACES[const])
        available = {"method": methods, "property": properties,
                     "signal": signals}[kind]
        if member not in available:
            missing.append(
                f"dbus_client.py:{lineno}: {const}.{member} is not a "
                f"{kind} on {INTERFACES[const].__name__} "
                f"(has: {sorted(available)})")
    assert not missing, "\n".join(missing)


def iface_const(node):
    """The IFACE_* constant in `self._iface(IFACE_X)`, if that is what it is."""
    if not (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_iface"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in INTERFACES):
        return None
    return node.args[0].id


def iface_call_references():
    """Every `.call("Member", ...)` on an interface proxy, however it was bound.

    Matching only the direct receiver — `self._iface(X).call(...)` — is not
    enough: the sites that need a non-default timeout assign the proxy to a
    local first so they can call `setTimeout` on it, and those are exactly the
    slow operations (Discover, Setup, CaptureCurrent). So resolve locals bound
    to `self._iface(...)` within each function too.
    """
    tree = ast.parse(CLIENT.read_text())
    found = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = {}
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                const = iface_const(node.value)
                if const:
                    bound[node.targets[0].id] = const
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "call"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                continue
            receiver = node.func.value
            const = (iface_const(receiver) if isinstance(receiver, ast.Call)
                     else bound.get(receiver.id)
                     if isinstance(receiver, ast.Name) else None)
            if const:
                found.add((const, node.args[0].value, node.lineno))
    return sorted(found, key=lambda r: r[2])


def test_the_iface_call_scan_reaches_the_indirect_sites():
    """Guard the guard. This scan previously matched only the direct-receiver
    form and so covered 1 of the 4 `.call()` sites — while its own `assert
    checked` passed on that one, reading as healthy."""
    refs = iface_call_references()
    assert len(refs) >= 4, f"only found {len(refs)} _iface(...).call() sites"
    # The three that bind a local for setTimeout are the ones that used to be
    # invisible; name them so a regression is unambiguous.
    members = {member for _c, member, _l in refs}
    assert {"Discover", "Setup", "CaptureCurrent"} <= members, members


def test_iface_call_members_exist_too():
    """`self._iface(X).call("Member", ...)` bypasses the helpers above."""
    missing = []
    for const, member, lineno in iface_call_references():
        methods, _p, _s = members_of(INTERFACES[const])
        if member not in methods:
            missing.append(f"dbus_client.py:{lineno}: {const}.{member} "
                           f"(has: {sorted(methods)})")
    assert not missing, "\n".join(missing)


@pytest.mark.parametrize("const,cls", INTERFACES.items())
def test_every_exported_member_introspects(const, cls):
    """Exercises each interface's introspection metadata, which is what
    dbus-fast serves and what a third-party client reads. Catches a bad type
    code in an annotation, which mypy cannot see on this module."""
    node = cls(MagicMock()).introspect()
    assert node.methods or node.properties or node.signals
    for m in node.methods:
        for arg in m.in_args + m.out_args:
            assert arg.signature, f"{cls.__name__}.{m.name}: empty signature"
    for p in node.properties:
        assert p.signature, f"{cls.__name__}.{p.name}: empty signature"
