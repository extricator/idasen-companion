"""State machine tests against MockDesk with a fake clock.

Every behavior of the reference script is pinned here: the two idle
thresholds, lock-as-idle, activity-after-idle
reset, time-jump reset, cycle variation, periodic sync, and interruption
detection with single retry to the original state.
"""

import random
from datetime import datetime

import pytest

from idasen_companion.core.config import AppConfig
from idasen_companion.core.machine import (
    AwayChanged,
    DeskState,
    HeldOffCycle,
    IdleChanged,
    MoveFailed,
    ResumedOnCycle,
    SeatChanged,
    StateMachine,
    StateSynced,
    Status,
    SyncFailed,
    TimeJumpDetected,
    TransitionCompleted,
    TransitionHeldForInput,
    TransitionSkipped,
)
from idasen_companion.desk.mock import MockDesk

SIT_H = 0.62
STAND_H = 1.10
OFF_CYCLE_H = 0.95  # not within tolerance of either preset target


def make_config(**automation_overrides) -> AppConfig:
    cfg = AppConfig()
    a = cfg.automation
    a.sit_duration = 45 * 60
    a.stand_duration = 25 * 60
    a.sit_variation = 0  # deterministic by default
    a.stand_variation = 0
    a.check_interval = 60
    a.idle_threshold = 10 * 60
    a.recent_input_threshold = 3 * 60
    a.sync_interval = 5 * 60
    for key, value in automation_overrides.items():
        setattr(a, key, value)
    cfg.presets = {"sit": SIT_H, "stand": STAND_H}
    return cfg


class ZeroRng(random.Random):
    def randint(self, a, b):
        return 0


class MaxRng(random.Random):
    def randint(self, a, b):
        return b


class Driver:
    def __init__(self, cfg=None, height=SIT_H, rng=None, now=1_000_000.0):
        self.cfg = cfg or make_config()
        self.desk = MockDesk(height)
        self.now = now
        self.m = StateMachine(self.cfg, self.desk, now=self.now, rng=rng or ZeroRng())

    async def start(self):
        return await self.m.start(self.now)

    async def tick(self, dt=60, idle_ms=1000, locked=False, away=False,
                   seatless=False):
        self.now += dt
        return await self.m.tick(self.now, idle_ms, locked, away, seatless)

    async def run_active_ticks(self, n, **kw):
        events = []
        for _ in range(n):
            events.extend(await self.tick(**kw))
        return events


# ----- initial sync -----

async def test_start_classifies_current_height():
    d = Driver(height=STAND_H)
    await d.start()
    assert d.m.state is DeskState.STANDING
    assert d.m.target_duration == 25 * 60


async def test_start_adopts_state_without_emitting_transition():
    # Startup is initialization, not a transition: seeding the state from the
    # real height must not emit a StateSynced (which would record a phantom
    # "external" move into stats/log on every restart).
    d = Driver(height=STAND_H)
    events = await d.start()
    assert not any(isinstance(e, StateSynced) for e in events)
    assert d.m.state is DeskState.STANDING


async def test_start_with_unreadable_height_keeps_default():
    d = Driver()
    d.desk.height_unavailable = True
    await d.start()
    assert d.m.state is DeskState.SITTING
    assert d.m.target_duration == 45 * 60


# ----- toggle target (tray left-click / --toggle shortcut) -----

async def test_toggle_target_is_opposite_of_current_height():
    d = Driver(height=SIT_H)
    await d.start()
    assert d.m.toggle_target_preset() == "stand"
    d = Driver(height=STAND_H)
    await d.start()
    assert d.m.toggle_target_preset() == "sit"


async def test_toggle_target_off_cycle_uses_seeded_state():
    # Booted off-cycle above the preset midpoint -> state is seeded STANDING
    # from the real height, so a toggle heads back down to sit.
    d = Driver(height=OFF_CYCLE_H)
    await d.start()
    assert d.m.held is True
    assert d.m.state is DeskState.STANDING  # seeded from the real position
    assert d.m.toggle_target_preset() == "sit"


