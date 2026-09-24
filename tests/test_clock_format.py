"""Babel-backed resolution of the independent hour-cycle preference."""

import pytest

from idasen_companion.core.display_prefs import ClockSetting, resolve_clock_style
from idasen_companion.core.locale_profile import TimeStyle

_TWELVE = TimeStyle.HOUR_AND_MINUTE_12
_TWENTY_FOUR = TimeStyle.HOUR_AND_MINUTE_24


@pytest.mark.parametrize(("setting", "expected"), [
    (ClockSetting.TWELVE, _TWELVE),
    (ClockSetting.TWENTY_FOUR, _TWENTY_FOUR),
])
@pytest.mark.parametrize("language", ["system", "en_US", "es_ES"])
def test_explicit_setting_ignores_language_and_environment(
        setting, expected, language):
    assert resolve_clock_style(
        setting, language=language,
        environ={"LC_TIME": "es_ES", "LANG": "en_US"}) is expected


@pytest.mark.parametrize(("environ", "expected"), [
    ({"LC_TIME": "en_US.UTF-8"}, _TWELVE),
    ({"LC_TIME": "es_ES.UTF-8"}, _TWENTY_FOUR),
    ({"LANG": "en_US.UTF-8"}, _TWELVE),
    ({"LANG": "en_GB.UTF-8"}, _TWENTY_FOUR),
    ({"LC_ALL": "en_US", "LC_TIME": "es_ES"}, _TWELVE),
    ({"LC_TIME": "C", "LANG": "en_US"}, _TWENTY_FOUR),
    ({}, _TWENTY_FOUR),
])
def test_system_uses_babel_for_the_system_time_locale(environ, expected):
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language="system", environ=environ) is expected


@pytest.mark.parametrize("language", ["en_US", "es_ES", "ar_EG"])
def test_selected_language_never_changes_system_hour_cycle(language):
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language=language,
        environ={"LC_TIME": "en_US"}) is _TWELVE
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language=language,
        environ={"LC_TIME": "es_ES"}) is _TWENTY_FOUR


def test_language_priority_list_is_not_a_time_locale_input():
    assert resolve_clock_style(
        ClockSetting.SYSTEM, language="system",
        environ={"LANGUAGE": "en_US:en"}) is _TWENTY_FOUR
