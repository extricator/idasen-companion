"""A failed move comes and tells you.

``MoveFailed`` means the desk ignored the app for a quarter of a minute across
two fresh BLE clients — the retry path reconnects rather than reusing a link
that already failed — the cycle resets, and up to a whole interval is lost.
Until now that was recorded in four places you had to go and look at. The
notification — with a "Try now" button — turns the lost interval into
something you choose to ignore rather than something that happens to you.

Built on the ``_daemon()`` MagicMock pattern from test_log_messages.py, which
is where the other ``_handle_event`` side effects are covered; the state
machine itself is unchanged by this work.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from idasen_companion.core.machine import (
    DeskState, HeldOffCycle, MoveFailed, SyncFailed,
)
from idasen_companion.core.presentation.formatter import (
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.gettext_translator import (
    GettextTranslator,
)
from idasen_companion.core.presentation.plain_locale import PlainLocaleFormatter
from idasen_companion.core.units import HeightUnit
from idasen_companion.daemon.main import Daemon

TARGET = 45 * 60


def _daemon(*, problems: bool = True, enabled: bool = False):
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.activity_log = MagicMock()
    d.stats = MagicMock()
    d.desk = MagicMock(last_error=None)
    d.config = MagicMock()
    d.config.notifications.enabled = enabled
    d.config.notifications.problems = problems
    d._ifaces = {"automation": MagicMock()}
    d.machine = MagicMock(held=False, target_duration=TARGET)
    d.machine.cycle_target.return_value = TARGET
    # A real Formatter, not a MagicMock: these tests assert on the rendered
    # summary and body handed to the notifier. Built directly rather than
    # through Daemon._build_formatter because `config` above is a MagicMock,
    # which has no resolvable [ui] units — the pair is the same one the
    # daemon builds for itself (D-06).
    d.fmt = Formatter(PresentationContext(
        locale=PlainLocaleFormatter(), translator=GettextTranslator(),
        unit=HeightUnit.CENTIMETRES))
    d._notifier = MagicMock(send=AsyncMock())
    d.manual_move_to_preset = AsyncMock()
    return d


def _failed(intended=DeskState.STANDING):
    # Named, not positional: MoveFailed declares `previous` first (the state
    # kept, since nothing moved) and `intended` second.
    previous = (DeskState.SITTING if intended is DeskState.STANDING
                else DeskState.STANDING)
    return MoveFailed(previous=previous, intended=intended,
                      next_target_duration=TARGET)


async def _settle():
    """Let the fire-and-forget notification task run."""
    await asyncio.sleep(0)


async def test_a_failed_move_notifies():
    d = _daemon()
    d.desk.last_error = "connect timed out"
    d._handle_event(_failed(), "automation")
    await _settle()
    d._notifier.send.assert_called_once()
    summary, body = d._notifier.send.call_args.args
    assert summary == "The desk didn't stand up"
    assert "connect timed out" in body


async def test_a_failed_sit_says_so():
    d = _daemon()
    d._handle_event(_failed(DeskState.SITTING), "automation")
    await _settle()
    summary, body = d._notifier.send.call_args.args
    assert summary == "The desk didn't sit down"
    # No reason available from the desk layer: the body still has to say what
    # happened, just not why.
    assert body == "It didn't respond. The next change is a whole interval away."


async def test_turning_the_setting_off_stops_the_notification():
    d = _daemon(problems=False)
    d._handle_event(_failed(), "automation")
    await _settle()
    d._notifier.send.assert_not_called()
    # The log lines are not the setting's business — they still go out.
    assert d.activity_log.emit.called


async def test_try_now_moves_to_the_preset_the_move_was_aiming_at():
    d = _daemon()
    d._handle_event(_failed(), "automation")
    await _settle()
    actions = d._notifier.send.call_args.kwargs["actions"]
    label, callback = actions["try-now"]
    assert label == "Try now"
    callback()
    await _settle()
    d.manual_move_to_preset.assert_awaited_once_with("stand")


async def test_try_now_after_a_failed_sit_moves_to_sit():
    d = _daemon()
    d._handle_event(_failed(DeskState.SITTING), "automation")
    await _settle()
    _label, callback = d._notifier.send.call_args.kwargs["actions"]["try-now"]
    callback()
    await _settle()
    d.manual_move_to_preset.assert_awaited_once_with("sit")


async def test_a_retry_that_fails_again_does_not_escape_the_task():
    """The move raises DBusError with nobody to receive it — a bare task would
    turn that into an asyncio "exception was never retrieved" traceback."""
    d = _daemon()
    d.manual_move_to_preset = AsyncMock(side_effect=RuntimeError("still dead"))
    await d._retry_failed_move("stand")
    assert any(call.args[0] == "warning"
               for call in d.activity_log.diag.call_args_list)


# ---- guards for the two deliberate exclusions -------------------------------
#
# Both of these are decisions, not oversights — see each test's docstring
# below for the reasoning. Do not "fix" them by wiring the notification up.


async def test_a_routine_sync_failure_never_notifies():
    """SyncFailed fires on every routine position check that can't reach the
    desk — every 5 minutes by default — so a desk left switched off would
    notify all afternoon. It stays a log line however `problems` is set."""
    d = _daemon(problems=True, enabled=True)
    d._handle_event(SyncFailed(), "automation")
    await _settle()
    d._notifier.send.assert_not_called()


async def test_automation_paused_still_rides_the_announcements_setting():
    """HeldOffCycle fires because *the user* moved the desk: it is the app
    explaining itself, not reporting a fault. Moving it onto `problems` would
    also silently change behaviour for anyone who already unticked `enabled`."""
    d = _daemon(problems=True, enabled=False)
    d._handle_event(HeldOffCycle(0.95), "automation")
    await _settle()
    d._notifier.send.assert_not_called()

    d = _daemon(problems=False, enabled=True)
    d._handle_event(HeldOffCycle(0.95), "automation")
    await _settle()
    d._notifier.send.assert_called_once()
