# SPDX-License-Identifier: GPL-3.0-or-later
"""Atomic strict snapshots travel over a disposable D-Bus session."""
import asyncio
import os

import pytest
from dbus_fast import Message
from dbus_fast.aio import MessageBus
from dbus_fast.constants import MessageType

from idasen_companion import DBUS_NAME, DBUS_PATH
from idasen_companion.core.strict_state import StrictState
from idasen_companion.daemon.service import Automation1
from idasen_companion.desk.mock import MockDesk
from machine_helpers import Driver, SIT_H, STAND_H, make_config
from test_strict_retry import daemon_for_driver


@pytest.mark.parametrize("payload", [
    '{"mode":"off","stage":"arrived","posture":null,"target_height":null}',
    '{"mode":"standing","stage":"pending","posture":"standing","target_height":NaN}',
    '{}',
])
def test_invalid_wire_snapshot_is_rejected(payload):
    with pytest.raises((ValueError, TypeError)):
        StrictState.from_json(payload)


async def test_physical_due_and_desk_releases_publish_immediately():
    driver = Driver(make_config(strict_mode="standing", sync_interval=0), height=STAND_H)
    driver.m.start_without_desk_read(driver.now)
    daemon = daemon_for_driver(driver)
    from unittest.mock import MagicMock
    auto = MagicMock()
    daemon._ifaces = {"automation": auto}
    driver.m._on_strict_changed = daemon._emit_strict_state
    assert driver.m.adopt_startup_height(STAND_H, driver.now, driver.m.startup_token())
    snapshot = driver.m.strict_snapshot
    driver.m.reconcile_strict_observation(SIT_H, generation=snapshot.generation, now=driver.now)
    assert StrictState.from_json(auto.StrictStateChanged.call_args.args[0]).stage == "released"
    driver.desk.height = SIT_H
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=1)
    assert driver.m.strict_snapshot.stage == "arrived"
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=1)
    assert StrictState.from_json(auto.StrictStateChanged.call_args.args[0]).stage == "released"
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=1)
    assert driver.m.strict_snapshot.stage == "arrived"
    driver.m.replace_desk(MockDesk())
    assert StrictState.from_json(auto.StrictStateChanged.call_args.args[0]).stage == "released"


async def test_live_private_bus_snapshot_is_atomic_before_move_finishes():
    assert "/tmp/dbus-" in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    daemon = daemon_for_driver(driver)
    server, client = await MessageBus().connect(), await MessageBus().connect()
    auto = Automation1(daemon)
    daemon._ifaces = {"automation": auto}
    driver.m._on_strict_changed = daemon._emit_strict_state
    server.export(DBUS_PATH, auto)
    await server.request_name(DBUS_NAME)
    signals = []
    client.add_message_handler(lambda msg: signals.append(msg.body[0])
                               if msg.message_type == MessageType.SIGNAL
                               and msg.member == "StrictStateChanged" else None)
    await client.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                              interface="org.freedesktop.DBus", member="AddMatch", signature="s",
                              body=[f"type='signal',interface='{DBUS_NAME}.Automation1'",]))

    async def get_state():
        reply = await client.call(Message(destination=DBUS_NAME, path=DBUS_PATH,
                                          interface="org.freedesktop.DBus.Properties", member="Get",
                                          signature="ss", body=[f"{DBUS_NAME}.Automation1", "StrictState"]))
        return StrictState.from_json(reply.body[0].value)

    entered, release = asyncio.Event(), asyncio.Event()
    original = driver.desk.move_to

    async def delayed(height, **kwargs):
        entered.set()
        await release.wait()
        return await original(height, **kwargs)

    driver.desk.move_to = delayed
    task = None
    try:
        assert await get_state() == StrictState("standing", "released", None, None)
        driver.m.active_time = driver.m.target_duration
        task = asyncio.create_task(driver.tick(dt=1))
        await asyncio.wait_for(entered.wait(), 2)
        pending = await get_state()
        assert pending == StrictState("standing", "pending", "standing", 1.1)
        assert any(StrictState.from_json(item) == pending for item in signals)
        release.set()
        await asyncio.wait_for(task, 2)
        arrived = await get_state()
        assert arrived == StrictState("standing", "arrived", "standing", 1.1)
        assert any(StrictState.from_json(item) == arrived for item in signals)
        driver.cfg.automation.strict_mode = "off"
        driver.m.update_config(driver.cfg)
        assert await get_state() == StrictState("off", "released", None, None)
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await server.release_name(DBUS_NAME)
        client.disconnect()
        server.disconnect()
        await asyncio.sleep(0)
