# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict recovery keeps one pinned intent across bounded attempts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from idasen_companion.core.clocks import WallInstant
from idasen_companion.core.lengths import Length
from idasen_companion.core.durations import Duration
from idasen_companion.core.machine import TransitionCompleted
from daemon_helpers import make_daemon_shell
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


def daemon_for_driver(driver):
    d = make_daemon_shell()
    d.config, d.desk, d.machine = driver.cfg, driver.desk, driver.m
    d._current_move_id = 0
    d._idle = SimpleNamespace(get_idle_ms=AsyncMock(return_value=0))
    d._lock = SimpleNamespace(is_locked=AsyncMock(return_value=False))
    d._session = SimpleNamespace(state=AsyncMock(return_value="foreground"))
    d._check_config_file = MagicMock()
    d._handle_event = MagicMock()
    d._maybe_warn = AsyncMock()
    d._emit_periodic_properties = MagicMock()
    d.accounting = MagicMock()
    d.activity_log = MagicMock()
    d._set_moving = MagicMock()
    return d


async def test_stop_during_readback_rejects_result_then_allows_new_attempt(monkeypatch):
    from idasen_companion.daemon import main as main_module

    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    d = daemon_for_driver(driver)
    clock = [1_000_001.0]
    monkeypatch.setattr(main_module.time, "time", lambda: clock[0])
    original_read = d.desk.get_height
    stopped = False

    async def read():
        nonlocal stopped
        if d.desk.move_calls and not stopped:
            stopped = True
            await d.stop_movement()
            clock[0] += 20
        return await original_read()

    d.desk.get_height = read
    await d._tick()
    assert d.machine.strict_snapshot.stage == "pending"
    assert not any(isinstance(call.args[0], TransitionCompleted)
                   for call in d._handle_event.call_args_list)
    clock[0] += 1
    await d._tick()
    assert d.desk.move_calls == [STAND_H, STAND_H]
    assert d.machine.strict_snapshot.stage == "arrived"
    assert d.machine.active_time == Duration(0)
    assert d.machine._last_check == WallInstant(clock[0])
    assert d.accounting.account.call_count == 2


async def test_lock_wait_resamples_presence_before_command(monkeypatch):
    from idasen_companion.daemon import main as main_module

    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    d = daemon_for_driver(driver)
    monkeypatch.setattr(main_module.time, "time", lambda: 1_000_001)
    await d._desk_lock.acquire()
    attempt = asyncio.create_task(d._tick())
    try:
        for _ in range(10):
            if d._session.state.await_count:
                break
            await asyncio.sleep(0)
        assert d._session.state.await_count == 1
        d._lock.is_locked.return_value = True
    finally:
        d._desk_lock.release()
    await asyncio.wait_for(attempt, 1)
    assert d.desk.move_calls == []
    assert d.accounting.account.call_count == 1
    assert d.machine.strict_snapshot.stage == "pending"


async def test_pending_guard_denies_threshold_and_resumes_after_accumulator_reset():
    from idasen_companion.core.machine import FreshPresence

    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    driver.desk.interrupt_next_move_at = Length(0.9)
    await driver.tick(dt=1)
    driver.m.active_time = Duration(0)
    current_idle = [driver.cfg.automation.recent_input_threshold * 1000]

    async def refresh():
        return FreshPresence(driver.now, current_idle[0], False)

    await driver.m.tick(driver.now, 0, False, refresh_presence=refresh)
    assert len(driver.desk.move_calls) == 1
    current_idle[0] = 0
    await driver.m.tick(driver.now, 0, False, refresh_presence=refresh)
    assert driver.desk.move_calls == [STAND_H, STAND_H]
    assert driver.m.strict_snapshot.stage == "arrived"


async def test_config_change_during_guard_blocks_issue_and_preserves_target():
    from idasen_companion.core.machine import FreshPresence

    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    driver.desk.interrupt_next_move_at = Length(0.9)
    await driver.tick(dt=1)
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_refresh():
        entered.set()
        await release.wait()
        return FreshPresence(driver.now, 0, False)

    attempt = asyncio.create_task(driver.m.tick(driver.now, 0, False,
                                                 refresh_presence=delayed_refresh))
    await asyncio.wait_for(entered.wait(), 1)
    driver.cfg.presets["stand"] = 1.15
    release.set()
    await asyncio.wait_for(attempt, 1)
    assert driver.desk.move_calls == [STAND_H]
    assert driver.m.strict_snapshot.target_height == STAND_H

    async def current():
        return FreshPresence(driver.now, 0, False)

    await driver.m.tick(driver.now, 0, False, refresh_presence=current)
    assert driver.desk.move_calls == [STAND_H, STAND_H]


async def test_stop_during_preparation_blocks_command_and_next_tick_retries(monkeypatch):
    from idasen_companion.daemon import main as main_module

    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    d = daemon_for_driver(driver)
    monkeypatch.setattr(main_module.time, "time", lambda: 1_000_001)
    original = d.desk.move_to
    preparing, release = asyncio.Event(), asyncio.Event()

    async def prepare(height, **kwargs):
        preparing.set()
        await release.wait()
        return await original(height, **kwargs)

    d.desk.move_to = prepare
    attempt = asyncio.create_task(d._tick())
    await asyncio.wait_for(preparing.wait(), 1)
    await d.stop_movement()
    release.set()
    await asyncio.wait_for(attempt, 1)
    assert d.desk.move_calls == []
    assert d.machine.strict_snapshot.stage == "pending"
    await d._tick()
    assert d.desk.move_calls == [STAND_H]
    assert d.machine.strict_snapshot.stage == "arrived"


async def test_repeated_attempts_yield_lock_and_accounting(monkeypatch):
    from idasen_companion.daemon import main as main_module

    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    d = daemon_for_driver(driver)
    monkeypatch.setattr(main_module.time, "time", lambda: 1_000_001)
    for count in range(1, 4):
        d.desk.interrupt_next_move_at = Length(0.9)
        await d._tick()
        async with d._desk_lock:
            assert len(d.desk.move_calls) == count
            assert d.accounting.account.call_count == count
            assert d._check_config_file.call_count == count
        assert d.machine.strict_snapshot.stage == "pending"
    assert d.desk.move_calls == [STAND_H] * 3