async def test_toggle_target_off_cycle_resumes_toward_state_not_position():
    # Interrupted going up: state stayed SITTING (where it came from) while the
    # desk is parked high, past the midpoint. Toggle keys off state, so it
    # resumes toward stand rather than flipping down to sit by position.
    d = Driver(height=SIT_H)
    await d.start()
    assert d.m.state is DeskState.SITTING
    d.m.last_height = 1.00  # parked high, off-cycle, but came from sitting
    assert d.m._cycle_state_for_height(1.00) is None
    assert d.m.toggle_target_preset() == "stand"


async def test_toggle_target_prefers_actual_preset_over_stale_state():
    # State says sitting but the desk is actually AT stand (external move):
    # the at-preset check wins over the stale state.
    d = Driver(height=SIT_H)
    await d.start()
    d.m.last_height = STAND_H
    assert d.m.toggle_target_preset() == "sit"


async def test_toggle_target_without_height_flips_state():
    d = Driver()
    d.desk.height_unavailable = True
    await d.start()  # keeps default SITTING, last_height stays None
    assert d.m.last_height is None
    assert d.m.toggle_target_preset() == "stand"


async def test_classify_boundary_is_the_preset_midpoint():
    # The sit/stand split tracks the presets, not a fixed constant. With
    # sit=0.70/stand=1.30 the midpoint is 1.00, so 0.95 is still "sitting"
    # (a fixed 0.88 threshold would have called it standing).
    cfg = make_config()
    cfg.presets = {"sit": 0.70, "stand": 1.30}
    d = Driver(cfg=cfg, height=0.95)
    await d.start()
    assert d.m._classify(0.95) is DeskState.SITTING
    assert d.m._classify(1.05) is DeskState.STANDING


# ----- active time accounting -----

async def test_active_time_accumulates_while_active():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    assert d.m.active_time == 600


async def test_idle_stops_accumulation_lenient_threshold():
    d = Driver()
    await d.start()
    await d.run_active_ticks(5)
    # 11 minutes idle >= 10 minute threshold -> idle, no accumulation
    await d.tick(idle_ms=11 * 60 * 1000)
    assert d.m.active_time == 300
    assert d.m.is_idle is True


async def test_below_lenient_threshold_still_accumulates():
    d = Driver()
    await d.start()
    # 4 minutes idle < 10 minute lenient threshold -> still "active time"
    await d.run_active_ticks(5, idle_ms=4 * 60 * 1000)
    assert d.m.active_time == 300
    assert d.m.is_idle is False


async def test_lock_counts_as_idle_regardless_of_idle_ms():
    d = Driver()
    await d.start()
    await d.tick(idle_ms=0, locked=True)
    assert d.m.is_idle is True
    assert d.m.active_time == 0


async def test_activity_after_idle_resets_accumulator():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)  # 600s accumulated
    await d.tick(idle_ms=11 * 60 * 1000)  # go idle
    assert d.m.active_time == 600  # kept while idle...
    await d.tick(idle_ms=1000)  # activity resumes
    # ...but reset on the idle->active edge; the resume tick itself counts.
    assert d.m.active_time == 60


async def test_time_jump_resets_without_accumulating():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    events = await d.tick(dt=400)  # > TIME_JUMP_THRESHOLD_SECONDS (300)
    assert any(isinstance(e, TimeJumpDetected) for e in events)
    assert d.m.active_time == 0


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
    assert accumulated == 600

    events = await d.tick(dt=-3600)
    assert any(isinstance(e, TimeJumpDetected) for e in events)
    assert d.m.active_time == 0
    assert d.m.time_remaining() <= d.m.target_duration


async def test_small_backward_step_is_still_a_jump():
    # Any backward step is impossible for a real tick, so there is no
    # "small enough to just accumulate" case.
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    events = await d.tick(dt=-5)
    assert any(isinstance(e, TimeJumpDetected) for e in events)
    assert d.m.active_time == 0


