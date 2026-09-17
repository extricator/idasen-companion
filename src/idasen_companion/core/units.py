"""The height unit as a type, and the arithmetic that switches on it.

Qt-free and IO-free, like :mod:`core.durations`: nothing here imports Qt, and
:func:`resolve_height_unit` reads nothing from the process — every input it
needs arrives as an argument. That is what lets it run on the daemon's side
of the D-Bus seam as easily as the GUI's.

D-04 — why this is two types, not one. ``"system"`` is not a unit; it is a
setting that resolves into one. Two types make the illegal state
unrepresentable — a formatter cannot be handed ``"system"`` — which is the
main thing the type buys. One type plus a documented resolver leaves nothing
stopping a later contributor widening the enum to include ``SYSTEM``, which
is exactly how the distinction erodes. :class:`UnitSetting` is what
``[ui] units`` stores; :class:`HeightUnit` is what a formatter receives;
:func:`resolve_height_unit` is the one place that turns the first into the
second.

Both enums are ``StrEnum``, the same choice ``core/machine.py`` makes for
``DeskState``/``Status`` and for the same reason: under a plain ``str, Enum``
a missed ``.value`` puts a Python repr (``HeightUnit.CENTIMETRES``) into
user-visible text instead of the wire value, and that failure is silent
until someone reads a screenshot.

The four functions below carry the height conversion and the fractional-digit
policy out of ``gui/util.py``: they take the unit as an explicit argument
rather than reading a module global, so neither backend is ever asked a
product question (PRES-07) — a formatter states a value and a unit, and the
answer is the same regardless of who is asking.

``resolve_height_unit``'s ``"system"`` policy is independent from app
language. An explicit setting answers for itself. Otherwise the territory
comes from the first set value of ``LC_ALL``, ``LC_MEASUREMENT`` and ``LANG``.
A territory of ``US`` or ``LR`` resolves to inches; everything else —
including ``GB``, deliberately, because a UK desk is advertised, reviewed and
sold in centimetres — resolves to centimetres. An absent or unparseable answer
resolves to centimetres. The retained ``language`` parameter is transitional
API compatibility and is deliberately ignored.
CLDR's own measurement-system field is coarser than this and is heading for
deprecation; this is this project's own settled product default, which the
Settings page can always override for good. The reasoning is settled and is
not to be re-derived here or at any call site.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

#: Metres per inch, exactly — the one conversion factor both height
#: functions below are built on.
METRES_PER_INCH = 0.0254


class UnitSetting(StrEnum):
    """What ``[ui] units`` stores: a display preference, not yet a unit.

    ``SYSTEM`` defers to :func:`resolve_height_unit`; ``CENTIMETRES`` and
    ``INCHES`` pin the unit outright. Declared in this order because
    ``core/config.py``'s ``VALID_UNITS`` is derived from it, and that order
    reaches a user-facing validation message.
    """

    SYSTEM = "system"
    CENTIMETRES = "cm"
    INCHES = "in"


class HeightUnit(StrEnum):
    """What a formatter receives: a unit, never a setting.

    These two tokens are internal vocabulary — never translated. The
    translated display strings (the leading-space spin-box suffixes, " cm" /
    " in" and their Spanish equivalents) are a different thing entirely, and
    stay in ``gui/util.py`` under the spin-box exception documented there.
    """

    CENTIMETRES = "cm"
    INCHES = "in"


_US_CUSTOMARY_TERRITORIES = frozenset({"US", "LR"})

#: Precedence order for the POSIX locale environment variables consulted
#: when neither an explicit setting nor ``language`` names a territory.
_SYSTEM_ENVIRON_PRECEDENCE = ("LC_ALL", "LC_MEASUREMENT", "LANG")


def territory_of(locale_value: str) -> str | None:
    """The two-letter territory out of a POSIX-shaped locale string.

    Handles ``language[_territory][.codeset][@modifier]`` — ``"en_US.UTF-8"``,
    ``"es_ES"``, ``"C"`` — and the colon-separated priority list GNU gettext
    puts in ``LANGUAGE`` (``"es_ES:es"``), of which only the first entry is
    read. Stops at the first ``:``, then the first ``.`` or ``@``, before
    looking for the ``_territory`` segment. Returns ``None`` when the string
    names no two-letter territory at all, which callers treat as "try the
    next source" rather than as an error.
    """
    # The colon split comes first and is not cosmetic. LANGUAGE is a GNU
    # gettext *priority list* — a real session carries "es_ES:es" — and both
    # resolvers consult it for a territory. Without this, "es_ES:es" partitions
    # to "ES:es", which is five characters and so names no territory at all:
    # the LANGUAGE step of both policies was silently inert for the only form
    # the variable is normally written in.
    core = locale_value.split(":", 1)[0]
    core = core.split(".", 1)[0].split("@", 1)[0]
    _, _, territory = core.partition("_")
    if len(territory) == 2 and territory.isalpha():
        return territory.upper()
    return None


def resolve_height_unit(setting: UnitSetting, *, language: str,
                         environ: Mapping[str, str]) -> HeightUnit:
    """A ``[ui] units`` setting as a concrete unit, resolving ``SYSTEM``.

    See the module docstring for the policy this implements and why it
    deliberately disagrees with the GUI's desktop-measurement-system
    resolver for the UK. Pure: every input is an argument, nothing is read
    from the process, and nothing here asks Qt anything.
    """
    if setting is not UnitSetting.SYSTEM:
        return HeightUnit(setting.value)

    # Retained in the signature while callers migrate, but deliberately not
    # used: selected language, system measurement locale and explicit unit
    # preference are independent product inputs.
    del language
    territory = None
    for key in _SYSTEM_ENVIRON_PRECEDENCE:
        value = environ.get(key)
        if value:
            territory = territory_of(value)
            break

    return HeightUnit.INCHES if territory in _US_CUSTOMARY_TERRITORIES \
        else HeightUnit.CENTIMETRES


def to_display_height(meters: float, unit: HeightUnit) -> float:
    """Metres as the number the user sees (1.105 -> 110.5 cm / 43.5 in)."""
    if unit == HeightUnit.INCHES:
        return meters / METRES_PER_INCH
    return meters * 100


def from_display_height(value: float, unit: HeightUnit) -> float:
    """The inverse of :func:`to_display_height`, back to metres.

    Displayed values are converted back only to *act* on them — moving the
    desk, or entering a brand-new preset. A height already in config is never
    round-tripped through the display, so the rounding here can't drift one.
    """
    if unit == HeightUnit.INCHES:
        return value * METRES_PER_INCH
    return value / 100


def height_decimals(unit: HeightUnit) -> int:
    """Decimal places a height is shown with.

    Two for inches, because one (2.54 mm per step) is coarser than the desk's
    own millimetre resolution — and Overview's Move button sends the spin
    box's value back to the desk, so a user who never touched the box could
    still shift the desk over a millimetre just by pressing Move.
    """
    return 2 if unit == HeightUnit.INCHES else 1


def height_step(unit: HeightUnit) -> float:
    """A single step of a height spin box, in display units."""
    return 0.25 if unit == HeightUnit.INCHES else 0.5
