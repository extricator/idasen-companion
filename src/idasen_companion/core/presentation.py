"""The ``Formatter`` facade and the context it holds.

This module records the design's § 14 call-site decision — the choice
between threading a presentation context explicitly through every
formatter's signature, and bundling it behind a small facade object — as
committed source so the reasoning stays beside the implementation.

**The chosen shape.** A single ``Formatter`` facade, built once from a
``PresentationContext``, so a call site reads ``Formatter(ctx).height(m)``
rather than ``fmt_height(m, ctx)``. The context is held by the facade
instead of being threaded through roughly twenty formatter signatures and
every ``gui/util.py`` wrapper around them.

**Why.** Two sources reached the same answer independently. The design
document says that for that many helpers it would probably choose the
facade form. Separately, and before that document was written, this
project's own backlog already proposed a small immutable object built from
language and unit, owned by the GUI's shared context, exposing the
vocabulary as methods. Two routes, one answer.

**The rejected alternative, and its argument.** Passing the context
explicitly at every call site — a plain function taking the value and the
context as arguments — is transparent, trivially testable, and carries no
object lifecycle: nothing to construct, nothing to hold onto past one
call. It was rejected on noise, not on merit: the same context argument
would repeat, unchanged, at every one of roughly twenty formatters times
every call site, plus every thin wrapper in ``gui/util.py`` that exists
only to thread it through. A parameter that is identical at every call is
a parameter worth binding once instead of repeating everywhere.

**What this facade is not.** There is still exactly one ``Formatter``
implementation — the polymorphism lives entirely in its collaborators, the
``LocaleProfile`` and ``Translator`` the context carries. That is the
distinction from the per-surface renderer set this project already
rejected: a Qt renderer and a headless renderer each reimplementing the
same formatting policy. Here the policy is written once, in this facade's
methods, and only the two small capabilities beneath it vary.

**How a widget with no context reaches this.** ``gui/widgets.py``'s paint
methods used to import a height formatter directly, because the widget they
paint had nothing to reach for. Neither this shape nor the rejected one
solved that on its own — PRES-06 did, by handing those widgets a
``Formatter`` at construction. A widget that needs one now takes one.
"""


from dataclasses import dataclass
from datetime import datetime

from . import display_prefs as units
from .durations import SUB_MINUTE_THRESHOLD_SECONDS, decompose_hms
from .machine import DeskState
from .display_prefs import HeightUnit
from .i18n import Translator
from .i18n import (
    AUTOMATION_PAUSED_BODY, AUTOMATION_PAUSED_SUMMARY, HEIGHT_CENTIMETRES,
    HEIGHT_INCHES, HOURS, HOURS_AND_MINUTES, HOURS_AND_MINUTES_COMPACT,
    MINUTES, MINUTES_ABBREVIATED, MINUTES_COMPACT, MOVE_FAILED_BODY,
    MOVE_FAILED_BODY_WITH_REASON, MOVE_FAILED_SITTING, MOVE_FAILED_STANDING,
    PRESET_TICK, PRE_MOVE_BODY, PRE_MOVE_SITTING, PRE_MOVE_STANDING, SECONDS,
    SECONDS_COMPACT, SKIP_ACTION, SNOOZE_ACTION, TRY_NOW_ACTION,
)
from .locale_profile import LocaleProfile, TimeStyle


@dataclass(frozen=True)
class PresentationContext:
    """The capability pair and unit a :class:`Formatter` renders through.

    Holds the two protocol instances a surface supplies — a
    locale-rendering backend and a message-translating backend — plus the
    display unit a height renders in. Frozen because it is built once per
    surface and handed to every ``Formatter`` that surface constructs;
    nothing here changes over the context's lifetime.

    ``unit`` carries no default. ``"system"`` is a setting, not a unit —
    :func:`idasen_companion.core.display_prefs.resolve_height_unit` is the one
    place that resolves it — and a default here would quietly let a
    caller hand this context an unresolved policy question instead of an
    answer.

    ``time_style`` carries no default for the same reason, and it is the
    same shape of question: ``"system"`` is a clock-format setting, not a
    clock, and one place resolves it into a style. A default here would
    let a caller hand this context the question instead of the answer.
    """

    locale: LocaleProfile
    translator: Translator
    unit: HeightUnit
    time_style: TimeStyle