async def test_reset_after_resume_matches_time_jump_effect():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    d.m.reset_after_resume()
    assert d.m.active_time == 0
    assert d.m.is_idle is False


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
    assert d.m.active_time == 0
    assert d.m.target_duration == 25 * 60


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
    d.m.active_time = 10_000  # past target
    await d.tick(idle_ms=0, locked=True)
    assert d.desk.move_calls == []


# ----- away in another session (VT switch / fast-user-switch) -----

async def test_away_blocks_movement_and_accounting():
    d = Driver()
    await d.start()
    await d.run_active_ticks(5)  # 300s accumulated
    d.m.active_time = 10_000  # past target
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
    assert d.m.active_time == 600  # kept while away
    await d.tick(idle_ms=1000, away=False)  # back in session, active
    # A real break abandons the approach; the returning tick itself counts.
    assert d.m.active_time == 60
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
    assert d.m.active_time == 2400 + 60


async def test_a_brief_switch_to_another_session_does_not_cost_the_cycle():
    d = Driver()
    await d.start()
    await d.run_active_ticks(40)
    await d.tick(idle_ms=0, away=True)
    events = await d.tick(idle_ms=0, away=False)
    assert d.m.active_time == 2400 + 60  # the away tick itself isn't credited
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
    assert d.m.active_time == 60  # reset, then the returning tick counted
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
    assert d.m.active_time == 0


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


# ----- cycle variation -----

async def test_variation_adds_up_to_max_whole_minutes():
    cfg = make_config(sit_variation=10 * 60, stand_variation=5 * 60)
    d = Driver(cfg=cfg, rng=MaxRng())
    await d.start()
    assert d.m.target_duration == 45 * 60 + 10 * 60  # sit base + max variation
    d.m.active_time = d.m.target_duration
    await d.tick()
    assert d.m.state is DeskState.STANDING
    assert d.m.target_duration == 25 * 60 + 5 * 60


async def test_variation_rounds_partial_minutes_up():
    # 90s variation -> ceil(90/60) = 2 whole minutes max, like the reference.
    cfg = make_config(sit_variation=90)
    d = Driver(cfg=cfg, rng=MaxRng())
    await d.start()
    assert d.m.target_duration == 45 * 60 + 2 * 60


# ----- interruption detection and the interruption policy -----

async def _interrupted_transition(policy, at=0.95):
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
    assert completed.final_height == pytest.approx(STAND_H)
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
    d.desk.interrupt_next_move_at = 0.95

    # First move lands at 0.95; make the recovery move also land off-target.
    original_move_to = d.desk.move_to

    async def move_to(height):
        if d.desk.move_calls:  # this is the recovery move
            d.desk.interrupt_next_move_at = 0.90
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
    assert d.m.active_time == 0  # fresh cycle, still sitting
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
    d.desk.interrupt_next_move_at = STAND_H - 0.015  # within ±0.02
    events = await d.tick()
    completed = [e for e in events if isinstance(e, TransitionCompleted)][0]
    assert completed.interrupted is False
    assert d.m.state is DeskState.STANDING


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
    assert d.m.target_duration == 0
    events = await d.run_active_ticks(60)  # an hour of active use
    assert not any(isinstance(e, TransitionCompleted) for e in events)
    assert d.desk.move_calls == []
    assert d.m.active_time == 0  # the clock never starts


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
    assert d.m.active_time > 0
    d.cfg.automation.enabled = False
    d.m.update_config(d.cfg)
    assert d.m.active_time == 0
    assert d.m.target_duration == 0

    d.cfg.automation.enabled = True
    d.m.update_config(d.cfg)
    assert d.m.active_time == 0
    assert d.m.target_duration == 45 * 60
    assert d.m.status(d.now) is not Status.DISABLED


async def test_disabling_mid_cycle_stops_an_overdue_move():
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration  # a move is due right now
    d.cfg.automation.enabled = False
    d.m.update_config(d.cfg)
    await d.tick()
    assert d.desk.move_calls == []


# ----- the new cycle's length rides along on every restart -----

