# SPDX-License-Identifier: GPL-3.0-or-later
"""Observed samples cross a private bus and age independently of active credit."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dbus_fast.aio import MessageBus
from dbus_fast.service import dbus_method

from idasen_companion import DBUS_NAME, DBUS_PATH
from idasen_companion.core.config import AppConfig
from idasen_companion.core.lengths import Length
from idasen_companion.core.machine import StateMachine
from idasen_companion.core.clocks import WallInstant
from idasen_companion.daemon.main import Daemon
from idasen_companion.daemon.service import Desk1, PositionObservationPayload
from idasen_companion.gui.dbus_client import DaemonClient
from idasen_companion.gui import dbus_client as client_mod
from idasen_companion.daemon import main as daemon_mod
from test_tray_tooltip import _make_tray
from test_daemon_emit import observed_daemon


async def settle(qapp, predicate):
    for _ in range(200):
        qapp.processEvents()
        if predicate():
            return
        await asyncio.sleep(0.005)
    assert predicate(), "private D-Bus delivery timed out"


@pytest.mark.asyncio
async def test_real_sample_reaches_tray_without_active_credit(qapp, monkeypatch):
    assert "/tmp/dbus-" in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    clock = SimpleNamespace(wall=1000.0, mono=10.0)
    fake_time = SimpleNamespace(time=lambda: clock.wall, monotonic=lambda: clock.mono)
    monkeypatch.setattr(daemon_mod, "time", fake_time)
    monkeypatch.setattr(client_mod, "time", fake_time, raising=False)
    daemon = Daemon.__new__(Daemon)
    daemon.config = AppConfig()
    daemon.machine = StateMachine(daemon.config, MagicMock(), now=WallInstant(clock.wall))
    daemon.moving = False
    daemon.desk_connected = True
    daemon._ifaces = {}
    from idasen_companion.core.clocks import MonotonicInstant
    daemon._last_height_emit = MonotonicInstant(0)
    desk = Desk1(daemon)
    daemon._ifaces["desk"] = desk
    bus = await MessageBus().connect()
    bus.export(DBUS_PATH, desk)
    await bus.request_name(DBUS_NAME)
    # Legacy synchronous getters are outside this tracer and would block the
    # asyncio service thread. The new async snapshot and live signals are real.
    monkeypatch.setattr(DaemonClient, "get_property", lambda *_: None)
    monkeypatch.setattr(DaemonClient, "list_presets", lambda *_: {})
    client = DaemonClient()
    client.available = False
    tray_fixture = _make_tray(client)
    tray, _ = next(tray_fixture)
    try:
        tray._on_position("sitting")
        tray._on_status("paused")
        tray._on_progress(600.0, 1800.0)
        daemon._on_live_height(Length(daemon.config.presets["sit"]))
        await settle(qapp, lambda: "for about 0s" in tray._tooltip_lines()[0])
        clock.wall += 20
        clock.mono += 20
        tray._tick()
        assert "for about 20s" in tray._tooltip_lines()[0]
        daemon._on_live_height(Length(daemon.config.presets["sit"]))
        await settle(qapp, lambda: client.position_observation_elapsed("sitting").seconds == 20)
        client.refresh_all()
        await settle(qapp, lambda: client.position_observation_elapsed("sitting").seconds == 20)
        daemon._on_live_height(Length(daemon.config.presets["stand"]))
        tray._on_position("standing")
        await settle(qapp, lambda: "for about 0s" in tray._tooltip_lines()[0])
    finally:
        next(tray_fixture, None)
        client.deleteLater()
        bus.disconnect()
        await asyncio.sleep(0)


class DelayedDesk(Desk1):
    def __init__(self, daemon):
        super().__init__(daemon)
        self.entered = asyncio.Event()
        self.complete = asyncio.Event()
        self.returned = asyncio.Event()

    @dbus_method()
    async def GetPositionObservation(self) -> PositionObservationPayload:
        snapshot = self.d.position_observation_snapshot()
        self.entered.set()
        await self.complete.wait()
        self.returned.set()
        return snapshot


@pytest.mark.asyncio
async def test_new_signal_and_owner_loss_supersede_delayed_reply(qapp, monkeypatch):
    assert "/tmp/dbus-" in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    daemon, clock = observed_daemon(monkeypatch)
    monkeypatch.setattr(client_mod, "time", SimpleNamespace(
        time=lambda: clock.wall, monotonic=lambda: clock.mono))
    monkeypatch.setattr(DaemonClient, "_ping", lambda *_: False)
    monkeypatch.setattr(DaemonClient, "get_property", lambda *_: None)
    monkeypatch.setattr(DaemonClient, "list_presets", lambda *_: {})
    desk = DelayedDesk(daemon)
    daemon._ifaces["desk"] = desk
    daemon._on_live_height(Length(daemon.config.presets["sit"]))
    bus = await MessageBus().connect()
    bus.export(DBUS_PATH, desk)
    await bus.request_name(DBUS_NAME)
    client = DaemonClient()
    try:
        client._refresh_position_observation()
        await settle(qapp, desk.entered.is_set)
        daemon._on_live_height(Length(daemon.config.presets["stand"]))
        await settle(qapp, lambda: client.position_observation_elapsed("standing") is not None)
        desk.complete.set()
        await settle(qapp, desk.returned.is_set)
        for _ in range(5):
            qapp.processEvents()
            await asyncio.sleep(0.005)
        assert client.position_observation_elapsed("standing").seconds == 0
        assert client.position_observation_elapsed("sitting") is None

        desk.entered.clear()
        desk.complete.clear()
        desk.returned.clear()
        client._refresh_position_observation()
        await settle(qapp, desk.entered.is_set)
        await bus.release_name(DBUS_NAME)
        await settle(qapp, lambda: client._position_observation is None)
        desk.complete.set()
        await settle(qapp, desk.returned.is_set)
        for _ in range(5):
            qapp.processEvents()
            await asyncio.sleep(0.005)
        assert client.position_observation_elapsed("standing") is None
    finally:
        desk.complete.set()
        client.deleteLater()
        bus.disconnect()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_old_peer_keeps_position_and_commands_without_duration(qapp, monkeypatch):
    from dbus_fast import Message
    from dbus_fast.constants import MessageType
    from test_cli_integration import Desk

    assert "/tmp/dbus-" in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    monkeypatch.setattr(DaemonClient, "get_property", lambda *_: None)
    monkeypatch.setattr(DaemonClient, "list_presets", lambda *_: {})
    calls = []
    bus = await MessageBus().connect()
    bus.export(DBUS_PATH, Desk(calls))
    await bus.request_name(DBUS_NAME)
    client = DaemonClient()
    positions = []
    client.positionChanged.connect(positions.append)
    try:
        client.refresh_all()
        await bus.send(Message(message_type=MessageType.SIGNAL, path=DBUS_PATH,
                               interface=client_mod.IFACE_DESK, member="PositionChanged",
                               signature="s", body=["standing"]))
        await settle(qapp, lambda: positions == ["standing"])
        assert client.position_observation_elapsed("standing") is None
        client.gesture_move("toggle")
        client.stop()
        await settle(qapp, lambda: calls == ["toggle", "stop"])
        assert client.available
    finally:
        client.deleteLater()
        bus.disconnect()
        await asyncio.sleep(0)


@pytest.mark.parametrize("payload", [
    ["sitting", True, 0.0, 0.0],  # incomplete flat tuple
    ["sitting", 1, 0.0, 0.0, 30.0],  # knownness is not a number
    ["sitting", True, 0, 0.0, 30.0],  # explicit doubles only
    ["sitting", True, 0.0, float("nan"), 30.0],
    ["sitting", True, 0.0, -1.0, 30.0],
    ["sitting", True, 0.0, 0.0, 0.0],  # exact expiry
    ["custom", True, 0.0, 0.0, 30.0],
    ["sitting", False, 0.0, 0.0, 30.0],
])
def test_malformed_or_unknown_observation_has_no_duration(payload):
    assert DaemonClient._decode_position_observation(payload) is None


@pytest.mark.parametrize("wall_step,mono_step,known", [
    (300, 1, True), (300, 30, False), (301, 1, False), (-1, 1, False),
])
def test_gui_cache_expires_and_drops_wall_discontinuity(
        qapp, monkeypatch, wall_step, mono_step, known):
    clock = SimpleNamespace(wall=1000.0, mono=0.0)
    monkeypatch.setattr(client_mod, "time", SimpleNamespace(
        time=lambda: clock.wall, monotonic=lambda: clock.mono))
    monkeypatch.setattr(DaemonClient, "_ping", lambda *_: False)
    client = DaemonClient()
    try:
        client._cache_position_observation(["sitting", True, 0.0, 0.0, 30.0])
        assert client.position_observation_elapsed("sitting").seconds == 0.0
        assert client.position_observation_elapsed("standing") is None
        clock.wall += wall_step
        clock.mono += mono_step
        assert (client.position_observation_elapsed("sitting") is not None) is known
    finally:
        client.deleteLater()