class Formatter:
    """Renders values and messages through an injected presentation context.

    Holds a :class:`PresentationContext` and nothing else. A method here
    owes exactly this: an atomic value goes through ``self._context.locale``,
    a whole message goes through ``self._context.translator``, and nothing
    is ever concatenated in Python — the values these two collaborators
    produce are substituted into a translated pattern instead (see
    ``core/presentation.py``'s callers and the whole-message rule).

    See the module docstring for the recorded § 14 decision — this facade
    over an explicit context argument at every call site — and the
    rejected alternative's own argument.
    """

    def __init__(self, context: PresentationContext) -> None:
        self._context = context

    @property
    def context(self) -> PresentationContext:
        """The context this facade was built from."""
        return self._context

    @property
    def unit(self) -> HeightUnit:
        """The unit heights render in, from the injected context."""
        return self._context.unit

    @property
    def time_style(self) -> TimeStyle:
        """The clock wall-clock times render on, from the injected context."""
        return self._context.time_style

    def to_display_height(self, meters: float) -> float:
        """Metres as the number the user sees (1.105 -> 110.5 cm / 43.5 in)."""
        return units.to_display_height(meters, self.unit)

    def from_display_height(self, value: float) -> float:
        """The inverse of :meth:`to_display_height`, back to metres."""
        return units.from_display_height(value, self.unit)

    def height_decimals(self) -> int:
        """Decimal places a height is shown with, for the injected unit."""
        return units.height_decimals(self.unit)

    def height_step(self) -> float:
        """A single step of a height spin box, in display units."""
        return units.height_step(self.unit)

    def height_value(self, meters: float, trim: bool = False) -> str:
        """Locale-formatted height *number*, with no unit (1.105 -> '110.5').

        Carries no translatable string — it is a bare number, never a unit
        suffix — which is why it can land ahead of the CAT-05 extraction
        widening.
        """
        return self._context.locale.number(
            self.to_display_height(meters),
            decimals=self.height_decimals(), trim_trailing_zeroes=trim)

    def height(self, meters: float, trim: bool = False) -> str:
        """A height as the GUI shows it, unit included (1.105 -> '110.5 cm').

        One whole translated message per unit, with the formatted number
        substituted in — so a language can order or space the unit
        differently, rather than always number-then-suffix. Every height
        the app renders goes through here or through :meth:`height_value`;
        nothing converts on its own, which is what keeps the unit a single
        decision rather than one per screen.
        """
        source = HEIGHT_INCHES if self.unit == HeightUnit.INCHES \
            else HEIGHT_CENTIMETRES
        return self._context.translator.message(
            source, value=self.height_value(meters, trim))

    def preset_tick(self, label: str, meters: float, trim: bool = False) -> str:
        """A preset tick's name next to its height, e.g. "Sit · 110.5".

        The one message every rail renders a preset tick through, so the
        separator is a catalog entry a language can change, and two rails
        cannot drift apart the way two identical ``f"{label} · {height}"``
        call sites eventually would.

        The height is deliberately the bare number from :meth:`height_value`,
        not :meth:`height` — a rail names the unit once at the end of the
        scale, which is why :meth:`height_value` exists at all, and why
        this method is not built on :meth:`height` instead.
        """
        return self._context.translator.message(
            PRESET_TICK, name=label, height=self.height_value(meters, trim))

    def connection_phrases(self, connected: bool, available: bool,
                           persistent: bool) -> tuple[str, str]:
        """The desk's connection state as ``(footer_text, chip_text)``.

        The door a caller with no Qt reaches the connection wording
        through. The GUI's own ``connection_state`` pairs the same two
        phrases with a theme colour and so stays in ``gui/``; both spellings
        resolve to the one implementation in :mod:`.words`.
        """
        key = connection_state_key(connected, available, persistent)
        return connection_phrases(self._context.translator, key)

    def status_label(self, status: str) -> str:
        """The long automation-status sentence for a status wire value."""
        return status_label(self._context.translator, status)

    def status_head(self, status: str) -> str:
        """The short Overview status head word for a status wire value."""
        return status_head(self._context.translator, status)

    def position_label(self, position: str) -> str:
        """The display word for a desk position wire value."""
        return position_label(self._context.translator, position)

    def preset_label(self, name: str) -> str:
        """The display name for a preset; a user's own name is verbatim."""
        return preset_label(self._context.translator, name)

    def trigger_label(self, trigger: str) -> str:
        """The word for a transition's trigger wire value."""
        return trigger_label(self._context.translator, trigger)

    # ----- the daemon's desktop notifications ---------------------------
    #
    # Whole sentences, selected here rather than by the caller. The daemon
    # used to hold both the desk-state branch and the substitution, which
    # meant its notification wording was assembled locally in a process
    # that could not be exercised by any shared test. These methods are
    # what make "the daemon assembles no duration and no state wording"
    # literally true at its call sites.

    def pre_move_summary(self, to_state: DeskState, seconds: float) -> str:
        """The pre-move warning's summary, e.g. "Standing up in about 5
        minutes".

        Takes the raw seconds rather than a rendered delay: rendering it
        here is what leaves the caller with no duration to assemble. The
        delay goes through :meth:`duration_verbose`, so a notification and
        a tooltip cannot disagree about what "1 hour 5 minutes" looks like.

        Each direction is a **whole sentence** with the delay substituted,
        never a verb joined to a fragment. A translator has to be able to
        move the delay relative to the words — and to choose different
        words for rising and lowering — which a shared "%s in about %s"
        shape would take away.
        """
        source = (PRE_MOVE_STANDING if to_state is DeskState.STANDING
                  else PRE_MOVE_SITTING)
        return self._context.translator.message(source) % \
            self.duration_verbose(seconds)

    def pre_move_body(self) -> str:
        """The pre-move warning's body, under either summary."""
        return self._context.translator.message(PRE_MOVE_BODY)

    def snooze_action_label(self, minutes: int) -> str:
        """The pre-move warning's snooze button, e.g. "Snooze 15 min"."""
        return self._context.translator.message(SNOOZE_ACTION) % minutes

    def skip_action_label(self) -> str:
        """The pre-move warning's skip button."""
        return self._context.translator.message(SKIP_ACTION)

    def automation_paused_summary(self) -> str:
        """Shown when the desk is parked at neither preset."""
        return self._context.translator.message(AUTOMATION_PAUSED_SUMMARY)

    def automation_paused_body(self) -> str:
        """The body of the automation-paused notification."""
        return self._context.translator.message(AUTOMATION_PAUSED_BODY)

    def move_failed_summary(self, intended: DeskState) -> str:
        """The failed-move summary, e.g. "The desk didn't stand up".

        A **whole sentence** per direction, for the same reason
        :meth:`pre_move_summary` is: a translator owns the word order, and
        two languages do not negate a verb in the same place.
        """
        source = (MOVE_FAILED_STANDING if intended is DeskState.STANDING
                  else MOVE_FAILED_SITTING)
        return self._context.translator.message(source)

    def move_failed_body(self, reason: str | None = None) -> str:
        """The failed-move body, with the desk's reason when there is one.

        ``reason`` is the daemon's own English diagnostic detail — it is
        substituted, never translated, the same way a D-Bus error body is.
        It is optional rather than defaulting to an empty string because
        the daemon's own value genuinely is ``str | None``; treating
        "absent" and "empty" alike here is what stops the caller having to
        coerce one into the other before it can ask for a sentence.
        """
        translator = self._context.translator
        if reason:
            return translator.message(MOVE_FAILED_BODY_WITH_REASON) % reason
        return translator.message(MOVE_FAILED_BODY)

    def try_now_action_label(self) -> str:
        """The failed-move notification's retry button."""
        return self._context.translator.message(TRY_NOW_ACTION)

    def later_label(self) -> str:
        """The stand-in for a snooze deadline not fetched yet."""
        return later_label(self._context.translator)

    def snooze_line(self, when_text: str) -> str:
        """"Snoozed until 14:32", from an already-formatted clock string."""
        return snooze_line(self._context.translator, when_text)

    def due_now_label(self) -> str:
        """Shown where a countdown would be, once it has run out."""
        return due_now_label(self._context.translator)

    def minutes_label(self, count: int) -> str:
        """The plural word for a count of minutes, e.g. "5 minutes"."""
        return minutes_label(self._context.translator, count)

    def position_or_custom(self, position: str) -> str:
        """The desk's position as a word, or "Custom" at neither preset."""
        return position_or_custom(self._context.translator, position)

    def countdown(self, seconds: float) -> str:
        """A running countdown, e.g. 125 -> "2:05"."""
        return countdown(
            self._context.translator, self._context.locale, seconds)

    def day_label(self, key: str) -> str:
        """The short day name for a schedule day key ('mon' -> 'Lun')."""
        return day_label(self._context.translator, key)

    def fmt_days(self, days: list[str]) -> str:
        """A schedule's day list, with consecutive runs collapsed to ranges."""
        return fmt_days(self._context.translator, days)

    # ----- the moment renderers: PRES-01's sanctioned divergence point ---
    #
    # These four ask the locale backend for a date/time *style* and never a
    # pattern (see core/presentation.pypy), which is what lets the
    # Qt-free backend answer differently — a fixed ISO date rather than a
    # weekday/month name table it would otherwise have to own itself.

    def day_short(self, when: datetime) -> str:
        """A short calendar day marker, e.g. "Mon 17" (Qt) / "2026-08-17"
        (Qt-free).

        Not to be confused with :meth:`day_label`, the unrelated
        schedule-day-key word ('mon' -> 'Lun') — that collision is the
        single most likely mistake at this site, which is why this method
        is named ``day_short`` rather than reusing ``day_label``.
        """
        return day_short(self._context.locale, when)

    def day_heading(self, when: datetime) -> str:
        """A full calendar date as a day-separator heading, e.g.
        "Mon 17 Aug 2026" (Qt) / "2026-08-17" (Qt-free)."""
        return day_heading(self._context.locale, when)

    def clock(self, when: datetime) -> str:
        """The wall-clock render, e.g. "14:32" or, in a 12-hour locale,
        "2:32 PM".

        Also not to be confused with :meth:`day_label`, the unrelated
        schedule-day-key word ('mon' -> 'Lun').
        """
        return clock(
            self._context.locale, self._context.time_style, when)

    def clock_with_seconds(self, when: datetime) -> str:
        """A wall-clock time to the second, e.g. "14:32:05" / "2:32:05 PM".

        The Activity Log's row stamp, and the only surface that reads a
        time to the second. It follows the same clock :meth:`clock` does —
        one resolved answer, two shapes — because a screen showing a
        12-hour tooltip beside a 24-hour log is the split this setting
        exists to close. The seconds are what orders two events inside the
        same minute, so they stay.
        """
        return clock(
            self._context.locale, self._context.time_style.with_seconds, when)

    def day_and_clock(self, when: datetime) -> str:
        """A day plus a wall-clock time, e.g. "Mon 17 14:32", as one whole
        translated message — see :mod:`.dates` for why the separating
        space is a catalog entry rather than a Python literal."""
        return day_and_clock(
            self._context.locale, self._context.translator,
            self._context.time_style, when)

    def duration_verbose(self, seconds: float) -> str:
        """A verbose duration for notification prose, e.g. "1 hour 5
        minutes" / "59 minutes" / "30 seconds".

        Shares ``core/durations.py``'s decomposition and threshold with
        every other duration renderer in the app (PRES-03's one policy),
        but keeps its own verbose message set: this text lands inside a
        notification sentence ("Desk will move in 1 hour 5 minutes"), where
        the compact "1h 05m" the journal and the Activity Log use would
        read as too terse.

        Below :data:`~idasen_companion.core.durations.SUB_MINUTE_THRESHOLD_SECONDS`
        this renders the seconds count alone, floored to at least one
        second so a near-zero delay still reads as a duration rather than
        "0 seconds" — the floor the daemon's own notification helper
        applied before this method absorbed it. At or above the
        threshold this decomposes into hours and minutes and, when both are
        present, nests two whole translated messages — one for the hours,
        one for the minutes — inside :data:`~.register.HOURS_AND_MINUTES`.

        That nesting is not a violation of the whole-message rule: it is
        the exact shape :func:`.fmt_days` and
        :data:`~.register.DAY_PAIR` already use and document, whole labels
        substituted into a translated
        pattern message, and ``tests/test_translation_markers.py``'s
        concatenation check already accepts it — that check flags ``+``,
        ``+=``, f-string interpolation and ``.join()``, never
        ``%``-substitution into a catalog pattern. Both numbers still agree
        correctly in any language, and the translator owns the separator
        and the order as well as the 
        """
        translator = self._context.translator
        if seconds < SUB_MINUTE_THRESHOLD_SECONDS:
            count = max(1, int(seconds))
            return translator.plural(*SECONDS, count) % count
        parts = decompose_hms(seconds)
        if parts.hours and parts.minutes:
            hours_part = translator.plural(*HOURS, parts.hours) % parts.hours
            minutes_part = translator.plural(*MINUTES, parts.minutes) % parts.minutes
            return translator.message(
                HOURS_AND_MINUTES, hours=hours_part, minutes=minutes_part)
        if parts.hours:
            return translator.plural(*HOURS, parts.hours) % parts.hours
        return translator.plural(*MINUTES, parts.minutes) % parts.minutes

    def duration_hm(self, seconds: float) -> str:
        """A compact hours-and-minutes duration, e.g. "1h 05m" / "45m".

        Floors a sub-minute value to "0m" rather than showing it — the
        journal's and the Activity Log's shared shape for a duration that
        has already crossed at least a minute (or hasn't, and is being
        shown that way on purpose; see :meth:`duration` for the sibling
        that keeps a sub-minute value visible instead).

        The minutes half is zero-padded through the locale backend's own
        ``integer(min_digits=2)`` operation, not a Python f-string — the
        case the locale profile's ``min_digits=2`` argument exists for.
        """
        locale = self._context.locale
        translator = self._context.translator
        parts = decompose_hms(seconds)
        if parts.hours:
            hours = locale.integer(parts.hours)
            minutes = locale.integer(parts.minutes, min_digits=2)
            return translator.message(
                HOURS_AND_MINUTES_COMPACT, hours=hours, minutes=minutes)
        minutes = locale.integer(parts.minutes)
        return translator.message(MINUTES_COMPACT, minutes=minutes)

    def duration(self, seconds: float) -> str:
        """A compact duration, keeping a sub-minute value visible ("45s").

        Below :data:`~idasen_companion.core.durations.SUB_MINUTE_THRESHOLD_SECONDS`
        this renders the seconds count alone; at or above it, this
        delegates to :meth:`duration_hm`. One threshold, one decomposition,
        one padding rule, shared with every other duration renderer in the
        app (PRES-03).

        A negative value clamps to zero, matching what
        :func:`~idasen_companion.core.durations.decompose_hms` does for the
        at-or-above-threshold branch. Both halves of this method have to
        agree about it: the clock the callers read is monotonic in
        principle but not in practice, and a delay computed across a
        suspend can arrive negative.
        """
        if seconds < SUB_MINUTE_THRESHOLD_SECONDS:
            locale = self._context.locale
            translator = self._context.translator
            secs = locale.integer(max(0, int(seconds)))
            return translator.message(SECONDS_COMPACT, seconds=secs)
        return self.duration_hm(seconds)

    def duration_minutes(self, seconds: float) -> str:
        """A duration for a control the user *picks* a value from, e.g.
        "45 min" — a dropdown item, a menu entry, a button label. Never the
        journal or the Activity Log, which keep :meth:`duration` and
        :meth:`duration_hm`'s compact shapes; those two are not callers of
        this method.

        Renders whole minutes only, through the same locale-backend integer
        operation every other duration method uses rather than a Python
        format string. **3600 seconds renders "60 min", never an hour
        decomposition** — the tray's own minutes-only design was deliberate,
        and unifying every picker onto this shape honours that design
        instead of quietly giving the tray hour decomposition it never
        wanted.

        **Zero renders "0 min".** A sub-minute value floors to zero minutes
        rather than showing seconds — that is what a minute-granularity
        picker's scale means; the seconds a sibling compact method would
        keep visible have no place on a scale whose smallest offered choice
        is a whole minute.

        A negative value clamps to zero, matching what :meth:`duration` and
        :func:`~idasen_companion.core.durations.decompose_hms` already do,
        and for the same reason: the clock these callers read is monotonic
        in principle and not in practice, and a delay computed across a
        suspend can arrive negative.
        """
        locale = self._context.locale
        translator = self._context.translator
        total_minutes = max(0, int(seconds)) // 60
        minutes = locale.integer(total_minutes)
        return translator.message(MINUTES_ABBREVIATED, minutes=minutes)


