# SPDX-License-Identifier: GPL-3.0-or-later
"""The daemon's public wire contract and its GUI/CLI consumers.

Full frozen introspection protects exported names, argument names/directions,
signatures and read-only access across all five interfaces. Real compound
signal dispatch also protects flat payload order at dbus-fast's notifier.
Client scans keep the GUI and CLI member strings aligned with that contract.
"""

import ast
from pathlib import Path
from unittest.mock import MagicMock
import xml.etree.ElementTree as ET

import pytest
from dbus_fast.service import ServiceInterface

from idasen_companion import DBUS_NAME
from idasen_companion import cli
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

# Frozen public contract; expectations are independent of the declarations.
EXPECTED_INTERFACE_XML = {
    "Desk1": (
        '<interface name="io.github.extricator.IdasenCompanion.Desk1">'
        '<method name="Discover">'
        '<arg name="timeout" direction="in" type="i" />'
        '<arg direction="out" type="s" />'
        '</method>'
        '<method name="GestureMove">'
        '<arg name="action" direction="in" type="s" />'
        '</method>'
        '<method name="GetPositionObservation">'
        '<arg direction="out" type="s" />'
        '<arg direction="out" type="b" />'
        '<arg direction="out" type="d" />'
        '<arg direction="out" type="d" />'
        '<arg direction="out" type="d" />'
        '</method>'
        '<method name="MoveToHeight">'
        '<arg name="height" direction="in" type="d" />'
        '</method>'
        '<method name="MoveToPreset">'
        '<arg name="name" direction="in" type="s" />'
        '</method>'
        '<method name="Setup">'
        '<arg name="mac" direction="in" type="s" />'
        '<arg direction="out" type="d" />'
        '</method>'
        '<method name="Sit" />'
        '<method name="Stand" />'
        '<method name="Stop" />'
        '<method name="Toggle" />'
        '<signal name="ConnectedChanged">'
        '<arg direction="out" type="b" />'
        '</signal>'
        '<signal name="HeightChanged">'
        '<arg direction="out" type="d" />'
        '</signal>'
        '<signal name="MovingChanged">'
        '<arg direction="out" type="b" />'
        '</signal>'
        '<signal name="PositionChanged">'
        '<arg direction="out" type="s" />'
        '</signal>'
        '<signal name="PositionObservationChanged">'
        '<arg direction="out" type="s" />'
        '<arg direction="out" type="b" />'
        '<arg direction="out" type="d" />'
        '<arg direction="out" type="d" />'
        '<arg direction="out" type="d" />'
        '</signal>'
        '<property name="Connected" type="b" access="read" />'
        '<property name="Height" type="d" access="read" />'
        '<property name="Moving" type="b" access="read" />'
        '<property name="Position" type="s" access="read" />'
        '</interface>'
    ),
    "Automation1": (
        '<interface name="io.github.extricator.IdasenCompanion.Automation1">'
        '<method name="Pause" />'
        '<method name="ReloadConfig" />'
        '<method name="Resume" />'
        '<method name="SetEnabled">'
        '<arg name="enabled" direction="in" type="b" />'
        '</method>'
        '<method name="SkipNext" />'
        '<method name="Snooze">'
        '<arg name="minutes" direction="in" type="i" />'
        '</method>'
        '<signal name="PreMoveWarning">'
        '<arg direction="out" type="s" />'
        '<arg direction="out" type="u" />'
        '</signal>'
        '<signal name="ProgressChanged">'
        '<arg direction="out" type="d" />'
        '<arg direction="out" type="d" />'
        '</signal>'
        '<signal name="StatusChanged">'
        '<arg direction="out" type="s" />'
        '</signal>'
        '<signal name="StrictStateChanged">'
        '<arg direction="out" type="s" />'
        '</signal>'
        '<signal name="TransitionCompleted">'
        '<arg direction="out" type="s" />'
        '<arg direction="out" type="s" />'
        '<arg direction="out" type="b" />'
        '</signal>'
        '<property name="ActiveTime" type="d" access="read" />'
        '<property name="Enabled" type="b" access="read" />'
        '<property name="IdleProvider" type="s" access="read" />'
        '<property name="SkipNextPending" type="b" access="read" />'
        '<property name="SnoozeUntil" type="d" access="read" />'
        '<property name="Status" type="s" access="read" />'
        '<property name="StrictState" type="s" access="read" />'
        '<property name="TargetDuration" type="d" access="read" />'
        '<property name="TimeRemaining" type="d" access="read" />'
        '</interface>'
    ),
    "Presets1": (
        '<interface name="io.github.extricator.IdasenCompanion.Presets1">'
        '<method name="CaptureCurrent">'
        '<arg name="name" direction="in" type="s" />'
        '<arg direction="out" type="d" />'
        '</method>'
        '<method name="Delete">'
        '<arg name="name" direction="in" type="s" />'
        '</method>'
        '<method name="List">'
        '<arg direction="out" type="s" />'
        '</method>'
        '<method name="Rename">'
        '<arg name="old" direction="in" type="s" />'
        '<arg name="new" direction="in" type="s" />'
        '</method>'
        '<method name="Save">'
        '<arg name="name" direction="in" type="s" />'
        '<arg name="height" direction="in" type="d" />'
        '</method>'
        '<signal name="PresetsChanged">'
        '<arg direction="out" type="s" />'
        '</signal>'
        '</interface>'
    ),
    "Stats1": (
        '<interface name="io.github.extricator.IdasenCompanion.Stats1">'
        '<method name="GetDaily">'
        '<arg name="start" direction="in" type="s" />'
        '<arg name="end" direction="in" type="s" />'
        '<arg direction="out" type="s" />'
        '</method>'
        '<method name="GetTransitions">'
        '<arg name="limit" direction="in" type="i" />'
        '<arg direction="out" type="s" />'
        '</method>'
        '</interface>'
    ),
    "Log1": (
        '<interface name="io.github.extricator.IdasenCompanion.Log1">'
        '<method name="GetRecent">'
        '<arg direction="out" type="s" />'
        '</method>'
        '<signal name="Entry">'
        '<arg direction="out" type="d" />'
        '<arg direction="out" type="s" />'
        '<arg direction="out" type="s" />'
        '<arg direction="out" type="s" />'
        '<arg direction="out" type="s" />'
        '<arg direction="out" type="s" />'
        '</signal>'
        '</interface>'
    ),
}

