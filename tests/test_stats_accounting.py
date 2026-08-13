"""Which elapsed time the daemon credits as sit/stand time.

Presence is a guess whenever there's no input: a silent stretch is either the
user reading at the desk (real sit/stand time) or the user gone (not). The
signals are identical, so the daemon credits silence only provisionally and
holds it back until something settles the question — input proves the user was
there, reaching the away threshold proves they weren't.

These drive ``Daemon._tick`` directly, because the attribution lives in the
daemon: ``StateMachine`` deliberately does no stats at all.
"""

import time
from datetime import date, timedelta
from pathlib import Path
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from idasen_companion.core.config import AppConfig
from idasen_companion.daemon.idle import (
    SEAT_BACKGROUND, SEAT_FOREGROUND, SEAT_NONE,
)
from idasen_companion.daemon.main import Daemon
from idasen_companion.daemon.stats import Stats

TICK = 60.0  # check_interval used throughout


class Harness:
    """A Daemon with a real Stats store and everything else stubbed.

    Bypasses ``__init__`` (which builds a D-Bus service, a desk and monitors)
    the same way ``test_daemon_emit`` does, and fakes the clock so a whole
    idle stretch runs in a few milliseconds.
    """

    def __init__(self, *, idle_threshold=600, recent_input_threshold=180):
        # Anchored on the real clock, not an arbitrary epoch: faking time.time
        # also fakes date.today(), and the rows are keyed by day.
        self.clock = time.time()
        self.stats = Stats(Path(":memory:"))

        d = Daemon.__new__(Daemon)

        d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here

        d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
        d.config = AppConfig()
        d.config.automation.check_interval = int(TICK)
        d.config.automation.idle_threshold = idle_threshold
        d.config.automation.recent_input_threshold = recent_input_threshold
        d.stats = self.stats
        d.activity_log = MagicMock()
        d.machine = MagicMock()
        d.machine.state = MagicMock(value="sitting")
        d.machine.held = False
        d.machine._last_check = self.clock
        d.machine.tick = AsyncMock(return_value=[])
        d._pending_credit = {}
        d._idle = MagicMock()
        d._lock = MagicMock()
        d._session = MagicMock()
        # _tick's other side effects are covered elsewhere; stub them so the
        # accounting is the only thing under test.
        d._check_config_file = MagicMock()
        d._handle_event = MagicMock()
        d._maybe_warn = AsyncMock()
        d._emit_periodic_properties = MagicMock()
        self.daemon = d

    async def tick(self, idle_s, *, locked=False, away=False, seatless=False,
                   held=False, elapsed=TICK):
        """Advance the clock by one interval and run a tick at that idleness."""
        self.daemon.machine._last_check = self.clock
        self.clock += elapsed
        self.daemon.machine.held = held
        self.daemon._idle.get_idle_ms = AsyncMock(return_value=int(idle_s * 1000))
        self.daemon._lock.is_locked = AsyncMock(return_value=locked)
        self.daemon._session.state = AsyncMock(return_value=(
            SEAT_NONE if seatless else
            SEAT_BACKGROUND if away else SEAT_FOREGROUND))
        import idasen_companion.daemon.main as main_mod
        real_time = main_mod.time.time
        main_mod.time.time = lambda: self.clock
        try:
            await self.daemon._tick()
        finally:
            main_mod.time.time = real_time

    async def silence(self, seconds, *, start=0.0, **kw):
        """Run ticks through a stretch with no input, idleness climbing."""
        idle = start
        for _ in range(int(seconds // TICK)):
            idle += TICK
            await self.tick(idle, **kw)

    def credited(self, state="sitting"):
        """Total credited to a state, summed over days — a stretch driven here
        can cross midnight if the suite happens to run at the wrong moment."""
        today = date.today()
        totals = self.stats.daily_totals(today - timedelta(days=1),
                                         today + timedelta(days=1))
        return sum(sec for _, s, sec in totals if s == state)


@pytest.mark.asyncio
async def test_working_time_is_credited_as_it_happens():
    """Input in every window: credited immediately, so "Today:" stays live."""
    h = Harness()
    for _ in range(10):
        await h.tick(5)
    assert h.credited() == pytest.approx(10 * TICK)


@pytest.mark.asyncio
async def test_silence_that_ends_in_input_counts_in_full():
    """Reading a dense page for eight minutes is time spent at the desk.

    Nothing distinguishes it from being away until it ends — and it ends with
    input, well short of the away threshold, so it was presence after all.
    """
    h = Harness()
    await h.tick(5)
    await h.silence(8 * 60)
    await h.tick(2)  # scrolled the page
    assert h.credited() == pytest.approx(10 * TICK)


@pytest.mark.asyncio
async def test_break_past_the_away_threshold_deposits_nothing():
    """The regression this suite exists for.

    Accounting used to credit every tick under the away threshold and never
    revisit it, so each break banked ~idle_threshold of phantom "active" time
    permanently. Crossing the threshold is precisely the evidence that the
    silence was absence, so that time must not survive it.
    """
    h = Harness()
    await h.tick(5)
    await h.silence(15 * 60)
    assert h.credited() == pytest.approx(TICK)  # only the tick with input


@pytest.mark.asyncio
async def test_returning_after_a_long_break_resumes_clean():
    h = Harness()
    await h.tick(5)
    await h.silence(15 * 60)
    await h.tick(2)  # back at the desk
    await h.tick(5)
    assert h.credited() == pytest.approx(3 * TICK)


@pytest.mark.asyncio
async def test_lock_discards_held_back_time():
    """A lock is proof of absence, at any idleness."""
    h = Harness()
    await h.tick(5)
    await h.silence(4 * 60)
    await h.tick(300, locked=True)
    await h.tick(2)
    assert h.credited() == pytest.approx(2 * TICK)


@pytest.mark.asyncio
async def test_switching_session_discards_held_back_time():
    h = Harness()
    await h.tick(5)
    await h.silence(4 * 60)
    await h.tick(300, away=True)
    await h.tick(2)
    assert h.credited() == pytest.approx(2 * TICK)


@pytest.mark.asyncio
async def test_suspend_sized_gap_discards_held_back_time():
    """A wall-clock jump is the stats-side twin of the machine's time-jump
    reset: the gap itself isn't credited, and neither is the silence before it.
    """
    h = Harness()
    await h.tick(5)
    await h.silence(4 * 60)
    await h.tick(3600, elapsed=3600)
    await h.tick(2)
    assert h.credited() == pytest.approx(2 * TICK)


@pytest.mark.asyncio
async def test_backward_clock_step_credits_nothing():
    """A clock correction can step backwards. Crediting a negative elapsed
    would *subtract* from a daily row, leaving a total that no amount of real
    desk time explains and a negative bar on the Statistics chart."""
    h = Harness()
    for _ in range(5):
        await h.tick(5)
    banked = h.credited()
    assert banked == pytest.approx(5 * TICK)

    await h.tick(5, elapsed=-3600)
    assert h.credited() == pytest.approx(banked)

    # ...and the row is still correct afterwards, not merely unchanged.
    await h.tick(5)
    assert h.credited() == pytest.approx(banked + TICK)


@pytest.mark.asyncio
async def test_off_cycle_time_is_not_attributed_to_either_state():
    """Held off-cycle the desk is at neither preset, so nothing to credit."""
    h = Harness()
    await h.tick(5, held=True)
    await h.tick(5, held=True)
    assert h.credited("sitting") == 0
    assert h.credited("standing") == 0


@pytest.mark.asyncio
async def test_held_back_time_lands_on_the_state_it_was_spent_in():
    """The desk can change position between silence and the input that
    confirms it, so held-back time is keyed by the state it was held in."""
    h = Harness()
    await h.tick(5)
    await h.silence(3 * 60)
    h.daemon.machine.state = MagicMock(value="standing")
    await h.tick(2)
    assert h.credited("sitting") == pytest.approx(4 * TICK)
    assert h.credited("standing") == pytest.approx(TICK)


@pytest.mark.asyncio
async def test_shutdown_commits_held_back_time():
    """Stopping mid-silence is not evidence of absence; don't lose the time."""
    h = Harness()
    await h.tick(5)
    await h.silence(4 * 60)
    assert h.credited() == pytest.approx(TICK)
    h.daemon._flush_pending_credit()
    assert h.credited() == pytest.approx(5 * TICK)
