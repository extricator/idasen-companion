# SPDX-License-Identifier: GPL-3.0-or-later
"""Actual automation requests use a disposable private D-Bus session."""
import asyncio
import os
from unittest.mock import MagicMock

from dbus_fast import Message
from dbus_fast.aio import MessageBus
from dbus_fast.constants import MessageType

from idasen_companion import DBUS_NAME, DBUS_PATH
from idasen_companion.core.lengths import Length
from idasen_companion.daemon.service import Automation1
from machine_helpers import Driver, make_config
from test_strict_retry import daemon_for_driver


async def test_pending_pause_refused_over_private_bus():
    assert "/tmp/dbus-" in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    driver.desk.interrupt_next_move_at = Length(0.9)
    await driver.tick(dt=1)
    daemon = daemon_for_driver(driver)
    daemon._emit_automation_state = MagicMock()
    before = (driver.m.strict_snapshot, driver.m.active_time, driver.m.paused,
              driver.m.snooze_until, driver.m.skip_next)
    server = await MessageBus().connect()
    client = await MessageBus().connect()
    server.export(DBUS_PATH, Automation1(daemon))
    await server.request_name(DBUS_NAME)
    try:
        reply = await client.call(Message(destination=DBUS_NAME, path=DBUS_PATH,
                                          interface=f"{DBUS_NAME}.Automation1", member="Pause"))
        assert reply.message_type == MessageType.ERROR
        assert reply.error_name == f"{DBUS_NAME}.Error.StrictEnforced"
        assert before == (driver.m.strict_snapshot, driver.m.active_time, driver.m.paused,
                          driver.m.snooze_until, driver.m.skip_next)
        daemon.activity_log.emit.assert_not_called()
    finally:
        await server.release_name(DBUS_NAME)
        client.disconnect()
        server.disconnect()
        await asyncio.sleep(0)
