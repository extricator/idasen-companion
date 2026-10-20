"""Desk synchronization, external movement and held recovery."""

from idasen_companion.core.lengths import Length
from idasen_companion.core.durations import Duration

from idasen_companion.core.machine import (
    DeskState,
    HeldOffCycle,
    ResumedOnCycle,
    StateSynced,
    Status,
    SyncFailed,
    TransitionCompleted,
)

from machine_helpers import (
    SIT_H,
    STAND_H,
    OFF_CYCLE_H,
    make_config,
    Driver,
)


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
    assert d.m.active_time == Duration.from_seconds(0)
    assert d.m.target_duration == Duration.from_seconds(25 * 60)


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
    d.m.active_time = d.m.target_duration - Duration.from_seconds(90)  # within the lead window after +60
    d.desk.height = STAND_H  # someone stood the desk via the panel
    events = await d.tick()
    assert any(isinstance(e, StateSynced) for e in events)
    assert not any(isinstance(e, TransitionCompleted) for e in events)
    assert d.desk.move_calls == []  # automation issued no move
    assert d.m.state is DeskState.STANDING
    assert d.m.active_time == Duration.from_seconds(0)


async def test_sync_before_decide_sync_holds_when_parked_off_cycle():
    """If the pre-decide read finds the desk parked off sit/stand, yield:
    hold and don't move it away from where the user put it."""
    d = Driver()
    await d.start()
    d.m.active_time = d.m.target_duration - Duration.from_seconds(90)
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
    assert d.m.target_duration == Duration.from_seconds(0)
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
    assert d.m.target_duration == Duration.from_seconds(25 * 60)


async def test_held_polls_even_when_sync_interval_disabled():
    cfg = make_config(sync_interval=0)
    d = Driver(cfg=cfg)
    await d.start()
    d.desk.height = OFF_CYCLE_H
    # No periodic poll, but a due transition triggers the pre-decide read.
    d.m.active_time = d.m.target_duration - Duration.from_seconds(90)
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
    assert d.m._sync_lead_time() == Duration.from_seconds(120)

    cfg.notifications.lead_time = 30      # check interval is the larger
    d = Driver(cfg=cfg)
    assert d.m._sync_lead_time() == Duration.from_seconds(60)


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
    d.m.active_time = d.m.target_duration - Duration.from_seconds(240)
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
    d.m.active_time = d.m.target_duration - Duration.from_seconds(90)
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
    d.m.active_time = d.m.target_duration - Duration.from_seconds(90)
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
    d = Driver(height=Length(0.70))  # off-cycle (0.08 m from sit), classifies as sitting
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
