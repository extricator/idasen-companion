# SPDX-License-Identifier: GPL-3.0-or-later
"""The control loop must outlive a failing tick.

`_tick` touches the desk, the session bus, logind and SQLite — all of which
fail in ordinary ways on a real machine. An exception used to unwind
`_run_until_stopped` and exit the process; systemd then restarts a daemon that
survives one tick and dies again, so `StartLimitBurst` never trips and the desk
simply stops moving, with only "Daemon stopping. / Daemon starting." pairs in
the Activity Log to show for it.
"""

import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from idasen_companion.core.clocks import WallInstant
from idasen_companion.core.config import AppConfig
from idasen_companion.daemon.accounting import ActiveTimeAccounting
from idasen_companion.daemon.main import Daemon
from machine_helpers import Driver
from daemon_helpers import make_daemon_shell


def make_daemon(tick):
    d = make_daemon_shell()
    d.config = AppConfig()
    d.desk = MagicMock()
    d._current_move_id = 0
    d.config.automation.check_interval = 0  # don't wait between ticks
    d.activity_log = MagicMock()
    d.accounting = MagicMock()
    d.machine = MagicMock()
    d.machine.strict_snapshot = None
    d._stop_event = asyncio.Event()
    d._initial_read = None
    d._adopt_initial_state = AsyncMock()
    d._tick = tick
    return d


@pytest.mark.asyncio
async def test_a_failing_tick_does_not_stop_the_loop():
    calls = []

    async def tick():
        calls.append(len(calls))
        if len(calls) <= 3:
            raise sqlite_style_error()
        d._stop_event.set()

    d = make_daemon(tick)
    await asyncio.wait_for(d._run_until_stopped(now=WallInstant(1_000_000.0)), timeout=5)

    assert len(calls) == 4  # kept going through all three failures
    levels = [c.args[0] for c in d.activity_log.diag.call_args_list]
    assert levels.count("error") == 3  # and said so every time


@pytest.mark.asyncio
async def test_cancellation_still_stops_the_loop():
    """The blanket except must not swallow CancelledError — that is how
    shutdown reaches the `finally` that releases the BLE link."""
    async def tick():
        raise asyncio.CancelledError

    d = make_daemon(tick)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(d._run_until_stopped(now=WallInstant(1_000_000.0)), timeout=5)


@pytest.mark.asyncio
async def test_loop_interval_equality_overrun_and_scalar_wait(monkeypatch):
    from idasen_companion.daemon import main as main_mod

    d = make_daemon(AsyncMock())
    d.config.automation.check_interval = 2
    readings = iter((10.0, 12.0, 20.0, 22.25))
    monkeypatch.setattr(main_mod, "time", SimpleNamespace(monotonic=lambda: next(readings)))
    waits = []

    async def wait_for(awaitable, *, timeout):
        awaitable.close()
        waits.append(timeout)
        if len(waits) == 1:
            d.activity_log.diag.assert_not_called()
        else:
            d._stop_event.set()

    monkeypatch.setattr(main_mod, "asyncio", SimpleNamespace(
        ensure_future=asyncio.ensure_future, CancelledError=asyncio.CancelledError,
        TimeoutError=asyncio.TimeoutError, wait_for=wait_for))
    formatter = MagicMock(wraps=main_mod.format_duration_human)
    monkeypatch.setattr(main_mod, "format_duration_human", formatter)
    await d._run_until_stopped(WallInstant(1_000_000.0))
    await d._initial_read

    assert waits == [2, 2] and all(type(interval) is int for interval in waits)
    assert [call.args[0] for call in formatter.call_args_list] == [2.25, 2]
    d.activity_log.diag.assert_called_once_with(
        "warning", "Control loop tick took 2 seconds (check interval is 2 seconds); "
        "automation was stalled for that long.")