async def test_completed_transition_reports_the_new_cycle_length():
    # The log line after a scheduled move should be able to say when the next
    # one is due, so the event carries the duration _begin_cycle just rolled.
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration
    events = await d.tick()
    completed = [e for e in events if isinstance(e, TransitionCompleted)][0]
    assert completed.next_target_duration == 25 * 60  # now standing
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
    assert failed.next_target_duration == 45 * 60  # still sitting


async def test_adopted_external_move_reports_the_new_cycle_length():
    d = Driver()
    await d.start()
    await d.run_active_ticks(3)
    d.desk.height = STAND_H  # someone used the paddle
    events = await d.tick(dt=5 * 60)
    synced = [e for e in events if isinstance(e, StateSynced)][0]
    assert synced.next_target_duration == 25 * 60


async def test_resume_from_held_reports_the_new_cycle_length():
    d = Driver()
    await d.start()
    d.desk.height = OFF_CYCLE_H
    await d.tick(dt=5 * 60)
    assert d.m.held
    d.desk.height = STAND_H
    events = await d.tick(dt=5 * 60)
    resumed = [e for e in events if isinstance(e, ResumedOnCycle)][0]
    assert resumed.next_target_duration == 25 * 60


# ----- periodic sync -----

async def test_sync_adopts_external_change_and_resets_timers():
    d = Driver()
    await d.start()
    await d.run_active_ticks(3)
    d.desk.height = STAND_H  # someone used the paddle
    events = await d.tick(dt=5 * 60)  # crosses sync_interval
    synced = [e for e in events if isinstance(e, StateSynced)]
    assert len(synced) == 1
    assert synced[0].current is DeskState.STANDING
    assert d.m.state is DeskState.STANDING
    assert d.m.active_time == 0
    assert d.m.target_duration == 25 * 60


async def test_sync_failure_keeps_internal_state():
    d = Driver()
    await d.start()
    d.desk.height_unavailable = True
    events = await d.tick(dt=5 * 60)
    assert any(isinstance(e, SyncFailed) for e in events)
    assert d.m.state is DeskState.SITTING


async def test_sync_matching_height_is_quiet():
    d = Driver()
    await d.start()
    events = await d.tick(dt=5 * 60)
    assert not any(isinstance(e, StateSynced) for e in events)


# ----- sync-before-decide + external-move handling -----

async def test_sync_before_decide_sync_skips_redundant_move_when_already_there():
    """The desk was moved to standing externally right before a due sit->stand
    transition. The pre-decide read adopts it, so automation must NOT issue a
    redundant move — the stale-position bug."""
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration - 90  # within the lead window after +60
    d.desk.height = STAND_H  # someone stood the desk via the panel
    events = await d.tick()
    assert any(isinstance(e, StateSynced) for e in events)
    assert not any(isinstance(e, TransitionCompleted) for e in events)
    assert d.desk.move_calls == []  # automation issued no move
    assert d.m.state is DeskState.STANDING
    assert d.m.active_time == 0


async def test_sync_before_decide_sync_holds_when_parked_off_cycle():
    """If the pre-decide read finds the desk parked off sit/stand, yield:
    hold and don't move it away from where the user put it."""
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration - 90
    d.desk.height = OFF_CYCLE_H
    events = await d.tick()
    assert any(isinstance(e, HeldOffCycle) for e in events)
    assert d.desk.move_calls == []
    assert d.m.held is True
    assert d.m.status(d.now) is Status.HELD


async def test_start_holds_when_off_cycle_under_yield():
    d = Driver(height=OFF_CYCLE_H)
    await d.start()
    assert d.m.held is True
    assert d.m.target_duration == 0
    assert d.m.status(d.now) is Status.HELD


async def test_start_adopts_off_cycle_under_adopt_policy():
    cfg = make_config(external_move_policy="adopt")
    d = Driver(cfg=cfg, height=OFF_CYCLE_H)
    await d.start()
    assert d.m.held is False
    assert d.m.state is DeskState.STANDING  # classify(0.95) > 0.88


