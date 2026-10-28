# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict admission covers movement entry and the actual BLE issue point."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from dbus_fast import DBusError

from idasen_companion.core.lengths import Length
from machine_helpers import Driver, STAND_H, SIT_H, make_config
from test_ble_desk import make_desk
from test_strict_retry import daemon_for_driver


async def pending_daemon():
    driver = Driver(make_config(strict_mode="standing", sync_interval=0))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    driver.desk.interrupt_next_move_at = Length(0.9)
    await driver.tick(dt=1)
    daemon = daemon_for_driver(driver)
    daemon.moving = False
    daemon._gesture_action = None
    daemon._gesture_start_height = None
    return driver, daemon


@pytest.mark.parametrize("method,args", [
    ("manual_move_to_preset", ("stand",)),
    ("toggle_sit_stand", ()),
    ("gesture_move", ("sit",)),
    ("manual_move_to_height", (Length(1.0),)),
])
async def test_pending_refuses_movement_before_mutation(method, args):
    driver, daemon = await pending_daemon()
    before = (driver.m.strict_snapshot, driver.m.active_time, daemon._current_move_id,
              daemon._gesture_action, daemon._gesture_start_height, list(driver.desk.move_calls))
    with pytest.raises(DBusError, match="strict mode"):
        await getattr(daemon, method)(*args)
    assert before == (driver.m.strict_snapshot, driver.m.active_time, daemon._current_move_id,
                      daemon._gesture_action, daemon._gesture_start_height, driver.desk.move_calls)
    daemon.activity_log.emit.assert_not_called()


async def test_queued_move_rechecks_after_lock():
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    daemon = daemon_for_driver(driver)
    daemon.moving = False
    await daemon._desk_lock.acquire()
    task = asyncio.create_task(daemon.manual_move_to_preset("stand"))
    await asyncio.sleep(0)
    driver.m.active_time = driver.m.target_duration
    driver.desk.interrupt_next_move_at = Length(0.9)
    await driver.tick(dt=1)
    before = list(driver.desk.move_calls)
    daemon._desk_lock.release()
    with pytest.raises(DBusError, match="strict mode"):
        await task
    assert driver.desk.move_calls == before
    assert daemon._current_move_id == 0


async def test_ordinary_repeat_stop_interrupts_while_desk_lock_is_held():
    driver = Driver(make_config())
    await driver.start()
    daemon = daemon_for_driver(driver)
    daemon.moving = True
    daemon._gesture_action = "stand"
    daemon._gesture_start_height = SIT_H
    daemon.config.ui.tray_repeat_move = "stop"
    await daemon._desk_lock.acquire()
    try:
        await asyncio.wait_for(daemon.gesture_move("stand"), 0.5)
        assert daemon._current_move_id == 1
        assert daemon._gesture_action is None
    finally:
        daemon._desk_lock.release()


async def test_fresh_physical_departure_allows_following_move_with_sync_off():
    driver = Driver(make_config(strict_mode="standing", sync_interval=0), height=STAND_H)
    driver.m.start_without_desk_read(driver.now)
    assert driver.m.adopt_startup_height(STAND_H, driver.now, driver.m.startup_token())
    daemon = daemon_for_driver(driver)
    daemon.moving = False
    daemon._ifaces = {}
    daemon._record_transition = MagicMock()
    driver.desk.height = SIT_H
    await daemon.manual_move_to_preset("stand")
    assert driver.m.strict_snapshot is None
    assert driver.desk.move_calls == [STAND_H]
    assert daemon._handle_event.call_count == 1


