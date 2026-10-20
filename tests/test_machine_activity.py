"""Active-time accounting, clock changes and session presence."""

from idasen_companion.core.machine import (
    AwayChanged,
    DeskState,
    IdleChanged,
    SeatChanged,
    StateSynced,
    Status,
    TimeJumpDetected,
    TransitionCompleted,
)
from idasen_companion.core.durations import Duration

from machine_helpers import (
    STAND_H,
    OFF_CYCLE_H,
    make_config,
    Driver,
)


# ----- active time accounting -----

async def test_active_time_accumulates_while_active():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    assert d.m.active_time == Duration.from_seconds(600)


async def test_idle_stops_accumulation_lenient_threshold():
    d = Driver()
    await d.start()
    await d.run_active_ticks(5)
    # 11 minutes idle >= 10 minute threshold -> idle, no accumulation
    await d.tick(idle_ms=11 * 60 * 1000)
    assert d.m.active_time == Duration.from_seconds(300)
    assert d.m.is_idle is True


async def test_below_lenient_threshold_still_accumulates():
    d = Driver()
    await d.start()
    # 4 minutes idle < 10 minute lenient threshold -> still "active time"
    await d.run_active_ticks(5, idle_ms=4 * 60 * 1000)
    assert d.m.active_time == Duration.from_seconds(300)
    assert d.m.is_idle is False


async def test_lock_counts_as_idle_regardless_of_idle_ms():
    d = Driver()
    await d.start()
    await d.tick(idle_ms=0, locked=True)
    assert d.m.is_idle is True
    assert d.m.active_time == Duration.from_seconds(0)


async def test_activity_after_idle_resets_accumulator():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)  # 600s accumulated
    await d.tick(idle_ms=11 * 60 * 1000)  # go idle
    assert d.m.active_time == Duration.from_seconds(600)  # kept while idle...
    await d.tick(idle_ms=1000)  # activity resumes
    # ...but reset on the idle->active edge; the resume tick itself counts.
    assert d.m.active_time == Duration.from_seconds(60)


async def test_time_jump_resets_without_accumulating():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    events = await d.tick(dt=400)  # > TIME_JUMP_THRESHOLD_SECONDS (300)
    assert any(isinstance(e, TimeJumpDetected) for e in events)
    assert d.m.active_time == Duration.from_seconds(0)


async def test_time_jump_keeps_exact_300_seconds_but_rejects_the_next_float():
    d = Driver()
    await d.start()
    exact_events = await d.tick(dt=300)
    assert not any(isinstance(event, TimeJumpDetected) for event in exact_events)
    assert d.m.active_time == Duration.from_seconds(300)

    events = await d.tick(dt=300 + 2**-22)
    jump = next(event for event in events if isinstance(event, TimeJumpDetected))
    assert jump.elapsed == Duration.from_seconds(300 + 2**-22)
    assert d.m.active_time == Duration.from_seconds(0)


async def test_time_jump_threshold_is_absolute_not_scaled_off_check_interval():
    # The threshold is deliberately a flat 300s rather than a multiple of
    # check_interval (see TIME_JUMP_THRESHOLD_SECONDS). Both cases below agree
    # under the absolute rule and disagree under the reference script's
    # "5 * check_interval" rule, so this fails if anyone re-couples them.
    d = Driver(cfg=make_config(check_interval=600))
    await d.start()
    events = await d.tick(dt=400)  # 400 > 300, but < 5 * 600
    assert any(isinstance(e, TimeJumpDetected) for e in events)

    d = Driver(cfg=make_config(check_interval=30))
    await d.start()
    await d.run_active_ticks(5, dt=30)
    events = await d.tick(dt=200)  # 200 < 300, but > 5 * 30
    assert not any(isinstance(e, TimeJumpDetected) for e in events)


async def test_backward_clock_step_resets_instead_of_subtracting():
    # A wall-clock correction can step *backwards* (NTP after a long offline
    # stretch, a dual-boot RTC fix, a restored snapshot). Letting a negative
    # elapsed through would subtract from active_time, silently pushing the
    # next move further out with nothing logged.
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    accumulated = d.m.active_time
    assert accumulated == Duration.from_seconds(600)

    events = await d.tick(dt=-3600)
    assert any(isinstance(e, TimeJumpDetected) for e in events)
    assert d.m.active_time == Duration.from_seconds(0)
    assert d.m.time_remaining() <= d.m.target_duration


