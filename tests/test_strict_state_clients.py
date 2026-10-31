# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict state is optional and owner-bound at the Qt client boundary."""
import asyncio
import os
from types import SimpleNamespace

import pytest
from dbus_fast.aio import MessageBus
pytest.importorskip("PySide6")
from PySide6.QtDBus import QDBusMessage

from idasen_companion import DBUS_NAME, DBUS_PATH
from idasen_companion.core.strict_state import StrictState
from idasen_companion.daemon.service import Automation1, Desk1
from idasen_companion.gui.dbus_client import DaemonClient
from machine_helpers import Driver, make_config
from test_strict_retry import daemon_for_driver
from test_position_observation_dbus import settle


@pytest.mark.asyncio
async def test_private_bus_initial_state_signal_and_owner_loss(qapp, monkeypatch):
    assert "/tmp/dbus-" in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    daemon = daemon_for_driver(driver)
    auto = Automation1(daemon)
    bus = await MessageBus().connect()
    bus.export(DBUS_PATH, auto)
    await bus.request_name(DBUS_NAME)
    monkeypatch.setattr(DaemonClient, "get_property", lambda *_: None)
    monkeypatch.setattr(DaemonClient, "list_presets", lambda *_: {})
    client = DaemonClient()
    try:
        await settle(qapp, lambda: client.strict_capability == "supported")
        assert client.strict_state == StrictState("standing", "released", None, None)
        auto.StrictStateChanged(StrictState("standing", "pending", "standing", 1.1).to_json())
        await settle(qapp, lambda: client.strict_state.stage == "pending")
        await bus.release_name(DBUS_NAME)
        await settle(qapp, lambda: client.strict_capability == "unknown")
        assert client.strict_state is None
    finally:
        client.deleteLater()
        bus.disconnect()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_old_private_bus_peer_keeps_ordinary_refresh(qapp, monkeypatch):
    assert "/tmp/dbus-" in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    driver = Driver(make_config())
    await driver.start()
    daemon = daemon_for_driver(driver)
    bus = await MessageBus().connect()
    bus.export(DBUS_PATH, Desk1(daemon))
    await bus.request_name(DBUS_NAME)
    monkeypatch.setattr(DaemonClient, "get_property", lambda _self, _iface, name:
                        "active" if name == "Status" else None)
    monkeypatch.setattr(DaemonClient, "list_presets", lambda *_: {})
    client = DaemonClient()
    statuses = []
    client.statusChanged.connect(statuses.append)
    try:
        client.refresh_all()
        await settle(qapp, lambda: client.strict_capability == "unsupported")
        assert client.strict_state is None
        assert statuses == ["active"]
    finally:
        client.deleteLater()
        bus.disconnect()
        await asyncio.sleep(0)


def test_late_read_and_obsolete_sender_cannot_overwrite(qapp, monkeypatch):
    from idasen_companion.gui import dbus_client
    monkeypatch.setattr(DaemonClient, "_ping", lambda *_: False)
    client = DaemonClient()
    callbacks = []
    class Watcher:
        def __init__(self, *_args):
            self.finished = SimpleNamespace(connect=callbacks.append)
        def reply(self):
            reply = QDBusMessage.createMethodCall("x.y", "/x", "x.y", "x")
            result = reply.createReply([StrictState("off", "released", None, None).to_json()])
            return result
        def deleteLater(self):
            pass
    monkeypatch.setattr(dbus_client, "QDBusPendingCallWatcher", Watcher)
    client._strict_owner = ":1.1"
    client._refresh_strict_state()
    signal = SimpleNamespace(service=lambda: ":1.1", arguments=lambda: [
        StrictState("standing", "pending", "standing", 1.1).to_json()])
    client._on_strict_state(signal)
    callbacks.pop()(Watcher())
    assert client.strict_state.stage == "pending"
    client._refresh_strict_state()
    monkeypatch.setattr(client, "_refresh_position_observation", lambda: None)
    monkeypatch.setattr(client, "_refresh_strict_state", lambda: None)
    client._on_observation_owner_changed(DBUS_NAME, ":1.1", ":1.2")
    callbacks.pop()(Watcher())
    client._on_strict_state(signal)
    assert client.strict_state is None
    assert client.strict_capability == "unknown"
    client.deleteLater()