from datetime import datetime

from .i18n import Translator
from .i18n import DAY_AND_CLOCK
from .locale_profile import DateStyle, LocaleProfile, TimeStyle


def day_short(locale: LocaleProfile, when: datetime) -> str:
    """A short calendar day marker, e.g. "Mon 17" (Qt) / "2026-08-17"
    (Qt-free). Carries no catalog entry — it renders through the locale
    backend only."""
    return locale.date(when, DateStyle.WEEKDAY_AND_DAY)


def day_heading(locale: LocaleProfile, when: datetime) -> str:
    """A full calendar date as a day-separator heading, e.g.
    "Mon 17 Aug 2026" (Qt) / "2026-08-17" (Qt-free). Carries no catalog
    entry — it renders through the locale backend only."""
    return locale.date(when, DateStyle.WEEKDAY_DAY_MONTH_YEAR)


def clock(locale: LocaleProfile, style: TimeStyle, when: datetime) -> str:
    """A wall-clock time on the clock ``style`` names, e.g. "14:32" or
    "2:32 PM". Carries no catalog entry — it renders through the locale
    backend only.

    ``style`` is an argument rather than a constant chosen here because
    which clock the app shows is a user setting resolved once, in
    ``core/display_prefs.py``, and carried to every renderer by the
    presentation context. A member named in this body would be a second
    place that answers the same question.
    """
    return locale.time(when, style)


