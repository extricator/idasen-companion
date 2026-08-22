"""Small GUI formatting helpers.

The height and duration renderers that once lived here now live under
``core/presentation/``, reached through a :class:`~idasen_companion.core.presentation.formatter.Formatter`
built onto an explicit unit (see ``gui/context.py``'s ``AppContext.fmt``) —
nothing in this module reads a process-global unit any more (D-07). What
stays here are the GUI-only spin-box suffix adapters (below), the words that
have not moved yet (Phase 14/15), and the small non-Qt helpers those words
still need.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, TypeVar, cast

from PySide6.QtCore import (
    QCoreApplication, QDate, QLocale, QTime, QT_TRANSLATE_NOOP,
)

from ..core.presentation import words
from ..core.presentation.gettext_translator import GettextTranslator
from ..core.units import HeightUnit

# The automation engine moves to these; they can't be deleted or renamed.
PROTECTED_PRESETS = ("sit", "stand")


def _tr(text: object) -> str:
    """Translate a ``util`` string at call time.

    Takes ``object`` because that is what PySide6's stubs say
    ``QT_TRANSLATE_NOOP`` returns, even though at runtime it hands back the
    string literal it was given, untouched.

    This module is imported at startup — before ``main()`` installs the
    ``QTranslator`` — so its user-facing strings can't be translated at
    import/definition time. They are instead marked for extraction with
    ``QT_TRANSLATE_NOOP`` (which ``lupdate`` recognizes; a plain ``_tr(...)``
    wrapper would hide the literal from it) and translated on each call here.
    """
    return QCoreApplication.translate("util", cast(str, text))


_F = TypeVar("_F", bound=Callable[..., Any])

# Names of every helper below whose return value is translated text.
# tests/test_translation_markers.py reads this set to know which calls a
# concatenation check must treat as equivalent to a bare _tr() call, and
# checks it against the module's own call graph so the set can't drift from
# what actually reaches _tr().
RETURNS_TRANSLATED: set[str] = set()


def returns_translated(func: _F) -> _F:
    """Declare that ``func``'s return value is translated text.

    A pure declaration, not behavior: it adds ``func.__name__`` to
    :data:`RETURNS_TRANSLATED` and returns ``func`` unchanged. The test suite
    reads the registry to decide which calls count as translated values when
    checking for glued-together translations; a helper that reaches ``_tr()``
    without this mark fails the suite at its own definition instead.
    """
    RETURNS_TRANSLATED.add(func.__name__)
    return func


@returns_translated
def connection_state(tokens, connected: bool, available: bool, persistent: bool):
    """Desk connection appearance as ``(color, footer_text, chip_text)``.

    Shared by the sidebar footer and the Overview connection chip so both
    read the same state. ``tokens`` is the active theme.

    **Why this one stays in ``gui/``.** Its words moved to
    ``core/presentation/words.py`` with the rest of the app's vocabulary,
    but what is left is a pairing of those words with a *theme colour*, and
    a theme is a Qt concept. ``docs/ARCHITECTURE.md``'s ``gui``/``daemon``
    -> ``core`` -> nothing rule keeps Qt out of ``core/``, so the pairing
    has nowhere else to live. A caller that wants only the wording — the
    daemon, or the future CLI — asks a ``Formatter`` for
    ``connection_phrases`` instead and reaches the same implementation.
    """
    key = words.connection_state_key(connected, available, persistent)
    if key == "connected":
        color = tokens.success
    elif key == "disconnected":
        color = tokens.error
    else:
        color = tokens.muted
    footer_text, chip_text = words.connection_phrases(GettextTranslator(), key)
    return (color, footer_text, chip_text)


@returns_translated
def suffix_height(unit: HeightUnit) -> str:
    """Translated height suffix for a spin box, leading space."""
    # QAbstractSpinBox.setSuffix does not insert a separating space itself,
    # so the leading space here is deliberate — do not strip it. This helper
    # (and suffix_minutes/suffix_seconds below) exists only for that spin-box
    # API — nothing else should call it; reach for Formatter.height instead.
    if unit == HeightUnit.INCHES:
        return _tr(QT_TRANSLATE_NOOP("util", " in"))
    return _tr(QT_TRANSLATE_NOOP("util", " cm"))


@returns_translated
def suffix_minutes() -> str:
    """Translated minutes suffix for a spin box, leading space."""
    # See suffix_height — the leading space is deliberate, setSuffix adds none.
    return _tr(QT_TRANSLATE_NOOP("util", " min"))


@returns_translated
def suffix_seconds() -> str:
    """Translated seconds suffix for a spin box, leading space."""
    # See suffix_height — the leading space is deliberate, setSuffix adds none.
    return _tr(QT_TRANSLATE_NOOP("util", " s"))


def fmt_countdown(seconds: float) -> str:
    """125 -> '2:05'."""
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


_DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
# Marked for extraction here; translated in day_label() (see _tr note above).
DAY_NAMES = {"mon": QT_TRANSLATE_NOOP("util", "Mon"),
             "tue": QT_TRANSLATE_NOOP("util", "Tue"),
             "wed": QT_TRANSLATE_NOOP("util", "Wed"),
             "thu": QT_TRANSLATE_NOOP("util", "Thu"),
             "fri": QT_TRANSLATE_NOOP("util", "Fri"),
             "sat": QT_TRANSLATE_NOOP("util", "Sat"),
             "sun": QT_TRANSLATE_NOOP("util", "Sun")}


@returns_translated
def day_label(key: str) -> str:
    """Translated short day name for a schedule day key ('mon' -> 'Lun').

    Public because the schedule day chips need it too: DAY_NAMES holds
    QT_TRANSLATE_NOOP markers, so reading it directly yields the untranslated
    source word.
    """
    return _tr(DAY_NAMES[key])


# A module constant so lupdate sees the literal (see _tr's docstring); it is
# reachable because the Automation page lets every day chip be unchecked and
# _validate does not refuse an empty list.

#: Stands in for the day list when an automation schedule has no days
#: selected, e.g. "Automation runs no days, 09:00–17:00."
_NO_DAYS = QT_TRANSLATE_NOOP("util", "no days")

#: A run of three or more consecutive days collapsed into a range, e.g.
#: "Mon–Fri". %(first)s is the run's first day, %(last)s its last.
_DAY_RANGE = QT_TRANSLATE_NOOP("util", "%(first)s–%(last)s")

#: Two day-list entries joined, e.g. "Mon, Wed". Folded left across a longer
#: list to build the whole thing, e.g. "Mon, Wed, Fri" — %(first)s is
#: everything assembled so far, %(second)s the next entry.
_DAY_PAIR = QT_TRANSLATE_NOOP("util", "%(first)s, %(second)s")


@returns_translated
def fmt_days(days: list[str]) -> str:
    """['mon'..'fri'] -> 'Mon–Fri'; ['mon','wed','fri'] -> 'Mon, Wed, Fri'.

    Consecutive runs of three or more days collapse into a range."""
    picked = [d for d in _DAY_ORDER if d in days]
    if not picked:
        return _tr(_NO_DAYS)
    runs: list[list[str]] = []
    for day in picked:
        if runs and (_DAY_ORDER.index(day)
                     - _DAY_ORDER.index(runs[-1][-1])) == 1:
            runs[-1].append(day)
        else:
            runs.append([day])
    parts = []
    for run in runs:
        if len(run) >= 3:
            parts.append(_tr(_DAY_RANGE) % {
                "first": day_label(run[0]), "last": day_label(run[-1])})
        else:
            parts.extend(day_label(d) for d in run)
    # One pair pattern, folded left across `parts`, rather than CLDR's
    # four-key start/middle/end set: this is a unit list ("3 ft, 2 in"), not
    # a sentence list, and both shipped languages render every position with
    # the same plain comma join and no conjunction — a fuller key set would
    # be catalog weight nobody can act on today. If a conjunction-taking
    # language ships later, this fold is where the key set would grow.
    result = parts[0]
    for part in parts[1:]:
        result = _tr(_DAY_PAIR) % {"first": result, "second": part}
    return result


# Marked for extraction here; translated in status_label() (import-time dict).
STATUS_LABELS = {
    "active": QT_TRANSLATE_NOOP("util", "Automation active"),
    "move-failed": QT_TRANSLATE_NOOP("util", "Last move failed"),
    "unconfigured": QT_TRANSLATE_NOOP("util", "Not set up yet — no desk chosen"),
    "disabled": QT_TRANSLATE_NOOP("util", "Automation off"),
    "paused": QT_TRANSLATE_NOOP("util", "Paused"),
    "snoozed": QT_TRANSLATE_NOOP("util", "Snoozed"),
    "user-idle": QT_TRANSLATE_NOOP("util", "Waiting — you seem to be away"),
    "locked": QT_TRANSLATE_NOOP("util", "Waiting — session locked"),
    "away": QT_TRANSLATE_NOOP("util", "Waiting — switched to another session"),
    "no-session": QT_TRANSLATE_NOOP("util", "On hold — no desktop session"),
    "out-of-schedule": QT_TRANSLATE_NOOP("util", "Outside scheduled hours"),
    "held": QT_TRANSLATE_NOOP("util", "Paused — desk moved off sit/stand"),
}


@returns_translated
def status_label(status: str) -> str:
    label = STATUS_LABELS.get(status)
    return _tr(label) if label is not None else status


# The Overview status head shown beside the status dot. Shorter than the
# equivalent STATUS_LABELS wording where the two differ; marked for
# extraction here, translated in status_head() (import-time dict).
STATUS_HEADS = {
    "active": QT_TRANSLATE_NOOP("util", "Active"),
    "paused": QT_TRANSLATE_NOOP("util", "Paused"),
    "user-idle": QT_TRANSLATE_NOOP("util", "You're away"),
    "away": QT_TRANSLATE_NOOP("util", "In another session"),
    "locked": QT_TRANSLATE_NOOP("util", "Session locked"),
    "out-of-schedule": QT_TRANSLATE_NOOP("util", "Outside schedule"),
    "disabled": QT_TRANSLATE_NOOP("util", "Automation off"),
    "held": QT_TRANSLATE_NOOP("util", "Off-cycle"),
    "move-failed": QT_TRANSLATE_NOOP("util", "Last move failed"),
}


@returns_translated
def status_head(status: str) -> str:
    """Translated Overview status head word for a status wire value.

    Falls back to the raw status string for an unrecognized key."""
    label = STATUS_HEADS.get(status)
    return _tr(label) if label is not None else status


# The desk position wire values ("sitting"/"standing") shown as UI words.
# Marked for extraction here; translated in position_label().
POSITION_LABELS = {
    "sitting": QT_TRANSLATE_NOOP("util", "Sitting"),
    "standing": QT_TRANSLATE_NOOP("util", "Standing"),
}


@returns_translated
def position_label(position: str) -> str:
    """Translated display word for a desk position wire value.

    Falls back to a capitalized copy for anything unrecognized, and "" for an
    empty/unknown position (callers substitute their own placeholder)."""
    label = POSITION_LABELS.get(position)
    if label is not None:
        return _tr(label)
    return position.capitalize() if position else ""


# What caused a recorded transition, as stored in the stats DB's `trigger`
# column and shown as a pill on the Statistics page. Marked here, translated
# in trigger_label().
TRIGGER_LABELS = {
    "automation": QT_TRANSLATE_NOOP("util", "automation"),
    "manual": QT_TRANSLATE_NOOP("util", "manual"),
    "external": QT_TRANSLATE_NOOP("util", "external"),
    "setup": QT_TRANSLATE_NOOP("util", "setup"),
}


@returns_translated
def trigger_label(trigger: str) -> str:
    """Translated word for a transition's trigger wire value."""
    label = TRIGGER_LABELS.get(trigger)
    return _tr(label) if label is not None else trigger


