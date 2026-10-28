# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheduled strict intent is backed by a real height observation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from daemon_helpers import make_daemon_shell
from idasen_companion.core.clocks import WallInstant
from idasen_companion.core.config import load_config
from idasen_companion.core.durations import Duration
from idasen_companion.core.lengths import Length
from idasen_companion.core.machine import DeskState, TransitionCompleted
from idasen_companion.daemon.config_file import ConfigFileStore
from idasen_companion.desk.mock import MockDesk
from machine_helpers import Driver, STAND_H, make_config


async def test_fresh_physical_departure_releases_arrived_intent():
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=1)
    snapshot = driver.m.strict_snapshot
    driver.desk.height = Length(0.95)
    await driver.m.force_sync(driver.now)
    assert driver.m.strict_snapshot is None
    assert driver.m.held
    assert snapshot.stage == "arrived"


async def test_pinned_arrival_survives_preset_edit_and_duration_reload():
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=1)
    snapshot = driver.m.strict_snapshot
    driver.m.active_time = Duration(100)
    driver.cfg.presets["stand"] = 1.2
    driver.cfg.automation.stand_duration = 1800
    driver.m.update_config(driver.cfg)
    assert driver.m.active_time == Duration(100)
    assert driver.m.target_duration == Duration(1800)
    await driver.m.force_sync(driver.now)
    assert driver.m.strict_snapshot == snapshot
    driver.m.update_config(driver.cfg, reroll_target=False)
    assert driver.m.target_duration == Duration(1800)


async def test_both_intervals_depart_at_boundary_and_capture_new_target():
    driver = Driver(make_config(strict_mode="both"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=1)
    first = driver.m.strict_snapshot
    driver.cfg.presets["sit"] = 0.7
    driver.m.update_config(driver.cfg, reroll_target=False)
    driver.m.active_time = driver.m.target_duration
    events = await driver.tick(dt=0)
    assert driver.m.strict_snapshot.posture is DeskState.SITTING
    assert driver.m.strict_snapshot.target_height == Length(0.7)
    assert driver.m.strict_snapshot.generation != first.generation
    assert len([e for e in events if isinstance(e, TransitionCompleted)]) == 1
    assert driver.m.active_time == Duration(0)
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=0)
    assert driver.m.strict_snapshot.posture is DeskState.STANDING
    assert driver.desk.move_calls == [STAND_H, Length(0.7), STAND_H]


async def test_reconciliation_requires_current_generation_and_fresh_height():
    driver = Driver(make_config(strict_mode="both"))
    await driver.start()
    driver.desk.interrupt_next_move_at = Length(0.9)
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=1)
    pending = driver.m.strict_snapshot
    assert not driver.m.reconcile_strict_observation(Length(0.95), generation=pending.generation)
    assert driver.m.strict_snapshot == pending
    assert not driver.m.reconcile_strict_observation(None, generation=pending.generation)
    driver.m.reconcile_strict_observation(STAND_H, generation=pending.generation)
    arrived = driver.m.strict_snapshot
    assert arrived.stage == "arrived"
    assert not driver.m.reconcile_strict_observation(Length(0.95), generation=arrived.generation + 1)
    assert driver.m.strict_snapshot == arrived
    driver.m.reconcile_strict_observation(Length(0.95), generation=arrived.generation)
    assert driver.m.strict_snapshot is None
    assert not driver.m.reconcile_strict_observation(STAND_H, generation=arrived.generation)


@pytest.mark.parametrize("mode,enabled", [("off", True), ("sitting", True), ("standing", False)])
async def test_policy_removal_releases_and_old_observation_cannot_restore(mode, enabled):
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=1)
    old = driver.m.strict_snapshot
    driver.cfg.automation.strict_mode = mode
    driver.cfg.automation.enabled = enabled
    driver.m.update_config(driver.cfg, reroll_target=False)
    assert driver.m.strict_snapshot is None
    driver.cfg.automation.strict_mode = "standing"
    driver.cfg.automation.enabled = True
    driver.m.update_config(driver.cfg, reroll_target=False)
    assert not driver.m.reconcile_strict_observation(STAND_H, generation=old.generation)
    assert driver.m.strict_snapshot is None