def day_and_clock(locale: LocaleProfile, translator: Translator,
                  style: TimeStyle, when: datetime) -> str:
    """A day plus a wall-clock time, e.g. "Mon 17 14:32", as one whole
    translated message — see the module docstring for why this composes
    :func:`day_short` and :func:`clock` through a catalog pattern rather
    than joining them in Python. ``style`` travels through to the clock
    half for the reason :func:`clock` gives."""
    return translator.message(
        DAY_AND_CLOCK, day=day_short(locale, when),
        clock=clock(locale, style, when))


from .locale_profile import LocaleProfile
from .i18n import Translator
from .i18n import (
    CONNECTION_CHIP_CONNECTED, CONNECTION_CHIP_DISCONNECTED,
    CONNECTION_CHIP_ON_DEMAND, CONNECTION_FOOTER_CONNECTED,
    CONNECTION_FOOTER_DISCONNECTED, CONNECTION_FOOTER_ON_DEMAND, COUNTDOWN,
    CUSTOM, DAY_NAMES, DAY_PAIR, DAY_RANGE, DUE_NOW, LATER, MINUTES, NO_DAYS,
    POSITION_LABELS, PRESET_LABELS, SNOOZED_UNTIL, STATUS_HEADS,
    STATUS_LABELS, TRIGGER_LABELS,
)

