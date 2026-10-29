# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict feedback follows the daemon and never strands a physical escape."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dbus_fast.aio import MessageBus
from PySide6.QtWidgets import QPushButton

from idasen_companion import DBUS_NAME, DBUS_PATH
from idasen_companion.daemon.service import Automation1, Desk1
from idasen_companion.gui.dbus_client import DaemonClient
from idasen_companion.gui.pages.overview import OverviewPage
from machine_helpers import Driver, SIT_H, STAND_H, make_config
from test_position_observation_dbus import settle
from test_strict_retry import daemon_for_driver
from test_tray_tooltip import _make_tray


@pytest.mark.asyncio
async def test_arrived_click_refuses_then_fresh_departure_releases(qapp, monkeypatch, make_app_context):
    assert "/tmp/dbus-" in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    driver = Driver(make_config(strict_mode="standing", sync_interval=0), height=STAND_H)
    driver.m.start_without_desk_read(driver.now)
    assert driver.m.adopt_startup_height(STAND_H, driver.now, driver.m.startup_token())
    daemon = daemon_for_driver(driver)
    daemon.moving = False
    daemon._record_transition = MagicMock()
    auto, desk = Automation1(daemon), Desk1(daemon)
    daemon._ifaces = {"automation": auto, "desk": desk}
    driver.m._on_strict_changed = daemon._emit_strict_state
    bus = await MessageBus().connect()
    bus.export(DBUS_PATH, auto)
    bus.export(DBUS_PATH, desk)
    await bus.request_name(DBUS_NAME)
    monkeypatch.setattr(DaemonClient, "get_property", lambda *_: None)
    monkeypatch.setattr(DaemonClient, "list_presets", lambda *_: {})
    client = DaemonClient()
    ctx = make_app_context(client, driver.cfg, load_config=True, tray_available=True)
    page = OverviewPage(ctx)
    tray_fixture = _make_tray(client, SimpleNamespace(ctx=ctx))
    tray, _ = next(tray_fixture)
    errors = []
    client.commandFailed.connect(lambda name, message: errors.append((name, message)))
    try:
        await settle(qapp, lambda: client.strict_capability == "supported")
        assert client.strict_state.stage == "arrived"
        assert "standing interval enforced" in page.strict_status.text()
        assert "standing interval enforced" in tray.toolTip()
        sit = next(button for button in page.findChildren(QPushButton) if button.text() == "Sit")
        assert sit.isEnabled()
        before = (driver.m.strict_snapshot, driver.m.active_time, daemon._current_move_id,
                  driver.cfg.automation.strict_mode, list(driver.desk.move_calls))
        sit.click()
        await settle(qapp, lambda: bool(errors))
        assert errors[0][0].endswith("StrictEnforced")
        assert before == (driver.m.strict_snapshot, driver.m.active_time, daemon._current_move_id,
                          driver.cfg.automation.strict_mode, driver.desk.move_calls)
        driver.desk.height = SIT_H
        assert sit.isEnabled()
        sit.click()
        await settle(qapp, lambda: client.strict_state.stage == "released" and bool(driver.desk.move_calls))
        assert driver.desk.move_calls == [SIT_H]
        assert "ordinary controls are available" in page.strict_status.text()
        assert "no interval enforced" in tray._strict_action.text()
        await bus.release_name(DBUS_NAME)
        await settle(qapp, lambda: client.strict_capability == "unknown")
        assert "currently unavailable" in page.strict_status.text()
        assert "status unavailable" in tray._strict_action.text()
    finally:
        next(tray_fixture, None)
        page.deleteLater()
        client.deleteLater()
        bus.disconnect()
        await asyncio.sleep(0)
