"""The translatable twin of the activity message catalog.

``core/logmsg.py`` holds the canonical English and the *structure* of every
activity line — which parameters it takes, whether it changes when the desk
next moves, what to say when nothing is scheduled. This module holds the same
English strings again, wrapped in ``QT_TRANSLATE_NOOP`` so ``lupdate`` can
extract them, and the GUI-side formatters.

Two copies is the price of the two-catalog design: the daemon must not depend
on Qt, and ``lupdate`` only extracts *literals* written inside a recognized
call — a ``QT_TRANSLATE_NOOP(logmsg.SOMETHING.text)`` is invisible to it. The
copies cannot drift silently, though: ``tests/test_log_catalog.py`` fails the
build if an id, a parameter or a string differs between the two.

Rendering differs from the daemon's on purpose. Same raw values, a different
reader: the journal wants ``1.1000m`` (stable, greppable, the units the
config speaks) where the GUI wants ``110.0 cm`` in the user's language,
matching every other number on screen. The duration itself now renders the
same compact shape on both sides (PRES-03) — only the height keeps a
second rendering.
"""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP

from ..core import logmsg
from ..core.presentation.formatter import Formatter
from ..core.logmsg import Param

_CONTEXT = "LogMessage"


def _tr(text: object) -> str:
    """Translate a catalog string at call time.

    Same reason as ``util._tr``: this module is imported before ``main()``
    installs the ``QTranslator``, so the strings are marked for extraction at
    definition time and translated on use.
    """
    return QCoreApplication.translate(_CONTEXT, cast(str, text))


# Lowercase on purpose: these land mid-sentence ("staying sitting."), where
# the capitalized labels in `util.position_label` would read wrong. Separate
# entries so translators can choose the right form for their language.
_STATE_WORDS = {
    "sitting": QT_TRANSLATE_NOOP("LogMessage", "sitting"),
    "standing": QT_TRANSLATE_NOOP("LogMessage", "standing"),
}

_NOT_AVAILABLE = QT_TRANSLATE_NOOP("LogMessage", "N/A")

CYCLE_NOTE = QT_TRANSLATE_NOOP(
    "LogMessage", " Next change after %(next_target)s of active time.")


def _state(value) -> str:
    return _tr(_STATE_WORDS.get(str(value), str(value)))


def build_formatters(fmt: Formatter) -> dict:
    """The per-``Param`` renderer table, built fresh for one render call.

    A module-level dict would close over a bare function once, at import
    time, with no route to the caller's current :class:`Formatter` — the
    same ambient-state trap D-07 closes for every other GUI height/duration
    call site. Building it here instead means the ``Param.DURATION``/
    ``Param.HEIGHT`` entries can read ``fmt`` directly.
    """
    return {
        Param.DURATION: lambda s: (_tr(_NOT_AVAILABLE) if s is None
                                   else fmt.duration(s)),
        Param.HEIGHT: lambda h: (_tr(_NOT_AVAILABLE) if h is None
                                 else fmt.height(h)),
        Param.STATE: _state,
        Param.TEXT: lambda t: _tr(_NOT_AVAILABLE) if t is None else str(t),
        Param.INT: lambda n: str(int(n)),
    }