#: The seven schedule day wire values in week order. Pure data — no
#: translation, no catalog entry. It lives here rather than in ``gui/``
#: because :func:`fmt_days` is its only consumer and a function under
#: ``core/`` may not reach back into ``gui/``.
DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def connection_state_key(connected: bool, available: bool,
                         persistent: bool) -> str:
    """The desk's connection state as a key: connected/disconnected/on-demand.

    Split out from :func:`connection_phrases` deliberately. ``gui/util.py``'s
    ``connection_state`` needs the same state twice — once to pick a theme
    colour, which cannot live under ``core/``, and once to pick the words,
    which now do — and one shared key lets it branch on each without either
    half restating the other's condition, where it would be free to drift.
    """
    if connected:
        return "connected"
    if not available or persistent:
        return "disconnected"
    return "on-demand"


def connection_phrases(translator: Translator, key: str) -> tuple[str, str]:
    """The ``(footer_text, chip_text)`` pair for a connection state key.

    Any key other than ``"connected"`` or ``"disconnected"`` falls through
    to the on-demand pair, which is exactly the shape the branch had before
    the move: two tests and a return, with the last state unguarded.
    """
    if key == "connected":
        return (translator.message(CONNECTION_FOOTER_CONNECTED),
                translator.message(CONNECTION_CHIP_CONNECTED))
    if key == "disconnected":
        return (translator.message(CONNECTION_FOOTER_DISCONNECTED),
                translator.message(CONNECTION_CHIP_DISCONNECTED))
    return (translator.message(CONNECTION_FOOTER_ON_DEMAND),
            translator.message(CONNECTION_CHIP_ON_DEMAND))