COMPOUND_SIGNAL_CASES = [
    (service_mod.Automation1, "ProgressChanged", (1.25, 7.5), "dd"),
    (service_mod.Automation1, "PreMoveWarning", ("standing", 45), "su"),
    (service_mod.Automation1, "TransitionCompleted",
     ("sitting", "standing", True), "ssb"),
    (service_mod.Log1, "Entry",
     (123.5, "info", "activity", "event.id", "{}", "message"), "dsssss"),
    (service_mod.Desk1, "PositionObservationChanged",
     ("standing", True, 0.0, 1.25, 388.75), "sbddd"),
]


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
        if name == "createMethodCall" and len(node.args) == 4:
            iface, member = node.args[2:]
            if (isinstance(iface, ast.Name) and iface.id in INTERFACES
                    and isinstance(member, ast.Constant) and isinstance(member.value, str)):
                found.append((iface.id, member.value, "method", node.lineno))
            continue
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


def test_observation_method_and_signal_are_in_the_client_scan():
    references = {(iface, member, kind) for iface, member, kind, _ in client_references()}
    assert ("IFACE_DESK", "GetPositionObservation", "method") in references
    assert ("IFACE_DESK", "PositionObservationChanged", "signal") in references


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


@pytest.mark.parametrize("name,expected_xml", EXPECTED_INTERFACE_XML.items())
def test_every_exported_interface_matches_frozen_xml(name, expected_xml):
    interface = getattr(service_mod, name)(MagicMock())
    actual_xml = ET.tostring(interface.introspect().to_xml(), encoding="unicode")
    assert actual_xml == expected_xml


@pytest.mark.parametrize("cls,member,payload,signature", COMPOUND_SIGNAL_CASES)
def test_compound_signal_notifies_flat_payload(cls, member, payload, signature):
    interface = cls(MagicMock())
    bus = MagicMock()
    ServiceInterface._get_buses(interface).add(bus)

    getattr(interface, member)(*payload)

    bus._interface_signal_notify.assert_called_once()
    notification = bus._interface_signal_notify.call_args.args
    assert notification[3:] == (signature, list(payload), [])


def test_every_cli_member_exists_on_the_daemon():
    expected = {
        service_mod.Desk1: {
            "properties": {"Connected", "Height", "Position", "Moving"},
            "methods": {"Sit", "Stand", "Toggle", "Stop", "MoveToPreset"},
        },
        service_mod.Automation1: {
            "properties": {"Status", "ActiveTime", "TimeRemaining", "SnoozeUntil"},
            "methods": set(),
        },
        service_mod.Stats1: {"properties": set(), "methods": {"GetDaily"}},
        service_mod.Log1: {"properties": set(), "methods": {"GetRecent"}},
    }
    assert {
        cli.IFACE_DESK, cli.IFACE_AUTO, cli.IFACE_STATS, cli.IFACE_LOG,
    } == {cls(MagicMock()).name for cls in expected}
    for cls, wanted in expected.items():
        methods, properties, _signals = members_of(cls)
        assert wanted["methods"] <= methods
        assert wanted["properties"] <= properties
def test_gui_length_commands_and_success_envelopes_stay_scalar(monkeypatch):
    pytest.importorskip("idasen_companion.gui")
    pytest.importorskip("PySide6")
    from types import SimpleNamespace
    from idasen_companion.core.lengths import Length
    from idasen_companion.gui import dbus_client

    sent = []
    client = SimpleNamespace(_async_call=lambda *args: sent.append(args))
    dbus_client.DaemonClient.move_to_height(client, Length(0.90123))
    dbus_client.DaemonClient.save_preset(client, "custom", Length(0.90123))
    assert sent == [
        (dbus_client.IFACE_DESK, "MoveToHeight", 0.90123),
        (dbus_client.IFACE_PRESETS, "Save", "custom", 0.90123),
    ]
    assert all(type(args[-1]) is float for args in sent)

    reply = SimpleNamespace(errorMessage=lambda: "read failed")
    iface = SimpleNamespace(setTimeout=lambda value: None, call=lambda *args: reply)
    client._iface = lambda name: iface
    values = [0.75]
    monkeypatch.setattr(dbus_client, "_reply_args", lambda message: values)
    assert dbus_client.DaemonClient.setup(client, "mock") == (True, 0.75)
    assert dbus_client.DaemonClient.capture_preset(client, "custom") == (True, 0.75)
    values.clear()
    assert dbus_client.DaemonClient.setup(client, "mock") == (False, "read failed")
    assert dbus_client.DaemonClient.capture_preset(client, "custom") == (False, "read failed")