TEXTS = {
    "daemon.starting": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Idasen Companion daemon %(version)s starting (config: "
        "%(config)s)"),
    "daemon.stopping": QT_TRANSLATE_NOOP(
        "LogMessage", "Daemon stopping."),
    "setup.imported_cli": QT_TRANSLATE_NOOP(
        "LogMessage",
        "First run: imported settings from idasen CLI config "
        "(mac=%(mac)s, %(presets)s preset(s))"),
    "setup.no_desk": QT_TRANSLATE_NOOP(
        "LogMessage",
        "No desk configured yet. Launch Idasen Companion to run the "
        "setup wizard; automation is on hold until then."),
    "setup.testing_desk": QT_TRANSLATE_NOOP(
        "LogMessage", "Setup: testing desk %(mac)s..."),
    "setup.desk_configured": QT_TRANSLATE_NOOP(
        "LogMessage", "Desk configured: %(mac)s (height %(height)s)."),
    "setup.starting_automation": QT_TRANSLATE_NOOP(
        "LogMessage", "Desk configured; starting automation."),
    "config.reloaded": QT_TRANSLATE_NOOP(
        "LogMessage", "Configuration reloaded."),
    "config.reload_failed": QT_TRANSLATE_NOOP(
        "LogMessage", "Config reload failed, keeping old config: %(error)s"),
    "config.desk_mac_changed": QT_TRANSLATE_NOOP(
        "LogMessage", "Desk MAC changed; reconnecting to new desk."),
    "idle.no_provider": QT_TRANSLATE_NOOP(
        "LogMessage",
        "No idle-time provider is available on this desktop, so the app"
        " cannot tell whether you are at the keyboard. Automation will "
        "move the desk on schedule whether you are here or not; idle, "
        "lock and away detection are all inoperative."),
    "presence.now_idle": QT_TRANSLATE_NOOP(
        "LogMessage", "Now idle (%(idle_time)s idle time)"),
    "presence.active_reset": QT_TRANSLATE_NOOP(
        "LogMessage", "Activity detected after idle period; resetting timers."),
    "presence.active_kept": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Activity detected after a brief interruption; keeping this "
        "cycle's progress."),
    "presence.away": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Switched away to another session; automation paused and the "
        "desk released."),
    "presence.back_reset": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Back in your session; automation resumed with a fresh cycle; "
        "re-reading the desk."),
    "presence.back_kept": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Back in your session; automation resumed where it left off; "
        "re-reading the desk."),
    "presence.no_seat": QT_TRANSLATE_NOOP(
        "LogMessage",
        "This account has no graphical session, so there is no desk to "
        "automate and no way to tell whether anyone is at it: "
        "automation is on hold and the desk is left to whoever is "
        "logged in. It still responds to explicit commands from here."),
    "presence.seat_back_reset": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Graphical session detected; automation is live again with a "
        "fresh cycle. Re-reading the desk."),
    "presence.seat_back_kept": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Graphical session detected; automation is live again where it "
        "left off. Re-reading the desk."),
    "suspend.suspending": QT_TRANSLATE_NOOP(
        "LogMessage", "System is suspending."),
    "suspend.resumed": QT_TRANSLATE_NOOP(
        "LogMessage", "Resumed from suspend; resetting timers."),
    "time.jump": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Detected potential time jump (%(elapsed)s elapsed); resetting "
        "state."),
    "time.stepped_back": QT_TRANSLATE_NOOP(
        "LogMessage",
        "The system clock moved backwards by %(elapsed)s; resetting state."),
    "startup.desk_not_ours": QT_TRANSLATE_NOOP(
        "LogMessage",
        "The desk is not this session's to read right now; leaving it "
        "alone. Its position will be read once it is."),
    "startup.read_failed": QT_TRANSLATE_NOOP(
        "LogMessage", "Initial desk read failed: %(error)s"),
    "startup.height_unavailable": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Could not read the desk at startup; automation will adopt its "
        "real position at the first sync that succeeds."),
    "startup.state_held": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Initial state: off-cycle (desk at %(height)s, not a sit/stand "
        "preset); automation paused until it returns to sit or stand."),
    "startup.state_automation_off": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Initial state: %(state)s (height: %(height)s); automation is "
        "off, so the desk will only move when you ask it to."),
    "startup.state": QT_TRANSLATE_NOOP(
        "LogMessage", "Initial state: %(state)s (height: %(height)s)."),
    "startup.cycle_reset": QT_TRANSLATE_NOOP(
        "LogMessage",
        "The cycle clock starts from now: time spent in this position "
        "before the restart is not carried over."),
    "cycle.skipped": QT_TRANSLATE_NOOP(
        "LogMessage", "Skipped transition as requested; staying %(state)s."),
    "cycle.synced": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Desk position changed from '%(previous)s' to '%(current)s' "
        "(%(height)s). Synchronizing."),
    "cycle.held_off": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Desk moved off sit/stand (%(height)s); automation paused until"
        " it returns to a preset."),
    "cycle.resumed_on": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Desk back at %(current)s (%(height)s); automation resumed."),
    "cycle.sync_failed": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Could not read desk height for state sync; keeping internal "
        "state."),
    "cycle.move_failed": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Move to %(intended)s failed: the desk did not respond and its "
        "height could not be read. Staying %(previous)s."),
    "cycle.move_failed_reason": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Move to %(intended)s failed: the desk did not respond and its "
        "height could not be read (%(reason)s). Staying %(previous)s."),
    "transition.held_for_input": QT_TRANSLATE_NOOP(
        "LogMessage",
        "A change is due, but the desk stayed put: no input for "
        "%(idle_time)s and moves need input within %(threshold)s. It will "
        "move once you're back."),
    "transition.completed": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Transition %(previous)s -> %(result)s completed (height "
        "%(height)s)."),
    "transition.interrupted_undo": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Movement to %(intended)s interrupted (height %(height)s); "
        "returned to start, now %(result)s."),
    "transition.interrupted_retry": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Movement to %(intended)s interrupted; moved toward it again "
        "(height %(height)s), now %(result)s."),
    "transition.interrupted_left": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Movement to %(intended)s interrupted (height %(height)s); left"
        " at %(result)s."),
    "automation.enabled": QT_TRANSLATE_NOOP(
        "LogMessage", "Automation turned on."),
    "automation.disabled": QT_TRANSLATE_NOOP(
        "LogMessage", "Automation turned off; manual control only."),
    "automation.paused": QT_TRANSLATE_NOOP(
        "LogMessage", "Automation paused."),
    "automation.resumed": QT_TRANSLATE_NOOP(
        "LogMessage", "Automation resumed."),
    "automation.skip_next": QT_TRANSLATE_NOOP(
        "LogMessage", "Next transition will be skipped."),
    "automation.snoozed": QT_TRANSLATE_NOOP(
        "LogMessage", "Snoozed for %(minutes)s minutes."),
    "manual.move": QT_TRANSLATE_NOOP(
        "LogMessage", "Manual move to %(target)s."),
    "manual.move_failed": QT_TRANSLATE_NOOP(
        "LogMessage", "Manual move to %(target)s failed."),
    "manual.move_failed_reason": QT_TRANSLATE_NOOP(
        "LogMessage", "Manual move to %(target)s failed: %(reason)s."),
    "manual.interrupted": QT_TRANSLATE_NOOP(
        "LogMessage",
        "Move to %(target)s interrupted at %(actual)s; returning to "
        "%(return_to)s."),
    "manual.synced": QT_TRANSLATE_NOOP(
        "LogMessage", "Now %(current)s (%(height)s) after manual move."),
    "manual.stopped": QT_TRANSLATE_NOOP(
        "LogMessage", "Movement stopped by user."),
    "gesture.reverse": QT_TRANSLATE_NOOP(
        "LogMessage", "Repeat gesture: reversing to the start position."),
    "gesture.stop": QT_TRANSLATE_NOOP(
        "LogMessage", "Repeat gesture: stopping the move."),
    "scan.started": QT_TRANSLATE_NOOP(
        "LogMessage", "Scanning for nearby desks..."),
    "scan.failed": QT_TRANSLATE_NOOP(
        "LogMessage", "Bluetooth scan failed: %(error)s"),
    "scan.finished": QT_TRANSLATE_NOOP(
        "LogMessage", "Scan finished: %(count)s device(s) found."),
    "desk.held_by_other": QT_TRANSLATE_NOOP(
        "LogMessage",
        "The desk is connected but unreachable from here, and another "
        "companion daemon is running (pid %(pids)s) — most likely "
        "another user's session still has the desk. Leaving its "
        "connection alone."),
    "preset.saved": QT_TRANSLATE_NOOP(
        "LogMessage", "Preset '%(name)s' saved at %(height)s."),
    "preset.deleted": QT_TRANSLATE_NOOP(
        "LogMessage", "Preset '%(name)s' deleted."),
    "preset.renamed": QT_TRANSLATE_NOOP(
        "LogMessage", "Preset '%(old)s' renamed to '%(new)s'."),
    "autostart.enabled": QT_TRANSLATE_NOOP(
        "LogMessage", "Autostart enabled: the daemon will start at login."),
    "autostart.disabled": QT_TRANSLATE_NOOP(
        "LogMessage", "Autostart disabled: the daemon will not start at login."),
}

# Appended instead of the cycle note when nothing is scheduled.
_FALLBACK_NOTES = {
    "cycle.move_failed": QT_TRANSLATE_NOOP(
        "LogMessage", " Will try again next cycle."),
    "cycle.move_failed_reason": QT_TRANSLATE_NOOP(
        "LogMessage", " Will try again next cycle."),
}


def render(msg_id: str, params: dict, text: str, *, fmt: Formatter) -> str:
    """The line to show for one log entry.

    ``text`` is the English the daemon already composed. It is the answer
    whenever this GUI doesn't recognize ``msg_id`` — an older client meeting a
    newer daemon, or a diagnostic line, which carries no id by design.

    ``fmt`` is keyword-only so the previous positional call cannot silently
    keep working with a wrong argument — every caller must now say
    explicitly which :class:`Formatter` a duration or height in this line
    renders through.
    """
    message = logmsg.get(msg_id)
    if message is None or msg_id not in TEXTS:
        return text
    return logmsg.render(
        message, params, build_formatters(fmt),
        text=_tr(TEXTS[msg_id]),
        cycle_note_text=_tr(CYCLE_NOTE),
        fallback_note=_tr(_FALLBACK_NOTES[msg_id])
        if msg_id in _FALLBACK_NOTES else "")
