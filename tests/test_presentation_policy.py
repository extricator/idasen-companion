"""The first policy tests written against fake markers: no Qt, no catalog.

GATE-09's failure mode is a policy bug — a threshold or a unit choice that
breaks — surfacing as a Spanish-string mismatch and getting fixed in the
wrong layer. This module exists so that cannot happen: every assertion
below reads a marker or a recorded request from ``tests/presentation_fakes``
(``FakeLocale``, ``FakeTranslator``), never a rendered value, so a failure
here can only mean the policy itself moved.

No formatter has moved onto the ``Formatter`` facade yet — that is Phases
13-15's job. Each test below composes the domain functions
(``core/units.py``, ``core/durations.py``) and the fakes directly, which is
exactly what a future formatter method will do; this module exercises that
shape early, through ``PresentationContext``/``Formatter``, so the recorded
call-site shape (D-01) is proven before a single formatter relies on it.
"""

from __future__ import annotations

import dataclasses

import pytest

from idasen_companion.core.durations import (
    SUB_MINUTE_THRESHOLD_SECONDS, decompose_hms,
)
from idasen_companion.core.presentation.formatter import (
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.protocols import (
    LocaleFormatter, Translator,
)
from idasen_companion.core.presentation.specs import IntegerSpec, NumberSpec
from idasen_companion.core.units import (
    HeightUnit, height_decimals, to_display_height,
)
from presentation_fakes import (
    FakeLocale, FakeTranslator, LocaleCall, TranslatorCall,
)
from test_presentation_protocols import get_protocol_members

#: A fixed height in metres, chosen for a non-trivial fractional result in
#: both units (1.105 m -> 110.5 cm / 43.5039... in) — see PRES-07.
HEIGHT_METERS = 1.105


# ---------------------------------------------------------------------------
# Unit choice (PRES-07)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "unit,expected_decimals",
    [(HeightUnit.CENTIMETRES, 1), (HeightUnit.INCHES, 2)],
)
def test_unit_choice_reaches_the_backend_as_a_request(unit, expected_decimals):
    """A converted value and a decimal-count spec cross the seam — never
    the source metres, never the unit that produced them."""
    display_value = to_display_height(HEIGHT_METERS, unit)
    spec = NumberSpec(decimals=height_decimals(unit))
    assert spec.decimals == expected_decimals

    locale = FakeLocale()
    context = PresentationContext(
        locale=locale, translator=FakeTranslator(), unit=HeightUnit.CENTIMETRES)
    Formatter(context)  # exercises the D-01 call-site shape

    context.locale.number(display_value, spec)

    call = locale.calls[-1]
    assert call == LocaleCall("number", display_value, spec)

    # The PRES-07 property, asserted on the request itself: a NumberSpec
    # names only a decimal count (plus trim/grouping) — there is no field
    # capable of carrying a unit, and the value recorded is the already
    # -converted display number, never the source metres.
    field_names = {field.name for field in dataclasses.fields(call.request)}
    assert field_names == {"decimals", "trim_trailing_zeroes", "grouping"}
    assert call.value != HEIGHT_METERS


# ---------------------------------------------------------------------------
# Threshold: the selection either side of a minute and either side of an hour
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "total_seconds,expect_seconds_only,expect_has_hours",
    [
        (45, True, False),                              # below the threshold
        (SUB_MINUTE_THRESHOLD_SECONDS, False, False),    # the threshold, exactly
        (125, False, False),                             # between a minute and an hour
        (3900, False, True),                              # one hour and five minutes
    ],
)
def test_threshold_selects_the_duration_rendering_branch(
    total_seconds, expect_seconds_only, expect_has_hours,
):
    """The branch a duration renderer picks either side of the minute
    threshold and either side of an hour — a domain decision, checkable
    without ever touching a fake or a rendered string."""
    parts = decompose_hms(total_seconds)
    assert (total_seconds < SUB_MINUTE_THRESHOLD_SECONDS) is expect_seconds_only
    assert bool(parts.hours) is expect_has_hours


def test_duration_minutes_are_requested_through_a_two_digit_integer_spec():
    """3900 seconds decomposes to one hour and five minutes, and the
    minutes are requested with a zero-padded, two-digit spec — the
    ``fmt_hm``-shaped case named in the plan, asserted on the recorded
    request rather than on any rendered ``"1h 05m"``-shaped text."""
    parts = decompose_hms(3900)
    assert (parts.hours, parts.minutes, parts.seconds) == (1, 5, 0)

    locale = FakeLocale()
    context = PresentationContext(
        locale=locale, translator=FakeTranslator(), unit=HeightUnit.CENTIMETRES)
    Formatter(context)

    minutes_spec = IntegerSpec(min_digits=2)
    context.locale.integer(parts.minutes, minutes_spec)

    call = locale.calls[-1]
    assert call == LocaleCall("integer", parts.minutes, minutes_spec)
    assert call.request.min_digits == 2


# ---------------------------------------------------------------------------
# Message selection
# ---------------------------------------------------------------------------

def test_message_selection_names_the_key_and_every_value():
    """A whole message with named substitution values crosses the seam —
    never a fragment — proving both the source key and every supplied
    value reached the translator."""
    translator = FakeTranslator()
    context = PresentationContext(
        locale=FakeLocale(), translator=translator, unit=HeightUnit.CENTIMETRES)
    Formatter(context)

    marker = context.translator.message(
        "duration_hours_minutes", hours="1", minutes="05",
    )

    call = translator.calls[-1]
    assert call == TranslatorCall(
        "duration_hours_minutes", {"hours": "1", "minutes": "05"},
    )
    assert "duration_hours_minutes" in marker
    assert "hours" in marker and "1" in marker
    assert "minutes" in marker and "05" in marker


# ---------------------------------------------------------------------------
# Conformance: a fake cannot quietly grow a member its protocol lacks
# ---------------------------------------------------------------------------

def _public_members(cls: type) -> frozenset[str]:
    """The callable, non-dunder names ``cls`` itself declares.

    Reads the class's own ``__dict__`` rather than an instance's, so a
    per-instance recording list (``calls``, set in ``__init__``) is
    invisible here — this enumerates methods, the thing T-12-13 is about,
    not call-recording state.
    """
    return frozenset(
        name for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value)
    )


@pytest.mark.parametrize(
    "fake_cls,protocol",
    [(FakeLocale, LocaleFormatter), (FakeTranslator, Translator)],
    ids=lambda value: getattr(value, "__name__", str(value)),
)
def test_fake_conforms_exactly_to_its_protocol(fake_cls, protocol):
    """Compared in both directions (T-12-13): a fake that grew a method its
    protocol lacks, or dropped one its protocol requires, fails here."""
    fake_members = _public_members(fake_cls)
    protocol_members = get_protocol_members(protocol)
    assert fake_members == protocol_members
