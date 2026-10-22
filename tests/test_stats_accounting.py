# SPDX-License-Identifier: GPL-3.0-or-later
"""Which elapsed time the daemon credits as sit/stand time.

Presence is a guess whenever there's no input: a silent stretch is either the
user reading at the desk (real sit/stand time) or the user gone (not). The
signals are identical, so the daemon credits silence only provisionally and
holds it back until something settles the question — input proves the user was
there, reaching the away threshold proves they weren't.

These drive ``Daemon._tick`` directly through its accounting collaborator:
``StateMachine`` deliberately does no stats at all.
"""

import time
from datetime import date, datetime, timedelta
from pathlib import Path
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from idasen_companion.core.clocks import WallInstant
from idasen_companion.core.config import AppConfig
from idasen_companion.core.durations import Duration
from idasen_companion.core.machine import Status
from idasen_companion.daemon.accounting import ActiveTimeAccounting
from idasen_companion.daemon.idle import (
    SEAT_BACKGROUND, SEAT_FOREGROUND, SEAT_NONE,
)
from idasen_companion.daemon.main import Daemon
from idasen_companion.daemon.stats import Stats
from machine_helpers import Driver

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
        d.desk = MagicMock()
        d._current_move_id = 0
        d.config.automation.check_interval = int(TICK)
        d.config.automation.idle_threshold = idle_threshold
        d.config.automation.recent_input_threshold = recent_input_threshold
        d.stats = self.stats
        d.accounting = ActiveTimeAccounting(d.stats)
        d.accounting.start(WallInstant(self.clock))
        d.activity_log = MagicMock()
        d.machine = MagicMock()
        d.machine.state = MagicMock(value="sitting")
        d.machine.held = False
        d.machine.tick = AsyncMock(return_value=[])
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


@pytest.fixture
def harness():
    instance = Harness()
    try:
        yield instance
    finally:
        instance.stats.close()


@pytest.mark.asyncio
async def test_constructed_daemon_can_save_config_account_time_and_discover(tmp_path):
    path = tmp_path / "config.toml"
    d = Daemon(path, mock_desk=True,
               stats_path=Path(":memory:"))
    try:
        config = AppConfig()
        config.desk.mac = "00:11:22:33:44:55"
        d.config_file.save(config)
        assert path.is_file()
        assert d.config_file.load() == config
        assert not d.config_file.poll_changed()

        d.accounting.start(WallInstant(0.0))
        d.accounting.account("sitting", WallInstant(TICK), held=False, idle_ms=60000,
                             absent=False, idle_threshold_seconds=600)
        d.accounting.flush()
        assert d.stats.daily_totals(date.today(), date.today()) == [
            (date.today().isoformat(), "sitting", TICK)]

        assert await d.discover(0) == [("Desk 0000 (mock)", config.desk.mac)]
    finally:
        d.stats.close()


@pytest.mark.asyncio
async def test_working_time_is_credited_as_it_happens(harness):
    """Input in every window: credited immediately, so "Today:" stays live."""
    h = harness
    for _ in range(10):
        await h.tick(5)
    assert h.credited() == pytest.approx(10 * TICK)


@pytest.mark.asyncio
async def test_cycle_clock_reset_does_not_change_active_time(harness):
    h = harness
    await h.tick(5)
    # A cycle restart between observations must not shorten the next window.
    h.daemon.machine._last_check = WallInstant(h.clock + TICK / 2)
    await h.tick(5)
    await h.tick(5)
    assert h.credited() == pytest.approx(3 * TICK)


@pytest.mark.asyncio
async def test_unseeded_accounting_observes_before_crediting(harness):
    h = harness
    h.daemon.accounting = ActiveTimeAccounting(h.stats)
    await h.tick(5)
    assert h.credited() == 0
    await h.tick(5)
    assert h.credited() == pytest.approx(TICK)


