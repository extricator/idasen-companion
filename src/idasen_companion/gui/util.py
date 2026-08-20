"""Small GUI formatting helpers.

Also the one place that knows what unit a height is *shown* in. Heights are
metres everywhere else — config, state machine, stats DB, D-Bus wire — and
become centimetres or inches only on their way to a widget. Nothing here
takes the unit as an argument: it is process-global state set once from
config, the same shape as the default ``QLocale`` that ``i18n`` installs, so
a call site can format a height without being told which unit is in force.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from PySide6.QtCore import (
    QCoreApplication, QDate, QLocale, QTime, QT_TRANSLATE_NOOP,
)

# The automation engine moves to these; they can't be deleted or renamed.
PROTECTED_PRESETS = ("sit", "stand")

#: The two height units, as stored in ``[ui] units`` (see core.config).
CENTIMETRES = "cm"
INCHES = "in"

#: Metres per inch, exactly.
_METRES_PER_INCH = 0.0254

# Set by set_height_unit() at startup and on every config change. Centimetres
# until then, so anything built before config is read still renders.
_unit = CENTIMETRES  # pylint: disable=invalid-name  # mutable singleton, reassigned via `global` below, not a true constant


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


def connection_state(tokens, connected: bool, available: bool, persistent: bool):
    """Desk connection appearance as ``(color, footer_text, chip_text)``.

    Shared by the sidebar footer and the Overview connection chip so both
    read the same state. ``tokens`` is the active theme."""
    if connected:
        return (tokens.success, _tr(QT_TRANSLATE_NOOP("util", "Desk: connected")),
                _tr(QT_TRANSLATE_NOOP("util", "Connected")))
    if not available or persistent:
        return (tokens.error, _tr(QT_TRANSLATE_NOOP("util", "Desk: disconnected")),
                _tr(QT_TRANSLATE_NOOP("util", "Disconnected")))
    return (tokens.muted, _tr(QT_TRANSLATE_NOOP("util", "Desk: on demand")),
            _tr(QT_TRANSLATE_NOOP("util", "Not connected · on demand")))


def fmt_number(value: float, decimals: int = 1, trim: bool = False) -> str:
    """Locale-formatted decimal number ('110.5' -> '110,5' under es_ES).

    Reads ``QLocale()`` — the default set by ``i18n.install_translators`` —
    rather than taking a locale argument, so every call site gets the
    desktop/config locale for free. ``trim`` drops a trailing ".0" (today's
    `:g` brevity for the chart labels) without touching the locale's
    ``zeroDigit()``/``decimalPoint()``, which a hand-rolled trim on the
    formatted string would risk doing wrong for a non-Latin digit set.
    """
    value = float(value)
    places = 0 if trim and value == int(value) else decimals
    return QLocale().toString(value, "f", places)


def resolve_height_unit(setting: str) -> str:
    """A ``[ui] units`` value as a concrete unit, resolving ``"system"``.

    Only US customary locales get inches. Qt reports the UK as imperial too,
    but a UK desk is advertised, reviewed and sold in centimetres, so
    following ``measurementSystem()`` literally there would hand most of
    those users the unit they don't use. Either way this is a default the
    Settings page can override for good.

    Read from the effective ``QLocale()`` — the config language where one is
    set, the desktop's otherwise — so the unit agrees with the decimal
    separator printed next to it. Choosing a UI language therefore also moves
    this default, which is the one case where the two questions come apart;
    the explicit setting is the answer to it.
    """
    if setting in (CENTIMETRES, INCHES):
        return setting
    imperial_us = QLocale.MeasurementSystem.ImperialUSSystem
    return INCHES if QLocale().measurementSystem() == imperial_us \
        else CENTIMETRES


def set_height_unit(setting: str) -> None:
    """Adopt a ``[ui] units`` value for every height rendered from now on.

    Called at startup and again whenever config changes — before
    ``configChanged`` reaches the pages, so a page redrawing in response
    already sees the new unit (see ``gui/context.py``).
    """
    global _unit
    _unit = resolve_height_unit(setting)


def height_unit() -> str:
    """The unit heights are currently shown in (``"cm"`` or ``"in"``)."""
    return _unit


def to_display_height(meters: float) -> float:
    """Metres as the number the user sees (1.105 -> 110.5 cm / 43.5 in)."""
    if _unit == INCHES:
        return meters / _METRES_PER_INCH
    return meters * 100


def from_display_height(value: float) -> float:
    """The inverse of :func:`to_display_height`, back to metres.

    Displayed values are converted back only to *act* on them — moving the
    desk, or entering a brand-new preset. A height already in config is never
    round-tripped through the display, so the rounding here can't drift one.
    """
    if _unit == INCHES:
        return value * _METRES_PER_INCH
    return value / 100


def height_decimals() -> int:
    """Decimal places a height is shown with.

    Two for inches, because one (2.54 mm per step) is coarser than the desk's
    own millimetre resolution — and Overview's Move button sends the spin
    box's value back to the desk, so a user who never touched the box could
    still shift the desk over a millimetre just by pressing Move.
    """
    return 2 if _unit == INCHES else 1


def height_step() -> float:
    """A single step of a height spin box, in display units."""
    return 0.25 if _unit == INCHES else 0.5


def fmt_height_value(meters: float, trim: bool = False) -> str:
    """Locale-formatted height *number*, with no unit (1.105 -> '110.5').

    For the places that draw the unit themselves or deliberately leave it off
    — the rails label a tick with the bare number, having named the unit once
    at the end of the scale. Everywhere else wants :func:`fmt_height`.
    """
    return fmt_number(to_display_height(meters), height_decimals(), trim)


def suffix_height() -> str:
    """Translated height suffix for a spin box, leading space."""
    # QAbstractSpinBox.setSuffix does not insert a separating space itself,
    # so the leading space here is deliberate — do not strip it.
    if _unit == INCHES:
        return _tr(QT_TRANSLATE_NOOP("util", " in"))
    return _tr(QT_TRANSLATE_NOOP("util", " cm"))


def fmt_height(meters: float, trim: bool = False) -> str:
    """A height as the GUI shows it, unit included (1.105 -> '110.5 cm').

    Every height the GUI renders goes through here or through
    :func:`fmt_height_value`; nothing converts on its own. That is what keeps
    the unit a single decision rather than one per screen.
    """
    return fmt_height_value(meters, trim) + suffix_height()


def suffix_minutes() -> str:
    """Translated minutes suffix for a spin box, leading space."""
    # See suffix_height — the leading space is deliberate, setSuffix adds none.
    return _tr(QT_TRANSLATE_NOOP("util", " min"))


def suffix_seconds() -> str:
    """Translated seconds suffix for a spin box, leading space."""
    # See suffix_height — the leading space is deliberate, setSuffix adds none.
    return _tr(QT_TRANSLATE_NOOP("util", " s"))


def fmt_hm(seconds: float) -> str:
    """3900 -> '1h 05m', 240 -> '4m'.

    Only the unit letters are translated — the numbers stay under 100, so
    there is no decimal separator or digit grouping for a locale to change.
    Minutes are pre-padded here rather than through ``QLocale``, which has no
    padded-integer overload.
    """
    minutes = int(seconds) // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return _tr(QT_TRANSLATE_NOOP(
            "util", "%(hours)sh %(minutes)sm")) % {
            "hours": hours, "minutes": f"{minutes:02d}"}
    return _tr(QT_TRANSLATE_NOOP("util", "%(minutes)sm")) % {"minutes": minutes}


def fmt_duration(seconds: float) -> str:
    """Like :func:`fmt_hm`, but keeps a sub-minute duration visible ('45s').

    The Activity Log reports durations that are genuinely shorter than a
    minute — the idle time on a screen lock is near zero, and a test config can
    set a 30-second cycle. `fmt_hm` floors those to "0m", so the journal read
    "Now idle (0 seconds idle time)" while the GUI said "0m". Splits at a
    minute exactly where the journal's own formatter does.
    """
    if seconds < 60:
        return _tr(QT_TRANSLATE_NOOP("util", "%(seconds)ss")) % {
            "seconds": f"{seconds:.0f}"}
    return fmt_hm(seconds)


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
            parts.append(f"{day_label(run[0])}–{day_label(run[-1])}")
        else:
            parts.extend(day_label(d) for d in run)
    return ", ".join(parts)


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


def fmt_day_and_clock(when: datetime) -> str:
    """A day plus a wall-clock time, e.g. "Mon 03 14:32"."""
    return f"{fmt_day_label(when)} {fmt_clock(when)}"


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


def snooze_line(until: float) -> str:
    """"Snoozed until 14:32", or "…until later" before the deadline arrives.

    ``until`` is a unix timestamp, or 0 when it is not known yet: the client
    fetches ``SnoozeUntil`` asynchronously on the snoozed announcement, so the
    first render has no time to show.
    """
    when = (fmt_clock(datetime.fromtimestamp(until)) if until
            else _tr(_LATER))
    return _tr(_SNOOZED_UNTIL) % when


def due_now_label() -> str:
    return _tr(_DUE_NOW)


def position_or_custom(position: str) -> str:
    """The desk's position as a word, or "Custom" when it is at neither preset."""
    return position_label(position) or _tr(_CUSTOM)
