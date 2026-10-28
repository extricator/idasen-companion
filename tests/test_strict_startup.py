# SPDX-License-Identifier: GPL-3.0-or-later
"""The initial daemon observation is the only strict startup authority."""

from unittest.mock import AsyncMock, MagicMock

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
