"""Babel 2.18 contract for the application's one locale value engine."""

from datetime import datetime

import pytest

from idasen_companion.core.locale_profile import (
    DateStyle, LocaleProfile, TimeStyle, resolve_app_locale,
)


@pytest.mark.parametrize(("locale_name", "decimal", "integer", "percent"), [
    ("en_US", "1,234.5", "12,345", "38%"),
    ("es_ES", "1.234,5", "12.345", "38\u00a0%"),
    # Babel 2.18 uses Arabic separators for ar_EG's default numbering system,
    # but currently leaves the digit glyphs Latin. Pin what it does, not an
    # assumption that selecting an Arabic locale substitutes native digits.
    ("ar_EG", "1٬234٫5", "12٬345", "38%"),
])
def test_number_integer_and_percent_matrix(
        locale_name, decimal, integer, percent):
    profile = LocaleProfile(locale_name)
    assert profile.number(1234.5, decimals=1, grouping=True) == decimal
    assert profile.integer(12345, grouping=True) == integer
    assert profile.percent(0.375) == percent


@pytest.mark.parametrize(("locale_name", "date_text", "time_text", "unit"), [
    ("en_US", "Mon 17 Aug 2026", "2:32:05 PM", "110.5 cm"),
    ("es_ES", "lun 17 ago 2026", "2:32:05 p.\u202fm.", "110,5 cm"),
    ("ar_EG", "الاثنين 17 أغسطس 2026", "2:32:05 م", "110٫5 سم"),
])
def test_date_time_and_unit_matrix(locale_name, date_text, time_text, unit):
    profile = LocaleProfile(locale_name)
    moment = datetime(2026, 8, 17, 14, 32, 5)
    assert profile.date(
        moment, DateStyle.WEEKDAY_DAY_MONTH_YEAR) == date_text
    assert profile.time(
        moment, TimeStyle.HOUR_MINUTE_AND_SECOND_12) == time_text
    assert profile.unit(
        110.5, "length-centimeter", decimals=1) == unit


def test_arabic_plural_categories_come_from_cldr():
    profile = LocaleProfile("ar_EG")
    assert [profile.plural_category(value) for value in (0, 1, 2, 3, 11, 100)] == [
        "zero", "one", "two", "few", "many", "other"]


def test_app_locale_resolution_is_explicit_and_deterministic():
    assert resolve_app_locale("es", {"LANG": "en_US"}) == "es"
    assert resolve_app_locale("system", {"LC_ALL": "es_ES.UTF-8"}) == "es_ES"
    assert resolve_app_locale("system", {"LANG": "C.UTF-8"}) == "en_US"