# The two protected presets, shown as UI words. User-created presets are the
# user's own words and are returned unchanged.
PRESET_LABELS = {
    "sit": QT_TRANSLATE_NOOP("util", "Sit"),
    "stand": QT_TRANSLATE_NOOP("util", "Stand"),
}


@returns_translated
def preset_label(name: str) -> str:
    """Display name for a preset.

    ``sit``/``stand`` are ours and translate; anything else the user named
    themselves and is shown verbatim. Replaces ``name.capitalize()``, which
    left the rail ticks and the tray submenu in English next to buttons that
    were translated — the same preset labelled two ways on one screen.
    """
    label = PRESET_LABELS.get(name)
    return _tr(label) if label is not None else name


def fmt_day_label(when: datetime) -> str:
    """A day as "Mon 03", in the user's locale.

    Python's ``strftime("%a %d")`` renders C-locale English regardless of the
    app language or $LANG, because nothing calls ``locale.setlocale``. QLocale
    is what every other user-visible value in this module goes through.
    """
    return QLocale().toString(QDate(when.year, when.month, when.day), "ddd dd")


def fmt_day_heading(when: datetime) -> str:
    """A full calendar date as a day-separator heading, e.g. "Mon 17 Aug 2026".

    QLocale supplies the weekday and month names in the user's language --
    Python's ``strftime`` would render C-locale English regardless of the app
    language or ``$LANG``, the same trap :func:`fmt_day_label` records above.
    Nothing here is marked with ``tr()``/``QT_TRANSLATE_NOOP``, so this
    introduces no translatable string and neither catalog gains an entry.

    The field order is fixed by the format string and suits the shipped
    languages (en, es); a locale that leads with the year would want
    ``QLocale.FormatType.LongFormat`` instead, at the cost of the compact
    shape this heading is written to match.
    """
    return QLocale().toString(
        QDate(when.year, when.month, when.day), "ddd dd MMM yyyy")


