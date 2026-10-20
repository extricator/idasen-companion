import pytest

from idasen_companion.core import durations
from idasen_companion.core.config import VALID_UNITS
from idasen_companion.core.durations import (
    DurationParts,
    decompose_hms,
    format_duration_compact,
    parse_duration,
)
from idasen_companion.core.presentation import format_duration_human
from idasen_companion.core.display_prefs import UnitSetting


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("45m", 2700),
        ("25m", 1500),
        ("1h", 3600),
        ("1h30m", 5400),
        ("90s", 90),
        ("1h5m30s", 3930),
        ("10M", 600),
        ("1h 30m", 5400),
    ],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "45", "m45", "4.5m"])
def test_parse_duration_invalid(text):
    with pytest.raises(ValueError):
        parse_duration(text)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (2700, "45m"),
        (5400, "1h30m"),
        (90, "1m30s"),
        (30, "30s"),
        (0, "0s"),
        (3661, "1h1m1s"),
    ],
)
def test_format_compact(seconds, text):
    assert format_duration_compact(seconds) == text


def test_compact_round_trip():
    for seconds in (1, 59, 60, 61, 3599, 3600, 3661, 2700, 86400):
        assert parse_duration(format_duration_compact(seconds)) == seconds


def test_format_human_preserves_the_released_journal_shape():
    assert format_duration_human(None) == "N/A"
    assert format_duration_human(30) == "30 seconds"
    assert format_duration_human(45.6) == "46 seconds"
    assert format_duration_human(90) == "1.5 minutes"
    assert format_duration_human(3900) == "65.0 minutes"


@pytest.mark.parametrize(
    ("seconds", "parts"),
    [
        (45, DurationParts(hours=0, minutes=0, seconds=45)),
        (59, DurationParts(hours=0, minutes=0, seconds=59)),
        (60, DurationParts(hours=0, minutes=1, seconds=0)),
        (125, DurationParts(hours=0, minutes=2, seconds=5)),
        (3600, DurationParts(hours=1, minutes=0, seconds=0)),
        (3900, DurationParts(hours=1, minutes=5, seconds=0)),
        (-5, DurationParts(hours=0, minutes=0, seconds=0)),
    ],
)
def test_decompose_hms(seconds, parts):
    assert decompose_hms(seconds) == parts


def test_valid_units_still_reads_the_three_strings_in_order():
    assert VALID_UNITS == ("system", "cm", "in")
    for member in UnitSetting:
        assert member.value in VALID_UNITS


def test_duration_keeps_number_kind_and_exposes_only_typed_arithmetic():
    duration_type = getattr(durations, "Duration", None)
    assert duration_type is not None

    giant = duration_type.from_seconds(2**53 + 1)
    fractional = duration_type.from_seconds(300 + 2**-22)
    negative = duration_type.from_seconds(-2)
    zero = duration_type.from_seconds(0)

    assert giant.seconds == 2**53 + 1
    assert isinstance(giant.seconds, int)
    assert fractional.seconds == 300 + 2**-22
    assert isinstance(fractional.seconds, float)
    assert not zero
    assert negative
    assert zero != 0

    assert (giant + duration_type.from_seconds(1)).seconds == 2**53 + 2
    assert (duration_type.from_seconds(5) - duration_type.from_seconds(2)).seconds == 3
    assert (duration_type.from_seconds(2) * 1.5).seconds == 3.0
    assert (duration_type.from_seconds(6) / 2).seconds == 3.0
    assert duration_type.from_seconds(6) / duration_type.from_seconds(2) == 3.0
    assert abs(duration_type.from_seconds(-2)).seconds == 2

    with pytest.raises(TypeError):
        _ = duration_type.from_seconds(1) + 1
    with pytest.raises(TypeError):
        _ = 1 + duration_type.from_seconds(1)
    with pytest.raises(TypeError):
        _ = duration_type.from_seconds(1) < 2
    with pytest.raises(TypeError):
        _ = 2 < duration_type.from_seconds(1)
    assert duration_type.from_seconds(1) != 1
    assert duration_type.from_seconds(1) != object()