def status_label(translator: Translator, status: str) -> str:
    """The long automation-status sentence for a status wire value.

    Falls back to the raw status string for an unrecognized key: a status
    the app has not been taught yet is better shown as its wire value than
    as nothing at all, and `tests/test_status_labels.py` is what stops that
    fallback from becoming the way a new status ships.
    """
    source = STATUS_LABELS.get(status)
    return translator.message(source) if source is not None else status


def status_head(translator: Translator, status: str) -> str:
    """The short Overview status head word for a status wire value.

    Falls back to the raw status string for an unrecognized key."""
    source = STATUS_HEADS.get(status)
    return translator.message(source) if source is not None else status


def position_label(translator: Translator, position: str) -> str:
    """The display word for a desk position wire value.

    Falls back to a capitalized copy for anything unrecognized, and ``""``
    for an empty/unknown position (callers substitute their own
    placeholder).
    """
    source = POSITION_LABELS.get(position)
    if source is not None:
        return translator.message(source)
    return position.capitalize() if position else ""


def preset_label(translator: Translator, name: str) -> str:
    """The display name for a preset.

    ``sit``/``stand`` are ours and translate; anything else the user named
    themselves and is shown verbatim. Replaces ``name.capitalize()``, which
    left the rail ticks and the tray submenu in English next to buttons
    that were translated — the same preset labelled two ways on one screen.
    """
    source = PRESET_LABELS.get(name)
    return translator.message(source) if source is not None else name