@pytest.mark.asyncio
@pytest.mark.parametrize("freeze", ["disabled", "paused", "snoozed", "outside-schedule"])
async def test_real_automation_freezes_leave_active_statistics_running(harness, freeze, monkeypatch):
    h = harness
    # Monday before the configured work window, independent of execution date.
    h.clock = datetime(2026, 1, 5, 8, 0).timestamp()
    monkeypatch.setattr(time, "time", lambda: h.clock)
    driver = Driver(now=h.clock)
    d = h.daemon
    d.config = driver.cfg
    d.machine = driver.m
    d.accounting.start(WallInstant(h.clock))
    if freeze == "disabled":
        d.config.automation.enabled = False
    elif freeze == "paused":
        d.machine.pause()
    elif freeze == "snoozed":
        d.machine.snooze(5, WallInstant(h.clock))
    else:
        d.config.schedule.enabled = True
        d.config.schedule.days = ["mon"]
        d.config.schedule.start = "09:00"
        d.config.schedule.end = "17:00"
    await driver.start()
    if freeze == "outside-schedule":
        assert d.machine.status(WallInstant(h.clock)) is Status.OUT_OF_SCHEDULE

    await h.tick(5)
    assert d.machine.active_time == Duration.from_seconds(0)
    assert h.credited() == pytest.approx(TICK)
    if freeze == "outside-schedule":
        assert h.stats.daily_totals(date(2026, 1, 5), date(2026, 1, 5)) == [
            ("2026-01-05", "sitting", TICK),
        ]
    await h.tick(5)
    assert d.machine.active_time == Duration.from_seconds(0)
    assert h.credited() == pytest.approx(2 * TICK)
    if freeze == "outside-schedule":
        assert h.stats.daily_totals(date(2026, 1, 5), date(2026, 1, 5)) == [
            ("2026-01-05", "sitting", 2 * TICK),
        ]


@pytest.mark.asyncio
async def test_tick_accounts_captured_position_after_unlock_before_events(harness):
    h = harness
    d = h.daemon
    order = []
    d.accounting = MagicMock()

    async def machine_tick(*args, refresh_presence=None):
        assert d._desk_lock.locked()
        order.append("machine")
        d.machine.state = MagicMock(value="standing")
        d.machine.held = True
        d.machine._last_check = WallInstant(h.clock)
        return ["transition"]

    def account(*args, **kwargs):
        assert not d._desk_lock.locked()
        order.append("account")

    d.machine.tick = AsyncMock(side_effect=machine_tick)
    d.accounting.account.side_effect = account
    d._handle_event.side_effect = lambda *a, **kw: order.append("event")
    await h.tick(5)

    d.accounting.account.assert_called_once_with(
        "sitting", WallInstant(h.clock), held=False, idle_ms=5000, absent=False,
        idle_threshold_seconds=600)
    assert order == ["machine", "account", "event"]


@pytest.mark.asyncio
async def test_silence_that_ends_in_input_counts_in_full(harness):
    """Reading a dense page for eight minutes is time spent at the desk.

    Nothing distinguishes it from being away until it ends — and it ends with
    input, well short of the away threshold, so it was presence after all.
    """
    h = harness
    await h.tick(5)
    await h.silence(8 * 60)
    await h.tick(2)  # scrolled the page
    assert h.credited() == pytest.approx(10 * TICK)


@pytest.mark.asyncio
async def test_break_past_the_away_threshold_deposits_nothing(harness):
    """The regression this suite exists for.

    Accounting used to credit every tick under the away threshold and never
    revisit it, so each break banked ~idle_threshold of phantom "active" time
    permanently. Crossing the threshold is precisely the evidence that the
    silence was absence, so that time must not survive it.
    """
    h = harness
    await h.tick(5)
    await h.silence(15 * 60)
    assert h.credited() == pytest.approx(TICK)  # only the tick with input


@pytest.mark.asyncio
async def test_returning_after_a_long_break_resumes_clean(harness):
    h = harness
    await h.tick(5)
    await h.silence(15 * 60)
    await h.tick(2)  # back at the desk
    await h.tick(5)
    assert h.credited() == pytest.approx(3 * TICK)


@pytest.mark.asyncio
async def test_lock_discards_held_back_time(harness):
    """A lock is proof of absence, at any idleness."""
    h = harness
    await h.tick(5)
    await h.silence(4 * 60)
    await h.tick(300, locked=True)
    await h.tick(2)
    assert h.credited() == pytest.approx(2 * TICK)


@pytest.mark.asyncio
async def test_switching_session_discards_held_back_time(harness):
    h = harness
    await h.tick(5)
    await h.silence(4 * 60)
    await h.tick(300, away=True)
    await h.tick(2)
    assert h.credited() == pytest.approx(2 * TICK)


@pytest.mark.asyncio
async def test_no_graphical_session_discards_held_back_time(harness):
    h = harness
    await h.tick(5)
    await h.silence(4 * 60)
    await h.tick(0, seatless=True)
    await h.tick(2)
    assert h.credited() == pytest.approx(2 * TICK)


