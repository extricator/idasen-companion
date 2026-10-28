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


async def test_scheduled_standing_arrives_only_on_verified_readback():
    driver = Driver(make_config(strict_mode="standing"))
    await driver.start()
    driver.m.active_time = driver.m.target_duration
    events = await driver.tick(dt=1)
    snapshot = getattr(driver.m, "strict_snapshot", None)
    assert snapshot is not None
    assert (snapshot.stage, snapshot.posture, snapshot.target_height) == (
        "arrived", DeskState.STANDING, STAND_H)
    completed = [e for e in events if isinstance(e, TransitionCompleted)]
    assert len(completed) == 1
    assert completed[0].next_target_duration == driver.m.target_duration
    assert driver.m.active_time == Duration(0)


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
