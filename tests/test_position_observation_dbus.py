# SPDX-License-Identifier: GPL-3.0-or-later
"""Observed samples cross a private bus and age independently of active credit."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dbus_fast.aio import MessageBus

from idasen_companion import DBUS_NAME, DBUS_PATH
from idasen_companion.core.config import AppConfig
from idasen_companion.core.lengths import Length
from idasen_companion.core.machine import StateMachine
from idasen_companion.core.clocks import WallInstant
from idasen_companion.daemon.main import Daemon
from idasen_companion.daemon.service import Desk1
from idasen_companion.gui.dbus_client import DaemonClient
from idasen_companion.gui import dbus_client as client_mod
from idasen_companion.daemon import main as daemon_mod
from test_tray_tooltip import _make_tray


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
        await settle(qapp, lambda: "for 0s" in tray._tooltip_lines()[0])
        clock.wall += 20
        clock.mono += 20
        tray._tick()
        assert "for 20s" in tray._tooltip_lines()[0]
        daemon._on_live_height(Length(daemon.config.presets["sit"]))
        await settle(qapp, lambda: client.position_observation_elapsed("sitting").seconds == 20)
        client.refresh_all()
        await settle(qapp, lambda: client.position_observation_elapsed("sitting").seconds == 20)
        daemon._on_live_height(Length(daemon.config.presets["stand"]))
        tray._on_position("standing")
        await settle(qapp, lambda: "for 0s" in tray._tooltip_lines()[0])
    finally:
        next(tray_fixture, None)
        client.deleteLater()
        bus.disconnect()
        await asyncio.sleep(0)