@pytest.mark.asyncio
async def test_tick_uses_the_reloaded_idle_threshold(harness):
    h = harness
    await h.tick(5)
    await h.silence(4 * 60)
    h.daemon._check_config_file.side_effect = lambda: setattr(
        h.daemon.config.automation, "idle_threshold", 120)
    await h.tick(300)
    await h.tick(2)
    assert h.credited() == pytest.approx(2 * TICK)


@pytest.mark.asyncio
async def test_suspend_sized_gap_discards_held_back_time(harness):
    """A wall-clock jump is the stats-side twin of the machine's time-jump
    reset: the gap itself isn't credited, and neither is the silence before it.
    """
    h = harness
    await h.tick(5)
    await h.silence(4 * 60)
    await h.tick(3600, elapsed=3600)
    await h.tick(2)
    assert h.credited() == pytest.approx(2 * TICK)


def test_exact_jump_boundary_discards_pending_credit_and_recovers(harness):
    h = harness
    owner = h.daemon.accounting
    now = WallInstant(2**30)
    owner.start(now)

    def observe(elapsed, idle_ms):
        nonlocal now
        now += Duration.from_seconds(elapsed)
        owner.account("sitting", now, held=False, idle_ms=idle_ms,
                      absent=False, idle_threshold_seconds=600)

    observe(300, 0)
    assert h.credited() == 300
    observe(60, 60000)  # provisional silence must be discarded with the jump
    observe(300 + 2**-22, 0)
    assert h.credited() == 300
    observe(60, 0)
    assert h.credited() == 360


@pytest.mark.asyncio
async def test_backward_clock_step_credits_nothing(harness):
    """A clock correction can step backwards. Crediting a negative elapsed
    would *subtract* from a daily row, leaving a total that no amount of real
    desk time explains and a negative bar on the Statistics chart."""
    h = harness
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
async def test_off_cycle_time_is_not_attributed_to_either_state(harness):
    """Held off-cycle the desk is at neither preset, so nothing to credit."""
    h = harness
    await h.tick(5, held=True)
    await h.tick(5, held=True)
    assert h.credited("sitting") == 0
    assert h.credited("standing") == 0
    await h.tick(5)
    assert h.credited("sitting") == pytest.approx(TICK)


@pytest.mark.asyncio
async def test_held_back_time_lands_on_the_state_it_was_spent_in(harness):
    """The desk can change position between silence and the input that
    confirms it, so held-back time is keyed by the state it was held in."""
    h = harness
    await h.tick(5)
    await h.silence(3 * 60)
    h.daemon.machine.state = MagicMock(value="standing")
    await h.tick(2)
    assert h.credited("sitting") == pytest.approx(4 * TICK)
    assert h.credited("standing") == pytest.approx(TICK)


@pytest.mark.asyncio
async def test_shutdown_commits_held_back_time(harness):
    """Stopping mid-silence is not evidence of absence; don't lose the time."""
    h = harness
    await h.tick(5)
    await h.silence(4 * 60)
    assert h.credited() == pytest.approx(TICK)
    h.daemon.accounting.flush()
    assert h.credited() == pytest.approx(5 * TICK)


@pytest.mark.asyncio
@pytest.mark.parametrize("settled_by", ["input", "shutdown"])
async def test_pending_credit_keeps_original_day_and_state(monkeypatch, settled_by, harness):
    from idasen_companion.daemon import accounting as accounting_mod
    from idasen_companion.daemon import stats as stats_mod

    current_day = date(2026, 1, 1)

    class AccountingDate(date):
        @classmethod
        def today(cls):
            return current_day

    monkeypatch.setattr(accounting_mod, "date", AccountingDate)
    monkeypatch.setattr(stats_mod, "date", AccountingDate)
    h = harness
    await h.tick(60)
    h.daemon.machine.state = MagicMock(value="standing")
    await h.tick(120)
    current_day = date(2026, 1, 2)
    await h.tick(180)
    assert h.stats.daily_totals(date(2026, 1, 1), date(2026, 1, 3)) == []

    current_day = date(2026, 1, 3)
    expected = [
        ("2026-01-01", "sitting", TICK),
        ("2026-01-01", "standing", TICK),
        ("2026-01-02", "standing", TICK),
    ]
    if settled_by == "input":
        await h.tick(2)
        expected.append(("2026-01-03", "standing", TICK))
    else:
        h.daemon.accounting.flush()

    assert h.stats.daily_totals(date(2026, 1, 1), current_day) == expected
    # The same buckets cannot be deposited again on a second flush.
    h.daemon.accounting.flush()
    assert h.stats.daily_totals(date(2026, 1, 1), current_day) == expected
