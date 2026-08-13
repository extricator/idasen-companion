import pytest

from idasen_companion.core.durations import (
    format_duration_compact,
    format_duration_human,
    parse_duration,
)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("45m", 2700),
        ("25m", 1500),
        ("1h", 3600),
        ("1h30m", 5400),
        ("90s", 90),
        ("1h5m30s", 3930),
        ("10M", 600),  # case-insensitive, like the reference script
        ("1h 30m", 5400),  # tolerate spaces between groups
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


def test_format_human_matches_reference_style():
    assert format_duration_human(None) == "N/A"
    assert format_duration_human(30) == "30 seconds"
    assert format_duration_human(2700) == "45.0 minutes"
