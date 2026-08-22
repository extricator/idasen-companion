"""The ``Formatter`` facade and the context it holds.

This module records the design's § 14 call-site decision — the choice
between threading a presentation context explicitly through every
formatter's signature, and bundling it behind a small facade object — as
committed source, because ``.planning/`` is gitignored on this project and
would take the reasoning with it if it lived there instead.

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
``LocaleFormatter`` and ``Translator`` the context carries. That is the
distinction from the per-surface renderer set this project already
rejected: a Qt renderer and a headless renderer each reimplementing the
same formatting policy. Here the policy is written once, in this facade's
methods, and only the two small capabilities beneath it vary.

**What this does not settle.** ``gui/widgets.py``'s paint method imports a
height formatter directly because the widget it paints has no context to
reach for. Neither this shape nor the rejected one solves that on its own;
it is PRES-06's problem, not this plan's.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import units
from ..durations import SUB_MINUTE_THRESHOLD_SECONDS, decompose_hms
from ..units import HeightUnit
from .protocols import LocaleFormatter, Translator
from .register import HOURS, HOURS_AND_MINUTES, MINUTES, SECONDS
from .specs import NumberSpec


@dataclass(frozen=True)
class PresentationContext:
    """The capability pair and unit a :class:`Formatter` renders through.

    Holds the two protocol instances a surface supplies — a
    locale-rendering backend and a message-translating backend — plus the
    display unit a height renders in. Frozen because it is built once per
    surface and handed to every ``Formatter`` that surface constructs;
    nothing here changes over the context's lifetime.

    ``unit`` carries no default. ``"system"`` is a setting, not a unit —
    :func:`idasen_companion.core.units.resolve_height_unit` is the one
    place that resolves it — and a default here would quietly let a
    caller hand this context an unresolved policy question instead of an
    answer.
    """

    locale: LocaleFormatter
    translator: Translator
    unit: HeightUnit


class Formatter:
    """Renders values and messages through an injected presentation context.

    Holds a :class:`PresentationContext` and nothing else. A method here
    owes exactly this: an atomic value goes through ``self._context.locale``,
    a whole message goes through ``self._context.translator``, and nothing
    is ever concatenated in Python — the values these two collaborators
    produce are substituted into a translated pattern instead (see
    ``core/presentation/formatter.py``'s callers and CLAUDE.md's
    whole-message rule).

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
            NumberSpec(decimals=self.height_decimals(), trim_trailing_zeroes=trim))

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
        "0 seconds" — the same floor ``daemon/i18n.py``'s ``human_delay``
        applied on its own before this method absorbed it. At or above the
        threshold this decomposes into hours and minutes and, when both are
        present, nests two whole translated messages — one for the hours,
        one for the minutes — inside :data:`~.register.HOURS_AND_MINUTES`.

        That nesting is not a violation of the whole-message rule: it is
        the exact shape ``gui/util.py``'s ``fmt_days``/``_DAY_PAIR`` already
        uses and documents, whole labels substituted into a translated
        pattern message, and ``tests/test_translation_markers.py``'s
        concatenation check already accepts it — that check flags ``+``,
        ``+=``, f-string interpolation and ``.join()``, never
        ``%``-substitution into a catalog pattern. Both numbers still agree
        correctly in any language, and the translator owns the separator
        and the order as well as the words.
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
