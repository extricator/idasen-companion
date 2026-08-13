"""The pre-move warning and its Snooze / Skip buttons.

The most-seen output the app produces, and it sat at zero coverage:
`_maybe_warn` was entirely unexecuted and `daemon/notify.py` at 28%, with
`Notifier.send`, `_ensure_signal_subscription` and `_on_message` never run.

Two subtleties are pinned here because both fail silently:

  - `_on_message` matches on the notification id, so a *stale* popup's button
    cannot act on the current cycle. Break it and clicking Snooze on an old
    notification snoozes a cycle the user wasn't looking at.
  - `_maybe_warn` deliberately keeps warning in the "move-failed" status: a
    failed move does not stop the cycle, so the warning must not switch itself
    off until the next success.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from idasen_companion.core.config import AppConfig
from idasen_companion.core.machine import DeskState, Status
from idasen_companion.daemon.dbus_util import DBusCallError
from idasen_companion.daemon.main import Daemon
from idasen_companion.daemon.notify import NOTIFY_IFACE, Notifier


# ----- Notifier -----

def make_bus():
    bus = MagicMock()
    bus.add_message_handler = MagicMock()
    return bus


def patch_call(monkeypatch, result=None, error=None):
    """Replace notify.call, recording every invocation."""
    import idasen_companion.daemon.notify as notify_mod
    calls = []

    async def fake(bus, dest, path, iface, member, sig=None, body=None):
        calls.append((dest, member, body))
        if error is not None:
            raise error
        return result if result is not None else [7]

    monkeypatch.setattr(notify_mod, "call", fake)
    return calls


async def test_send_flattens_actions_into_the_key_label_list(monkeypatch):
    calls = patch_call(monkeypatch)
    n = Notifier(make_bus())

    ok = await n.send("Standing up in about 2 minutes", "body",
                      actions={"snooze": ("Snooze 15 min", lambda: None),
                               "skip": ("Skip this one", lambda: None)})

    assert ok
    notify = [c for c in calls if c[1] == "Notify"][0]
    # org.freedesktop.Notifications takes a flat [key, label, key, label] array.
    assert notify[2][5] == ["snooze", "Snooze 15 min", "skip", "Skip this one"]
    assert notify[2][3] == "Standing up in about 2 minutes"


async def test_send_reports_failure_instead_of_raising(monkeypatch):
    patch_call(monkeypatch, error=DBusCallError("no notification server"))
    n = Notifier(make_bus())
    assert await n.send("summary") is False  # daemon carries on without one


async def test_actions_subscribe_once_not_per_notification(monkeypatch):
    calls = patch_call(monkeypatch)
    n = Notifier(make_bus())
    for _ in range(3):
        await n.send("s", actions={"skip": ("Skip", lambda: None)})
    assert len([c for c in calls if c[1] == "AddMatch"]) == 1


async def test_a_notification_without_actions_does_not_subscribe(monkeypatch):
    calls = patch_call(monkeypatch)
    n = Notifier(make_bus())
    await n.send("summary")
    assert [c for c in calls if c[1] == "AddMatch"] == []


def make_action_message(notification_id, key):
    m = MagicMock()
    m.interface = NOTIFY_IFACE
    m.member = "ActionInvoked"
    m.body = [notification_id, key]
    return m


async def test_the_current_notifications_button_fires(monkeypatch):
    patch_call(monkeypatch, result=[42])
    fired = []
    n = Notifier(make_bus())
    await n.send("s", actions={"snooze": ("Snooze", lambda: fired.append("snooze"))})

    n._on_message(make_action_message(42, "snooze"))
    assert fired == ["snooze"]


async def test_a_stale_notifications_button_is_ignored(monkeypatch):
    """The id check is the whole guard. Without it, clicking Snooze on a
    notification from a previous cycle snoozes the current one."""
    patch_call(monkeypatch, result=[42])
    fired = []
    n = Notifier(make_bus())
    await n.send("s", actions={"snooze": ("Snooze", lambda: fired.append("snooze"))})

    n._on_message(make_action_message(41, "snooze"))   # the previous popup
    assert fired == []


async def test_an_unknown_action_key_is_ignored(monkeypatch):
    patch_call(monkeypatch, result=[42])
    n = Notifier(make_bus())
    await n.send("s", actions={"snooze": ("Snooze", lambda: None)})
    n._on_message(make_action_message(42, "detonate"))  # must not raise


async def test_unrelated_signals_are_left_alone(monkeypatch):
    patch_call(monkeypatch, result=[42])
    fired = []
    n = Notifier(make_bus())
    await n.send("s", actions={"snooze": ("Snooze", lambda: fired.append("x"))})

    other = MagicMock()
    other.interface = "org.example.Other"
    other.member = "ActionInvoked"
    other.body = [42, "snooze"]
    assert n._on_message(other) is None  # not handled exclusively
    assert fired == []


# ----- _maybe_warn -----

def warn_daemon(*, remaining, target=1500, status="active",
                lead_time=30, check_interval=60, enabled=True,
                state=DeskState.SITTING):
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.config = AppConfig()
    d.config.notifications.enabled = enabled
    d.config.notifications.lead_time = lead_time
    d.config.automation.check_interval = check_interval
    d.machine = MagicMock()
    d.machine.time_remaining.return_value = remaining
    d.machine.target_duration = target
    d.machine.state = state
    # A real Status, not a MagicMock: _maybe_warn compares against
    # COUNTDOWN_STATUSES, and a stand-in matches nothing.
    d.machine.status.return_value = Status(status)
    d._warned_this_cycle = False
    d._ifaces = {"automation": MagicMock()}
    d._notifier = MagicMock()
    d._notifier.send = AsyncMock(return_value=True)
    return d


async def drain():
    """Let the fire-and-forget notification task run."""
    await asyncio.sleep(0)


async def test_warning_fires_once_inside_the_window():
    d = warn_daemon(remaining=45)
    await d._maybe_warn(0.0)
    await drain()
    d._ifaces["automation"].PreMoveWarning.assert_called_once_with("standing", 45)
    d._notifier.send.assert_awaited_once()


async def test_warning_does_not_repeat_within_the_same_cycle():
    d = warn_daemon(remaining=45)
    for _ in range(4):
        await d._maybe_warn(0.0)
    await drain()
    assert d._ifaces["automation"].PreMoveWarning.call_count == 1


async def test_warning_rearms_once_the_cycle_moves_out_of_the_window():
    d = warn_daemon(remaining=45)
    await d._maybe_warn(0.0)
    d.machine.time_remaining.return_value = 900      # new cycle, far out
    await d._maybe_warn(0.0)
    assert d._warned_this_cycle is False
    d.machine.time_remaining.return_value = 45
    await d._maybe_warn(0.0)
    await drain()
    assert d._ifaces["automation"].PreMoveWarning.call_count == 2


async def test_no_warning_outside_the_window():
    d = warn_daemon(remaining=600)
    await d._maybe_warn(0.0)
    d._ifaces["automation"].PreMoveWarning.assert_not_called()


async def test_no_warning_when_notifications_are_off():
    d = warn_daemon(remaining=45, enabled=False)
    await d._maybe_warn(0.0)
    d._ifaces["automation"].PreMoveWarning.assert_not_called()


async def test_no_warning_when_no_cycle_is_running():
    d = warn_daemon(remaining=45, target=0)
    await d._maybe_warn(0.0)
    d._ifaces["automation"].PreMoveWarning.assert_not_called()


@pytest.mark.parametrize("status", ["paused", "snoozed", "out-of-schedule",
                                    "disabled", "user-idle"])
async def test_no_warning_while_the_cycle_is_frozen(status):
    d = warn_daemon(remaining=45, status=status)
    await d._maybe_warn(0.0)
    d._ifaces["automation"].PreMoveWarning.assert_not_called()


async def test_a_failed_move_keeps_warning():
    """A failed move does not stop the cycle — the next attempt is still
    coming — so the warning must not switch itself off until the next
    success. Dropping "move-failed" from the allowed statuses is silent."""
    d = warn_daemon(remaining=45, status="move-failed")
    await d._maybe_warn(0.0)
    await drain()
    d._ifaces["automation"].PreMoveWarning.assert_called_once_with("standing", 45)


async def test_the_window_is_at_least_one_check_interval():
    """With lead_time < check_interval the window widens to the interval, so a
    tick reliably lands inside it. A bare 30s window on a 60s tick can be
    jumped clean over, silently dropping the warning."""
    d = warn_daemon(remaining=50, lead_time=30, check_interval=60)
    await d._maybe_warn(0.0)
    await drain()
    d._ifaces["automation"].PreMoveWarning.assert_called_once()


async def test_the_announced_time_is_the_real_remaining_time():
    """Not the lead time: with the window rounded up to check_interval the
    warning fires early, and must say how long is actually left."""
    d = warn_daemon(remaining=52, lead_time=30, check_interval=60)
    await d._maybe_warn(0.0)
    await drain()
    _state, seconds = d._ifaces["automation"].PreMoveWarning.call_args.args
    assert seconds == 52


async def test_the_warning_names_the_direction_the_desk_will_go():
    d = warn_daemon(remaining=45, state=DeskState.STANDING)
    await d._maybe_warn(0.0)
    await drain()
    d._ifaces["automation"].PreMoveWarning.assert_called_once_with("sitting", 45)


async def test_snooze_and_skip_are_offered_and_wired_to_the_daemon():
    d = warn_daemon(remaining=45)
    d.snooze = MagicMock()
    d.skip_next = MagicMock()
    await d._maybe_warn(0.0)
    await drain()

    actions = d._notifier.send.await_args.kwargs["actions"]
    assert set(actions) == {"snooze", "skip"}

    actions["snooze"][1]()
    d.snooze.assert_called_once()
    actions["skip"][1]()
    d.skip_next.assert_called_once()