def fmt_clock(when: datetime) -> str:
    """A wall-clock time in the user's locale, e.g. "14:32" or "2:32 PM".

    Hardcoded ``%H:%M`` is wrong in a 12-hour locale.
    """
    return QLocale().toString(QTime(when.hour, when.minute),
                              QLocale.FormatType.ShortFormat)


@returns_translated
def fmt_day_and_clock(when: datetime) -> str:
    """A day plus a wall-clock time, e.g. "Mon 03 14:32".

    Renders through one whole translated message so the separating space
    stops being a Python literal — a language that separates a date from a
    time differently has no other way to say so. Neither fmt_day_label nor
    fmt_clock is itself a translated value (both format through QLocale and
    carry no catalog entry, the same as Formatter.height_value), so no
    mechanical check can ever flag this site; it converts on that reasoning
    alone.
    """
    return _tr(QT_TRANSLATE_NOOP("util", "%(day)s %(clock)s")) % {
        "day": fmt_day_label(when), "clock": fmt_clock(when)}


# What the daemon's D-Bus error *names* mean, in the user's language.
#
# The daemon raises DBusError with an English body, and that body crosses the
# wire — so it cannot go through the daemon's own gettext (it would be in the
# daemon's language, not the reader's) and it is in neither catalog. Keying on
# the stable error *name* and owning the sentence here is what makes these
# translatable at all. The English body is kept as diagnostic detail, not as
# the user-facing text.
DAEMON_ERROR_MESSAGES = {
    "MoveFailed": QT_TRANSLATE_NOOP(
        "util", "The desk did not respond. Check that it is powered and in "
                "range, then try again."),
    "SetupFailed": QT_TRANSLATE_NOOP(
        "util", "Could not connect to the desk. Make sure it is powered, "
                "nearby, and in pairing mode."),
    "NoHeight": QT_TRANSLATE_NOOP(
        "util", "Could not read the desk's height."),
    "OutOfRange": QT_TRANSLATE_NOOP(
        "util", "That height is outside the desk's range."),
    "InvalidPreset": QT_TRANSLATE_NOOP(
        "util", "That preset name or height is not valid."),
    "UnknownPreset": QT_TRANSLATE_NOOP(
        "util", "There is no preset by that name."),
    "ConfigWriteFailed": QT_TRANSLATE_NOOP(
        "util", "Could not save the configuration. Check that your home "
                "directory is writable and has free space."),
}