@pytest.mark.asyncio
async def test_startup_origin_survives_adoption_setup_reload_and_controls(monkeypatch, tmp_path):
    from idasen_companion.daemon import main as main_mod

    origin = 1_000_000.0
    clock = origin - 1000  # construction age must not become active time
    driver = Driver(now=clock)
    d = Daemon(tmp_path / "config.toml", mock_desk=True, stats_path=Path(":memory:"))
    d.config, d.desk, d.machine = driver.cfg, driver.desk, driver.m
    d.config.automation.check_interval = 1
    d.config_file.save(d.config)
    d._idle = MagicMock(get_idle_ms=AsyncMock(return_value=1000))
    d._lock = MagicMock(is_locked=AsyncMock(return_value=False))
    d._session = MagicMock(state=AsyncMock(return_value="foreground"))
    d._maybe_warn = AsyncMock()
    d._emit_periodic_properties = MagicMock()
    d._emit_automation_state = MagicMock()
    monkeypatch.setattr(main_mod.time, "time", lambda: clock)
    totals = []

    async def tick():
        nonlocal clock
        if not totals:
            clock = origin + 25
            await d._initial_read  # real adoption resets the cycle at this later time
        else:
            clock += 30
            await d._start_after_setup()
            d.reload_config()
            d.set_automation_enabled(False)
            d.set_automation_enabled(True)
            d.pause()
            d.snooze(5)
            d.resume()
            clock += 30
        await Daemon._tick(d)
        totals.append(sum(seconds for _, _, seconds in d.stats.daily_totals(
            date(1970, 1, 1), date(2100, 1, 1))))
        if len(totals) == 2:
            d._stop_event.set()

    d._tick = tick
    try:
        await asyncio.wait_for(d._run_until_stopped(WallInstant(origin)), timeout=5)
        assert totals == [25, 85]
    finally:
        d.stats.close()


def sqlite_style_error():
    import sqlite3
    return sqlite3.OperationalError("attempt to write a readonly database")


# ----- background tasks are kept alive and audible -----

@pytest.mark.asyncio
async def test_a_spawned_task_is_held_until_it_finishes():
    """CPython keeps only a *weak* reference to a running task, so a bare
    ensure_future can be collected mid-flight. The worst cases here release
    BLE links; vanishing silently leaves the orphaned link the whole shutdown
    path exists to prevent."""
    import gc

    d = make_daemon(AsyncMock())
    started = asyncio.Event()
    release = asyncio.Event()
    ran_to_completion = []

    async def work():
        started.set()
        await release.wait()
        ran_to_completion.append(True)

    d._spawn(work(), "doing the thing")   # deliberately not assigned
    await started.wait()
    assert len(d._tasks) == 1, "task not retained"

    gc.collect()                          # nothing else references it
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert ran_to_completion == [True], "task was collected mid-flight"
    assert d._tasks == set(), "finished task never discarded"


@pytest.mark.asyncio
async def test_a_failing_spawned_task_is_reported():
    """An exception in a detached task surfaces only as asyncio's "exception
    was never retrieved" on stderr, which the user never sees.
    _start_after_setup is the sharp one: it is the only thing that starts
    automation once the wizard supplies an address."""
    d = make_daemon(AsyncMock())

    async def boom():
        raise RuntimeError("could not reach the desk")

    d._spawn(boom(), "starting automation after setup")
    for _ in range(4):
        await asyncio.sleep(0)

    levels = [c.args[0] for c in d.activity_log.diag.call_args_list]
    messages = [c.args[1] for c in d.activity_log.diag.call_args_list]
    assert "warning" in levels
    assert any("starting automation after setup" in m for m in messages), messages
    assert d._tasks == set()


@pytest.mark.asyncio
async def test_a_cancelled_spawned_task_is_not_reported_as_a_failure():
    d = make_daemon(AsyncMock())

    async def forever():
        await asyncio.Event().wait()

    task = d._spawn(forever(), "waiting")
    await asyncio.sleep(0)
    task.cancel()
    for _ in range(3):
        await asyncio.sleep(0)

    assert not d.activity_log.diag.called
    assert d._tasks == set()


# ----- the tick and manual moves are serialized -----

@pytest.mark.asyncio
async def test_a_manual_move_waits_for_the_desk_lock():
    """dbus-fast dispatches every interface method as its own task, so
    Sit/Stand/MoveToHeight ran concurrently with the automation tick. The
    damaging interleaving: the machine's _execute_transition captures the
    state, awaits a multi-second BLE move, the user's manual move preempts it
    at the desk layer, and the automation path then reads a height that is not
    its target, calls that an interruption and applies interruption_policy —
    which by default moves the desk *back*, undoing what the user asked for.
    """
    order = []
    d = make_daemon(AsyncMock())
    d._manual_move_locked = AsyncMock(
        side_effect=lambda *a, **kw: order.append("manual"))

    await d._desk_lock.acquire()          # the tick is mid-move
    try:
        manual = asyncio.ensure_future(d._manual_move(1.10, "stand"))
        for _ in range(5):
            await asyncio.sleep(0)
        assert order == [], "manual move ran while the tick held the desk"
    finally:
        d._desk_lock.release()

    await asyncio.wait_for(manual, timeout=5)
    assert order == ["manual"], "manual move never ran after the lock freed"