def trigger_label(translator: Translator, trigger: str) -> str:
    """The word for a transition's trigger wire value.

    Falls back to the raw trigger string for an unrecognized key."""
    source = TRIGGER_LABELS.get(trigger)
    return translator.message(source) if source is not None else trigger


def later_label(translator: Translator) -> str:
    """The stand-in for a snooze deadline the client has not fetched yet."""
    return translator.message(LATER)


def snooze_line(translator: Translator, when_text: str) -> str:
    """"Snoozed until 14:32" — one whole message, the time substituted in.

    ``when_text`` is an *already-formatted* clock string, not a timestamp:
    formatting a wall-clock time needs a locale backend and a timezone, and
    the caller already has both. Taking the finished text keeps this
    function a word rather than a date renderer, and means the eventual
    move of the clock formatter changes only what fills this argument, not
    this function.
    """
    return translator.message(SNOOZED_UNTIL) % when_text


def due_now_label(translator: Translator) -> str:
    """Shown where a countdown would be, once it has run out."""
    return translator.message(DUE_NOW)


def minutes_label(translator: Translator, count: int) -> str:
    """The plural *word* for a count of minutes, e.g. 1 -> "1 minute",
    5 -> "5 minutes" — selected by the catalog's own plural rule rather than
    a Python ``count == 1`` check.

    Deliberately narrower than :meth:`~.formatter.Formatter.duration_verbose`,
    which this could otherwise be built from
    (``duration_verbose(count * 60)``): that method decomposes into hours
    and minutes, so a 60-minute value would render as "1 hour" — correct
    for a duration, wrong here, where 60 is one of a fixed menu of minute
    choices and must read as such. This function has no decomposition to
    do, so it does none.
    """
    return translator.plural(*MINUTES, count) % count


def position_or_custom(translator: Translator, position: str) -> str:
    """The desk's position as a word, or "Custom" at neither preset."""
    return (position_label(translator, position)
            or translator.message(CUSTOM))


def countdown(translator: Translator, locale: LocaleProfile,
              seconds: float) -> str:
    """A running countdown, e.g. 125 -> "2:05".

    Takes both capabilities because a countdown needs both: the two numbers
    are the locale backend's to render — including zero padding through its
    ``min_digits`` argument rather than a Python format spec — and the
    separator between them is the translator's, so a
    language that punctuates a countdown differently can say so. Nothing
    here is assembled in Python.

    A negative value clamps to zero, as it did before this rendered
    through the shared layer: the clock the callers read is monotonic in
    principle but not in practice.
    """
    minutes, secs = divmod(max(0, int(seconds)), 60)
    return translator.message(
        COUNTDOWN,
        minutes=locale.integer(minutes),
        seconds=locale.integer(secs, min_digits=2))