async def test_small_backward_step_is_still_a_jump():
    # Any backward step is impossible for a real tick, so there is no
    # "small enough to just accumulate" case.
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    events = await d.tick(dt=-5)
    assert any(isinstance(e, TimeJumpDetected) for e in events)
    assert d.m.active_time == Duration.from_seconds(0)


async def test_reset_after_resume_matches_time_jump_effect():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    d.m.reset_after_resume()
    assert d.m.active_time == Duration.from_seconds(0)
    assert d.m.is_idle is False


# ----- away in another session (VT switch / fast-user-switch) -----

async def test_away_blocks_movement_and_accounting():
    d = Driver()
    await d.start()
    await d.run_active_ticks(5)  # 300s accumulated
    d.m.active_time = Duration.from_seconds(10_000)  # past target
    events = await d.tick(idle_ms=0, away=True)
    assert d.desk.move_calls == []  # never move while away
    assert not any(isinstance(e, TransitionCompleted) for e in events)
    # Accounting is frozen while away (no accumulation).
    before = d.m.active_time
    await d.run_active_ticks(3, idle_ms=0, away=True)
    assert d.m.active_time == before


async def test_away_reports_away_status_over_locked():
    d = Driver()
    await d.start()
    await d.tick(idle_ms=0, away=True)
    assert d.m.status(d.now) is Status.AWAY
    # Away is more specific than lock when both hold.
    await d.tick(idle_ms=0, locked=True, away=True)
    assert d.m.status(d.now) is Status.AWAY


async def test_away_emits_awaychanged_not_idlechanged():
    d = Driver()
    await d.start()
    events = await d.tick(idle_ms=1000, away=True)
    assert [e for e in events if isinstance(e, AwayChanged)][0].away is True
    assert not any(isinstance(e, IdleChanged) for e in events)
    # Returning emits AwayChanged(False), again without an IdleChanged.
    events = await d.tick(idle_ms=1000, away=False)
    assert [e for e in events if isinstance(e, AwayChanged)][0].away is False
    assert not any(isinstance(e, IdleChanged) for e in events)


async def test_long_absence_in_another_session_resets_accumulator():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)  # 600s accumulated
    await d.run_active_ticks(10, idle_ms=0, away=True)  # 10 min elsewhere
    assert d.m.active_time == Duration.from_seconds(600)  # kept while away
    await d.tick(idle_ms=1000, away=False)  # back in session, active
    # A real break abandons the approach; the returning tick itself counts.
    assert d.m.active_time == Duration.from_seconds(60)
    assert d.m.status(d.now) is Status.ACTIVE


async def test_a_brief_lock_does_not_cost_the_whole_cycle():
    """Lock and away flip the idle flag instantly, with no duration attached,
    so a 60-second interruption used to throw away 44 minutes of sitting —
    on every install, shared machine or not."""
    d = Driver()
    await d.start()
    await d.run_active_ticks(40)  # 2400s of a 45-minute sit target
    await d.tick(idle_ms=0, locked=True)
    await d.tick(idle_ms=0, locked=False)
    # Progress survives; the locked tick itself is still not credited, since
    # that minute genuinely wasn't spent at the desk.
    assert d.m.active_time == Duration.from_seconds(2400 + 60)


async def test_a_brief_switch_to_another_session_does_not_cost_the_cycle():
    d = Driver()
    await d.start()
    await d.run_active_ticks(40)
    await d.tick(idle_ms=0, away=True)
    events = await d.tick(idle_ms=0, away=False)
    assert d.m.active_time == Duration.from_seconds(2400 + 60)  # the away tick itself isn't credited
    assert [e for e in events if isinstance(e, AwayChanged)][0].reset is False


async def test_plain_idleness_still_resets_however_it_is_measured():
    """Reference parity where it is specified: plain idleness cannot be
    noticed until it has already run past the threshold, so it always counts
    as a real break — the backdating must not accidentally forgive it."""
    d = Driver()
    await d.start()
    await d.run_active_ticks(20)
    # One tick reporting idleness just past the threshold, then activity.
    await d.tick(idle_ms=601 * 1000)
    events = await d.tick(idle_ms=0)
    assert d.m.active_time == Duration.from_seconds(60)  # reset, then the returning tick counted
    assert [e for e in events if isinstance(e, IdleChanged)][0].reset is True