async def test_sync_holds_on_external_off_cycle_move():
    d = Driver()
    await d.start()
    await d.run_active_ticks(3)
    d.desk.height = OFF_CYCLE_H  # parked off-cycle with the panel
    events = await d.tick(dt=5 * 60)
    assert any(isinstance(e, HeldOffCycle) for e in events)
    assert d.m.held is True
    # Held freezes the clock: no accumulation while off-cycle.
    before = d.m.active_time
    await d.run_active_ticks(5)
    assert d.m.active_time == before


async def test_held_resumes_when_desk_returns_to_preset():
    d = Driver()
    await d.start()
    d.desk.height = OFF_CYCLE_H
    await d.tick(dt=5 * 60)  # enter hold
    assert d.m.held is True
    d.desk.height = STAND_H  # user parked it back at stand
    events = await d.tick(dt=5 * 60)
    resumed = [e for e in events if isinstance(e, ResumedOnCycle)]
    assert len(resumed) == 1
    assert resumed[0].current is DeskState.STANDING
    assert d.m.held is False
    assert d.m.state is DeskState.STANDING
    assert d.m.target_duration == 25 * 60


async def test_held_polls_even_when_sync_interval_disabled():
    cfg = make_config(sync_interval=0)
    d = Driver(cfg=cfg)
    await d.start()
    d.desk.height = OFF_CYCLE_H
    # No periodic poll, but a due transition triggers the pre-decide read.
    d.m.active_time = d.m.target_duration - 90
    await d.tick()
    assert d.m.held is True
    # With polling off, a held desk still polls at HELD_POLL_INTERVAL so a
    # return to a preset is noticed without any app interaction.
    d.desk.height = SIT_H
    events = await d.tick(dt=5 * 60)
    assert any(isinstance(e, ResumedOnCycle) for e in events)
    assert d.m.held is False


async def test_sync_lead_time_is_the_larger_of_lead_time_and_check_interval():
    """`max`, not `min`, and the docstring spends five lines saying why: the
    window must be at least the notification lead time so the warning is based
    on fresh state, and never less than one check interval so a tick reliably
    lands inside it before the move is due.

    No test ever set lead_time, so every case had lead_time(30) <
    check_interval(60) and `min` passed the whole suite — with `min` the read
    fires 30s ahead, which at a 60s tick means it may not fire at all.
    """
    cfg = make_config(check_interval=60)
    cfg.notifications.enabled = True

    cfg.notifications.lead_time = 120     # lead time is the larger
    d = Driver(cfg=cfg)
    assert d.m._sync_lead_time() == 120

    cfg.notifications.lead_time = 30      # check interval is the larger
    d = Driver(cfg=cfg)
    assert d.m._sync_lead_time() == 60


async def test_a_long_lead_time_reads_the_desk_early_enough_to_warn_on():
    """The behaviour the window exists for, driven rather than asserted on the
    helper: with a 2-minute lead the pre-decide read must have happened by the
    time the warning is due, not one tick before the move."""
    cfg = make_config(check_interval=60)
    cfg.notifications.enabled = True
    cfg.notifications.lead_time = 120
    d = Driver(cfg=cfg)
    await d.start()

    # Each tick advances active_time by one check_interval (60s), so seed
    # 240 out to land at 180 remaining — outside a 120s window.
    d.m.active_time = d.m.target_duration - 240
    await d.tick()
    assert d.m._synced_before_decide is False

    # Next tick lands at 120 remaining: exactly the window, so it must fire.
    await d.tick()
    assert d.m._synced_before_decide is True, "no fresh read to base the warning on"


