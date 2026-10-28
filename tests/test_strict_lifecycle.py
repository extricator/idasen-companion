# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheduled strict intent is backed by a real height observation."""

from idasen_companion.core.durations import Duration
from idasen_companion.core.machine import DeskState, TransitionCompleted
from machine_helpers import Driver, STAND_H, make_config


async def test_scheduled_standing_arrives_only_on_verified_readback():
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    events = await driver.tick(dt=1)
    snapshot = getattr(driver.m, "strict_snapshot", None)
    assert snapshot is not None
    assert (snapshot.stage, snapshot.posture, snapshot.target_height) == (
        "arrived", DeskState.STANDING, STAND_H)
    completed = [e for e in events if isinstance(e, TransitionCompleted)]
    assert len(completed) == 1
    assert completed[0].next_target_duration == driver.m.target_duration
    assert driver.m.active_time == Duration(0)