async def test_strict_armed_during_undo_read_prevents_return():
    driver = Driver(make_config(strict_mode="standing"))
    driver.m.start_without_desk_read(driver.now)
    driver.m.last_height = SIT_H
    daemon = daemon_for_driver(driver)
    daemon.moving = False
    driver.desk.interrupt_next_move_at = Length(0.9)
    entered, release = asyncio.Event(), asyncio.Event()
    read = driver.desk.get_height

    async def delayed_read():
        entered.set()
        await release.wait()
        return await read()

    driver.desk.get_height = delayed_read
    task = asyncio.create_task(daemon.manual_move_to_preset("stand"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert driver.m.adopt_startup_height(STAND_H, driver.now, driver.m.startup_token())
        release.set()
        await asyncio.wait_for(task, 2)
        assert driver.desk.move_calls == [STAND_H]
    finally:
        release.set()


async def test_strict_armed_during_ble_connect_prevents_driver_and_gesture_mutation():
    driver = Driver(make_config(strict_mode="standing"))
    driver.m.start_without_desk_read(driver.now)
    desk, fake = make_desk(connection_mode="persistent")
    driver.m.replace_desk(desk)
    daemon = daemon_for_driver(driver)
    daemon.desk = desk
    daemon.moving = False
    daemon._gesture_action = None
    daemon._gesture_start_height = SIT_H
    daemon.config.ui.tray_repeat_move = "stop"
    entered, release = asyncio.Event(), asyncio.Event()
    connect = fake.connect

    async def delayed_connect():
        entered.set()
        await release.wait()
        await connect()

    fake.connect = delayed_connect
    task = asyncio.create_task(daemon.gesture_move("stand"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert driver.m.adopt_startup_height(STAND_H, driver.now, driver.m.startup_token())
        release.set()
        with pytest.raises(DBusError, match="strict mode"):
            await asyncio.wait_for(task, 2)
        assert fake.moves == []
        assert daemon._current_move_id == 0
        assert daemon._gesture_action is None
        daemon.activity_log.emit.assert_not_called()
    finally:
        release.set()
        await desk.disconnect()


@pytest.mark.parametrize("denial", ["strict", "session"])
async def test_predecision_read_reports_admission_denial(denial):
    driver = Driver(make_config(strict_mode="standing"))
    driver.m.start_without_desk_read(driver.now)
    daemon = daemon_for_driver(driver)
    daemon.moving = False
    entered, release = asyncio.Event(), asyncio.Event()

    async def read():
        entered.set()
        await release.wait()
        return SIT_H

    driver.desk.get_height = read
    task = asyncio.create_task(daemon.toggle_sit_stand())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if denial == "strict":
            assert driver.m.adopt_startup_height(STAND_H, driver.now, driver.m.startup_token())
        else:
            daemon._session.state.return_value = "background"
        release.set()
        with pytest.raises(DBusError) as error:
            await asyncio.wait_for(task, 2)
        assert error.value.type.endswith("StrictEnforced" if denial == "strict" else "SessionInactive")
        assert not driver.desk.move_calls
    finally:
        release.set()


@pytest.mark.parametrize("failure", ["strict", "session", "preparation"])
async def test_repeat_reverse_clears_moving_when_successor_cannot_issue(failure):
    driver = Driver(make_config(strict_mode="standing"))
    driver.m.start_without_desk_read(driver.now)
    daemon = daemon_for_driver(driver)
    daemon.moving = True
    daemon._gesture_action = "stand"
    daemon._gesture_start_height = SIT_H
    daemon.config.ui.tray_repeat_move = "reverse"
    stop = driver.desk.stop

    async def stopping():
        await stop()
        if failure == "strict":
            driver.desk.height = STAND_H
            assert driver.m.adopt_startup_height(STAND_H, driver.now, driver.m.startup_token())
        elif failure == "session":
            daemon._session.state.return_value = "background"

    driver.desk.stop = stopping
    if failure == "preparation":
        from idasen_companion.desk.port import MoveFailure
        driver.desk.move_to = AsyncMock(return_value=MoveFailure.NOT_ISSUED)
    with pytest.raises(DBusError):
        await daemon.gesture_move("stand")
    daemon._set_moving.assert_called_once_with(False)
    from idasen_companion.daemon.main import logmsg
    assert all(call.args[0] != logmsg.GESTURE_REVERSE
               for call in daemon.activity_log.emit.call_args_list)


async def test_failed_reverse_does_not_clear_newer_move_owner():
    driver = Driver(make_config())
    driver.m.start_without_desk_read(driver.now)
    daemon = daemon_for_driver(driver)
    daemon.moving = True
    daemon._gesture_action = "stand"
    daemon._gesture_start_height = SIT_H
    daemon.config.ui.tray_repeat_move = "reverse"

    async def stopping():
        daemon._current_move_id += 1  # A newer operation takes ownership.
        daemon._session.state.return_value = "background"

    driver.desk.stop = stopping
    with pytest.raises(DBusError):
        await daemon.gesture_move("stand")
    daemon._set_moving.assert_not_called()
