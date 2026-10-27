# SPDX-License-Identifier: GPL-3.0-or-later
"""Automation controls, pause, schedule, skip and cycle targets."""

from datetime import datetime

import pytest

from idasen_companion.core.clocks import WallInstant
from idasen_companion.core.durations import Duration
from idasen_companion.core.machine import (
    DeskState,
    HeldOffCycle,
    StateSynced,
    Status,
    TransitionCompleted,
    TransitionSkipped,
)

from machine_helpers import (
    STAND_H,
    OFF_CYCLE_H,
    make_config,
    Driver,
)


# ----- automation switched off (manual-only use) -----

def _disabled(cfg=None):
    cfg = cfg or make_config()
    cfg.automation.enabled = False
    return cfg


async def test_disabled_reports_its_own_status():
    d = Driver(cfg=_disabled())
    await d.start()
    assert d.m.status(d.now) is Status.DISABLED


async def test_disabled_outranks_pause_and_schedule():
    # With the cycle off there is no timer for pause/snooze to act on, so the
    # UI must not offer them — which means the status has to say "off", not
    # "paused", even when both are true.
    d = Driver(cfg=_disabled())
    await d.start()
    d.m.pause()
    assert d.m.status(d.now) is Status.DISABLED


async def test_disabled_never_moves_the_desk():
    d = Driver(cfg=_disabled())
    await d.start()
    assert d.m.target_duration == Duration.from_seconds(0)
    events = await d.run_active_ticks(60)  # an hour of active use
    assert not any(isinstance(e, TransitionCompleted) for e in events)
    assert d.desk.move_calls == []
    assert d.m.active_time == Duration.from_seconds(0)  # the clock never starts


async def test_disabled_still_tracks_where_the_desk_is():
    # Stats are attributed to the tracked position, so the sync must keep
    # running with automation off — that's the whole point of manual use.
    d = Driver(cfg=_disabled())
    await d.start()
    d.desk.height = STAND_H  # moved by hand
    events = await d.tick(dt=5 * 60)
    synced = [e for e in events if isinstance(e, StateSynced)]
    assert synced and synced[0].current is DeskState.STANDING
    assert d.m.state is DeskState.STANDING


async def test_disabled_never_holds_off_cycle():
    # "Automation paused — the desk was moved to an unrecognized position" is
    # nonsense when automation is already off; a desk parked at an arbitrary
    # height is just normal manual use.
    d = Driver(cfg=_disabled())
    await d.start()
    d.desk.height = OFF_CYCLE_H
    events = await d.tick(dt=5 * 60)
    assert not any(isinstance(e, HeldOffCycle) for e in events)
    assert not d.m.held
    assert d.m.status(d.now) is Status.DISABLED


async def test_enabling_starts_a_fresh_cycle_not_an_overdue_one():
    # Re-enabling must not inherit the accumulator: resuming a cycle that was
    # already due would move the desk seconds after the toggle.
    d = Driver()
    await d.start()
    await d.run_active_ticks(40)
    assert d.m.active_time > Duration.from_seconds(0)
    d.cfg.automation.enabled = False
    d.m.update_config(d.cfg)
    assert d.m.active_time == Duration.from_seconds(0)
    assert d.m.target_duration == Duration.from_seconds(0)

    d.cfg.automation.enabled = True
    d.m.update_config(d.cfg)
    assert d.m.active_time == Duration.from_seconds(0)
    assert d.m.target_duration == Duration.from_seconds(45 * 60)
    assert d.m.status(d.now) is not Status.DISABLED


async def test_disabling_mid_cycle_stops_an_overdue_move():
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration  # a move is due right now
    d.cfg.automation.enabled = False
    d.m.update_config(d.cfg)
    await d.tick()
    assert d.desk.move_calls == []


# ----- pause / snooze / schedule / skip -----

async def test_pause_freezes_clock_and_blocks_transitions():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    d.m.pause()
    await d.run_active_ticks(60)
    assert d.m.active_time == Duration.from_seconds(600)  # frozen, not reset
    assert d.desk.move_calls == []
    assert d.m.status(d.now) is Status.PAUSED
    d.m.resume()
    await d.run_active_ticks(1)
    assert d.m.active_time == Duration.from_seconds(660)
    assert d.m.status(d.now) is Status.ACTIVE


