"""Resolve independent clock and height-unit display preferences."""


from collections.abc import Mapping
from enum import StrEnum

from .locale_profile import (
    TimeStyle, locale_uses_twelve_hour_clock, normalize_locale,
)


class ClockSetting(StrEnum):
    """What ``[ui] clock_format`` stores: a preference, not a clock."""

    SYSTEM = "system"
    TWELVE = "12"
    TWENTY_FOUR = "24"


def _system_time_locale(environ: Mapping[str, str]) -> str | None:
    """Resolve the POSIX time locale without using the selected app language."""
    for key in ("LC_ALL", "LC_TIME", "LANG"):
        value = environ.get(key)
        if value:
            # The first explicit time-locale input answers outright. C,
            # POSIX, invalid and unsupported values use the deterministic
            # 24-hour fallback rather than leaking into another category.
            return normalize_locale(value)
    return None


def resolve_clock_style(setting: ClockSetting, *, language: str,
                        environ: Mapping[str, str]) -> TimeStyle:
    """Resolve a setting once; ``language`` is retained for API compatibility.

    The accepted preference model intentionally does not consult ``language``
    for ``SYSTEM``. Changing the app's words and symbols must not silently
    change the user's hour cycle.
    """
    del language
    if setting is ClockSetting.TWELVE:
        return TimeStyle.HOUR_AND_MINUTE_12
    if setting is ClockSetting.TWENTY_FOUR:
        return TimeStyle.HOUR_AND_MINUTE_24
    locale_name = _system_time_locale(environ)
    if locale_name and locale_uses_twelve_hour_clock(locale_name):
        return TimeStyle.HOUR_AND_MINUTE_12
    return TimeStyle.HOUR_AND_MINUTE_24

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
