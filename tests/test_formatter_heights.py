"""Height arithmetic on the ``Formatter`` facade — the first real methods.

Built against the real :class:`PlainLocaleFormatter` (not the markers in
``presentation_fakes``) precisely because these methods produce a rendered
number, and a marker-only test could not tell "110.5" from a policy bug
that happened to also produce a string.
"""

from __future__ import annotations

import pytest

from idasen_companion.core.presentation.english import EnglishTranslator
from idasen_companion.core.presentation.formatter import (
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.specs import TimeStyle
from idasen_companion.core.presentation.plain_locale import PlainLocaleFormatter
from idasen_companion.core.units import HeightUnit

#: A fixed height in metres, chosen for a non-trivial fractional result in
#: both units (1.105 m -> 110.5 cm / 43.5039... in) — see PRES-07.
HEIGHT_METERS = 1.105


def _formatter(unit: HeightUnit) -> Formatter:
    context = PresentationContext(
        locale=PlainLocaleFormatter(), translator=EnglishTranslator(), unit=unit,
        time_style=TimeStyle.HOUR_AND_MINUTE_24)
    return Formatter(context)


@pytest.mark.parametrize(
    "unit,expected",
    [(HeightUnit.CENTIMETRES, 110.5), (HeightUnit.INCHES, 43.503937007874015)],
)
def test_to_display_height(unit, expected):
    assert _formatter(unit).to_display_height(HEIGHT_METERS) == pytest.approx(expected)


@pytest.mark.parametrize(
    "unit,expected_decimals", [(HeightUnit.CENTIMETRES, 1), (HeightUnit.INCHES, 2)],
)
def test_height_decimals(unit, expected_decimals):
    assert _formatter(unit).height_decimals() == expected_decimals


@pytest.mark.parametrize(
    "unit,expected_step", [(HeightUnit.CENTIMETRES, 0.5), (HeightUnit.INCHES, 0.25)],
)
def test_height_step(unit, expected_step):
    assert _formatter(unit).height_step() == expected_step


@pytest.mark.parametrize(
    "unit,expected", [(HeightUnit.CENTIMETRES, "110.5"), (HeightUnit.INCHES, "43.50")],
)
def test_height_value_renders_through_the_locale(unit, expected):
    assert _formatter(unit).height_value(HEIGHT_METERS) == expected


def test_height_value_trims_a_whole_number():
    assert _formatter(HeightUnit.CENTIMETRES).height_value(1.20, trim=True) == "120"


def test_from_display_height_is_the_inverse():
    formatter = _formatter(HeightUnit.INCHES)
    display = formatter.to_display_height(HEIGHT_METERS)
    assert formatter.from_display_height(display) == pytest.approx(HEIGHT_METERS)


def test_unit_property_reads_the_injected_context():
    assert _formatter(HeightUnit.INCHES).unit == HeightUnit.INCHES
