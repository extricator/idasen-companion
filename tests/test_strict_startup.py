# SPDX-License-Identifier: GPL-3.0-or-later
"""The initial daemon observation is the only strict startup authority."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from daemon_helpers import make_daemon_shell
from idasen_companion.core.durations import Duration
from machine_helpers import Driver, STAND_H, make_config


async def test_daemon_startup_arms_selected_posture_without_transition():
    driver = Driver(make_config(strict_mode="standing"), height=STAND_H)
    driver.m.start_without_desk_read(driver.now)
    daemon = make_daemon_shell()
    daemon.machine, daemon.desk, daemon.config = driver.m, driver.desk, driver.cfg
    daemon._entitled_to_desk = AsyncMock(return_value=True)
    daemon.activity_log = MagicMock()
    daemon._emit_periodic_properties = MagicMock()
    daemon._scheduled_target = MagicMock(return_value="sit")
    await daemon._adopt_initial_state()
    assert driver.m.strict_snapshot is not None
    assert driver.m.strict_snapshot.stage == "arrived"
    assert driver.m.strict_snapshot.target_height == STAND_H
    assert driver.m.active_time == Duration(0)
    assert driver.desk.move_calls == []
    await daemon._adopt_initial_state()
    assert driver.m.strict_snapshot.stage == "arrived"


@pytest.mark.parametrize("change", ["disable", "stop", "entitlement"])
async def test_stale_startup_read_cannot_adopt_after_intervening_change(change):
    driver = Driver(make_config(strict_mode="standing"), height=STAND_H)
    driver.m.start_without_desk_read(driver.now)
    daemon = make_daemon_shell()
    daemon.machine, daemon.desk, daemon.config = driver.m, driver.desk, driver.cfg
    daemon.activity_log = MagicMock()
    daemon._emit_periodic_properties = MagicMock()
    daemon._scheduled_target = MagicMock(return_value="sit")
    daemon._entitled_to_desk = AsyncMock(return_value=True)
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_read():
        entered.set()
        await release.wait()
        return STAND_H

    driver.desk.get_height = blocked_read
    task = asyncio.create_task(daemon._adopt_initial_state())
    await asyncio.wait_for(entered.wait(), 1)
    if change == "disable":
        driver.cfg.automation.enabled = False
        driver.m.update_config(driver.cfg)
        driver.cfg.automation.enabled = True
        driver.m.update_config(driver.cfg)
    elif change == "stop":
        daemon._current_move_id = 0
        daemon._gesture_action = None
        daemon._set_moving = MagicMock()
        await daemon.stop_movement()
    else:
        daemon._entitled_to_desk.return_value = False
    release.set()
    await asyncio.wait_for(task, 1)
    assert driver.m.strict_snapshot is None
    assert driver.m.last_height is None
