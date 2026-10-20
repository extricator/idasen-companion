"""Cycle variation, restart events, remaining time and status contracts."""

from idasen_companion.core.durations import Duration

from idasen_companion.core.machine import (
    DeskState,
    MoveFailed,
    ResumedOnCycle,
    StateSynced,
    Status,
    TransitionCompleted,
)

from machine_helpers import (
    STAND_H,
    OFF_CYCLE_H,
    make_config,
    MaxRng,
    Driver,
)


# ----- cycle variation -----

async def test_variation_adds_up_to_max_whole_minutes():
    cfg = make_config(sit_variation=10 * 60, stand_variation=5 * 60)
    d = Driver(cfg=cfg, rng=MaxRng())
    await d.start()
    assert d.m.target_duration == Duration.from_seconds(45 * 60 + 10 * 60)  # sit base + max variation
    d.m.active_time = d.m.target_duration
    await d.tick()
    assert d.m.state is DeskState.STANDING
    assert d.m.target_duration == Duration.from_seconds(25 * 60 + 5 * 60)


async def test_variation_rounds_partial_minutes_up():
    # 90s variation -> ceil(90/60) = 2 whole minutes max, like the reference.
    cfg = make_config(sit_variation=90)
    d = Driver(cfg=cfg, rng=MaxRng())
    await d.start()
    assert d.m.target_duration == Duration.from_seconds(45 * 60 + 2 * 60)


# ----- the new cycle's length rides along on every restart -----

async def test_completed_transition_reports_the_new_cycle_length():
    # The log line after a scheduled move should be able to say when the next
    # one is due, so the event carries the duration _begin_cycle just rolled.
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration
    events = await d.tick()
    completed = [e for e in events if isinstance(e, TransitionCompleted)][0]
    assert completed.next_target_duration == Duration.from_seconds(25 * 60)  # now standing
    assert completed.next_target_duration == d.m.target_duration


async def test_failed_move_reports_the_new_cycle_length():
    # Nothing moved, but a fresh cycle still started in the same state — the
    # retry window is a real number, not "next cycle".
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration
    d.desk.height_unavailable = True

    async def refuse(height):
        return False

    d.desk.move_to = refuse
    events = await d.tick()
    failed = [e for e in events if isinstance(e, MoveFailed)][0]
    assert failed.next_target_duration == Duration.from_seconds(45 * 60)  # still sitting


async def test_adopted_external_move_reports_the_new_cycle_length():
    d = Driver()
    await d.start()
    await d.run_active_ticks(3)
    d.desk.height = STAND_H  # someone used the paddle
    events = await d.tick(dt=5 * 60)
    synced = [e for e in events if isinstance(e, StateSynced)][0]
    assert synced.next_target_duration == Duration.from_seconds(25 * 60)


async def test_resume_from_held_reports_the_new_cycle_length():
    d = Driver()
    await d.start()
    d.desk.height = OFF_CYCLE_H
    await d.tick(dt=5 * 60)
    assert d.m.held
    d.desk.height = STAND_H
    events = await d.tick(dt=5 * 60)
    resumed = [e for e in events if isinstance(e, ResumedOnCycle)][0]
    assert resumed.next_target_duration == Duration.from_seconds(25 * 60)


# ----- status extras -----

async def test_status_reflects_lock_and_idle():
    d = Driver()
    await d.start()
    await d.tick(idle_ms=0, locked=True)
    assert d.m.status(d.now) is Status.LOCKED
    await d.tick(idle_ms=11 * 60 * 1000)
    assert d.m.status(d.now) is Status.USER_IDLE
    await d.tick(idle_ms=1000)
    assert d.m.status(d.now) is Status.ACTIVE


async def test_time_remaining_countdown():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    assert d.m.time_remaining() == Duration.from_seconds(45 * 60 - 600)


async def test_config_hot_reload_recomputes_target_keeps_active_time():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    new_cfg = make_config(sit_duration=30 * 60)
    new_cfg.presets = dict(d.cfg.presets)
    d.m.update_config(new_cfg)
    assert d.m.active_time == Duration.from_seconds(600)  # kept
    assert d.m.target_duration == Duration.from_seconds(30 * 60)  # new duration effective now


# ----- the status sets the GUI shares -----

def test_the_status_sets_cover_every_status_exactly_once_where_they_should():
    """These three sets are consumed by the tray, the Overview and the daemon.
    They used to be restated there as bare tuples — 4 sites each — so adding a
    status meant finding every literal by grep, and MOVE_FAILED's membership in
    the countdown set (a failed move does *not* stop the cycle) is exactly the
    subtlety that gets dropped when a set is retyped by hand.
    """
    from idasen_companion.core.machine import (
        COUNTDOWN_STATUSES, NO_CYCLE_STATUSES, RESUMABLE_STATUSES,
    )
    all_statuses = set(Status)

    # Every status is either counting down or not; nothing may be both.
    assert not (COUNTDOWN_STATUSES & NO_CYCLE_STATUSES)
    assert COUNTDOWN_STATUSES | NO_CYCLE_STATUSES <= all_statuses

    # Resumable is a subset of the frozen ones — you cannot resume a cycle
    # that is already running.
    assert RESUMABLE_STATUSES <= NO_CYCLE_STATUSES

    # A status in neither set is a status nobody decided about. USER_IDLE and
    # the presence states are deliberately in neither: the clock is frozen but
    # it thaws by itself, so there is nothing to resume and nothing to render.
    undecided = all_statuses - COUNTDOWN_STATUSES - NO_CYCLE_STATUSES
    assert undecided == {Status.USER_IDLE, Status.LOCKED, Status.AWAY,
                         Status.NO_SESSION}, undecided


def test_a_failed_move_still_counts_as_a_running_cycle():
    from idasen_companion.core.machine import COUNTDOWN_STATUSES
    assert Status.MOVE_FAILED in COUNTDOWN_STATUSES