@pytest.mark.asyncio
async def test_the_tick_takes_the_desk_lock():
    """The other half: a manual move in flight must delay the tick, not run
    alongside it."""
    d = make_daemon(AsyncMock())
    d.machine = MagicMock()
    d.machine.tick = AsyncMock(return_value=[])
    d._check_config_file = MagicMock()
    d._idle = MagicMock(get_idle_ms=AsyncMock(return_value=0))
    d._lock = MagicMock(is_locked=AsyncMock(return_value=False))
    d._session = MagicMock(state=AsyncMock(return_value="foreground"))
    d.stats = MagicMock()
    d.accounting = ActiveTimeAccounting(d.stats)
    d._handle_event = MagicMock()
    d._maybe_warn = AsyncMock()
    d._emit_periodic_properties = MagicMock()
    d.machine.held = False
    d.machine.state = MagicMock(value="sitting")

    await d._desk_lock.acquire()          # a manual move is in flight
    try:
        # The real _tick, not make_daemon's stub, since the lock is inside it.
        tick = asyncio.ensure_future(Daemon._tick(d))
        for _ in range(5):
            await asyncio.sleep(0)
        d.machine.tick.assert_not_awaited()
    finally:
        d._desk_lock.release()

    await asyncio.wait_for(tick, timeout=5)
    d.machine.tick.assert_awaited_once()


@pytest.mark.asyncio
async def test_queued_manual_command_expires_before_a_stalled_tick_recovers(monkeypatch):
    from dbus_fast.errors import DBusError
    from idasen_companion.daemon import main as main_mod

    d = make_daemon(AsyncMock())
    d._session = MagicMock(state=AsyncMock(return_value="foreground"))
    d._manual_move_locked = AsyncMock()
    monkeypatch.setattr(main_mod, "MANUAL_LOCK_TIMEOUT", 0.02)
    await d._desk_lock.acquire()
    try:
        with pytest.raises(DBusError):
            await d._manual_move(1.10, "stand")
    finally:
        d._desk_lock.release()
    d._manual_move_locked.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_command_rechecks_seat_before_desk_io():
    from dbus_fast.errors import DBusError

    d = make_daemon(AsyncMock())
    states = iter(("foreground", "background"))

    async def seat_state():
        return next(states)

    d._session = MagicMock(state=seat_state)
    d._manual_move_locked = AsyncMock()
    with pytest.raises(DBusError):
        await d._manual_move(1.10, "stand")
    d._manual_move_locked.assert_not_awaited()
    assert not d._desk_lock.locked()


@pytest.mark.asyncio
async def test_stop_is_not_blocked_by_a_move_holding_the_lock():
    """Stop must be able to interrupt a move that holds the lock — that is the
    whole point of it, and taking the lock there would deadlock the one
    operation the user reaches for when the desk is going somewhere wrong."""
    d = make_daemon(AsyncMock())
    d.activity_log = MagicMock()
    d.desk = MagicMock()
    d.desk.stop = AsyncMock()
    d._current_move_id = 0
    d.moving = True
    d._gesture_action = "stand"
    d._ifaces = {"desk": MagicMock()}

    await d._desk_lock.acquire()          # a move is in flight
    try:
        await asyncio.wait_for(d.stop_movement(), timeout=2)
    finally:
        d._desk_lock.release()

    d.desk.stop.assert_awaited_once()
    assert d.moving is False


@pytest.mark.asyncio
async def test_automated_move_refreshes_presence_at_the_ble_command_boundary(monkeypatch):
    from idasen_companion.daemon import main as main_mod
    from idasen_companion.core.durations import Duration
    from idasen_companion.core.machine import StateMachine, TransitionCompleted
    from test_ble_desk import make_desk

    driver = Driver()
    desk, fake = make_desk(connection_mode="persistent")
    d = make_daemon(AsyncMock())
    d.config, d.desk = driver.cfg, desk
    d._current_move_id = 0
    d.machine = StateMachine(d.config, desk, now=driver.now)
    await d.machine.start(driver.now)
    d.machine.active_time = d.machine.target_duration
    target = d.machine.target_duration
    clock = driver.now.epoch_seconds
    idle = 0
    observed = asyncio.Event()
    order = []

    async def get_idle():
        order.append("idle")
        observed.set()
        return idle

    async def unlocked():
        order.append("lock")
        return False

    async def foreground():
        order.append("seat")
        return "foreground"

    d._check_config_file = MagicMock()
    d._idle = SimpleNamespace(get_idle_ms=get_idle)
    d._lock = SimpleNamespace(is_locked=unlocked)
    d._session = SimpleNamespace(state=foreground)
    d._handle_event = MagicMock()
    d._maybe_warn = AsyncMock()
    d._emit_periodic_properties = MagicMock()
    monkeypatch.setattr(main_mod.time, "time", lambda: clock)

    await d._desk_lock.acquire()
    tick = asyncio.create_task(Daemon._tick(d))
    try:
        await asyncio.wait_for(observed.wait(), 2)
        idle = d.config.automation.recent_input_threshold * 1000
        clock += 1
    finally:
        d._desk_lock.release()
    try:
        await asyncio.wait_for(tick, 2)
        assert fake.moves == [], "stale pre-lock input authorized a physical command"
        assert order[-3:] == ["lock", "seat", "idle"]
        assert d.machine.target_duration == target
        assert d.machine.active_time == target
        assert not any(isinstance(c.args[0], TransitionCompleted)
                       for c in d._handle_event.call_args_list)
        idle -= 1  # adjacent eligible millisecond, not a new cycle
        await asyncio.wait_for(Daemon._tick(d), 2)
        assert fake.moves == [1.10]
        assert d.machine.active_time == Duration.from_seconds(0)
    finally:
        await desk.disconnect()


