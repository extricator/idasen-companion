# SPDX-License-Identifier: GPL-3.0-or-later
"""Cycle admission uses current strict intent and fresh desk evidence."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.parametrize("control", ["pause", "skip_next", "snooze"])
async def test_ordinary_cycle_controls_do_not_wait_for_movement(control):
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    daemon = daemon_for_driver(driver)
    daemon._emit_automation_state = MagicMock()
    await daemon._desk_lock.acquire()
    try:
        await asyncio.wait_for(getattr(daemon, control)(*((5,) if control == "snooze" else ())), 0.5)
        assert {"pause": driver.m.paused, "skip_next": driver.m.skip_next,
                "snooze": driver.m.snooze_until is not None}[control]
    finally:
        daemon._desk_lock.release()


async def test_pending_controls_and_movement_refuse_while_lock_held():
    from test_strict_movement import pending_daemon
    driver, daemon = await pending_daemon()
    await daemon._desk_lock.acquire()
    try:
        for operation in (daemon.pause(), daemon.manual_move_to_preset("sit")):
            with pytest.raises(DBusError) as error:
                await asyncio.wait_for(operation, 0.5)
            assert error.value.type.endswith("StrictEnforced")
        assert not driver.m.paused
    finally:
        daemon._desk_lock.release()


@pytest.mark.parametrize("control,field", [("skip_next", "skip_next"), ("snooze", "snooze_until")])
async def test_cycle_controls_refuse_arrived_and_allow_ordinary(control, field):
    driver, daemon = await arrived_daemon()
    args = (5,) if control == "snooze" else ()
    before = getattr(driver.m, field)
    with pytest.raises(DBusError):
        await getattr(daemon, control)(*args)
    assert getattr(driver.m, field) == before
    daemon.activity_log.emit.assert_not_called()
    driver.cfg.automation.strict_mode = "off"
    driver.m.update_config(driver.cfg)
    await getattr(daemon, control)(*args)
    assert getattr(driver.m, field) != before


async def test_invalidated_read_cannot_release_intent():
    driver, daemon = await arrived_daemon()
    entered, release = asyncio.Event(), asyncio.Event()

    async def read():
        entered.set()
        await release.wait()
        return SIT_H

    driver.desk.get_height = read
    task = asyncio.create_task(daemon.pause())
    await entered.wait()
    daemon._invalidate_position_observation()
    release.set()
    with pytest.raises(DBusError):
        await task
    assert driver.m.strict_snapshot.stage == "arrived"
    assert not driver.m.paused


async def test_unentitled_after_lock_wait_never_reads_desk():
    driver, daemon = await arrived_daemon()
    daemon._session.state.side_effect = ["foreground", "background"]
    driver.desk.get_height = AsyncMock()
    with pytest.raises(DBusError, match="session"):
        await daemon.pause()
    driver.desk.get_height.assert_not_awaited()


async def test_in_place_config_change_invalidates_departure_read():
    driver, daemon = await arrived_daemon()
    entered, release = asyncio.Event(), asyncio.Event()

    async def read():
        entered.set()
        await release.wait()
        return SIT_H

    driver.desk.get_height = read
    task = asyncio.create_task(daemon.pause())
    await entered.wait()
    driver.cfg.presets["stand"] = 1.15
    driver.m.update_config(driver.cfg, reroll_target=False)
    release.set()
    with pytest.raises(DBusError, match="strict mode"):
        await task
    assert driver.m.strict_snapshot.target_height == STAND_H
    assert not driver.m.paused


async def test_release_during_read_still_requires_current_entitlement():
    driver, daemon = await arrived_daemon()
    entered, release = asyncio.Event(), asyncio.Event()

    async def read():
        entered.set()
        await release.wait()
        return SIT_H

    driver.desk.get_height = read
    task = asyncio.create_task(daemon.pause())
    await entered.wait()
    driver.cfg.automation.strict_mode = "off"
    driver.m.update_config(driver.cfg)
    daemon._session.state.return_value = "background"
    release.set()
    with pytest.raises(DBusError, match="session"):
        await task
    assert not driver.m.paused


async def test_notification_control_observes_refusal():
    driver, daemon = await arrived_daemon()
    from idasen_companion.daemon.main import Daemon
    daemon._maybe_warn = Daemon._maybe_warn.__get__(daemon)
    daemon._warned_this_cycle = False
    daemon.config.notifications.enabled = True
    daemon.config.notifications.lead_time = int(driver.m.target_duration.seconds)
    daemon.fmt = daemon._build_formatter(daemon.config)
    daemon._ifaces = {"automation": MagicMock()}
    daemon._notifier = MagicMock(send=AsyncMock())
    await daemon._maybe_warn(driver.now)
    await asyncio.gather(*list(daemon._tasks))
    callback = daemon._notifier.send.await_args.kwargs["actions"]["skip"][1]
    callback()
    await asyncio.gather(*list(daemon._tasks))
    assert not driver.m.skip_next
    daemon.activity_log.diag.assert_called_once()
