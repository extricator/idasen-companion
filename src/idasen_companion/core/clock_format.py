"""The clock format as a setting, and the one place it becomes a style.

Qt-free and IO-free, like :mod:`core.units`: nothing here imports Qt,
nothing imports the C library's locale machinery, and
:func:`resolve_clock_style` reads nothing from the process — every input it
needs arrives as an argument. That is what lets both front ends run it over
their own environment and reach the same answer.

**Why this is two types, not one**, the same argument :mod:`core.units`
makes for the height unit: ``"system"`` is not a clock, it is a setting that
resolves into one. Two types make the illegal state unrepresentable — a
backend cannot be handed ``"system"`` — and one type plus a documented
resolver leaves nothing stopping a later contributor widening the style enum
to include it. :class:`ClockSetting` is what ``[ui] clock_format`` stores;
:class:`~.presentation.specs.TimeStyle` is what a backend receives; this
module's resolver is the one place that turns the first into the second.

``ClockSetting`` is a ``StrEnum`` for the reason ``core/units.py`` gives for
its own: under a plain ``str, Enum`` a missed ``.value`` puts a Python repr
into user-visible text, and that failure is silent until someone reads a
screenshot.

**The ``"system"`` policy, stated as policy rather than as a claim about
CLDR.** An explicit setting answers for itself. Otherwise, in order:

1. ``LC_ALL``, then ``LC_TIME``. The **first one set decides outright** —
   its territory if it names one, and 24-hour if it does not. A user who has
   set the POSIX time locale has stated what they want time to look like, and
   ``LC_TIME=C`` is a statement, not an absence.
2. Failing both, the territory of ``language`` — the app's own display
   language setting, when the user has pinned one that names a territory.
3. Failing that, the first of ``LANG``, ``LANGUAGE`` that names a territory.
   These select a language rather than a time format, so unlike step 1 a
   value naming no territory is passed over rather than treated as an answer.
4. Failing everything, 24-hour.

**Rejected: territory only, reusing the height resolver's sources verbatim.**
It ignores ``LC_TIME`` entirely, so a machine carrying ``LANG=en_US.UTF-8``
with ``LC_TIME=C`` — the development machine, measured 2026-08-29 — would
flip from the 24-hour clock its window shows today to a 12-hour one, a
visible change for someone who set nothing.

**Rejected: ``LC_TIME`` with no territory fallback at all.** A US user with
no ``LC_TIME`` set would drop from the 12-hour clock their window shows today
to 24-hour. Same failure, different user.

**Where the territory set comes from.** Derived offline on 2026-08-29 from
CLDR, by asking, for every territory CLDR knows, for the locale CLDR itself
considers predominant there, rendering a known afternoon hour through that
locale's own short time format, and reading the rendered digits — never
substring-matching a format code, because ``en_US``'s answer is a compound
directive containing neither of the obvious markers and a naive match
classifies the one territory this policy most needs to get right as 24-hour.
A hand-written list was the rejected alternative: it is wrong at the edges,
and CLDR is the data everyone else is quoting when they write one. Territories
CLDR names no predominant locale for are absent, and so resolve to 24-hour.

The derivation ran once and its result is shipped as a frozen set; nothing at
runtime asks a locale database anything. Re-derive it rather than trusting it
if it starts looking wrong — and note that the explicit ``"12"`` and ``"24"``
values exist precisely so a user whose territory this set guesses wrong can
override it for good. The reasoning is settled and is not to be re-derived
here or at any call site.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from .presentation.specs import TimeStyle
from .units import territory_of


class ClockSetting(StrEnum):
    """What ``[ui] clock_format`` stores: a preference, not yet a clock.

    ``SYSTEM`` defers to :func:`resolve_clock_style`; ``TWELVE`` and
    ``TWENTY_FOUR`` pin the clock outright. Declared in this order because
    ``core/config.py``'s ``VALID_CLOCK_FORMATS`` is derived from it, and that
    order reaches a user-facing validation message.
    """

    SYSTEM = "system"
    TWELVE = "12"
    TWENTY_FOUR = "24"


#: Territories whose predominant CLDR locale renders a 12-hour clock. See the
#: module docstring for how this was derived and when.
#:
#: **Four rules govern the derivation, and every one of them is here because
#: breaking it put wrong data in this set.**
#: ``tests/test_locale_backend.py`` re-derives the set against the installed
#: CLDR and asserts equality, so none of the four can be lost silently.
#:
#: 1. **Digits are read whatever script writes them.** Afghanistan, Iran,
#:    Comoros, Myanmar and Nepal all render ``14:32`` — as ``۱۴:۳۲``, ``١٤:٣٢``,
#:    ``၁၄:၃၂`` and ``१४:३२``. The first derivation matched ASCII ``14`` only,
#:    found none, and filed all five as 12-hour. They shipped wrong.
#: 2. **Only territories CLDR actually has a locale for.** ``QLocale`` answers
#:    for any territory you ask about, falling back to a default — so a
#:    derivation that walks the whole enum marks Antarctica, Bouvet Island and
#:    the European Union as 12-hour. That is not merely noise: it inverts this
#:    module's own documented fallback, which is 24-hour when nothing names a
#:    territory.
#: 3. **A territory's likely locale decides, so its main language wins.** Some
#:    territories disagree internally — ``es_CL`` is 12-hour and ``arn_CL`` is
#:    24-hour, ``en_GB`` is 24-hour and ``gd_GB`` is 12-hour. Neither unanimity
#:    nor a majority works (only two of five installed ``*_US`` locales are
#:    12-hour, so both rules would drop the United States). CLDR's own
#:    likely-subtags resolution names the language a territory actually speaks,
#:    which is the question being asked.
#: 4. **The likely locale is only believed when it is for the territory that
#:    was asked about.** For American Samoa, Palau, Samoa, Vanuatu, Tokelau and
#:    Tuvalu, Qt resolves no likely locale and silently returns one for a
#:    different territory — whose rendering then follows whatever
#:    ``QLocale.setDefault`` happens to hold, making the derivation depend on
#:    process-global mutable state and answer differently depending on what ran
#:    before it. Comparing the returned territory against the requested one
#:    catches that; those six fall back to their own locales, which are
#:    unanimous. The re-derivation asserts that unanimity rather than assuming
#:    it, so a future CLDR that splits one of them fails loudly instead of
#:    being guessed at.
TWELVE_HOUR_TERRITORIES = frozenset({
    "AE", "AG", "AL", "AR", "AS", "AU", "BB", "BD", "BH", "BM", "BN",
    "BO", "BS", "BT", "CA", "CL", "CO", "CR", "CU", "CY", "DJ", "DM",
    "DO", "DZ", "EC", "EG", "EH", "ER", "ET", "FJ", "FM", "GD", "GH",
    "GM", "GR", "GT", "GU", "GY", "HK", "HN", "IN", "IQ", "JM", "JO",
    "KH", "KI", "KN", "KP", "KR", "KW", "KY", "LB", "LC", "LR", "LS",
    "LY", "MH", "MO", "MP", "MR", "MW", "MX", "MY", "NA", "NI", "NZ",
    "OM", "PA", "PE", "PG", "PH", "PK", "PR", "PS", "PW", "QA", "SA",
    "SB", "SD", "SG", "SL", "SO", "SS", "SV", "SY", "SZ", "TC", "TD",
    "TN", "TO", "TT", "TW", "UM", "US", "UY", "VC", "VE", "VG", "VI",
    "VU", "WS", "YE", "ZM",
})

#: The POSIX variables that name the *time* locale, in precedence order. The
#: first one set answers outright — see step 1 of the module docstring's
#: policy.
_TIME_LOCALE_PRECEDENCE = ("LC_ALL", "LC_TIME")

#: The POSIX variables that name a *language*, consulted after ``language``
#: itself and only for the territory they carry. Two constants rather than
#: one because the policy interleaves the app's own language setting between
#: them, which is where this resolver's shape genuinely differs from the
#: height one.
_LANGUAGE_ENVIRON_PRECEDENCE = ("LANG", "LANGUAGE")


def _style_for_territory(territory: str | None) -> TimeStyle:
    """The clock a territory implies, defaulting to 24-hour for no answer."""
    return (TimeStyle.HOUR_AND_MINUTE_12
            if territory in TWELVE_HOUR_TERRITORIES
            else TimeStyle.HOUR_AND_MINUTE_24)


def resolve_clock_style(setting: ClockSetting, *, language: str,
                        environ: Mapping[str, str]) -> TimeStyle:
    """A ``[ui] clock_format`` setting as a concrete style, resolving
    ``SYSTEM``.

    See the module docstring for the policy this implements and for both
    alternatives it rejects. Pure: every input is an argument, nothing is
    read from the process, and nothing here asks Qt or the C library
    anything.

    The style returned is the minute-only one for the clock resolved; a
    surface that renders seconds asks its formatter for the seconds-bearing
    style on the same clock rather than resolving a second time.
    """
    if setting is ClockSetting.TWELVE:
        return TimeStyle.HOUR_AND_MINUTE_12
    if setting is ClockSetting.TWENTY_FOUR:
        return TimeStyle.HOUR_AND_MINUTE_24

    for key in _TIME_LOCALE_PRECEDENCE:
        time_locale = environ.get(key)
        if time_locale:
            return _style_for_territory(territory_of(time_locale))

    territory = territory_of(language)
    if territory is None:
        for key in _LANGUAGE_ENVIRON_PRECEDENCE:
            value = environ.get(key)
            if value:
                territory = territory_of(value)
                if territory is not None:
                    break

    return _style_for_territory(territory)