async def test_sync_before_decide_read_deferred_when_notifications_off():
    """With warnings off there is no lead window to serve, so the pre-decide
    read does not fire a tick early — it collapses into the move tick. The
    reconcile isn't lost, just no longer early: an external move is adopted when
    the transition comes due, not ahead of it (so on-demand BLE connects once,
    at the move, not before)."""
    cfg = make_config(sync_interval=0)  # pre-decide is the only freshness source
    cfg.notifications.enabled = False
    d = Driver(cfg=cfg)
    await d.start()
    # Land inside what would be the lead window (remaining 30 after +60) but
    # short of due. With warnings off, no early read fires.
    d.m.active_time = d.m.target_duration - 90
    d.desk.height = STAND_H  # external move mid-cycle
    events = await d.tick()  # remaining 30 > window(0): no read
    assert d.m._synced_before_decide is False
    assert not any(isinstance(e, StateSynced) for e in events)
    assert d.m.state is DeskState.SITTING  # not adopted yet
    assert d.desk.move_calls == []
    # At the due point the read fires (collapsed into the move tick) and still
    # adopts the external move rather than issuing a redundant transition.
    d.m.active_time = d.m.target_duration
    events = await d.tick()
    assert any(isinstance(e, StateSynced) for e in events)
    assert not any(isinstance(e, TransitionCompleted) for e in events)
    assert d.desk.move_calls == []
    assert d.m.state is DeskState.STANDING


async def test_sync_before_decide_rearms_after_idle_reset():
    """A pre-decide read done before an idle interruption must not satisfy the
    next approach: after activity resets the accumulator the flag re-arms, so
    the desk is read again before the real transition and an external move
    made during the idle gap is caught instead of moved over."""
    cfg = make_config(sync_interval=0)  # pre-decide is the only freshness source
    d = Driver(cfg=cfg)
    await d.start()
    # Climb into the lead window so the pre-decide read fires once.
    d.m.active_time = d.m.target_duration - 90
    await d.tick()  # remaining 30 <= window -> pre-decide sync (desk at sit)
    assert d.m._synced_before_decide is True
    # Go idle, then return: activity-after-idle resets the accumulator AND the
    # pre-decide flag (the fix — previously the flag stuck True).
    await d.tick(idle_ms=11 * 60 * 1000)
    d.desk.height = STAND_H  # external move during the idle gap
    await d.tick(idle_ms=1000)
    assert d.m._synced_before_decide is False
    # Reach the due point: the re-armed pre-decide read adopts the external
    # move rather than issuing a redundant transition onto it.
    d.m.active_time = d.m.target_duration
    events = await d.tick()
    assert any(isinstance(e, StateSynced) for e in events)
    assert not any(isinstance(e, TransitionCompleted) for e in events)
    assert d.desk.move_calls == []
    assert d.m.state is DeskState.STANDING


async def test_adopt_resume_from_held_emits_no_phantom_statesynced():
    """Switching to 'adopt' while held, then reconciling an off-cycle height
    that classifies to the held state, must resume via ResumedOnCycle (X->X,
    ignored by the daemon) rather than a phantom StateSynced(X, X)."""
    d = Driver(height=0.70)  # off-cycle (0.08 m from sit), classifies as sitting
    await d.start()
    assert d.m.held is True and d.m.state is DeskState.SITTING
    new = make_config(external_move_policy="adopt")
    new.presets = dict(d.cfg.presets)
    d.m.update_config(new)
    events = await d.m.force_sync(d.now)
    assert not any(isinstance(e, StateSynced) for e in events)
    resumed = [e for e in events if isinstance(e, ResumedOnCycle)]
    assert len(resumed) == 1
    assert resumed[0].previous is resumed[0].current  # X -> X
    assert d.m.held is False


async def test_held_recovery_polls_despite_large_sync_interval():
    """A held desk polls at HELD_POLL_INTERVAL even when sync_interval is set
    far longer, so a return to a preset is noticed promptly."""
    cfg = make_config(sync_interval=2 * 60 * 60)  # 2h periodic sync
    d = Driver(cfg=cfg, height=OFF_CYCLE_H)
    await d.start()
    assert d.m.held is True
    d.desk.height = STAND_H
    events = await d.tick(dt=5 * 60)  # one HELD_POLL_INTERVAL, well under 2h
    assert any(isinstance(e, ResumedOnCycle) for e in events)
    assert d.m.held is False


# ----- pause / snooze / schedule / skip -----

