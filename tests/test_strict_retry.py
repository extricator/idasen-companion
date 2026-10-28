# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict recovery keeps one pinned intent across bounded attempts."""

import asyncio
from types import SimpleNamespace

from idasen_companion.core.clocks import WallInstant
from idasen_companion.core.lengths import Length
from idasen_companion.core.machine import TransitionCompleted
from test_control_loop import make_daemon
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


async def test_pending_loop_paces_and_shutdown_interrupts_wait():
    calls = []
    second_tick = asyncio.Event()

    async def tick():
        calls.append(asyncio.get_running_loop().time())
        if len(calls) == 2:
            second_tick.set()

    daemon = make_daemon(tick)
    daemon.config.automation.check_interval = 60
    daemon.machine.strict_snapshot = SimpleNamespace(stage="pending")
    loop = asyncio.create_task(daemon._run_until_stopped(WallInstant(1000)))
    try:
        await asyncio.wait_for(second_tick.wait(), 1)
        assert 0.08 <= calls[1] - calls[0] < 1
        daemon._stop_event.set()
        await asyncio.wait_for(loop, 1)
    finally:
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)
        await daemon._initial_read


async def test_disable_during_move_discards_completion():
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    original_move = driver.desk.move_to

    async def move(height, **kwargs):
        result = await original_move(height, **kwargs)
        driver.cfg.automation.enabled = False
        driver.m.update_config(driver.cfg)
        return result

    driver.desk.move_to = move
    events = await driver.tick(dt=1)
    assert driver.m.strict_snapshot is None
    assert not any(isinstance(event, TransitionCompleted) for event in events)
