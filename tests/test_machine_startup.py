"""Startup adoption, target classification and unconfigured lifecycle."""

from idasen_companion.core.machine import (
    DeskState,
    StateSynced,
    Status,
)

from machine_helpers import (
    SIT_H,
    STAND_H,
    OFF_CYCLE_H,
    make_config,
    Driver,
)


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