@pytest.mark.parametrize("invalidation", [
    "snooze", "config", "preset", "desk", "control", "target", "schedule-boundary",
])
async def test_automated_guard_rechecks_controls_after_presence_yield(monkeypatch, invalidation):
    from idasen_companion.daemon import main as main_mod
    from idasen_companion.core.durations import Duration

    driver = Driver()
    await driver.start()
    d = make_daemon(AsyncMock())
    d.config, d.desk, d.machine = driver.cfg, driver.desk, driver.m
    d.machine.active_time = d.machine.target_duration
    clock = driver.now.epoch_seconds
    if invalidation == "schedule-boundary":
        # Start inside an allowed window and finish on a disallowed day.
        from datetime import datetime
        d.config.schedule.enabled = True
        d.config.schedule.days = [datetime.fromtimestamp(clock).strftime("%a").lower()]
        d.config.schedule.start, d.config.schedule.end = "00:00", "23:59"
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def idle():
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            await release.wait()
        return 0

    d._idle = SimpleNamespace(get_idle_ms=idle)
    d._lock = SimpleNamespace(is_locked=AsyncMock(return_value=False))
    d._session = SimpleNamespace(state=AsyncMock(return_value="foreground"))
    d._check_config_file = MagicMock()
    d._handle_event = MagicMock()
    d._maybe_warn = AsyncMock()
    d._emit_periodic_properties = MagicMock()
    monkeypatch.setattr(main_mod.time, "time", lambda: clock)
    task = asyncio.create_task(Daemon._tick(d))
    await asyncio.wait_for(entered.wait(), 2)
    if invalidation == "snooze":
        d.machine.snooze(5, driver.now)
    elif invalidation == "config":
        d.config = AppConfig()
    elif invalidation == "preset":
        d.config.presets["stand"] = 1.15
    elif invalidation == "desk":
        d.desk = MagicMock()
    elif invalidation == "control":
        d._current_move_id += 1
    elif invalidation == "target":
        d.machine.target_duration += Duration.from_seconds(1)
    else:
        clock += 86400
    release.set()
    await asyncio.wait_for(task, 2)
    assert driver.desk.move_calls == []
    d._handle_event.assert_not_called()


@pytest.mark.parametrize("seat, locked, expected_moves", [
    ("background", False, []), ("no-session", False, []),
    ("unknown", False, [1.10]), ("foreground", True, []),
], ids=["background", "seatless", "unknown", "locked"])
async def test_refreshed_absence_verdict_reaches_automated_admission(
        monkeypatch, seat, locked, expected_moves):
    from idasen_companion.daemon import main as main_mod
    from idasen_companion.core.lengths import Length

    driver = Driver()
    await driver.start()
    d = make_daemon(AsyncMock())
    d.config, d.desk, d.machine = driver.cfg, driver.desk, driver.m
    d.machine.active_time = d.machine.target_duration
    d._idle = SimpleNamespace(get_idle_ms=AsyncMock(return_value=0))
    d._lock = SimpleNamespace(is_locked=AsyncMock(side_effect=[False, locked]))
    d._session = SimpleNamespace(state=AsyncMock(side_effect=["foreground", seat]))
    d._check_config_file = MagicMock()
    d._handle_event = MagicMock()
    d._maybe_warn = AsyncMock()
    d._emit_periodic_properties = MagicMock()
    monkeypatch.setattr(main_mod.time, "time", lambda: driver.now.epoch_seconds)
    await asyncio.wait_for(Daemon._tick(d), 2)
    assert driver.desk.move_calls == [Length(height) for height in expected_moves]
