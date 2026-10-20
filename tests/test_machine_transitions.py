"""Movement gates, interruptions, failures and moving callbacks."""

import pytest

from idasen_companion.core.lengths import Length
from idasen_companion.core.durations import Duration
from idasen_companion.core.machine import (
    DeskState,
    MoveFailed,
    StateMachine,
    Status,
    TransitionCompleted,
    TransitionHeldForInput,
)

from machine_helpers import (
    SIT_H,
    STAND_H,
    OFF_CYCLE_H,
    make_config,
    ZeroRng,
    Driver,
)


# ----- the two-threshold movement gate -----

async def test_transition_fires_when_recently_active():
    d = Driver()
    await d.start()
    events = await d.run_active_ticks(45)  # reaches 2700s target
    completed = [e for e in events if isinstance(e, TransitionCompleted)]
    assert len(completed) == 1
    assert completed[0].result is DeskState.STANDING
    assert d.desk.move_calls == [STAND_H]
    assert d.m.state is DeskState.STANDING
    assert d.m.active_time == Duration.from_seconds(0)
    assert d.m.target_duration == Duration.from_seconds(25 * 60)


async def test_desk_does_not_move_in_ambiguous_idle_window():
    """Idle 4 min: below the lenient threshold (time accumulates) but above
    the strict recent-input threshold (desk must not move)."""
    d = Driver()
    await d.start()
    ambiguous = 4 * 60 * 1000
    events = await d.run_active_ticks(50, idle_ms=ambiguous)
    assert d.m.active_time >= d.m.target_duration  # transition is due...
    assert d.desk.move_calls == []  # ...but the desk stayed put
    assert not any(isinstance(e, TransitionCompleted) for e in events)
    # The moment input becomes recent, the pending transition fires.
    events = await d.tick(idle_ms=1000)
    assert [e for e in events if isinstance(e, TransitionCompleted)]
    assert d.desk.move_calls == [STAND_H]


async def test_a_hold_for_input_is_reported_once_and_re_arms():
    """The gate is otherwise invisible: a move waiting for the user and a move
    that was never due look identical in the log. Report it — but once per
    hold, not once per tick, and again if a later cycle is held too."""
    d = Driver()
    await d.start()
    ambiguous = 4 * 60 * 1000  # accumulates time, but too idle to move
    events = await d.run_active_ticks(50, idle_ms=ambiguous)
    holds = [e for e in events if isinstance(e, TransitionHeldForInput)]
    assert len(holds) == 1
    assert holds[0].idle_ms == ambiguous
    assert holds[0].threshold_seconds == 3 * 60
    assert d.desk.move_calls == []

    # Input returns: the pending move fires and the latch re-arms.
    events = await d.tick(idle_ms=1000)
    assert [e for e in events if isinstance(e, TransitionCompleted)]
    assert not [e for e in events if isinstance(e, TransitionHeldForInput)]

    events = await d.run_active_ticks(50, idle_ms=ambiguous)
    assert len([e for e in events if isinstance(e, TransitionHeldForInput)]) == 1


async def test_no_hold_reported_before_the_transition_is_due():
    """Being idle early in a cycle isn't news — nothing was waiting to move."""
    d = Driver()
    await d.start()
    events = await d.run_active_ticks(5, idle_ms=4 * 60 * 1000)
    assert not [e for e in events if isinstance(e, TransitionHeldForInput)]


async def test_desk_does_not_move_while_locked():
    d = Driver()
    await d.start()
    d.m.active_time = Duration.from_seconds(10_000)  # past target
    await d.tick(idle_ms=0, locked=True)
    assert d.desk.move_calls == []


# ----- interruption detection and the interruption policy -----

async def _interrupted_transition(policy, at=Length(0.95)):
    """Run one due transition that the paddle stops at ``at`` metres under
    ``interruption_policy``, and hand back the driver plus the event."""
    cfg = make_config()
    cfg.automation.interruption_policy = policy
    d = Driver(cfg=cfg)
    await d.start()
    d.m.active_time = d.m.target_duration
    d.desk.interrupt_next_move_at = at  # grabbed the paddle mid-move
    events = await d.tick()
    return d, [e for e in events if isinstance(e, TransitionCompleted)][0]


async def test_undo_policy_returns_to_original_state():
    d, completed = await _interrupted_transition("undo")
    assert completed.interrupted is True
    assert completed.recovery == "undo"
    assert completed.result is DeskState.SITTING  # back to original
    assert d.desk.move_calls == [STAND_H, SIT_H]  # exactly one recovery move
    assert d.m.state is DeskState.SITTING


