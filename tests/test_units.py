"""Pure, Qt-free tests for :mod:`idasen_companion.core.units`.

No PySide6 import anywhere in this module or in what it imports — that
absence is itself part of what the module promises.
"""

import pytest

from idasen_companion.core.units import (
    METRES_PER_INCH,
    HeightUnit,
    UnitSetting,
    from_display_height,
    height_decimals,
    height_step,
    resolve_height_unit,
    territory_of,
    to_display_height,
)


# Whether PySide6 stays out of sys.modules on this path is checked with a
# fresh `python -I` invocation (see 12-03-SUMMARY.md), not as a test here:
# this suite's own conftest.py conditionally imports PySide6 in an autouse
# fixture, so by the time any test body runs the process may already have
# loaded it regardless of what this module imports.


# ---- resolving the setting ------------------------------------------------


@pytest.mark.parametrize("setting", [UnitSetting.CENTIMETRES, UnitSetting.INCHES])
@pytest.mark.parametrize("language", ["en_US", "es_ES"])
def test_an_explicit_unit_ignores_language_and_environment(setting, language):
    unit = resolve_height_unit(setting, language=language, environ={"LANG": "es_ES"})
    assert unit.value == setting.value


def test_system_with_language_en_us_resolves_to_inches():
    assert resolve_height_unit(
        UnitSetting.SYSTEM, language="en_US", environ={}) == HeightUnit.INCHES


def test_system_with_language_es_es_resolves_to_centimetres():
    assert resolve_height_unit(
        UnitSetting.SYSTEM, language="es_ES", environ={}) == HeightUnit.CENTIMETRES


def test_system_with_language_en_gb_resolves_to_centimetres():
    # Qt calls the UK imperial; a UK desk is sold in centimetres regardless.
    assert resolve_height_unit(
        UnitSetting.SYSTEM, language="en_GB", environ={}) == HeightUnit.CENTIMETRES


@pytest.mark.parametrize(("environ", "expected"), [
    ({"LC_ALL": "en_US.UTF-8"}, HeightUnit.INCHES),
    ({"LC_MEASUREMENT": "en_US"}, HeightUnit.INCHES),
    ({"LANG": "en_US"}, HeightUnit.INCHES),
    ({"LANGUAGE": "en_US"}, HeightUnit.INCHES),
    ({"LC_ALL": "es_ES", "LANG": "en_US"}, HeightUnit.CENTIMETRES),
    ({"LC_MEASUREMENT": "es_ES", "LANG": "en_US"}, HeightUnit.CENTIMETRES),
    ({"LANG": "es_ES", "LANGUAGE": "en_US"}, HeightUnit.CENTIMETRES),
])
def test_system_with_language_system_falls_through_the_environment_in_order(
        environ, expected):
    assert resolve_height_unit(
        UnitSetting.SYSTEM, language="system", environ=environ) == expected


@pytest.mark.parametrize("language", ["", "system", "C", "es"])
def test_an_unparseable_language_falls_through_to_the_environment(language):
    assert resolve_height_unit(
        UnitSetting.SYSTEM, language=language,
        environ={"LANG": "en_US"}) == HeightUnit.INCHES


def test_an_absent_or_unparseable_environment_resolves_to_centimetres():
    assert resolve_height_unit(
        UnitSetting.SYSTEM, language="system", environ={}) == HeightUnit.CENTIMETRES
    assert resolve_height_unit(
        UnitSetting.SYSTEM, language="system",
        environ={"LANG": "C"}) == HeightUnit.CENTIMETRES


# ---- the conversion itself ------------------------------------------------


@pytest.mark.parametrize("unit", [HeightUnit.CENTIMETRES, HeightUnit.INCHES])
@pytest.mark.parametrize("meters", [0.62, 0.75, 1.105, 1.27])
def test_a_displayed_height_round_trips_within_a_micrometre(unit, meters):
    shown = to_display_height(meters, unit)
    back = from_display_height(shown, unit)
    assert back == pytest.approx(meters, abs=1e-6)


def test_centimetres_convert_as_before():
    assert to_display_height(1.105, HeightUnit.CENTIMETRES) == pytest.approx(110.5)
    assert from_display_height(110.5, HeightUnit.CENTIMETRES) == pytest.approx(1.105)


def test_inches_convert_through_the_named_constant():
    assert to_display_height(1.105, HeightUnit.INCHES) == pytest.approx(
        1.105 / METRES_PER_INCH)
    assert from_display_height(43.5, HeightUnit.INCHES) == pytest.approx(
        43.5 * METRES_PER_INCH)


def test_inches_carry_a_second_decimal():
    assert height_decimals(HeightUnit.INCHES) == 2
    assert height_decimals(HeightUnit.CENTIMETRES) == 1


def test_height_step_differs_by_unit():
    assert height_step(HeightUnit.INCHES) == 0.25
    assert height_step(HeightUnit.CENTIMETRES) == 0.5


# ---- LANGUAGE's colon list ------------------------------------------------

@pytest.mark.parametrize(("value", "expected"), [
    ("es_ES:es", "ES"),
    ("en_US:en", "US"),
    ("pt_BR:pt_PT:pt", "BR"),
    # A first entry naming no territory still answers None rather than
    # searching the rest of the list: the list is a *priority* order, so a
    # later entry is a fallback the user ranked lower, not a better answer.
    ("es:es_ES", None),
    ("C", None),
    ("", None),
])
def test_territory_of_reads_the_first_entry_of_a_gettext_priority_list(
        value, expected):
    """``LANGUAGE`` is a colon list, and both resolvers consult it.

    Without the colon split ``"es_ES:es"`` partitions to ``"ES:es"`` — five
    characters, so no territory — and the LANGUAGE step of the clock and
    height policies was inert for the only form the variable normally takes.
    """
    assert territory_of(value) == expected