async def test_saved_policy_reaches_daemon_tick_and_event_handler(tmp_path, monkeypatch):
    from idasen_companion.daemon import main as daemon_module
    from idasen_companion.core.machine import StateMachine

    path = tmp_path / "config.toml"
    path.write_text('[automation]\nstrict_mode = "standing"\n')
    d = make_daemon_shell()
    d.activity_log = MagicMock()
    d.config_file = ConfigFileStore(path, d.activity_log)
    d.config = load_config(path)
    d.mock_mode = True
    d.desk = MockDesk(Length(d.config.presets["sit"]))
    d.machine = StateMachine(d.config, d.desk, now=WallInstant(1000))
    d._ifaces = {"automation": MagicMock()}
    d.reload_config()
    await d.machine.start(WallInstant(1000))
    d.machine.active_time = d.machine.target_duration
    d._check_config_file = MagicMock()
    d._handle_event = MagicMock()
    d._maybe_warn = AsyncMock()
    d._emit_periodic_properties = MagicMock()
    d.accounting = MagicMock()
    d._current_move_id = 0
    d._idle = SimpleNamespace(get_idle_ms=AsyncMock(return_value=0))
    d._lock = SimpleNamespace(is_locked=AsyncMock(return_value=False))
    d._session = SimpleNamespace(state=AsyncMock(return_value="foreground"))
    monkeypatch.setattr(daemon_module.time, "time", lambda: 1001)
    await d._tick()
    assert d.desk.move_calls == [Length(d.config.presets["stand"])]
    assert d.machine.strict_snapshot.stage == "arrived"
    assert d.machine.strict_snapshot.target_height == Length(d.config.presets["stand"])
    completions = [c.args[0] for c in d._handle_event.call_args_list
                   if isinstance(c.args[0], TransitionCompleted)]
    assert len(completions) == 1
    assert completions[0].next_target_duration == d.machine.target_duration
    assert d.machine.active_time == Duration(0)


@pytest.mark.parametrize("readback", [None, Length(0.9)])
async def test_unverified_scheduled_move_stays_pending(readback):
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    original_move = driver.desk.move_to

    async def move(height, **kwargs):
        result = await original_move(height, **kwargs)
        driver.desk.height_unavailable = readback is None
        if readback is not None:
            driver.desk.height = readback
        return result

    driver.desk.move_to = move
    driver.m.active_time = driver.m.target_duration
    events = await driver.tick(dt=1)
    assert driver.m.strict_snapshot.stage == "pending"
    assert driver.m.strict_snapshot.target_height == STAND_H
    assert driver.m.state == DeskState.SITTING
    assert not any(isinstance(e, TransitionCompleted) for e in events)


async def test_pending_intent_survives_noop_reload_and_completes_on_pinned_height():
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.desk.interrupt_next_move_at = Length(0.9)
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=1)
    snapshot = driver.m.strict_snapshot
    elapsed, duration = driver.m.active_time, driver.m.target_duration
    driver.cfg.presets["stand"] = 1.15
    driver.m.update_config(driver.cfg, reroll_target=False)
    assert driver.m.strict_snapshot == snapshot
    assert (driver.m.active_time, driver.m.target_duration) == (elapsed, duration)
    driver.desk.height = STAND_H
    events = await driver.m.force_sync(driver.now)
    assert driver.m.strict_snapshot.stage == "arrived"
    assert len([e for e in events if isinstance(e, TransitionCompleted)]) == 1
    assert not await driver.m.force_sync(driver.now)


@pytest.mark.parametrize("mode,initial,expected", [
    ("sitting", STAND_H, DeskState.SITTING),
    ("both", STAND_H, DeskState.SITTING),
])
async def test_scheduled_sitting_selection(mode, initial, expected):
    driver = Driver(make_config(strict_mode=mode), height=initial)
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=1)
    assert driver.m.strict_snapshot.posture == expected
    assert driver.m.strict_snapshot.stage == "arrived"


async def test_manual_arrival_and_selection_change_do_not_arm():
    driver = Driver(make_config())
    await driver.start()
    driver.desk.height = STAND_H
    await driver.m.force_sync(driver.now)
    driver.cfg.automation.strict_mode = "standing"
    driver.m.update_config(driver.cfg, reroll_target=False)
    assert driver.m.strict_snapshot is None


async def test_skip_and_unselected_scheduled_transition_do_not_arm():
    driver = Driver(make_config(strict_mode="standing"), height=STAND_H)
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    driver.m.request_skip_next()
    await driver.tick(dt=1)
    assert driver.m.strict_snapshot is None
    driver.m.active_time = driver.m.target_duration
    events = await driver.tick(dt=1)
    assert driver.m.strict_snapshot is None
    assert any(isinstance(e, TransitionCompleted) for e in events)


async def test_pending_explicit_target_wins_over_overlapping_preset_bands():
    config = make_config(strict_mode="standing")
    config.presets = {"sit": 1.0, "stand": 1.02}
    config.advanced.movement_tolerance = 0.03125
    driver = Driver(config, height=Length(1.0))
    await driver.start()
    driver.desk.interrupt_next_move_at = Length(0.9)
    driver.m.active_time = driver.m.target_duration
    await driver.tick(dt=1)
    driver.desk.height = Length(1.02 - 0.03125)
    events = await driver.m.force_sync(driver.now)
    assert driver.m.state == DeskState.STANDING
    assert len([e for e in events if isinstance(e, TransitionCompleted)]) == 1
