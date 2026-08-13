"""Rule 1 from docs/LOGGING.md: a line that changes when the desk will next
move must say when.

The trailing "Next change after ..." used to be attached per call site, so it
appeared on the five events that happened to carry a duration and was missing
from every event that *reset the accumulator* — coming back from idle, waking
from suspend, a time jump, returning to your session. Those are exactly the
lines that most need it: they tell the user the clock went back to zero and
then decline to say what it is counting toward.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from idasen_companion.core import logmsg
from idasen_companion.core.machine import (
    AwayChanged, DeskState, IdleChanged, MoveFailed, ResumedOnCycle,
    SeatChanged, StateSynced, TimeJumpDetected, TransitionCompleted,
)
from idasen_companion.daemon.main import Daemon
from idasen_companion.daemon.ringlog import FORMATTERS

TARGET = 25 * 60


def _daemon(target: int = TARGET):
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.activity_log = MagicMock()
    d.stats = MagicMock()
    d.desk = MagicMock(last_error=None)
    d.config = MagicMock()
    # Both notification gates off: this file is about the *lines* the daemon
    # logs, and a MagicMock answers every unset attribute truthily — which
    # would send this bare daemon down the notify path instead.
    d.config.notifications.enabled = False
    d.config.notifications.problems = False
    d._ifaces = {"automation": MagicMock()}
    d.machine = MagicMock(held=False, target_duration=target)
    # What the daemon asks for now: the machine decides whether a cycle is
    # running at all (see test_cycle_target.py for the real thing).
    d.machine.cycle_target.return_value = target
    return d


def _lines(d):
    """Every line the daemon logged, rendered the way the journal sees it."""
    out = []
    for call in d.activity_log.emit.call_args_list:
        message, params = call.args[0], call.kwargs
        out.append(logmsg.render(message, params, FORMATTERS))
    for call in d.activity_log.diag.call_args_list:
        out.append(call.args[1])
    return out


# Events that carry the new cycle length themselves, because the machine
# rolled one when it emitted them.
@pytest.mark.parametrize("event", [
    TransitionCompleted(DeskState.SITTING, DeskState.STANDING,
                        DeskState.STANDING, interrupted=False, recovery="none",
                        final_height=1.10, trigger="automation",
                        next_target_duration=TARGET),
    StateSynced(DeskState.SITTING, DeskState.STANDING, 1.10, TARGET),
    ResumedOnCycle(DeskState.SITTING, DeskState.STANDING, 1.10, TARGET),
    MoveFailed(DeskState.SITTING, DeskState.STANDING, 45 * 60),
])
def test_cycle_restart_says_when_the_next_change_is_due(event):
    d = _daemon()
    d._handle_event(event, "automation")
    assert any("Next change after" in line for line in _lines(d)), _lines(d)


# Events that reset the accumulator without rolling a new target. The cycle
# length is unchanged — only the progress was discarded — so the number has to
# come off the machine. This is the case the whole item came from.
@pytest.mark.parametrize("event", [
    IdleChanged(False, 0, reset=True),
    AwayChanged(False, reset=True),
    SeatChanged(True, reset=True),
    TimeJumpDetected(3600.0),
])
def test_reset_events_say_what_the_clock_is_now_counting_toward(event):
    d = _daemon()
    d._handle_event(event, "automation")
    lines = _lines(d)
    assert any("Next change after 25.0 minutes of active time." in line
               for line in lines), lines


def test_resume_from_suspend_says_what_the_clock_is_counting_toward(monkeypatch):
    """The suspend path doesn't go through _handle_event, and had the same gap."""
    d = _daemon()
    d._idle = MagicMock()
    # The handler kicks off an idle probe; there's no loop to schedule it on.
    # Stubbed at _spawn, the seam the daemon now uses, rather than at
    # asyncio.ensure_future underneath it.
    monkeypatch.setattr(d, "_spawn", lambda coro, what: None)
    message = MagicMock(interface="org.freedesktop.login1.Manager",
                        member="PrepareForSleep", body=[False])
    d._on_system_message(message)
    lines = _lines(d)
    assert any("Next change after 25.0 minutes of active time." in line
               for line in lines), lines
    # Reset before report, or the line states the pre-reset cycle.
    d.machine.reset_after_resume.assert_called_once()


@pytest.mark.parametrize("event", [
    IdleChanged(False, 0, reset=True),
    AwayChanged(False, reset=True),
    SeatChanged(True, reset=True),
    TimeJumpDetected(3600.0),
])
def test_reset_events_promise_nothing_when_no_cycle_is_scheduled(event):
    """Automation off, or the desk held off-cycle: no move is coming, so the
    line must not claim one is."""
    d = _daemon(target=0)
    d._handle_event(event, "automation")
    assert not any("Next change after" in line for line in _lines(d))


def test_scheduled_target_comes_from_the_machine():
    d = _daemon()
    d.machine.cycle_target.return_value = 0
    assert d._scheduled_target() == 0


def test_brief_interruption_keeps_quiet_about_the_target():
    """A brief interruption keeps this cycle's progress, so the full target
    would be wrong and the line already states the resulting state."""
    d = _daemon()
    d._handle_event(IdleChanged(False, 0, reset=False), "automation")
    line = _lines(d)[0]
    assert "keeping this cycle's progress" in line
    assert "Next change after" not in line


def test_interrupted_transition_still_says_when_the_next_change_is_due():
    d = _daemon()
    d._handle_event(TransitionCompleted(
        DeskState.SITTING, DeskState.STANDING, DeskState.SITTING,
        interrupted=True, recovery="undo", final_height=0.95,
        trigger="automation", next_target_duration=45 * 60), "automation")
    assert "Next change after 45.0 minutes of active time." in _lines(d)[0]


def test_failed_move_names_the_retry_window_instead_of_next_cycle():
    d = _daemon()
    d._handle_event(MoveFailed(DeskState.SITTING, DeskState.STANDING, 45 * 60),
                    "automation")
    line = _lines(d)[0]
    assert "will try again next cycle" not in line
    assert "Next change after 45.0 minutes of active time." in line


def test_failed_move_falls_back_when_no_cycle_was_scheduled():
    # next_target 0 means nothing was scheduled (automation off, or the desk is
    # held) — the line must not claim a change is coming.
    d = _daemon()
    d._handle_event(MoveFailed(DeskState.SITTING, DeskState.STANDING, 0),
                    "automation")
    line = _lines(d)[0]
    assert "Next change after" not in line
    assert "Will try again next cycle." in line


def test_failed_move_carries_the_reason_from_the_desk_layer():
    """Per-attempt BLE errors are diagnostic now, so the user-facing warning
    has to carry the last one or it says something failed but not why."""
    d = _daemon()
    d.desk.last_error = "connect timed out"
    d._handle_event(MoveFailed(DeskState.SITTING, DeskState.STANDING, TARGET),
                    "automation")
    assert "connect timed out" in _lines(d)[0]