async def test_two_people_taking_turns_still_reach_a_transition():
    """The shared-desk payoff. Each user's turn is `away` from the other's
    daemon; short handovers must not zero the cycle every time or neither
    person's desk ever moves."""
    d = Driver()
    await d.start()
    for _ in range(6):
        await d.run_active_ticks(8, idle_ms=0)             # my 8 minutes
        await d.run_active_ticks(5, idle_ms=0, away=True)  # their 5 minutes
    # Not merely "something moved": a bug that moved the desk on every
    # away->back edge would satisfy a non-empty check. Exactly one transition,
    # to stand, is the property — 48 min of my own time against a 45 min sit.
    assert d.desk.move_calls == [STAND_H], (
        f"expected one sit->stand move, got {d.desk.move_calls}")


# ----- no graphical session at all (headless, SSH, pre-login) -----

async def test_seatless_never_moves_the_desk():
    """The sharpest bug this closes, and it isn't multi-user: with no session
    every presence signal fails open — the idle providers report a flat 0
    ("at the keyboard"), lock detection reports unlocked — so the daemon used
    to run a full cycle for someone at the end of an SSH connection."""
    d = Driver()
    await d.start()
    await d.run_active_ticks(120, idle_ms=0, seatless=True)  # 2h, target 45m
    assert d.desk.move_calls == []


async def test_seatless_suspends_desk_reads_and_accounting():
    d = Driver(make_config(sync_interval=60))
    await d.start()
    reads = d.desk.get_height_calls
    await d.run_active_ticks(10, idle_ms=0, seatless=True)
    assert d.desk.get_height_calls == reads
    assert d.m.active_time == Duration.from_seconds(0)


async def test_seatless_reports_its_own_status_not_away():
    d = Driver()
    await d.start()
    await d.tick(idle_ms=0, seatless=True)
    assert d.m.status(d.now) is Status.NO_SESSION


async def test_gaining_a_session_resumes_and_reads_the_desk():
    """A daemon that started before login must come alive when its user logs
    in, rather than staying inert until something restarts it."""
    d = Driver(make_config(sync_interval=60 * 60))
    await d.start()
    await d.tick(idle_ms=0, seatless=True)
    assert [e for e in (await d.tick(idle_ms=0, seatless=True))
            if isinstance(e, SeatChanged)] == []  # edge fires once, not per tick
    d.desk.height = STAND_H  # someone with a session used it meanwhile
    events = await d.tick(idle_ms=1000, seatless=False)
    assert [e for e in events if isinstance(e, SeatChanged)][0].has_seat is True
    assert d.m.state is DeskState.STANDING  # reconciled on the way back


async def test_away_suspends_the_periodic_desk_read():
    """The desk is shared and takes one client at a time, so a backgrounded
    session must not keep polling it: the reading is one this session is barred
    from acting on, bought by competing for the single connection slot with the
    session that is actually in front."""
    d = Driver(make_config(sync_interval=60))
    await d.start()
    reads = d.desk.get_height_calls
    await d.run_active_ticks(10, idle_ms=0, away=True)
    assert d.desk.get_height_calls == reads


async def test_away_suspends_the_held_off_cycle_poll():
    """The held-desk fallback poll ignores sync_interval = 0 so a desk parked
    off-cycle is noticed when it comes back — but it must yield to another
    session too, or one account keeps connecting every few minutes for as long
    as the desk stays parked."""
    d = Driver(make_config(sync_interval=0), height=OFF_CYCLE_H)
    await d.start()
    assert d.m.held
    reads = d.desk.get_height_calls
    await d.run_active_ticks(20, idle_ms=0, away=True)  # 20 min > HELD_POLL_INTERVAL
    assert d.desk.get_height_calls == reads


async def test_return_from_away_reads_the_desk_unconditionally():
    """Whoever was in front may have moved the desk, however brief the switch,
    so coming back reconciles immediately rather than waiting out the periodic
    sync timer."""
    d = Driver(make_config(sync_interval=60 * 60))  # periodic sync nowhere near due
    await d.start()
    await d.tick(idle_ms=0, away=True)
    d.desk.height = STAND_H  # moved by the session that was in front
    events = await d.tick(idle_ms=1000, away=False)
    synced = [e for e in events if isinstance(e, StateSynced)]
    assert synced and synced[0].current is DeskState.STANDING
    assert d.m.state is DeskState.STANDING
