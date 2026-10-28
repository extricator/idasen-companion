# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict recovery keeps one pinned intent across bounded attempts."""

from idasen_companion.core.lengths import Length
from machine_helpers import Driver, STAND_H, make_config


async def test_pending_retries_once_per_tick_with_pinned_target():
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    driver.desk.interrupt_next_move_at = Length(0.9)
    await driver.tick(dt=1)
    driver.cfg.presets["stand"] = 1.15
    driver.m.update_config(driver.cfg, reroll_target=False)
    driver.desk.interrupt_next_move_at = Length(0.9)
    await driver.tick(dt=1)
    assert driver.desk.move_calls == [STAND_H, STAND_H]
    assert driver.m.strict_snapshot.stage == "pending"
