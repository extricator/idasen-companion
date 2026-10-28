# SPDX-License-Identifier: GPL-3.0-or-later
"""Control ops must announce automation state immediately.

Regression for: pause/resume/skip/snooze changed the state machine but never
emitted StatusChanged/ProgressChanged, so clients (window + tray) only found
out on the next periodic tick (up to check_interval = 60s later).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

import pytest

from idasen_companion.core.clocks import MonotonicInstant, WallInstant
from idasen_companion.core.lengths import Length
from idasen_companion.daemon.main import Daemon
from daemon_helpers import make_daemon_shell
from idasen_companion.core.durations import Duration


def observed_daemon(monkeypatch):
    from idasen_companion.daemon import main as daemon_mod
    from idasen_companion.core.config import AppConfig
    from idasen_companion.core.machine import StateMachine
    from idasen_companion.desk.mock import MockDesk

    clock = SimpleNamespace(wall=1000.0, mono=0.0)
    monkeypatch.setattr(daemon_mod, "time", SimpleNamespace(
        time=lambda: clock.wall, monotonic=lambda: clock.mono))
    d = make_daemon_shell()
    d.config = AppConfig()
    d.desk = MockDesk(Length(d.config.presets["sit"]))
    d.moving = False
    d._ifaces = {"desk": MagicMock()}
    d._last_height_emit = MonotonicInstant(0)
    d.machine = StateMachine(d.config, d.desk, now=WallInstant(clock.wall),
                             on_moving=d._set_moving, on_height_observed=d._observe_height,
                             on_observation_tick=d._check_observation_continuity)
    return d, clock


async def test_observed_thirty_minutes_preserves_ten_minutes_active(monkeypatch):
    d, clock = observed_daemon(monkeypatch)
    await d.machine.start(WallInstant(clock.wall))
    for minute in range(1, 31):
        clock.wall, clock.mono = 1000 + minute * 60, minute * 60
        if minute == 11:
            d.machine.pause()
        await d.machine.tick(WallInstant(clock.wall), 0, False)
    assert d.position_observation_snapshot()[3] == 1800.0
    assert d.machine.active_time == Duration(600)


async def test_healthy_default_sync_with_read_latency_preserves_observation(monkeypatch):
    d, clock = observed_daemon(monkeypatch)
    await d.machine.start(WallInstant(clock.wall))
    d.machine.pause()
    original_read = d.desk.get_height

    async def delayed_read():
        height = await original_read()
        clock.wall += 1
        clock.mono += 1
        return height

    d.desk.get_height = delayed_read
    for second in (60, 120, 180, 240, 300):
        clock.wall, clock.mono = 1000 + second, second
        await d.machine.tick(WallInstant(clock.wall), 0, False)
    assert d.position_observation_snapshot() == ("sitting", True, 1000.0, 301.0, 390.0)
    assert d.machine.active_time == Duration(0)


async def test_daemon_tick_preserves_notification_during_presence_acquisition(monkeypatch):
    d, clock = observed_daemon(monkeypatch)
    await d.machine.start(WallInstant(clock.wall))
    d.machine.pause()
    d._check_config_file = lambda: None
    d._maybe_warn = AsyncMock()
    d._emit_periodic_properties = MagicMock()
    d.accounting = MagicMock()
    d._current_move_id = 0

    async def idle():
        clock.wall += 1
        clock.mono += 1
        d._on_live_height(Length(d.config.presets["sit"]))
        return 0

    d._idle = SimpleNamespace(get_idle_ms=idle)
    d._lock = SimpleNamespace(is_locked=AsyncMock(return_value=False))
    d._session = SimpleNamespace(state=AsyncMock(return_value="foreground"))
    clock.wall, clock.mono = 1060, 60
    await d._tick()
    assert d.position_observation_snapshot() == ("sitting", True, 1000.0, 61.0, 390.0)
    assert d.machine.active_time == Duration(0)


def test_healthy_release_and_getters_do_not_renew_lease(monkeypatch):
    d, clock = observed_daemon(monkeypatch)
    d._on_live_height(Length(d.config.presets["sit"]))
    assert d.position_observation_snapshot()[4] == 390.0
    d._on_connection_change(False)
    clock.wall += 200
    clock.mono += 200
    assert d.position_observation_snapshot()[3:] == (200.0, 190.0)
    # Repeated cached publication is not a new sample.
    d._emit_position_observation()
    clock.wall += 190
    clock.mono += 190
    assert d.position_observation_snapshot()[1] is False


def test_custom_and_movement_drop_duration_until_real_confirmation(monkeypatch):
    d, _clock = observed_daemon(monkeypatch)
    d._on_live_height(Length(d.config.presets["sit"]))
    d._on_live_height(Length(0.9))
    assert d.position_observation_snapshot()[1] is False
    d._on_live_height(Length(d.config.presets["sit"]))
    d._set_moving(True)
    d._on_live_height(Length(d.config.presets["stand"]))
    assert d.position_observation_snapshot()[1] is False
    d._set_moving(False)
    assert d.position_observation_snapshot()[1] is False


@pytest.mark.parametrize("readable", [True, False])
async def test_automatic_final_observation_requires_verified_height(monkeypatch, readable):
    d, clock = observed_daemon(monkeypatch)
    await d.machine.start(WallInstant(clock.wall))
    d.desk.height_unavailable = not readable
    await d.machine._execute_transition(WallInstant(clock.wall))
    snapshot = d.position_observation_snapshot()
    assert snapshot[1] is readable
    if readable:
        assert snapshot[0] == "standing" and snapshot[3] == 0.0


@pytest.mark.parametrize("boundary", ["explicit", "custom", "wall-jump"])
async def test_read_spanning_invalidation_cannot_reseed_via_callback(monkeypatch, boundary):
    d, clock = observed_daemon(monkeypatch)
    d._on_live_height(Length(d.config.presets["sit"]))
    entered, complete = asyncio.Event(), asyncio.Event()

    async def delayed_read():
        entered.set()
        await complete.wait()
        height = Length(d.config.presets["sit"])
        d._on_live_height(height)  # BLE's duplicate successful-read callback
        return height

    d.desk.get_height = delayed_read
    task = asyncio.create_task(d.machine.refresh_height(WallInstant(clock.wall)))
    await entered.wait()
    if boundary == "custom":
        d._on_live_height(Length(0.9))
    elif boundary == "wall-jump":
        clock.wall += 301
        assert d.position_observation_snapshot()[1] is False
    else:
        d._invalidate_position_observation()
    complete.set()
    await task
    assert d.position_observation_snapshot()[1] is False


async def test_overlapping_reads_keep_their_own_invalidation_generation(monkeypatch):
    d, clock = observed_daemon(monkeypatch)
    first_entered, second_entered = asyncio.Event(), asyncio.Event()
    first_complete, second_complete = asyncio.Event(), asyncio.Event()
    read_lock = asyncio.Lock()
    reads = 0

    async def serialized_read():
        nonlocal reads
        async with read_lock:
            reads += 1
            entered, complete = ((first_entered, first_complete) if reads == 1
                                 else (second_entered, second_complete))
            entered.set()
            await complete.wait()
            height = Length(d.config.presets["sit"])
            d._on_live_height(height)  # the synchronous BleDesk read callback
            return height

    d.desk.get_height = serialized_read
    first = asyncio.create_task(d.machine.refresh_height(WallInstant(clock.wall)))
    await first_entered.wait()
    d._invalidate_position_observation()
    second = asyncio.create_task(d.machine.refresh_height(WallInstant(clock.wall)))
    await asyncio.sleep(0)  # B acquires its token while waiting for A's desk lock.
    first_complete.set()
    await first
    await second_entered.wait()
    assert d.position_observation_snapshot()[1] is False
    second_complete.set()
    await second
    assert d.position_observation_snapshot()[0:2] == ("sitting", True)


async def test_ble_notification_keeps_working_with_inherited_read_context(monkeypatch):
    import struct

    from idasen_companion.desk.ble import BleDesk

    d, clock = observed_daemon(monkeypatch)
    subscribed, notify = asyncio.Event(), asyncio.Event()
    notified = asyncio.Event()

    async def start_notify(_uuid, callback):
        subscribed.set()
        await notify.wait()
        callback(None, bytearray(struct.pack("<HH", 4800, 0)))  # standing
        notified.set()

    ble = BleDesk("", on_height=d._on_live_height)
    ble._desk = SimpleNamespace(_client=SimpleNamespace(start_notify=start_notify))
    subscription = None

    async def read_with_subscription():
        nonlocal subscription
        subscription = asyncio.create_task(ble._try_start_notify())
        await subscribed.wait()
        return Length(d.config.presets["sit"])

    d.desk.get_height = read_with_subscription
    await d.machine.refresh_height(WallInstant(clock.wall))
    d._invalidate_position_observation()
    notify.set()
    await notified.wait()
    await subscription
    assert d.position_observation_snapshot()[0:2] == ("standing", True)


async def test_capture_reports_actual_success_and_invalidates_failed_read(monkeypatch):
    from dbus_fast.errors import DBusError

    d, _clock = observed_daemon(monkeypatch)
    d.save_preset = MagicMock()
    assert await d.capture_current_preset("custom") == Length(d.config.presets["sit"])
    assert d.position_observation_snapshot()[0:2] == ("sitting", True)
    d.desk.height_unavailable = True
    with pytest.raises(DBusError) as error:
        await d.capture_current_preset("custom")
    assert error.value.type.endswith(".Error.NoHeight")
    assert d.position_observation_snapshot()[1] is False
    d.save_preset.assert_called_once_with("custom", Length(d.config.presets["sit"]))


@pytest.mark.parametrize("sleeping", [True, False])
def test_both_sleep_edges_invalidate_before_any_later_sample(monkeypatch, sleeping):
    d, _clock = observed_daemon(monkeypatch)
    d.activity_log = MagicMock()
    d._scheduled_target = lambda: "stand"
    d._idle = SimpleNamespace(probe=AsyncMock())
    d._spawn = lambda coroutine, *_: coroutine.close()
    d._on_live_height(Length(d.config.presets["sit"]))
    d._on_system_message(SimpleNamespace(interface="org.freedesktop.login1.Manager",
                                        member="PrepareForSleep", body=[sleeping]))
    assert d.position_observation_snapshot()[1] is False
    if sleeping:
        d._on_live_height(Length(d.config.presets["sit"]))
        assert d.position_observation_snapshot()[1] is False


@pytest.mark.parametrize("field", ["sit", "stand", "tolerance", "sync", "check"])
def test_observation_config_changes_invalidate_and_rebound_lease(monkeypatch, field):
    import copy

    d, _clock = observed_daemon(monkeypatch)
    d.mock_mode = True
    d.activity_log = MagicMock()
    d._report_config_warnings = MagicMock()
    d._build_formatter = MagicMock()
    d._emit_automation_state = MagicMock()
    updated = copy.deepcopy(d.config)
    if field in ("sit", "stand"):
        updated.presets[field] += 0.01
    elif field == "tolerance":
        updated.advanced.movement_tolerance += 0.001
    elif field == "sync":
        updated.automation.sync_interval = 100
    else:
        updated.automation.check_interval = 20
    d.config_file = MagicMock()
    d.config_file.load.return_value = updated
    d._on_live_height(Length(d.config.presets["sit"]))
    d.reload_config()
    assert d.position_observation_snapshot()[1] is False
    d._on_live_height(Length(d.config.presets["sit"]))
    expected = {"sync": 190.0, "check": 350.0}.get(field, 390.0)
    assert d.position_observation_snapshot()[4] == expected


def test_presentation_and_automation_toggle_preserve_observation(monkeypatch):
    import copy

    d, clock = observed_daemon(monkeypatch)
    d.mock_mode = True
    d.activity_log = MagicMock()
    d._report_config_warnings = MagicMock()
    d._build_formatter = MagicMock()
    d._emit_automation_state = MagicMock()
    updated = copy.deepcopy(d.config)
    updated.ui.units = "in"
    updated.automation.enabled = False
    d.config_file = MagicMock()
    d.config_file.load.return_value = updated
    d._on_live_height(Length(d.config.presets["sit"]))
    clock.wall += 10
    clock.mono += 10
    d.reload_config()
    assert d.position_observation_snapshot()[3:] == (10.0, 380.0)


def test_saved_cycle_preset_invalidates_and_swap_rejects_old_desk(monkeypatch):
    from idasen_companion.desk.mock import MockDesk

    d, _clock = observed_daemon(monkeypatch)
    d.activity_log = MagicMock()
    d._check_config_file = MagicMock()
    d.config_file = MagicMock()
    d._ifaces["presets"] = MagicMock()
    d._on_live_height(Length(d.config.presets["sit"]))
    d.save_preset("sit", Length(0.63))
    assert d.position_observation_snapshot()[1] is False
    d._on_live_height(Length(0.63))
    previous_desk = d.desk
    d._make_desk = lambda: MockDesk(Length(0.63))
    d._spawn = lambda coroutine, *_: coroutine.close()
    d._swap_desk()
    d._on_desk_height(previous_desk, Length(0.63))
    assert d.position_observation_snapshot()[1] is False


async def test_seatless_live_callbacks_are_suppressed_and_failure_clears(monkeypatch):
    d, clock = observed_daemon(monkeypatch)
    await d.machine.start(WallInstant(clock.wall))
    await d.machine.tick(WallInstant(clock.wall + 1), 0, False, seatless=True)
    d._on_live_height(Length(d.config.presets["sit"]))
    assert d.position_observation_snapshot()[1] is False
    await d.machine.tick(WallInstant(clock.wall + 2), 0, False)
    assert d.position_observation_snapshot()[1] is True
    d.desk.height_unavailable = True
    await d.machine.force_sync(WallInstant(clock.wall + 3))
    assert d.position_observation_snapshot()[1] is False


def test_disabled_periodic_sync_still_has_finite_lease(monkeypatch):
    d, clock = observed_daemon(monkeypatch)
    d.config.automation.sync_interval = 0
    d._on_live_height(Length(d.config.presets["sit"]))
    for step in (200, 190):
        clock.wall += step
        clock.mono += step
        snapshot = d.position_observation_snapshot()
    assert snapshot[1] is False


def _daemon():
    """A Daemon with just the collaborators the control ops touch, bypassing
    the real __init__ (which builds a RingLog, D-Bus service, desk, ...)."""
    d = make_daemon_shell()
    d.activity_log = MagicMock()
    d.machine = MagicMock()
    d.machine.strict_snapshot = None
    d.machine.active_time = Duration.from_seconds(120.0)
    d.machine.target_duration = Duration.from_seconds(300.0)
    d.machine.snooze_until = None
    d.machine.skip_next = False
    d.machine.status.return_value = MagicMock(value="active")
    d.config = MagicMock()
    d.config.automation.enabled = True
    d.config.automation.strict_mode = "off"
    d._ifaces = {"automation": MagicMock()}
    return d


def _assert_announced(d):
    auto = d._ifaces["automation"]
    assert auto.StatusChanged.called, "StatusChanged not emitted"
    assert auto.ProgressChanged.called, "ProgressChanged not emitted"
    assert auto.emit_properties_changed.called, "PropertiesChanged not emitted"


async def test_pause_emits_state():
    d = _daemon()
    await d.pause()
    assert d.machine.pause.called
    _assert_announced(d)


def test_resume_emits_state():
    d = _daemon()
    d.resume()
    assert d.machine.resume.called
    _assert_announced(d)


async def test_skip_next_emits_state():
    d = _daemon()
    await d.skip_next()
    assert d.machine.request_skip_next.called
    _assert_announced(d)


async def test_snooze_emits_state():
    d = _daemon()
    await d.snooze(10)
    assert d.machine.snooze.called
    d.activity_log.emit.assert_called_once()
    assert d.activity_log.emit.call_args.kwargs == {
        "minutes": 10, "duration": 600}
    _assert_announced(d)


@pytest.mark.parametrize("op", ["pause", "resume", "skip_next", "snooze"])
async def test_progress_uses_current_machine_values(op):
    d = _daemon()
    result = (d.snooze if op == "snooze" else getattr(d, op))(
        *( (10,) if op == "snooze" else () ))
    if op != "resume":
        await result
    d._ifaces["automation"].ProgressChanged.assert_called_with(120.0, 300.0)


async def test_toggle_moves_to_machine_chosen_preset():
    # Desk1.Toggle delegates the "which way?" decision to the machine and
    # moves there — the tray click and --toggle shortcut both ride this path.
    d = make_daemon_shell()
    d.machine = MagicMock()
    d.machine.strict_snapshot = None
    d.config = MagicMock()
    d.config.presets = {"stand": 1.10}
    d.machine.refresh_height = AsyncMock()
    d.machine.toggle_target_preset.return_value = "stand"
    d.manual_move_to_preset = AsyncMock()
    async def refresh():
        await d.machine.refresh_height(WallInstant(0))
        return True
    d._manual_refresh_locked = refresh
    async def move(_height, _label, **_kwargs):
        await d.manual_move_to_preset("stand")
    d._manual_move_locked = move
    await d.toggle_sit_stand()
    d.machine.refresh_height.assert_awaited_once()  # pre-decide read before deciding
    d.manual_move_to_preset.assert_awaited_once_with("stand")


async def test_toggle_from_background_never_reads_the_desk():
    from dbus_fast.errors import DBusError
    from idasen_companion.daemon.idle import SEAT_BACKGROUND

    d = Daemon.__new__(Daemon)
    d._session = MagicMock(state=AsyncMock(return_value=SEAT_BACKGROUND))
    d.machine = MagicMock(refresh_height=AsyncMock())
    with pytest.raises(DBusError):
        await d.toggle_sit_stand()
    d.machine.refresh_height.assert_not_awaited()


def _gesture_daemon(*, moving=False, active=None, start_height=Length(0.62),
                    repeat="reverse"):
    d = make_daemon_shell()
    d.activity_log = MagicMock()
    d.moving = moving
    d._gesture_action = active
    d._gesture_start_height = start_height
    d.config = MagicMock()
    d.config.ui.tray_repeat_move = repeat
    d.config.presets = {"sit": 0.62, "stand": 1.10}
    d.machine = MagicMock()
    d.machine.strict_snapshot = None
    d.machine.toggle_target_preset.return_value = "stand"
    d.machine.last_height = Length(0.75)
    d.machine.refresh_height = AsyncMock()  # the START-path pre-decide read
    d.toggle_sit_stand = AsyncMock()
    d.manual_move_to_preset = AsyncMock()
    d.manual_move_to_height = AsyncMock()
    d.stop_movement = AsyncMock()
    async def refresh():
        await d.machine.refresh_height(WallInstant(0))
        return True
    async def move(_height, label, *, on_issue=None, **_kwargs):
        if on_issue is not None:
            on_issue()
        if d._gesture_action == "toggle":
            await d.toggle_sit_stand(refresh=False)
        else:
            await d.manual_move_to_preset(label.split("'")[1])
    d._manual_refresh_locked = refresh
    d._manual_move_locked = move
    return d


async def test_gesture_move_idle_starts_and_records_start():
    d = _gesture_daemon(moving=False)
    await d.gesture_move("toggle")
    d.machine.refresh_height.assert_awaited_once()  # pre-decide read on start
    d.toggle_sit_stand.assert_awaited_once_with(refresh=False)  # no double read
    d.stop_movement.assert_not_awaited()
    assert d._gesture_action == "toggle"
    assert d._gesture_start_height == Length(0.75)  # captured from machine.last_height


async def test_gesture_toggle_start_height_is_fresh_not_stale_cache():
    # The reverse target must be the desk's real position when the gesture
    # fired, not a stale cache. It's captured AFTER the pre-decide read, so an
    # external move (cache 0.62, desk really at 1.10) is reflected — and the
    # toggle direction and reverse target agree.
    d = _gesture_daemon(moving=False)
    d.machine.last_height = Length(0.62)  # stale cache

    async def do_refresh(_now):
        d.machine.last_height = Length(1.10)  # the real position

    d.machine.refresh_height = AsyncMock(side_effect=do_refresh)
    await d.gesture_move("toggle")
    assert d._gesture_start_height == Length(1.10)  # fresh, not the 0.62 cache
    d.toggle_sit_stand.assert_awaited_once_with(refresh=False)


async def test_sit_gesture_also_reads_before_recording_start():
    # Non-toggle gestures get the same fresh reverse target (and move directly).
    d = _gesture_daemon(moving=False)
    d.machine.last_height = Length(0.62)

    async def do_refresh(_now):
        d.machine.last_height = Length(1.10)

    d.machine.refresh_height = AsyncMock(side_effect=do_refresh)
    await d.gesture_move("sit")
    d.machine.refresh_height.assert_awaited_once()
    assert d._gesture_start_height == Length(1.10)
    d.manual_move_to_preset.assert_awaited_once_with("sit")


async def test_sit_gesture_skips_read_when_not_reversing():
    # With repeat != "reverse" the reverse target is never used, so an explicit
    # sit/stand skips the pre-move read and starts moving a round-trip sooner.
    d = _gesture_daemon(moving=False, repeat="stop")
    d.machine.last_height = Length(0.75)
    await d.gesture_move("sit")
    d.machine.refresh_height.assert_not_awaited()
    assert d._gesture_start_height == Length(0.75)  # cached pre-move height
    d.manual_move_to_preset.assert_awaited_once_with("sit")


async def test_toggle_gesture_reads_even_without_reverse():
    # Toggle always needs the fresh position to choose a direction, regardless
    # of the repeat mode.
    d = _gesture_daemon(moving=False, repeat="stop")
    await d.gesture_move("toggle")
    d.machine.refresh_height.assert_awaited_once()
    d.toggle_sit_stand.assert_awaited_once_with(refresh=False)


async def test_gesture_move_repeat_reverses_to_start():
    d = _gesture_daemon(moving=True, active="toggle", start_height=Length(0.62),
                        repeat="reverse")
    await d.gesture_move("toggle")
    # The reverse move is the successor, so the "moving" flag stays up for it.
    d.stop_movement.assert_awaited_once_with(expect_successor=True)
    d.manual_move_to_height.assert_awaited_once_with(Length(0.62))
    assert d._gesture_action is None


async def test_gesture_move_repeat_stops_without_reverse():
    d = _gesture_daemon(moving=True, active="toggle", repeat="stop")
    await d.gesture_move("toggle")
    # Nothing follows this one, so it owns the teardown.
    d.stop_movement.assert_awaited_once_with(expect_successor=False)
    d.manual_move_to_height.assert_not_awaited()


async def test_gesture_move_off_reissues_the_move():
    d = _gesture_daemon(moving=True, active="toggle", repeat="off")
    await d.gesture_move("toggle")
    d.stop_movement.assert_not_awaited()
    d.toggle_sit_stand.assert_awaited_once()  # re-issued, not cancelled


async def test_gesture_move_different_action_redirects_not_stops():
    # A different gesture mid-move heads to its own target; the desk layer
    # preempts the move in flight, so this must not stop.
    d = _gesture_daemon(moving=True, active="toggle", repeat="reverse")
    await d.gesture_move("sit")
    d.stop_movement.assert_not_awaited()
    d.manual_move_to_preset.assert_awaited_once_with("sit")


async def test_gesture_move_rejects_unknown_action():
    import pytest
    from dbus_fast.errors import DBusError
    d = _gesture_daemon()
    with pytest.raises(DBusError):
        await d.gesture_move("wiggle")


async def _interruptible_daemon(policy="undo"):
    import time
    from idasen_companion.core.config import AppConfig
    from idasen_companion.core.machine import StateMachine
    from idasen_companion.desk.mock import MockDesk

    d = Daemon.__new__(Daemon)

    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here

    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.activity_log = MagicMock()
    d.stats = MagicMock()
    d._ifaces = {"desk": MagicMock(), "automation": MagicMock()}
    d._notifier = MagicMock()
    d._notifier.send = AsyncMock()
    d.moving = False
    d.desk_connected = True
    d._current_move_id = 0
    cfg = AppConfig()
    cfg.presets = {"sit": 0.62, "stand": 1.10}
    cfg.automation.interruption_policy = policy
    d.config = cfg
    # A real Formatter: this fixture drives a real StateMachine, which can
    # emit HeldOffCycle -- whose notification renders through it. __init__ is
    # bypassed here, so run()'s own _build_formatter never fires.
    d.fmt = Daemon._build_formatter(d, cfg)
    d.desk = MockDesk(height=Length(0.62))
    d.machine = StateMachine(cfg, d.desk, now=WallInstant(time.time()))
    await d.machine.start(WallInstant(time.time()))  # last_height = 0.62, state sitting
    return d


async def test_manual_preset_move_returns_to_start_on_interruption():
    # Physical paddle stops the toward-stand move at 0.80; the desk should
    # return to where it started (0.62), not park off-cycle.
    d = await _interruptible_daemon("undo")
    d.desk.interrupt_next_move_at = Length(0.80)
    await d.manual_move_to_preset("stand")
    assert d.desk.move_calls == [Length(1.10), Length(0.62)]
    assert abs(d.desk.height - Length(0.62)) < Length(1e-9)


async def test_manual_move_clears_the_failed_status():
    # A manual move the desk accepts is a successful move, so a stale
    # move-failed status must not survive it -- and clients shouldn't have to
    # wait for the next periodic tick to find out.
    d = await _interruptible_daemon("undo")
    d.machine.move_failed = True
    await d.manual_move_to_preset("stand")
    assert d.machine.move_failed is False
    assert d._ifaces["automation"].StatusChanged.called


async def test_manual_preset_move_no_return_when_reaching_target():
    # A clean move to the preset must not issue a spurious return move.
    d = await _interruptible_daemon("undo")
    await d.manual_move_to_preset("stand")
    assert d.desk.move_calls == [Length(1.10)]


async def test_manual_preset_move_respects_leave_policy():
    d = await _interruptible_daemon("leave")
    d.desk.interrupt_next_move_at = Length(0.80)
    await d.manual_move_to_preset("stand")
    assert d.desk.move_calls == [Length(1.10)]  # left where the paddle stopped it


async def test_manual_preset_move_does_not_retry():
    # "Try again" is an automation-only policy: a companion move you stop by
    # hand is a live instruction to stop, so the manual path treats it as
    # "leave" rather than pushing back against the paddle.
    d = await _interruptible_daemon("retry")
    d.desk.interrupt_next_move_at = Length(0.80)
    await d.manual_move_to_preset("stand")
    assert d.desk.move_calls == [Length(1.10)]


async def test_manual_move_to_height_does_not_bounce_back():
    # The slider's explicit target (and the reverse gesture) must not return.
    d = await _interruptible_daemon("undo")
    d.desk.interrupt_next_move_at = Length(0.80)
    await d.manual_move_to_height(Length(1.05))
    assert d.desk.move_calls == [Length(1.05)]


async def test_software_stop_mid_move_does_not_return_to_start():
    # A deliberate stop (Desk1.Stop / repeat-stop) or a superseding move bumps
    # _current_move_id during the move; the desk must then stay where it stopped
    # rather than bounce back like a physical interruption would.
    d = await _interruptible_daemon("undo")
    d.desk.interrupt_next_move_at = Length(0.80)
    orig_move_to = d.desk.move_to

    async def move_to_then_stop(h, **kwargs):
        result = await orig_move_to(h, **kwargs)
        d._current_move_id += 1  # stand in for stop_movement()/a superseding move
        return result

    d.desk.move_to = move_to_then_stop
    await d.manual_move_to_preset("stand")
    assert d.desk.move_calls == [Length(1.10)]  # no return move — stayed put


async def test_superseded_move_keeps_moving_flag_and_skips_reconcile():
    # When a newer move supersedes this one mid-flight, this move must not
    # clear the shared "moving" flag (the newer move owns it) nor run its own
    # reconciliation (which would read a mid-flight height).
    d = await _interruptible_daemon()
    d.machine.force_sync = AsyncMock(return_value=[])
    orig_move_to = d.desk.move_to

    async def supersede(h, **kwargs):
        result = await orig_move_to(h, **kwargs)
        d._current_move_id += 1  # a newer move started during ours
        return result

    d.desk.move_to = supersede
    await d.manual_move_to_preset("stand")
    assert d.moving is True  # left True for the superseding move to clear
    d.machine.force_sync.assert_not_called()  # skipped its own reconciliation


def _stopping_daemon(*, moving=True, gesture="stand"):
    d = make_daemon_shell()
    d.machine = MagicMock()
    d.activity_log = MagicMock()
    d.desk = MagicMock()
    d.desk.stop = AsyncMock()
    d._current_move_id = 5
    d.moving = moving
    d._gesture_action = gesture
    d._gesture_start_height = Length(0.62)
    d._ifaces = {"desk": MagicMock()}
    return d


async def test_stop_movement_bumps_move_id():
    d = _stopping_daemon()
    await d.stop_movement()
    assert d._current_move_id == 6  # invalidates the in-flight move's return-to-start
    d.desk.stop.assert_awaited_once()


async def test_a_plain_stop_clears_the_move_state():
    """`stop_movement` bumping the sequence is exactly what stops the in-flight
    `_manual_move` clearing `moving` in its own `finally` — it steps aside for
    a successor. A plain Stop has no successor, so it must tear down itself;
    otherwise `moving` stays true forever (nothing else clears it, and the
    periodic property emit does not include Moving)."""
    d = _stopping_daemon()
    await d.stop_movement()
    assert d.moving is False
    assert d._gesture_action is None
    d._ifaces["desk"].MovingChanged.assert_called_once_with(False)


async def test_stop_then_the_same_gesture_moves_that_way_not_back():
    """The wedge's real cost. With `moving` and `_gesture_action` left stale,
    pressing the tray's Stand a second time took the repeat-to-cancel branch
    and reversed the desk *down* to the sit height."""
    d = _stopping_daemon(gesture="stand")
    d.config = MagicMock()
    d.config.ui.tray_repeat_move = "reverse"
    d.machine = MagicMock(last_height=Length(1.10))
    d.machine.strict_snapshot = None
    d.machine.refresh_height = AsyncMock()
    d.manual_move_to_preset = AsyncMock()
    d.manual_move_to_height = AsyncMock()
    d.config.presets = {"stand": 1.10}
    async def refresh():
        await d.machine.refresh_height(WallInstant(0))
        return True
    async def move(_height, _label, *, on_issue=None, **_kwargs):
        if on_issue is not None:
            on_issue()
        await d.manual_move_to_preset("stand")
    d._manual_refresh_locked = refresh
    d._manual_move_locked = move

    await d.stop_movement()          # Overview's Stop button / --stop
    await d.gesture_move("stand")    # tray "Stand" again

    d.manual_move_to_preset.assert_awaited_once_with("stand")
    d.manual_move_to_height.assert_not_awaited()  # i.e. did not reverse to sit


async def test_a_stop_that_precedes_a_reverse_leaves_the_flag_for_it():
    """The one case where the flag must stay up: the repeat-gesture reverse
    issues its own move immediately, and dropping Moving in between would
    flicker the tray and let a third gesture start a fresh move."""
    d = _stopping_daemon()
    await d.stop_movement(expect_successor=True)
    assert d.moving is True
    d._ifaces["desk"].MovingChanged.assert_not_called()


# ----- turning automation off persists, unlike Pause -----

def _enable_daemon(tmp_path, enabled=True):
    import time
    from idasen_companion.core.config import AppConfig, load_config
    from idasen_companion.daemon.config_file import ConfigFileStore
    from idasen_companion.core.machine import StateMachine
    from idasen_companion.desk.mock import MockDesk

    d = make_daemon_shell()

    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here

    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.activity_log = MagicMock()
    d._ifaces = {"automation": MagicMock()}
    cfg = AppConfig()
    cfg.automation.enabled = enabled
    d.config = cfg
    d.config_file = ConfigFileStore(tmp_path / "config.toml", d.activity_log)
    d.config_file.save(cfg)
    d.machine = StateMachine(cfg, MockDesk(height=Length(0.62)), now=WallInstant(time.time()))
    return d, load_config


def test_set_automation_enabled_persists_to_config(tmp_path):
    d, load = _enable_daemon(tmp_path)
    d.set_automation_enabled(False)
    assert load(d.config_file.path).automation.enabled is False
    assert d.machine.status(WallInstant(0.0)).value == "disabled"
    _assert_announced(d)


async def test_snooze_deadline_adapters_keep_scalar_zero_and_clamped_minutes(tmp_path, monkeypatch):
    from idasen_companion.daemon import main as main_mod
    from idasen_companion.daemon.service import Automation1

    d, _ = _enable_daemon(tmp_path)
    interface = Automation1(d)
    assert d.machine.snooze_until is None
    assert interface.SnoozeUntil == 0.0
    monkeypatch.setattr(main_mod.time, "time", lambda: 0.0)
    await d.snooze(0)
    assert d.machine.snooze_until == WallInstant(60.0)
    assert d.activity_log.emit.call_args.kwargs == {"minutes": 1, "duration": 60}
    for deadline, expected in ((WallInstant(60.0), 60.0),
                               (WallInstant(0.0), 0.0),
                               (WallInstant(-2.5), -2.5), (None, 0.0)):
        d.machine.snooze_until = deadline
        d._emit_automation_state()
        payload = d._ifaces["automation"].emit_properties_changed.call_args.args[0]
        assert interface.SnoozeUntil == payload["SnoozeUntil"] == expected
        assert type(interface.SnoozeUntil) is float
        assert type(payload["SnoozeUntil"]) is float


def test_set_automation_enabled_is_a_no_op_when_unchanged(tmp_path):
    d, _ = _enable_daemon(tmp_path)
    d.set_automation_enabled(True)
    # This asserted `not d.activity_log.info.called`, which could never fail:
    # RingLog has no `info` method (only emit/diag/_record/entries) and
    # `d.activity_log` is a MagicMock, so the attribute was auto-created and
    # never called. Deleting the early return in set_automation_enabled still
    # passed.
    assert not d.activity_log.emit.called, \
        "logged a change that did not happen"
    auto = d._ifaces["automation"]
    assert not auto.StatusChanged.called, "bus traffic for a no-op"
    assert not auto.emit_properties_changed.called


def test_turning_automation_back_on_starts_a_fresh_cycle(tmp_path):
    d, _ = _enable_daemon(tmp_path, enabled=False)
    d.set_automation_enabled(True)
    assert d.machine.target_duration > Duration.from_seconds(0)
    assert d.machine.active_time == Duration.from_seconds(0)


def test_an_automation_write_consumes_its_own_revision(tmp_path):
    d, _ = _enable_daemon(tmp_path)
    d.set_automation_enabled(False)
    assert not d.config_file.poll_changed()


@pytest.mark.parametrize("error_kind", ["config", "os"])
def test_failed_automation_write_restores_state_without_announcing(tmp_path, monkeypatch, error_kind):
    from dbus_fast import DBusError
    from idasen_companion.core.config import ConfigError
    from idasen_companion.daemon import config_file as config_file_mod

    d, load = _enable_daemon(tmp_path)
    before_status = d.machine.status(WallInstant(0.0))
    error = ConfigError("invalid") if error_kind == "config" else OSError("disk full")
    monkeypatch.setattr(config_file_mod, "save_config", MagicMock(side_effect=error))

    with pytest.raises(DBusError) as raised:
        d.set_automation_enabled(False)

    assert raised.value.type.endswith(".Error.ConfigWriteFailed")
    assert d.config.automation.enabled is True
    assert load(d.config_file.path).automation.enabled is True
    assert d.machine.status(WallInstant(0.0)) == before_status
    d.activity_log.emit.assert_not_called()
    d._ifaces["automation"].StatusChanged.assert_not_called()
    d._ifaces["automation"].emit_properties_changed.assert_not_called()
    assert not d.config_file.poll_changed()


async def test_setup_saves_through_the_same_watcher_before_scheduling_sync(tmp_path):
    d, load = _enable_daemon(tmp_path)
    d.mock_mode = True
    d.desk = MagicMock(get_height=AsyncMock(return_value=Length(0.95)))
    observed = []

    async def sync():
        observed.append((load(d.config_file.path).desk.mac,
                         d.config_file.poll_changed()))

    d._post_setup_sync = sync
    assert await d.setup_desk(" AA:BB:CC:DD:EE:FF ") == Length(0.95)
    await asyncio.gather(*d._tasks)

    assert observed == [("AA:BB:CC:DD:EE:FF", False)]


def test_live_height_keeps_domain_cache_and_scalar_bus_payload(tmp_path, monkeypatch):
    from idasen_companion.daemon import main as main_mod
    from idasen_companion.daemon.service import Desk1

    d = Daemon(tmp_path / "config.toml", mock_desk=True, stats_path=tmp_path / "stats.sqlite")
    d.machine = MagicMock()
    clock = 0.499
    monkeypatch.setattr(main_mod, "time", SimpleNamespace(monotonic=lambda: clock))
    iface = MagicMock()

    class Interfaces(dict):
        def get(self, key):
            # Throttle admission advances the stamp before interface lookup.
            assert d._last_height_emit == MonotonicInstant(clock)
            return super().get(key)

    d._ifaces = Interfaces(desk=iface)
    try:
        assert d._last_height_emit == MonotonicInstant(0.0)
        d._on_live_height(Length(0.95))
        assert d.machine.last_height == Length(0.95)
        iface.HeightChanged.assert_not_called()
        assert d._last_height_emit == MonotonicInstant(0.0)

        clock = 0.5
        d._on_live_height(Length(1.105))
        assert d.machine.last_height == Length(1.105)
        iface.HeightChanged.assert_called_once_with(1.105)
        iface.emit_properties_changed.assert_called_once_with({"Height": 1.105})
        assert Desk1(d).Height == 1.105

        d._ifaces.clear()
        clock = 1.0
        d._on_live_height(Length(1.12))
        assert d._last_height_emit == MonotonicInstant(1.0)
    finally:
        d.stats.close()


async def test_direct_height_bounds_remain_inclusive_and_do_not_accept_slack(tmp_path):
    import math
    from dbus_fast.errors import DBusError
    from idasen_companion.core.config import MIN_HEIGHT, MAX_HEIGHT

    d, _ = _enable_daemon(tmp_path)
    d._manual_move = AsyncMock()
    for height in (MIN_HEIGHT, MAX_HEIGHT):
        await d.manual_move_to_height(Length(height))
    assert [call.args[0] for call in d._manual_move.await_args_list] == [
        Length(MIN_HEIGHT), Length(MAX_HEIGHT)]
    for height in (math.nextafter(MIN_HEIGHT, -math.inf),
                   math.nextafter(MAX_HEIGHT, math.inf)):
        with pytest.raises(DBusError) as error:
            await d.manual_move_to_height(Length(height))
        assert error.value.type.endswith(".Error.OutOfRange")
    assert d._manual_move.await_count == 2


async def test_capture_rounds_before_slack_validation_and_stores_raw_metres(tmp_path):
    from dbus_fast.errors import DBusError

    d, load = _enable_daemon(tmp_path)
    d._ifaces["presets"] = MagicMock()
    d.desk = MagicMock(get_height=AsyncMock(return_value=Length(0.60996)))
    d.machine._desk = d.desk
    assert await d.capture_current_preset("low") == Length(0.61)
    d.save_preset("high", Length(1.28))
    d.save_preset("lean", Length(0.955555))
    saved = load(d.config_file.path).presets
    assert saved["low"] == 0.61 and saved["high"] == 1.28
    assert saved["lean"] == 0.9556
    assert all(type(saved[name]) is float for name in ("low", "high", "lean"))
    with pytest.raises(DBusError) as error:
        d.save_preset("outside", Length(0.60996))
    assert error.value.type.endswith(".Error.InvalidPreset")
