"""Control ops must announce automation state immediately.

Regression for: pause/resume/skip/snooze changed the state machine but never
emitted StatusChanged/ProgressChanged, so clients (window + tray) only found
out on the next periodic tick (up to check_interval = 60s later).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from idasen_companion.daemon.main import Daemon


def _daemon():
    """A Daemon with just the collaborators the control ops touch, bypassing
    the real __init__ (which builds a RingLog, D-Bus service, desk, ...)."""
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.activity_log = MagicMock()
    d.machine = MagicMock()
    d.machine.active_time = 120.0
    d.machine.target_duration = 300.0
    d.machine.snooze_until = 0.0
    d.machine.skip_next = False
    d.machine.status.return_value = MagicMock(value="active")
    d.config = MagicMock()
    d.config.automation.enabled = True
    d._ifaces = {"automation": MagicMock()}
    return d


def _assert_announced(d):
    auto = d._ifaces["automation"]
    assert auto.StatusChanged.called, "StatusChanged not emitted"
    assert auto.ProgressChanged.called, "ProgressChanged not emitted"
    assert auto.emit_properties_changed.called, "PropertiesChanged not emitted"


def test_pause_emits_state():
    d = _daemon()
    d.pause()
    assert d.machine.pause.called
    _assert_announced(d)


def test_resume_emits_state():
    d = _daemon()
    d.resume()
    assert d.machine.resume.called
    _assert_announced(d)


def test_skip_next_emits_state():
    d = _daemon()
    d.skip_next()
    assert d.machine.request_skip_next.called
    _assert_announced(d)


def test_snooze_emits_state():
    d = _daemon()
    d.snooze(10)
    assert d.machine.snooze.called
    _assert_announced(d)


@pytest.mark.parametrize("op", ["pause", "resume", "skip_next", "snooze"])
def test_progress_uses_current_machine_values(op):
    d = _daemon()
    (d.snooze if op == "snooze" else getattr(d, op))(
        *( (10,) if op == "snooze" else () ))
    d._ifaces["automation"].ProgressChanged.assert_called_with(120.0, 300.0)


async def test_toggle_moves_to_machine_chosen_preset():
    # Desk1.Toggle delegates the "which way?" decision to the machine and
    # moves there — the tray click and --toggle shortcut both ride this path.
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.machine = MagicMock()
    d.machine.refresh_height = AsyncMock()
    d.machine.toggle_target_preset.return_value = "stand"
    d.manual_move_to_preset = AsyncMock()
    await d.toggle_sit_stand()
    d.machine.refresh_height.assert_awaited_once()  # pre-decide read before deciding
    d.manual_move_to_preset.assert_awaited_once_with("stand")


def _gesture_daemon(*, moving=False, active=None, start_height=0.62,
                    repeat="reverse"):
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.activity_log = MagicMock()
    d.moving = moving
    d._gesture_action = active
    d._gesture_start_height = start_height
    d.config = MagicMock()
    d.config.ui.tray_repeat_move = repeat
    d.machine = MagicMock()
    d.machine.last_height = 0.75
    d.machine.refresh_height = AsyncMock()  # the START-path pre-decide read
    d.toggle_sit_stand = AsyncMock()
    d.manual_move_to_preset = AsyncMock()
    d.manual_move_to_height = AsyncMock()
    d.stop_movement = AsyncMock()
    return d


async def test_gesture_move_idle_starts_and_records_start():
    d = _gesture_daemon(moving=False)
    await d.gesture_move("toggle")
    d.machine.refresh_height.assert_awaited_once()  # pre-decide read on start
    d.toggle_sit_stand.assert_awaited_once_with(refresh=False)  # no double read
    d.stop_movement.assert_not_awaited()
    assert d._gesture_action == "toggle"
    assert d._gesture_start_height == 0.75  # captured from machine.last_height


async def test_gesture_toggle_start_height_is_fresh_not_stale_cache():
    # The reverse target must be the desk's real position when the gesture
    # fired, not a stale cache. It's captured AFTER the pre-decide read, so an
    # external move (cache 0.62, desk really at 1.10) is reflected — and the
    # toggle direction and reverse target agree.
    d = _gesture_daemon(moving=False)
    d.machine.last_height = 0.62  # stale cache

    async def do_refresh(_now):
        d.machine.last_height = 1.10  # the real position

    d.machine.refresh_height = AsyncMock(side_effect=do_refresh)
    await d.gesture_move("toggle")
    assert d._gesture_start_height == 1.10  # fresh, not the 0.62 cache
    d.toggle_sit_stand.assert_awaited_once_with(refresh=False)


async def test_sit_gesture_also_reads_before_recording_start():
    # Non-toggle gestures get the same fresh reverse target (and move directly).
    d = _gesture_daemon(moving=False)
    d.machine.last_height = 0.62

    async def do_refresh(_now):
        d.machine.last_height = 1.10

    d.machine.refresh_height = AsyncMock(side_effect=do_refresh)
    await d.gesture_move("sit")
    d.machine.refresh_height.assert_awaited_once()
    assert d._gesture_start_height == 1.10
    d.manual_move_to_preset.assert_awaited_once_with("sit")


async def test_sit_gesture_skips_read_when_not_reversing():
    # With repeat != "reverse" the reverse target is never used, so an explicit
    # sit/stand skips the pre-move read and starts moving a round-trip sooner.
    d = _gesture_daemon(moving=False, repeat="stop")
    d.machine.last_height = 0.75
    await d.gesture_move("sit")
    d.machine.refresh_height.assert_not_awaited()
    assert d._gesture_start_height == 0.75  # cached pre-move height
    d.manual_move_to_preset.assert_awaited_once_with("sit")


async def test_toggle_gesture_reads_even_without_reverse():
    # Toggle always needs the fresh position to choose a direction, regardless
    # of the repeat mode.
    d = _gesture_daemon(moving=False, repeat="stop")
    await d.gesture_move("toggle")
    d.machine.refresh_height.assert_awaited_once()
    d.toggle_sit_stand.assert_awaited_once_with(refresh=False)


async def test_gesture_move_repeat_reverses_to_start():
    d = _gesture_daemon(moving=True, active="toggle", start_height=0.62,
                        repeat="reverse")
    await d.gesture_move("toggle")
    # The reverse move is the successor, so the "moving" flag stays up for it.
    d.stop_movement.assert_awaited_once_with(expect_successor=True)
    d.manual_move_to_height.assert_awaited_once_with(0.62)
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
    d.desk = MockDesk(height=0.62)
    d.machine = StateMachine(cfg, d.desk, now=time.time())
    await d.machine.start(time.time())  # last_height = 0.62, state sitting
    return d


async def test_manual_preset_move_returns_to_start_on_interruption():
    # Physical paddle stops the toward-stand move at 0.80; the desk should
    # return to where it started (0.62), not park off-cycle.
    d = await _interruptible_daemon("undo")
    d.desk.interrupt_next_move_at = 0.80
    await d.manual_move_to_preset("stand")
    assert d.desk.move_calls == [1.10, 0.62]
    assert abs(d.desk.height - 0.62) < 1e-9


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
    assert d.desk.move_calls == [1.10]


async def test_manual_preset_move_respects_leave_policy():
    d = await _interruptible_daemon("leave")
    d.desk.interrupt_next_move_at = 0.80
    await d.manual_move_to_preset("stand")
    assert d.desk.move_calls == [1.10]  # left where the paddle stopped it


async def test_manual_preset_move_does_not_retry():
    # "Try again" is an automation-only policy: a companion move you stop by
    # hand is a live instruction to stop, so the manual path treats it as
    # "leave" rather than pushing back against the paddle.
    d = await _interruptible_daemon("retry")
    d.desk.interrupt_next_move_at = 0.80
    await d.manual_move_to_preset("stand")
    assert d.desk.move_calls == [1.10]


async def test_manual_move_to_height_does_not_bounce_back():
    # The slider's explicit target (and the reverse gesture) must not return.
    d = await _interruptible_daemon("undo")
    d.desk.interrupt_next_move_at = 0.80
    await d.manual_move_to_height(1.05)
    assert d.desk.move_calls == [1.05]


async def test_software_stop_mid_move_does_not_return_to_start():
    # A deliberate stop (Desk1.Stop / repeat-stop) or a superseding move bumps
    # _current_move_id during the move; the desk must then stay where it stopped
    # rather than bounce back like a physical interruption would.
    d = await _interruptible_daemon("undo")
    d.desk.interrupt_next_move_at = 0.80
    orig_move_to = d.desk.move_to

    async def move_to_then_stop(h):
        result = await orig_move_to(h)
        d._current_move_id += 1  # stand in for stop_movement()/a superseding move
        return result

    d.desk.move_to = move_to_then_stop
    await d.manual_move_to_preset("stand")
    assert d.desk.move_calls == [1.10]  # no return move — stayed put


async def test_superseded_move_keeps_moving_flag_and_skips_reconcile():
    # When a newer move supersedes this one mid-flight, this move must not
    # clear the shared "moving" flag (the newer move owns it) nor run its own
    # reconciliation (which would read a mid-flight height).
    d = await _interruptible_daemon()
    d.machine.force_sync = AsyncMock(return_value=[])
    orig_move_to = d.desk.move_to

    async def supersede(h):
        result = await orig_move_to(h)
        d._current_move_id += 1  # a newer move started during ours
        return result

    d.desk.move_to = supersede
    await d.manual_move_to_preset("stand")
    assert d.moving is True  # left True for the superseding move to clear
    d.machine.force_sync.assert_not_called()  # skipped its own reconciliation


def _stopping_daemon(*, moving=True, gesture="stand"):
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.activity_log = MagicMock()
    d.desk = MagicMock()
    d.desk.stop = AsyncMock()
    d._current_move_id = 5
    d.moving = moving
    d._gesture_action = gesture
    d._gesture_start_height = 0.62
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
    d.machine = MagicMock(last_height=1.10)
    d.machine.refresh_height = AsyncMock()
    d.manual_move_to_preset = AsyncMock()
    d.manual_move_to_height = AsyncMock()

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
    from idasen_companion.core.config import AppConfig, load_config, save_config
    from idasen_companion.core.machine import StateMachine
    from idasen_companion.desk.mock import MockDesk

    d = Daemon.__new__(Daemon)

    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here

    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.activity_log = MagicMock()
    d._ifaces = {"automation": MagicMock()}
    cfg = AppConfig()
    cfg.automation.enabled = enabled
    d.config = cfg
    d.config_path = tmp_path / "config.toml"
    save_config(cfg, d.config_path)
    d.machine = StateMachine(cfg, MockDesk(height=0.62), now=time.time())
    # set_automation_enabled now re-checks the file before writing, so a hand
    # edit made in the last check_interval isn't clobbered. Seed the mtime the
    # way the daemon would have after writing this file itself; leaving it None
    # would make the check treat the file as newly appeared and hot-reload it.
    d._config_mtime = d.config_path.stat().st_mtime
    return d, load_config


def test_set_automation_enabled_persists_to_config(tmp_path):
    d, load = _enable_daemon(tmp_path)
    d.set_automation_enabled(False)
    assert load(d.config_path).automation.enabled is False
    assert d.machine.status(0.0).value == "disabled"
    _assert_announced(d)


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
    assert d.machine.target_duration > 0
    assert d.machine.active_time == 0