def day_label(translator: Translator, key: str) -> str:
    """The short day name for a schedule day key ('mon' -> 'Lun').

    Public because the schedule day chips need it too: :data:`DAY_NAMES`
    holds unrendered source strings, so reading it directly yields the
    untranslated English word.
    """
    return translator.message(DAY_NAMES[key])


def fmt_days(translator: Translator, days: list[str]) -> str:
    """['mon'..'fri'] -> 'Mon–Fri'; ['mon','wed','fri'] -> 'Mon, Wed, Fri'.

    Consecutive runs of three or more days collapse into a range.
    """
    picked = [d for d in DAY_ORDER if d in days]
    if not picked:
        return translator.message(NO_DAYS)
    runs: list[list[str]] = []
    for day in picked:
        if runs and (DAY_ORDER.index(day)
                     - DAY_ORDER.index(runs[-1][-1])) == 1:
            runs[-1].append(day)
        else:
            runs.append([day])
    parts = []
    for run in runs:
        if len(run) >= 3:
            parts.append(translator.message(
                DAY_RANGE, first=day_label(translator, run[0]),
                last=day_label(translator, run[-1])))
        else:
            parts.extend(day_label(translator, d) for d in run)
    # One pair pattern, folded left across `parts`, rather than CLDR's
    # four-key start/middle/end set: this is a unit list ("3 ft, 2 in"), not
    # a sentence list, and both shipped languages render every position with
    # the same plain comma join and no conjunction — a fuller key set would
    # be catalog weight nobody can act on today. If a conjunction-taking
    # language ships later, this fold is where the key set would grow.
    result = parts[0]
    for part in parts[1:]:
        result = translator.message(DAY_PAIR, first=result, second=part)
    return result


class EnglishTranslator:
    """Returns every source string unchanged, selecting English's plural rule.

    Deliberately reaches no catalog of any kind -- no import of the
    process-wide translation module, no ``ngettext``, nothing that follows
    ``[ui] language``. That absence is the entire point: it is what keeps
    this backend's output identical regardless of that catalog's current
    binding.
    """

    def message(self, source: str, **values: object) -> str:
        return source % values if values else source

    def plural(self, singular: str, plural: str, count: int,
               **values: object) -> str:
        text = singular if count == 1 else plural
        return text % values if values else text


def format_duration_human(seconds: float | None) -> str:
    """The released stable-English journal duration shape.

    Matches the shape ``gui/log_catalog.py`` renders the same
    ``Param.DURATION`` value in, which closes the split PRES-03 exists to
    close -- the same log event no longer reads "45.0 minutes" for journald
    and "45m" for the Activity Log.

    ``None`` renders as "N/A", the same convention
    ``core/logmsg.py``'s ``Param.HEIGHT`` formatter already uses; nothing in
    this move changes that.

    Builds a throwaway :class:`~idasen_companion.core.presentation.Formatter`
    per call rather than binding one at module level -- the module-level
    instance :mod:`tests.test_presentation_no_globals` flags and PRES-02
    forbids. It cannot live in ``core/durations.py`` instead:
    ``core/presentation.py`` already imports that module for
    ``decompose_hms``, so the reverse import here would be circular. The
    unit is stated explicitly as centimetres, the same one-line convention
    plan 13-03's ``daemon/i18n.py`` uses for its own throwaway context --
    the journal never renders a height, so the unit is inert, but
    :class:`~idasen_companion.core.presentation.PresentationContext`
    carries no default for it to fall back on.
    """
    if seconds is None:
        return "N/A"
    if seconds >= 60:
        return f"{seconds / 60:.1f} minutes"
    return f"{seconds:.0f} seconds"


from .i18n import Translator
from .i18n import DAEMON_ERROR_GENERIC, DAEMON_ERROR_MESSAGES


def daemon_error_message(translator: Translator, name: str,
                         detail: str = "") -> str:
    """A translated sentence for a daemon D-Bus error name.

    ``name`` may be the full ``…Error.MoveFailed`` or the bare tail. Falls
    back to the daemon's English ``detail`` — untranslated, but better than
    silence — and finally to a generic line.
    """
    key = name.rsplit(".", 1)[-1] if name else ""
    source = DAEMON_ERROR_MESSAGES.get(key)
    if source is not None:
        return translator.message(source)
    if detail:
        return detail
    return translator.message(DAEMON_ERROR_GENERIC)