@returns_translated
def daemon_error_message(name: str, detail: str = "") -> str:
    """A translated sentence for a daemon D-Bus error name.

    ``name`` may be the full ``…Error.MoveFailed`` or the bare tail. Falls back
    to the daemon's English detail — untranslated, but better than silence —
    and finally to a generic line.
    """
    key = name.rsplit(".", 1)[-1] if name else ""
    label = DAEMON_ERROR_MESSAGES.get(key)
    if label is not None:
        return _tr(label)
    if detail:
        return detail
    return _tr(QT_TRANSLATE_NOOP(
        "util", "The background service could not carry out that request."))


# ----- shared cycle rendering (the tray and Overview say the same things) -----
#
# These were written out in both gui/tray.py and gui/pages/overview.py, and
# the duplication had already reached the catalogs: "later", "Snoozed until
# %s", "Due now" and "Custom" each appeared twice in the .ts, under the
# TrayIcon and OverviewPage contexts. Two entries per concept means a
# translator can render one state two ways — which is the drift the tray's own
# docstring says it copied Overview's wording to avoid.

_LATER = QT_TRANSLATE_NOOP("util", "later")
_SNOOZED_UNTIL = QT_TRANSLATE_NOOP("util", "Snoozed until %s")
#: Shown where a countdown would be, once it has run out.
_DUE_NOW = QT_TRANSLATE_NOOP("util", "Due now")
#: The desk is at neither preset — parked somewhere of the user's choosing.
_CUSTOM = QT_TRANSLATE_NOOP("util", "Custom")


@returns_translated
def snooze_line(until: float) -> str:
    """"Snoozed until 14:32", or "…until later" before the deadline arrives.

    ``until`` is a unix timestamp, or 0 when it is not known yet: the client
    fetches ``SnoozeUntil`` asynchronously on the snoozed announcement, so the
    first render has no time to show.
    """
    when = (fmt_clock(datetime.fromtimestamp(until)) if until
            else _tr(_LATER))
    return _tr(_SNOOZED_UNTIL) % when


@returns_translated
def due_now_label() -> str:
    return _tr(_DUE_NOW)


@returns_translated
def position_or_custom(position: str) -> str:
    """The desk's position as a word, or "Custom" when it is at neither preset."""
    return position_label(position) or _tr(_CUSTOM)