async def test_snooze_freezes_until_expiry():
    d = Driver()
    await d.start()
    await d.run_active_ticks(5)
    d.m.snooze(10, d.now)
    with pytest.raises(TypeError):
        d.m.snooze_until + 1
    await d.run_active_ticks(9)  # 9 min < 10 min snooze
    assert d.m.active_time == Duration.from_seconds(300)
    assert d.m.status(d.now) is Status.SNOOZED
    await d.tick()  # equality is expired, not another snoozed tick
    assert d.m.snooze_until is None
    assert d.m.active_time > Duration.from_seconds(300)
    assert d.m.status(d.now) is Status.ACTIVE


async def test_resume_clears_snooze():
    d = Driver()
    await d.start()
    d.m.snooze(30, d.now)
    d.m.resume()
    assert d.m.status(d.now) is Status.ACTIVE


async def test_out_of_schedule_freezes():
    cfg = make_config()
    cfg.schedule.enabled = True
    cfg.schedule.days = ["mon", "tue", "wed", "thu", "fri"]
    cfg.schedule.start = "09:00"
    cfg.schedule.end = "17:00"
    # Friday inside the window first, so there is progress to freeze. Asserting
    # active_time == 0 from a standing start (as this did) cannot tell a freeze
    # from a reset — the two differ by exactly what happens to existing credit.
    friday_noon = datetime(2026, 7, 17, 12, 0).timestamp()
    d = Driver(cfg=cfg, now=friday_noon)
    await d.start()
    await d.run_active_ticks(10)
    assert d.m.active_time == Duration.from_seconds(600)
    assert d.m.status(d.now) is Status.ACTIVE

    # ...then step to Saturday, outside the schedule.
    d.now = WallInstant(datetime(2026, 7, 18, 12, 0).timestamp())
    d.m._last_check = d.now
    await d.run_active_ticks(10)
    assert d.m.active_time == Duration.from_seconds(600), "out-of-schedule reset the cycle, not froze it"
    assert d.desk.move_calls == []
    assert d.m.status(d.now) is Status.OUT_OF_SCHEDULE


async def test_in_schedule_runs_normally():
    cfg = make_config()
    cfg.schedule.enabled = True
    friday_ten = datetime(2026, 7, 17, 10, 0).timestamp()
    d = Driver(cfg=cfg, now=friday_ten)
    await d.start()
    await d.run_active_ticks(10)
    assert d.m.active_time == Duration.from_seconds(600)


async def test_skip_next_consumes_one_transition():
    d = Driver()
    await d.start()
    d.m.request_skip_next()
    d.m.active_time = d.m.target_duration
    events = await d.tick()
    assert any(isinstance(e, TransitionSkipped) for e in events)
    assert d.desk.move_calls == []
    assert d.m.state is DeskState.SITTING
    assert d.m.active_time == Duration.from_seconds(0)
    assert d.m.skip_next is False
    # The following cycle transitions normally.
    d.m.active_time = d.m.target_duration
    await d.tick()
    assert d.m.state is DeskState.STANDING


# ----- cycle_target: what a log line may promise (rule 1, docs/LOGGING.md) -----

async def test_cycle_target_is_the_running_cycle():
    d = Driver()
    await d.start()
    assert d.m.cycle_target(d.now) == 45 * 60


async def test_cycle_target_is_zero_while_frozen():
    """Pause, snooze and the schedule stop the clock with no scheduled end, so
    a "next change after ..." note would promise a move that isn't coming.
    Reading target_duration alone reported one for all three."""
    d = Driver()
    await d.start()
    d.m.pause()
    assert d.m.cycle_target(d.now) == 0
    d.m.resume()
    assert d.m.cycle_target(d.now) == 45 * 60

    d.m.snooze(10, d.now)
    assert d.m.cycle_target(d.now) == 0
    d.m.resume()

    d.m.held = True
    assert d.m.cycle_target(d.now) == 0
    d.m.held = False

    d.m.unconfigured = True
    assert d.m.cycle_target(d.now) == 0


async def test_cycle_target_is_zero_out_of_schedule():
    cfg = make_config()
    cfg.schedule.enabled = True
    saturday_noon = datetime(2026, 7, 18, 12, 0).timestamp()
    d = Driver(cfg=cfg, now=saturday_noon)
    await d.start()
    assert d.m.cycle_target(d.now) == 0


async def test_cycle_target_survives_a_lock():
    """Being idle or locked stops the accumulator advancing, but the cycle in
    progress is still this one — and those are exactly the lines that need to
    say what it is."""
    d = Driver()
    await d.start()
    await d.tick(idle_ms=1000, locked=True)
    assert d.m.status(d.now) is Status.LOCKED
    assert d.m.cycle_target(d.now) == 45 * 60
