"""The control loop must outlive a failing tick.

`_tick` touches the desk, the session bus, logind and SQLite — all of which
fail in ordinary ways on a real machine. An exception used to unwind
`_run_until_stopped` and exit the process; systemd then restarts a daemon that
survives one tick and dies again, so `StartLimitBurst` never trips and the desk
simply stops moving, with only "Daemon stopping. / Daemon starting." pairs in
the Activity Log to show for it.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from idasen_companion.core.config import AppConfig
from idasen_companion.daemon.main import Daemon


def make_daemon(tick):
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.config = AppConfig()
    d.config.automation.check_interval = 0  # don't wait between ticks
    d.activity_log = MagicMock()
    d.machine = MagicMock()
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
    await asyncio.wait_for(d._run_until_stopped(now=1_000_000.0), timeout=5)

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
        await asyncio.wait_for(d._run_until_stopped(now=1_000_000.0), timeout=5)


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
    d._pending_credit = {}
    d._handle_event = MagicMock()
    d._maybe_warn = AsyncMock()
    d._emit_periodic_properties = MagicMock()
    d.machine.held = False
    d.machine.state = MagicMock(value="sitting")
    d.machine._last_check = 0.0

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