async def test_leave_policy_accepts_where_the_desk_stopped():
    """0.95m classifies as 'standing' but is NOT within tolerance of the
    1.10m target — the reference treats this as interrupted."""
    d, completed = await _interrupted_transition("leave")
    assert completed.interrupted is True
    assert completed.recovery == "none"
    assert completed.result is DeskState.STANDING  # classified, accepted
    assert d.desk.move_calls == [STAND_H]  # no recovery move
    assert d.m.state is DeskState.STANDING


async def test_retry_policy_moves_toward_the_target_again():
    d, completed = await _interrupted_transition("retry")
    assert completed.interrupted is True
    assert completed.recovery == "retry"
    assert completed.result is DeskState.STANDING  # reached on the second try
    assert completed.final_height.metres == pytest.approx(STAND_H.metres)
    assert d.desk.move_calls == [STAND_H, STAND_H]
    assert d.m.state is DeskState.STANDING


@pytest.mark.parametrize("policy,recovered", [("undo", SIT_H), ("retry", STAND_H)])
async def test_second_interruption_is_accepted_not_fought(policy, recovered):
    """Recovery is attempted exactly once. A user (or an obstruction) stopping
    the desk twice in a row is taken at its word: the height it landed on is
    classified and accepted, with no third move."""
    cfg = make_config()
    cfg.automation.interruption_policy = policy
    d = Driver(cfg=cfg)
    await d.start()
    d.m.active_time = d.m.target_duration
    d.desk.interrupt_next_move_at = Length(0.95)

    # First move lands at 0.95; make the recovery move also land off-target.
    original_move_to = d.desk.move_to

    async def move_to(height):
        if d.desk.move_calls:  # this is the recovery move
            d.desk.interrupt_next_move_at = Length(0.90)
        return await original_move_to(height)

    d.desk.move_to = move_to
    events = await d.tick()
    completed = [e for e in events if isinstance(e, TransitionCompleted)][0]
    assert completed.interrupted and completed.recovery == policy
    assert d.desk.move_calls == [STAND_H, recovered]  # no third attempt
    assert completed.result is DeskState.STANDING  # classify(0.90) > 0.88
    assert d.m.state is DeskState.STANDING


async def test_unreadable_height_after_move_assumes_intended():
    # Command accepted, only the verification read failed: keep the reference
    # script's optimism. Contrast with the unreachable-desk test below.
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration

    async def move_then_lose_height(height):
        d.desk.height = height
        d.desk.height_unavailable = True
        d.desk.move_calls.append(height)
        return True

    d.desk.move_to = move_then_lose_height
    events = await d.tick()
    completed = [e for e in events if isinstance(e, TransitionCompleted)][0]
    assert completed.final_height is None
    assert completed.result is DeskState.STANDING
    assert d.m.state is DeskState.STANDING


async def test_unreachable_desk_reports_failure_instead_of_success():
    # Both the command and the read-back fail — an unreachable desk. Claiming
    # a completed transition here flipped the state, logged a success and
    # wrote a stats row for a move that never happened.
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration
    d.desk.fail_next_move = True
    d.desk.height_unavailable = True
    events = await d.tick()
    failed = [e for e in events if isinstance(e, MoveFailed)]
    assert len(failed) == 1
    assert failed[0].intended is DeskState.STANDING
    assert failed[0].previous is DeskState.SITTING
    assert not any(isinstance(e, TransitionCompleted) for e in events)
    assert d.m.state is DeskState.SITTING


async def test_failed_move_is_retried_on_the_next_cycle():
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration
    d.desk.fail_next_move = True
    d.desk.height_unavailable = True
    await d.tick()
    assert d.m.active_time == Duration.from_seconds(0)  # fresh cycle, still sitting
    d.desk.height_unavailable = False
    d.m.active_time = d.m.target_duration
    events = await d.tick()
    completed = [e for e in events if isinstance(e, TransitionCompleted)][0]
    assert completed.result is DeskState.STANDING


async def test_failed_move_shows_in_the_status():
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration
    d.desk.fail_next_move = True
    d.desk.height_unavailable = True
    await d.tick()
    assert d.m.status(d.now) is Status.MOVE_FAILED


async def test_successful_move_clears_the_failed_status():
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration
    d.desk.fail_next_move = True
    d.desk.height_unavailable = True
    await d.tick()
    assert d.m.status(d.now) is Status.MOVE_FAILED
    d.desk.height_unavailable = False
    d.m.active_time = d.m.target_duration
    await d.tick()
    assert d.m.status(d.now) is Status.ACTIVE
    assert d.m.move_failed is False