async def test_pause_freezes_clock_and_blocks_transitions():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    d.m.pause()
    await d.run_active_ticks(60)
    assert d.m.active_time == 600  # frozen, not reset
    assert d.desk.move_calls == []
    assert d.m.status(d.now) is Status.PAUSED
    d.m.resume()
    await d.run_active_ticks(1)
    assert d.m.active_time == 660
    assert d.m.status(d.now) is Status.ACTIVE


async def test_snooze_freezes_until_expiry():
    d = Driver()
    await d.start()
    await d.run_active_ticks(5)
    d.m.snooze(10, d.now)
    await d.run_active_ticks(9)  # 9 min < 10 min snooze
    assert d.m.active_time == 300
    assert d.m.status(d.now) is Status.SNOOZED
    await d.run_active_ticks(2)  # snooze expired mid-way
    assert d.m.active_time > 300
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
    assert d.m.active_time == 600
    assert d.m.status(d.now) is Status.ACTIVE

    # ...then step to Saturday, outside the schedule.
    d.now = datetime(2026, 7, 18, 12, 0).timestamp()
    d.m._last_check = d.now
    await d.run_active_ticks(10)
    assert d.m.active_time == 600, "out-of-schedule reset the cycle, not froze it"
    assert d.desk.move_calls == []
    assert d.m.status(d.now) is Status.OUT_OF_SCHEDULE


async def test_in_schedule_runs_normally():
    cfg = make_config()
    cfg.schedule.enabled = True
    friday_ten = datetime(2026, 7, 17, 10, 0).timestamp()
    d = Driver(cfg=cfg, now=friday_ten)
    await d.start()
    await d.run_active_ticks(10)
    assert d.m.active_time == 600


async def test_skip_next_consumes_one_transition():
    d = Driver()
    await d.start()
    d.m.request_skip_next()
    d.m.active_time = d.m.target_duration
    events = await d.tick()
    assert any(isinstance(e, TransitionSkipped) for e in events)
    assert d.desk.move_calls == []
    assert d.m.state is DeskState.SITTING
    assert d.m.active_time == 0
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
    assert d.m.time_remaining() == 45 * 60 - 600


async def test_config_hot_reload_recomputes_target_keeps_active_time():
    d = Driver()
    await d.start()
    await d.run_active_ticks(10)
    new_cfg = make_config(sit_duration=30 * 60)
    new_cfg.presets = dict(d.cfg.presets)
    d.m.update_config(new_cfg)
    assert d.m.active_time == 600  # kept
    assert d.m.target_duration == 30 * 60  # new duration effective now


# ----- unconfigured (no desk address yet) -----

async def test_unconfigured_machine_stays_inert():
    """A daemon with no desk address must not run a phantom cycle.

    Without this the machine rolls a target, accumulates active time, fires
    the pre-move warning and records transitions against a desk that isn't
    there — which on a multi-user box means notifying people who never set
    the app up. target_duration staying 0 is what gates the daemon's warning.
    """
    d = Driver()
    d.m.unconfigured = True
    await d.start()
    assert d.m.target_duration == 0
    assert d.m.status(d.now) is Status.UNCONFIGURED

    events = await d.run_active_ticks(200, idle_ms=0)
    assert events == []
    assert d.m.active_time == 0
    assert d.m.target_duration == 0
    assert d.m.last_height is None  # never even read the desk


async def test_unconfigured_status_outranks_everything():
    d = Driver()
    d.m.unconfigured = True
    await d.start()
    d.m.pause()
    assert d.m.status(d.now) is Status.UNCONFIGURED


async def test_clearing_unconfigured_lets_the_cycle_start():
    """What the daemon does after the setup wizard writes a MAC."""
    d = Driver()
    d.m.unconfigured = True
    await d.start()
    assert d.m.target_duration == 0

    d.m.unconfigured = False
    await d.m.start(d.now)
    assert d.m.target_duration == 45 * 60
    assert d.m.last_height == SIT_H
    assert d.m.status(d.now) is Status.ACTIVE


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
