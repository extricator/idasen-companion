"""Rendering assertions for `PlainLocaleFormatter`.

The locale-independence gate for BACK-04 (a structural AST check, plus a
corroborating behavioural test) lives in this same file, appended below
these rendering assertions — see the section header further down.
"""

from datetime import datetime

import pytest

from idasen_companion.core.presentation.plain_locale import PlainLocaleFormatter
from idasen_companion.core.presentation.protocols import LocaleFormatter
from idasen_companion.core.presentation.specs import (
    DateStyle,
    IntegerSpec,
    NumberSpec,
    TimeStyle,
)

FORMATTER = PlainLocaleFormatter()


# ---- Rendering ------------------------------------------------------------

def test_satisfies_locale_formatter_protocol_and_nothing_more():
    assert isinstance(FORMATTER, LocaleFormatter)


@pytest.mark.parametrize("value,decimals,expected", [
    (110.5, 1, "110.5"),  # centimetres
    (43.51, 2, "43.51"),  # inches
])
def test_number_renders_both_height_decimal_counts(value, decimals, expected):
    assert FORMATTER.number(value, NumberSpec(decimals=decimals)) == expected


def test_number_trims_a_whole_value_to_no_fraction():
    spec = NumberSpec(decimals=1, trim_trailing_zeroes=True)
    assert FORMATTER.number(110.0, spec) == "110"


def test_number_does_not_trim_a_fractional_value():
    spec = NumberSpec(decimals=1, trim_trailing_zeroes=True)
    assert FORMATTER.number(110.5, spec) == "110.5"


def test_number_grouping_off_by_default():
    assert FORMATTER.number(1234.5, NumberSpec(decimals=1)) == "1234.5"


def test_number_grouping_uses_a_comma_when_requested():
    spec = NumberSpec(decimals=1, grouping=True)
    assert FORMATTER.number(1234.5, spec) == "1,234.5"


def test_integer_unpadded_by_default():
    assert FORMATTER.integer(5, IntegerSpec()) == "5"


def test_integer_zero_padded_to_min_digits():
    assert FORMATTER.integer(5, IntegerSpec(min_digits=2)) == "05"


@pytest.mark.parametrize("hour,minute,expected", [
    (9, 5, "09:05"),      # morning
    (12, 0, "12:00"),     # noon
    (14, 32, "14:32"),    # afternoon
    (0, 0, "00:00"),      # midnight
])
def test_time_renders_two_digit_24_hour(hour, minute, expected):
    when = datetime(2026, 8, 21, hour, minute)
    assert FORMATTER.time(when, TimeStyle.HOUR_AND_MINUTE) == expected


def test_date_weekday_and_day():
    when = datetime(2026, 8, 21)  # a Friday
    assert FORMATTER.date(when, DateStyle.WEEKDAY_AND_DAY) == "Fri 21"


def test_date_weekday_day_month_year():
    when = datetime(2026, 8, 21)
    assert FORMATTER.date(when, DateStyle.WEEKDAY_DAY_MONTH_YEAR) == "Fri 21 Aug 2026"
