"""Pure, Qt-free tests for :mod:`idasen_companion.core.clock_format`.

The policy the resolver implements is pinned here, on pure inputs, so CI
guards it forever with no locale installed anywhere and nothing skipped. The
*mechanism* behind the territory set is deliberately revisable — the module
docstring records how it was derived and when — but the answers below are the
contract, and changing one of them is a decision somebody has to make out
loud rather than a diff that slips past.

No PySide6 import anywhere in this module or in what it imports, the same
absence :mod:`tests.test_units` promises for the height resolver.
"""

import pytest

from idasen_companion.core.clock_format import (
    TWELVE_HOUR_TERRITORIES,
    ClockSetting,
    resolve_clock_style,
)
from idasen_companion.core.presentation.specs import TimeStyle

_TWELVE = TimeStyle.HOUR_AND_MINUTE_12
_TWENTY_FOUR = TimeStyle.HOUR_AND_MINUTE_24


# ---- an explicit setting answers for itself -------------------------------


@pytest.mark.parametrize(("setting", "expected"), [
    (ClockSetting.TWELVE, _TWELVE),
    (ClockSetting.TWENTY_FOUR, _TWENTY_FOUR),
])
@pytest.mark.parametrize("language", ["system", "en_US", "es_ES", "en_GB"])
@pytest.mark.parametrize("environ", [
    {},
    {"LC_TIME": "C"},
    {"LC_ALL": "en_US.UTF-8"},
    {"LANG": "es_ES.UTF-8", "LANGUAGE": "en_US"},
])
def test_an_explicit_setting_ignores_language_and_environment(
        setting, expected, language, environ):
    assert resolve_clock_style(
        setting, language=language, environ=environ) is expected


# ---- what "system" reads --------------------------------------------------


def test_nothing_names_a_territory_so_the_answer_is_twenty_four_hour():
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language="system", environ={}) is _TWENTY_FOUR


def test_the_time_locale_wins_over_the_language_environment():
    """The development machine, measured 2026-08-29: LANG names a US locale
    and LC_TIME is set to one that names no territory. LC_TIME is a
    statement about how time should look, so it decides, and it decides
    24-hour — which is what that machine's window already showed."""
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language="system",
        environ={"LC_TIME": "C", "LANG": "en_US.UTF-8"}) is _TWENTY_FOUR


def test_a_us_language_environment_with_no_time_locale_is_twelve_hour():
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language="system",
        environ={"LANG": "en_US.UTF-8"}) is _TWELVE


def test_lc_all_beats_lc_time():
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language="system",
        environ={"LC_ALL": "en_US", "LC_TIME": "es_ES"}) is _TWELVE


def test_the_apps_own_language_answers_when_it_names_a_territory():
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language="en_US", environ={}) is _TWELVE


def test_a_language_naming_no_territory_falls_through_to_the_environment():
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language="es",
        environ={"LANG": "en_US"}) is _TWELVE


def test_the_app_language_beats_the_language_environment():
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language="en_GB",
        environ={"LANG": "en_US"}) is _TWENTY_FOUR


@pytest.mark.parametrize("language", ["en_GB", "es_ES", "de_DE", "fr_FR"])
def test_a_twenty_four_hour_territory_resolves_to_twenty_four_hour(language):
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language=language, environ={}) is _TWENTY_FOUR


@pytest.mark.parametrize("value", ["C", "POSIX", "", "en", "not a locale"])
def test_a_time_locale_naming_no_territory_answers_twenty_four_hour(value):
    """An empty value is the one that keeps searching: POSIX treats an unset
    and an empty variable the same, so it is not the statement a set one is.
    """
    expected = _TWELVE if value == "" else _TWENTY_FOUR
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language="system",
        environ={"LC_TIME": value, "LANG": "en_US"}) is expected


@pytest.mark.parametrize("value", ["C", "en", "not a locale"])
def test_a_language_variable_naming_no_territory_is_passed_over(value):
    """Unlike the time locale, LANG and LANGUAGE select a language rather
    than a time format, so one that names no territory is skipped rather
    than treated as an answer."""
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language="system",
        environ={"LANG": value, "LANGUAGE": "en_US"}) is _TWELVE


# ---- the two types stay two types -----------------------------------------


def test_every_setting_maps_to_a_style_a_backend_can_render():
    """No ``ClockSetting`` member resolves to something outside the style
    enum, and none of them can hand a backend the setting itself."""
    for setting in ClockSetting:
        style = resolve_clock_style(setting, language="system", environ={})
        assert isinstance(style, TimeStyle)
        assert style in (_TWELVE, _TWENTY_FOUR)


def test_the_territory_set_holds_the_two_the_policy_is_written_against():
    assert "US" in TWELVE_HOUR_TERRITORIES
    assert "GB" not in TWELVE_HOUR_TERRITORIES


def test_every_recorded_territory_is_an_upper_case_two_letter_code():
    """The parser hands back an upper-cased two-letter code, so a lower-case
    or three-letter entry here would be dead data that never matches."""
    odd = sorted(code for code in TWELVE_HOUR_TERRITORIES
                 if len(code) != 2 or not code.isalpha() or not code.isupper())
    assert not odd, f"territory code(s) the parser can never produce: {odd}"
