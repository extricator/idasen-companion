# SPDX-License-Identifier: GPL-3.0-or-later
"""Cycle admission uses current strict intent and fresh desk evidence."""
from unittest.mock import MagicMock

import pytest
from dbus_fast import DBusError

from machine_helpers import Driver, STAND_H, SIT_H, make_config
from test_strict_retry import daemon_for_driver


async def arrived_daemon():
    driver = Driver(make_config(strict_mode="standing", sync_interval=0), height=STAND_H)
    driver.m.start_without_desk_read(driver.now)
    assert driver.m.adopt_startup_height(STAND_H, driver.now, driver.m.startup_token())
    daemon = daemon_for_driver(driver)
    daemon.moving = False
    daemon._ifaces = {}
    daemon._emit_automation_state = MagicMock()
    return driver, daemon


async def test_arrived_pause_requires_fresh_departure():
    driver, daemon = await arrived_daemon()
    with pytest.raises(DBusError, match="strict mode"):
        await daemon.pause()
    assert not driver.m.paused
    assert driver.m.strict_snapshot.stage == "arrived"
    driver.desk.height = SIT_H
    await daemon.pause()
    assert driver.m.strict_snapshot is None
    assert driver.m.paused
    assert daemon._handle_event.call_count == 1


async def test_unselected_sitting_pause_needs_no_read():
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    daemon = daemon_for_driver(driver)
    daemon._emit_automation_state = MagicMock()
    driver.desk.get_height = MagicMock(side_effect=AssertionError("unexpected read"))
    await daemon.pause()
    assert driver.m.paused