async def test_failed_status_yields_to_the_users_own_intent():
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration
    d.desk.fail_next_move = True
    d.desk.height_unavailable = True
    await d.tick()
    assert d.m.status(d.now) is Status.MOVE_FAILED

    d.m.pause()
    assert d.m.status(d.now) is Status.PAUSED
    d.m.resume()

    events = await d.tick(locked=True)
    assert d.m.status(d.now) is Status.LOCKED
    events = await d.tick(locked=False, idle_ms=20 * 60 * 1000)
    assert d.m.status(d.now) is Status.USER_IDLE


async def test_failed_move_still_reports_a_running_cycle():
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration
    d.desk.fail_next_move = True
    d.desk.height_unavailable = True
    await d.tick()
    assert d.m.status(d.now) is Status.MOVE_FAILED
    assert d.m.cycle_target(d.now) == 45 * 60


async def test_failed_command_still_verifies_when_height_is_readable():
    # A failed command doesn't prove nothing moved (the error can land
    # mid-travel), so a readable height still wins over the return value.
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration

    async def fail_but_move_partway(height):
        d.desk.height = OFF_CYCLE_H
        d.desk.move_calls.append(height)
        return False

    d.desk.move_to = fail_but_move_partway
    events = await d.tick()
    assert not any(isinstance(e, MoveFailed) for e in events)
    completed = [e for e in events if isinstance(e, TransitionCompleted)][0]
    assert completed.interrupted


async def test_move_within_tolerance_counts_as_completed():
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration
    d.desk.interrupt_next_move_at = STAND_H - Length(0.015)  # within ±0.02
    events = await d.tick()
    completed = [e for e in events if isinstance(e, TransitionCompleted)][0]
    assert completed.interrupted is False
    assert d.m.state is DeskState.STANDING


# ----- Desk1.Moving during an automation move -----

async def test_an_automation_move_reports_moving_true_then_false():
    """`Desk1.Moving` was set only by the daemon's *manual* move path, so it
    was never true while automation drove the desk: the window and tray showed
    it stationary mid-travel, and the tray's repeat-to-cancel gesture — which
    tests exactly this flag — could not cancel an automation move and started
    a competing one instead."""
    seen = []
    cfg = make_config()
    d = Driver(cfg=cfg)
    d.m = StateMachine(cfg, d.desk, now=d.now, rng=ZeroRng(),
                       on_moving=seen.append)
    await d.m.start(d.now)

    await d.run_active_ticks(45)          # reaches the 2700s sit target

    assert d.desk.move_calls == [STAND_H], "no move to observe"
    assert seen == [True, False], f"Moving not published around the move: {seen}"


async def test_moving_goes_false_even_when_the_move_fails():
    seen = []
    cfg = make_config()
    d = Driver(cfg=cfg)
    d.m = StateMachine(cfg, d.desk, now=d.now, rng=ZeroRng(),
                       on_moving=seen.append)
    await d.m.start(d.now)
    d.desk.fail_next_move = True

    await d.run_active_ticks(45)

    assert seen and seen[-1] is False, f"left Moving stuck true: {seen}"


async def test_no_moving_signal_when_no_transition_happens():
    seen = []
    cfg = make_config()
    d = Driver(cfg=cfg)
    d.m = StateMachine(cfg, d.desk, now=d.now, rng=ZeroRng(),
                       on_moving=seen.append)
    await d.m.start(d.now)
    await d.run_active_ticks(5)           # nowhere near due
    assert seen == []


async def test_arrival_tolerance_includes_exact_edge_and_rejects_next_float():
    import math

    cfg = make_config(interruption_policy="leave")
    # A supported binary-exact tolerance isolates inclusivity from subtraction
    # roundoff; the default 0.02 is covered by the existing near-target case.
    cfg.advanced.movement_tolerance = 0.03125
    d = Driver(cfg=cfg)
    edge = cfg.presets["stand"] - cfg.advanced.movement_tolerance
    d.desk.interrupt_next_move_at = Length(edge)
    exact, = await d.m._execute_transition(d.now)
    assert exact.interrupted is False
    d.m.state = DeskState.SITTING
    d.desk.interrupt_next_move_at = Length(math.nextafter(edge, -math.inf))
    outside, = await d.m._execute_transition(d.now)
    assert outside.interrupted is True
    assert len(d.desk.move_calls) == 2  # leave never adds a recovery
