"""``Formatter.duration_verbose`` -- the merged PRES-03/D-02 duration policy.

Built against the real :class:`EnglishTranslator` (not the markers in
``presentation_fakes``), the same choice ``test_formatter_heights.py`` makes:
these methods produce rendered English text, and a marker-only test could
not distinguish "1 hour" from a policy bug that happened to also produce a
string.
"""

from __future__ import annotations

import pytest

from idasen_companion.core.presentation.english import EnglishTranslator
from idasen_companion.core.presentation.formatter import (
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.plain_locale import PlainLocaleFormatter
from idasen_companion.core.units import HeightUnit


def _formatter() -> Formatter:
    context = PresentationContext(
        locale=PlainLocaleFormatter(), translator=EnglishTranslator(),
        unit=HeightUnit.CENTIMETRES)
    return Formatter(context)


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "1 second"),        # floored to at least one, never "0 seconds"
        (1, "1 second"),
        (2, "2 seconds"),
        (30, "30 seconds"),
        (59, "59 seconds"),
    ],
)
def test_below_the_minute_threshold_renders_seconds_only(seconds, expected):
    assert _formatter().duration_verbose(seconds) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (60, "1 minute"),
        (90, "1 minute"),           # D-02's measured range: floor, not round
        (120, "2 minutes"),
        (3599, "59 minutes"),        # D-02's corrected range: still sub-hour
    ],
)
def test_sub_hour_durations_render_minutes_only(seconds, expected):
    assert _formatter().duration_verbose(seconds) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (3600, "1 hour"),
        (7200, "2 hours"),
    ],
)
def test_whole_hours_render_hours_only(seconds, expected):
    assert _formatter().duration_verbose(seconds) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (3660, "1 hour 1 minute"),
        (3900, "1 hour 5 minutes"),   # D-02's own worked example
        (7260, "2 hours 1 minute"),
        (7500, "2 hours 5 minutes"),
    ],
)
def test_hours_and_minutes_nest_two_whole_messages(seconds, expected):
    assert _formatter().duration_verbose(seconds) == expected
