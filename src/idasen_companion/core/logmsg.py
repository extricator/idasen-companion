"""The activity-channel message catalog.

See ``docs/LOGGING.md`` for the policy this implements. In short: log lines
carry a **channel** (who the line is for), a **level** (how bad it is) and,
on the activity channel, a **stable id plus raw parameters** rather than a
finished sentence.

Only the activity channel is catalogued. Those lines answer "why did my desk
do that?", so they have to be re-renderable in the reader's language: the
daemon composes English for journald (stable and greppable, which is what a
bug report needs) while the GUI receives the id and the parameters and writes
its own sentence with ``tr()``. Diagnostic lines stay free-form English —
they exist to be pasted into a bug report and are never translated, so a
catalog entry for each would be overhead with no payoff.

Parameters are **raw values, never pre-formatted strings**: seconds, metres,
state names. A ``"25.0 minutes"`` on the wire cannot be localized, which
defeats the point. Each parameter declares its *kind* instead, and each side
supplies its own formatter per kind — which is also why the journal says
``1.1000m`` where the GUI says ``110 cm``.

This module is deliberately Qt-free and IO-free; ``gui/log_catalog.py`` holds
the translatable twin of every ``text`` here, and ``tests/test_log_catalog.py``
fails the build if the two drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .presentation import format_duration_human
from .i18n import Translator
from .i18n import MessageKey, NP_, P_


class Channel(StrEnum):
    """Who a line is for. See docs/LOGGING.md."""

    ACTIVITY = "activity"      # the person using the desk
    DIAGNOSTIC = "diagnostic"  # whoever is reading a bug report


class Param(StrEnum):
    """The kind of a message parameter, which decides how each side renders it.

    The daemon formats for the journal (English, metres); the GUI formats for
    display (translated, centimetres). Same raw value, two renderings.
    """

    DURATION = "duration"  # seconds (float|int|None)
    HEIGHT = "height"      # metres (float|None)
    STATE = "state"        # DeskState value: "sitting" / "standing"
    TEXT = "text"          # free string (str|None)
    INT = "int"            # plain count


@dataclass(frozen=True)
class Message:
    """One catalogued activity line.

    ``text`` is a ``%``-style template over the named ``params``. Literal
    percent signs must be escaped as ``%%``.

    ``cycle_note`` marks the lines that change *when the desk will next move*.
    Those get the trailing "Next change after …" sentence appended
    automatically from the ``next_target`` parameter — rule 1 in
    ``docs/LOGGING.md``, and the reason it is a property of the catalog rather
    than something each call site remembers to add. ``fallback_note`` covers
    the case where nothing was scheduled (``next_target`` of 0: automation off,
    or the desk held off-cycle), so the line never claims a change is coming
    when none is.
    """

    id: str
    level: str
    text: MessageKey
    plural_text: MessageKey | str = ""
    plural_param: str = ""
    params: dict[str, Param] = field(default_factory=dict)
    cycle_note: bool = False
    fallback_note: str = ""

    @property
    def channel(self) -> Channel:
        """Catalogued messages are activity by construction; the diagnostic
        channel is free-form (``RingLog.diag``)."""
        return Channel.ACTIVITY


# The sentence appended to every cycle_note message. Split out because it is
# one string reused across a dozen lines, and because the GUI has to be able
# to translate it once rather than a dozen times.
#
# Says *active* time on purpose: the number is a target for the accumulator,
# not a wall-clock deadline — go idle and the change is further off than the
# figure suggests.
CYCLE_NOTE = Message(
    id="cycle.next",
    level="info",
    text=P_('activity-log.entry', " Next change after %(next_target)s of active time."),
    params={"next_target": Param.DURATION},
)


# How each parameter kind renders for the journal: English, and metres to four
# places (the units the desk and the config speak). Lives here rather than in
# the daemon because the GUI also writes English journal entries — for actions
# it takes while the daemon is down — and must not import from `daemon/`.
ENGLISH_FORMATTERS = {
    Param.DURATION: format_duration_human,
    Param.HEIGHT: lambda h: "N/A" if h is None else f"{h:.4f}m",
    Param.STATE: lambda s: str(s),
    Param.TEXT: lambda t: "n/a" if t is None else str(t),
    Param.INT: lambda n: str(int(n)),
}


_CATALOG: dict[str, Message] = {}


def _m(msg: Message) -> Message:
    """Register a message and hand it back, so each entry below is both a
    module constant and a catalog row without repeating its id."""
    _CATALOG[msg.id] = msg
    return msg


# ----- daemon lifecycle -----

DAEMON_STARTING = _m(Message(
    id="daemon.starting", level="info",
    text=P_('activity-log.entry', "Idasen Companion daemon %(version)s starting (config: %(config)s)"),
    params={"version": Param.TEXT, "config": Param.TEXT}))

DAEMON_STOPPING = _m(Message(
    id="daemon.stopping", level="info", text=P_('activity-log.entry', "Daemon stopping.")))

# ----- setup and configuration -----

SETUP_IMPORTED_CLI_TEXT = NP_(
    "activity-log.entry",
    "First run: imported settings from idasen CLI config "
    "(mac=%(mac)s, %(presets)s preset)",
    "First run: imported settings from idasen CLI config "
    "(mac=%(mac)s, %(presets)s presets)")

SETUP_IMPORTED_CLI = _m(Message(
    id="setup.imported_cli", level="info",
    text=SETUP_IMPORTED_CLI_TEXT[0], plural_text=SETUP_IMPORTED_CLI_TEXT[1],
    plural_param="presets",
    params={"mac": Param.TEXT, "presets": Param.INT}))

SETUP_NO_DESK = _m(Message(
    id="setup.no_desk", level="warning",
    text=P_('activity-log.entry', "No desk configured yet. Launch Idasen Companion to run the setup "
         "wizard; automation is on hold until then.")))

SETUP_TESTING_DESK = _m(Message(
    id="setup.testing_desk", level="info",
    text=P_('activity-log.entry', "Setup: testing desk %(mac)s..."),
    params={"mac": Param.TEXT}))

SETUP_DESK_CONFIGURED = _m(Message(
    id="setup.desk_configured", level="info",
    text=P_('activity-log.entry', "Desk configured: %(mac)s (height %(height)s)."),
    params={"mac": Param.TEXT, "height": Param.HEIGHT}))

SETUP_STARTING_AUTOMATION = _m(Message(
    id="setup.starting_automation", level="info",
    text=P_('activity-log.entry', "Desk configured; starting automation.")))

CONFIG_RELOADED = _m(Message(
    id="config.reloaded", level="info", text=P_('activity-log.entry', "Configuration reloaded.")))

CONFIG_RELOAD_FAILED = _m(Message(
    id="config.reload_failed", level="error",
    text=P_('activity-log.entry', "Config reload failed, keeping old config: %(error)s"),
    params={"error": Param.TEXT}))

CONFIG_UNKNOWN_SECTION = _m(Message(
    id="config.unknown_section", level="warning",
    text=P_('activity-log.entry',
            "Configuration warning: %(path)s contains unknown section "
            "[%(section)s]; preserving it."),
    params={"path": Param.TEXT, "section": Param.TEXT}))

CONFIG_UNKNOWN_OPTION = _m(Message(
    id="config.unknown_option", level="warning",
    text=P_('activity-log.entry',
            "Configuration warning: %(path)s contains unknown option "
            "[%(section)s] %(key)s; preserving it."),
    params={"path": Param.TEXT, "section": Param.TEXT, "key": Param.TEXT}))

CONFIG_UNKNOWN_TOP_LEVEL_KEY = _m(Message(
    id="config.unknown_top_level_key", level="warning",
    text=P_('activity-log.entry',
            "Configuration warning: %(path)s contains unknown top-level key "
            "%(key)s; preserving it."),
    params={"path": Param.TEXT, "key": Param.TEXT}))

CONFIG_DESK_MAC_CHANGED = _m(Message(
    id="config.desk_mac_changed", level="info",
    text=P_('activity-log.entry', "Desk MAC changed; reconnecting to new desk.")))

# ----- presence -----

IDLE_NO_PROVIDER = _m(Message(
    id="idle.no_provider", level="warning",
    text=P_('activity-log.entry', "No idle-time provider is available on this desktop, so the app "
         "cannot tell whether you are at the keyboard. Automation will move "
         "the desk on schedule whether you are here or not; idle, lock and "
         "away detection are all inoperative.")))

PRESENCE_NOW_IDLE = _m(Message(
    id="presence.now_idle", level="info",
    text=P_('activity-log.entry', "Now idle (%(idle_time)s idle time)"),
    params={"idle_time": Param.DURATION}))

PRESENCE_ACTIVE_RESET = _m(Message(
    id="presence.active_reset", level="info",
    text=P_('activity-log.entry', "Activity detected after idle period; resetting timers."),
    params={"next_target": Param.DURATION}, cycle_note=True))

PRESENCE_ACTIVE_KEPT = _m(Message(
    id="presence.active_kept", level="info",
    text=P_('activity-log.entry', "Activity detected after a brief interruption; keeping this cycle's "
         "progress.")))

PRESENCE_AWAY = _m(Message(
    id="presence.away", level="info",
    text=P_('activity-log.entry', "Switched away to another session; automation paused and the desk "
         "released.")))

PRESENCE_BACK_RESET = _m(Message(
    id="presence.back_reset", level="info",
    text=P_('activity-log.entry', "Back in your session; automation resumed with a fresh cycle; "
         "re-reading the desk."),
    params={"next_target": Param.DURATION}, cycle_note=True))

PRESENCE_BACK_KEPT = _m(Message(
    id="presence.back_kept", level="info",
    text=P_('activity-log.entry', "Back in your session; automation resumed where it left off; "
         "re-reading the desk.")))

PRESENCE_NO_SEAT = _m(Message(
    id="presence.no_seat", level="warning",
    text=P_('activity-log.entry', "This account has no graphical session, so there is no desk to "
         "automate and no way to tell whether anyone is at it: automation is "
         "on hold and the desk is left to whoever is logged in. It still "
         "responds to explicit commands from here.")))

PRESENCE_SEAT_BACK_RESET = _m(Message(
    id="presence.seat_back_reset", level="info",
    text=P_('activity-log.entry', "Graphical session detected; automation is live again with a fresh "
         "cycle. Re-reading the desk."),
    params={"next_target": Param.DURATION}, cycle_note=True))

PRESENCE_SEAT_BACK_KEPT = _m(Message(
    id="presence.seat_back_kept", level="info",
    text=P_('activity-log.entry', "Graphical session detected; automation is live again where it left "
         "off. Re-reading the desk.")))

# ----- suspend and time -----

SUSPEND_SUSPENDING = _m(Message(
    id="suspend.suspending", level="info", text=P_('activity-log.entry', "System is suspending.")))

SUSPEND_RESUMED = _m(Message(
    id="suspend.resumed", level="info",
    text=P_('activity-log.entry', "Resumed from suspend; resetting timers."),
    params={"next_target": Param.DURATION}, cycle_note=True))

TIME_JUMP = _m(Message(
    id="time.jump", level="info",
    text=P_('activity-log.entry', "Detected potential time jump (%(elapsed)s elapsed); resetting state."),
    params={"elapsed": Param.DURATION, "next_target": Param.DURATION},
    cycle_note=True))

# A *backward* step gets its own line rather than reusing time.jump with a
# negative duration: nothing "elapsed", so reporting one would be a misleading
# number, and "-3600 seconds elapsed" is how it would have read. The parameter
# carries the size of the correction, unsigned.
TIME_STEPPED_BACK = _m(Message(
    id="time.stepped_back", level="info",
    text=P_('activity-log.entry', "The system clock moved backwards by %(elapsed)s; resetting state."),
    params={"elapsed": Param.DURATION, "next_target": Param.DURATION},
    cycle_note=True))

# ----- startup state adoption -----

STARTUP_DESK_NOT_OURS = _m(Message(
    id="startup.desk_not_ours", level="info",
    text=P_('activity-log.entry', "The desk is not this session's to read right now; leaving it alone. "
         "Its position will be read once it is.")))

STARTUP_READ_FAILED = _m(Message(
    id="startup.read_failed", level="warning",
    text=P_('activity-log.entry', "Initial desk read failed: %(error)s"),
    params={"error": Param.TEXT}))

STARTUP_HEIGHT_UNAVAILABLE = _m(Message(
    id="startup.height_unavailable", level="warning",
    text=P_('activity-log.entry', "Could not read the desk at startup; automation will adopt its real "
         "position at the first sync that succeeds.")))

STARTUP_STATE_HELD = _m(Message(
    id="startup.state_held", level="info",
    text=P_('activity-log.entry', "Initial state: off-cycle (desk at %(height)s, not a sit/stand "
         "preset); automation paused until it returns to sit or stand."),
    params={"height": Param.HEIGHT}))

STARTUP_STATE_AUTOMATION_OFF = _m(Message(
    id="startup.state_automation_off", level="info",
    text=P_('activity-log.entry', "Initial state: %(state)s (height: %(height)s); automation is off, "
         "so the desk will only move when you ask it to."),
    params={"state": Param.STATE, "height": Param.HEIGHT}))

STARTUP_STATE = _m(Message(
    id="startup.state", level="info",
    text=P_('activity-log.entry', "Initial state: %(state)s (height: %(height)s)."),
    params={"state": Param.STATE, "height": Param.HEIGHT,
            "next_target": Param.DURATION},
    cycle_note=True))

# Deliberately not a cycle_note line: STARTUP_STATE, emitted immediately
# before it, already carries the "Next change after …" sentence. This one
# exists to say *why* that number is a whole fresh interval — cycle progress
# is not persisted across a restart, so a restart landing late in an interval
# silently defers the move. Saying so is not the fix (see TODO.md), but it
# turns "my desk just didn't switch" into something the log explains.
STARTUP_CYCLE_RESET = _m(Message(
    id="startup.cycle_reset", level="info",
    text=P_('activity-log.entry', "The cycle clock starts from now: time spent in this position "
         "before the restart is not carried over.")))

# ----- the cycle -----

CYCLE_SKIPPED = _m(Message(
    id="cycle.skipped", level="info",
    text=P_('activity-log.entry', "Skipped transition as requested; staying %(state)s."),
    params={"state": Param.STATE, "next_target": Param.DURATION},
    cycle_note=True))

CYCLE_SYNCED = _m(Message(
    id="cycle.synced", level="info",
    text=P_('activity-log.entry', "Desk position changed from '%(previous)s' to '%(current)s' "
         "(%(height)s). Synchronizing."),
    params={"previous": Param.STATE, "current": Param.STATE,
            "height": Param.HEIGHT, "next_target": Param.DURATION},
    cycle_note=True))

CYCLE_HELD_OFF = _m(Message(
    id="cycle.held_off", level="info",
    text=P_('activity-log.entry', "Desk moved off sit/stand (%(height)s); automation paused until it "
         "returns to a preset."),
    params={"height": Param.HEIGHT}))

CYCLE_RESUMED_ON = _m(Message(
    id="cycle.resumed_on", level="info",
    text=P_('activity-log.entry', "Desk back at %(current)s (%(height)s); automation resumed."),
    params={"current": Param.STATE, "height": Param.HEIGHT,
            "next_target": Param.DURATION},
    cycle_note=True))

CYCLE_SYNC_FAILED = _m(Message(
    id="cycle.sync_failed", level="warning",
    text=P_('activity-log.entry', "Could not read desk height for state sync; keeping internal state.")))

CYCLE_MOVE_FAILED = _m(Message(
    id="cycle.move_failed", level="warning",
    text=P_('activity-log.entry', "Move to %(intended)s failed: the desk did not respond and its "
         "height could not be read. Staying %(previous)s."),
    params={"intended": Param.STATE, "previous": Param.STATE,
            "next_target": Param.DURATION},
    cycle_note=True, fallback_note=P_('activity-log.entry', " Will try again next cycle.")))

CYCLE_MOVE_FAILED_REASON = _m(Message(
    id="cycle.move_failed_reason", level="warning",
    text=P_('activity-log.entry', "Move to %(intended)s failed: the desk did not respond and its "
         "height could not be read (%(reason)s). Staying %(previous)s."),
    params={"intended": Param.STATE, "previous": Param.STATE,
            "reason": Param.TEXT, "next_target": Param.DURATION},
    cycle_note=True, fallback_note=P_('activity-log.entry', " Will try again next cycle.")))

# ----- transitions -----

# Emitted once per held-back stretch, not once per tick. Without it the strict
# recent-input gate is invisible in hindsight: a move that waited for you and a
# move that never came due look identical in the log, and the only way to tell
# whether the desk respected the threshold is to catch it in the act.
TRANSITION_HELD_FOR_INPUT = _m(Message(
    id="transition.held_for_input", level="info",
    text=P_('activity-log.entry', "A change is due, but the desk stayed put: no input for "
         "%(idle_time)s and moves need input within %(threshold)s. It will "
         "move once you're back."),
    params={"idle_time": Param.DURATION, "threshold": Param.DURATION}))

TRANSITION_COMPLETED = _m(Message(
    id="transition.completed", level="info",
    text=P_('activity-log.entry', "Transition %(previous)s -> %(result)s completed (height "
         "%(height)s)."),
    params={"previous": Param.STATE, "result": Param.STATE,
            "height": Param.HEIGHT, "next_target": Param.DURATION},
    cycle_note=True))

TRANSITION_INTERRUPTED_UNDO = _m(Message(
    id="transition.interrupted_undo", level="warning",
    text=P_('activity-log.entry', "Movement to %(intended)s interrupted (height %(height)s); returned "
         "to start, now %(result)s."),
    params={"intended": Param.STATE, "result": Param.STATE,
            "height": Param.HEIGHT, "next_target": Param.DURATION},
    cycle_note=True))

TRANSITION_INTERRUPTED_RETRY = _m(Message(
    id="transition.interrupted_retry", level="warning",
    text=P_('activity-log.entry', "Movement to %(intended)s interrupted; moved toward it again (height "
         "%(height)s), now %(result)s."),
    params={"intended": Param.STATE, "result": Param.STATE,
            "height": Param.HEIGHT, "next_target": Param.DURATION},
    cycle_note=True))

TRANSITION_INTERRUPTED_LEFT = _m(Message(
    id="transition.interrupted_left", level="warning",
    text=P_('activity-log.entry', "Movement to %(intended)s interrupted (height %(height)s); left at "
         "%(result)s."),
    params={"intended": Param.STATE, "result": Param.STATE,
            "height": Param.HEIGHT, "next_target": Param.DURATION},
    cycle_note=True))

# ----- automation control -----

AUTOMATION_ENABLED = _m(Message(
    id="automation.enabled", level="info", text=P_('activity-log.entry', "Automation turned on.")))

AUTOMATION_DISABLED = _m(Message(
    id="automation.disabled", level="info",
    text=P_('activity-log.entry', "Automation turned off; manual control only.")))

AUTOMATION_PAUSED = _m(Message(
    id="automation.paused", level="info", text=P_('activity-log.entry', "Automation paused.")))

AUTOMATION_RESUMED = _m(Message(
    id="automation.resumed", level="info", text=P_('activity-log.entry', "Automation resumed.")))

AUTOMATION_SKIP_NEXT = _m(Message(
    id="automation.skip_next", level="info",
    text=P_('activity-log.entry', "Next transition will be skipped.")))

AUTOMATION_SNOOZED = _m(Message(
    id="automation.snoozed", level="info",
    text=P_('activity-log.entry', "Snoozed for %(duration)s."),
    params={"duration": Param.DURATION}))

# ----- manual moves -----

MANUAL_MOVE = _m(Message(
    id="manual.move", level="info", text=P_('activity-log.entry', "Manual move to %(target)s."),
    params={"target": Param.TEXT}))

MANUAL_MOVE_FAILED = _m(Message(
    id="manual.move_failed", level="warning",
    text=P_('activity-log.entry', "Manual move to %(target)s failed."),
    params={"target": Param.TEXT}))

MANUAL_MOVE_FAILED_REASON = _m(Message(
    id="manual.move_failed_reason", level="warning",
    text=P_('activity-log.entry', "Manual move to %(target)s failed: %(reason)s."),
    params={"target": Param.TEXT, "reason": Param.TEXT}))

MANUAL_INTERRUPTED = _m(Message(
    id="manual.interrupted", level="warning",
    text=P_('activity-log.entry', "Move to %(target)s interrupted at %(actual)s; returning to "
         "%(return_to)s."),
    params={"target": Param.TEXT, "actual": Param.HEIGHT,
            "return_to": Param.HEIGHT}))

MANUAL_SYNCED = _m(Message(
    id="manual.synced", level="info",
    text=P_('activity-log.entry', "Now %(current)s (%(height)s) after manual move."),
    params={"current": Param.STATE, "height": Param.HEIGHT,
            "next_target": Param.DURATION},
    cycle_note=True))

MANUAL_STOPPED = _m(Message(
    id="manual.stopped", level="info", text=P_('activity-log.entry', "Movement stopped by user.")))

GESTURE_REVERSE = _m(Message(
    id="gesture.reverse", level="info",
    text=P_('activity-log.entry', "Repeat gesture: reversing to the start position.")))

GESTURE_STOP = _m(Message(
    id="gesture.stop", level="info",
    text=P_('activity-log.entry', "Repeat gesture: stopping the move.")))

# ----- discovery and connectivity -----

SCAN_STARTED = _m(Message(
    id="scan.started", level="info", text=P_('activity-log.entry', "Scanning for nearby desks...")))

SCAN_FAILED = _m(Message(
    id="scan.failed", level="warning",
    text=P_('activity-log.entry', "Bluetooth scan failed: %(error)s"),
    params={"error": Param.TEXT}))

SCAN_FINISHED_TEXT = NP_(
    "activity-log.entry",
    "Scan finished: %(count)s device found.",
    "Scan finished: %(count)s devices found.")

SCAN_FINISHED = _m(Message(
    id="scan.finished", level="info",
    text=SCAN_FINISHED_TEXT[0], plural_text=SCAN_FINISHED_TEXT[1],
    plural_param="count",
    params={"count": Param.INT}))

DESK_HELD_BY_OTHER = _m(Message(
    id="desk.held_by_other", level="warning",
    text=P_('activity-log.entry', "The desk is connected but unreachable from here, and another "
         "companion daemon is running (pid %(pids)s) — most likely another "
         "user's session still has the desk. Leaving its connection alone."),
    params={"pids": Param.TEXT}))

# ----- presets -----

PRESET_SAVED = _m(Message(
    id="preset.saved", level="info",
    text=P_('activity-log.entry', "Preset '%(name)s' saved at %(height)s."),
    params={"name": Param.TEXT, "height": Param.HEIGHT}))

PRESET_DELETED = _m(Message(
    id="preset.deleted", level="info", text=P_('activity-log.entry', "Preset '%(name)s' deleted."),
    params={"name": Param.TEXT}))

# One line, because it is one operation. A rename used to be a Save plus a
# Delete and read as two unrelated events in the log.
PRESET_RENAMED = _m(Message(
    id="preset.renamed", level="info",
    text=P_('activity-log.entry', "Preset '%(old)s' renamed to '%(new)s'."),
    params={"old": Param.TEXT, "new": Param.TEXT}))

# ----- written by the GUI, not the daemon -----
#
# Enabling autostart is a real change to system state made at a moment when
# the daemon — which owns the log — is by definition not running. The GUI
# writes these to the journal itself under the same ids, so they land in the
# Activity Log in order alongside everything else. See docs/LOGGING.md.

AUTOSTART_ENABLED = _m(Message(
    id="autostart.enabled", level="info",
    text=P_('activity-log.entry', "Autostart enabled: the daemon will start at login.")))

AUTOSTART_DISABLED = _m(Message(
    id="autostart.disabled", level="info",
    text=P_('activity-log.entry', "Autostart disabled: the daemon will not start at login.")))


def get(msg_id: str) -> Message | None:
    """Look up a catalogued message, or None if this reader doesn't know it.

    Returning None rather than raising is deliberate: a GUI talking to a newer
    daemon will meet ids it has never heard of, and the right response is to
    fall back to the English text the daemon sent along, not to crash.
    """
    return _CATALOG.get(msg_id)


def all_messages() -> dict[str, Message]:
    """The whole catalog, for the drift test and for tooling."""
    return dict(_CATALOG)


def render(msg: Message, params: dict, formatters: dict, *,
           text: str | None = None, cycle_note_text: str | None = None,
           fallback_note: str | None = None,
           translator: Translator | None = None) -> str:
    """Compose ``msg``'s sentence from raw ``params``.

    ``formatters`` maps each :class:`Param` kind to a callable that turns a raw
    value into display text — English/metres on the daemon side, translated/
    centimetres in the GUI. Missing parameters render as ``?`` rather than
    raising: a half-rendered line still tells the reader something, whereas an
    exception inside the logger loses the line entirely and takes its caller
    with it.

    The three text overrides are how the GUI reuses this: it passes the
    *translated* twin of each string (``gui/log_catalog.py``) while the
    structure — which parameters, whether a cycle note belongs, which fallback
    — stays defined here, in one place.
    """
    if msg.id == "automation.snoozed" and "duration" not in params \
            and "minutes" in params:
        params = {**params, "duration": params["minutes"] * 60}
    values = {}
    for name, kind in msg.params.items():
        raw = params.get(name)
        try:
            values[name] = formatters[kind](raw)
        except Exception:
            values[name] = "?"
    if text is not None:
        template = text
    elif msg.plural_text:
        count = int(params.get(msg.plural_param, 0))
        template = (translator.plural(msg.text, msg.plural_text, count)
                    if translator else (msg.text if count == 1
                                        else msg.plural_text))
    else:
        template = translator.message(msg.text) if translator else msg.text
    try:
        rendered = template % values
    except (KeyError, ValueError, TypeError):
        rendered = template
    if msg.cycle_note:
        target = params.get("next_target") or 0
        if target > 0:
            note = (translator.message(CYCLE_NOTE.text)
                    if cycle_note_text is None and translator
                    else CYCLE_NOTE.text if cycle_note_text is None
                    else cycle_note_text)
            try:
                rendered += note % {
                    "next_target": formatters[Param.DURATION](target)}
            except (KeyError, ValueError, TypeError):
                pass
        else:
            rendered += ((translator.message(msg.fallback_note)
                          if translator and msg.fallback_note
                          else msg.fallback_note)
                         if fallback_note is None else fallback_note)
    return rendered
