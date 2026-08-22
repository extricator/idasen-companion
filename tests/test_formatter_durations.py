"""``Formatter.duration_verbose``/``duration``/``duration_hm`` -- the merged
PRES-03/D-01/D-02 duration policy.

Built against the real :class:`EnglishTranslator` (not the markers in
``presentation_fakes``), the same choice ``test_formatter_heights.py`` makes:
these methods produce rendered English text, and a marker-only test could
not distinguish "1 hour" from a policy bug that happened to also produce a
string.
"""

from __future__ import annotations

import pytest

from idasen_companion.core.presentation.english import (
    EnglishTranslator, format_duration_human,
)
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


# ---- duration / duration_hm / format_duration_human (D-01) ----------------
#
# The compact PRES-03 policy: one threshold, one decomposition, one padding
# rule, shared by every compact renderer -- the journal (format_duration_human)
# and the Activity Log and the tray (Formatter.duration/duration_hm). The
# boundary table below walks the seam at every point that can disagree: just
# under and at the sub-minute threshold, just under and at the hour mark, and
# a value that exercises both padded minutes and a two-digit hour count.

_BOUNDARY_TABLE = (
    (0, "0s", "0m"),
    (1, "1s", "0m"),
    (30, "30s", "0m"),
    (59, "59s", "0m"),
    (60, "1m", "1m"),
    (61, "1m", "1m"),
    (90, "1m", "1m"),
    (2700, "45m", "45m"),
    (3600, "1h 00m", "1h 00m"),
    (3900, "1h 05m", "1h 05m"),
    (7325, "2h 02m", "2h 02m"),
)


@pytest.mark.parametrize("seconds,duration_expected,duration_hm_expected",
                          _BOUNDARY_TABLE)
def test_duration_boundary_table(seconds, duration_expected, duration_hm_expected):
    fmt = _formatter()
    assert fmt.duration(seconds) == duration_expected
    assert fmt.duration_hm(seconds) == duration_hm_expected


@pytest.mark.parametrize("seconds,duration_expected,_duration_hm_expected",
                          _BOUNDARY_TABLE)
def test_format_duration_human_matches_duration(
        seconds, duration_expected, _duration_hm_expected):
    # format_duration_human is Formatter.duration through the same
    # PlainLocaleFormatter/EnglishTranslator pair this file's own
    # _formatter() builds -- the journal and this test's Formatter must
    # never answer differently for the same input.
    assert format_duration_human(seconds) == duration_expected


def test_format_duration_human_none_is_not_available():
    assert format_duration_human(None) == "N/A"


def test_duration_hm_clamps_a_negative_delay_to_zero():
    # fmt_hm(-5) was a live bug: int(-5) // 60 == -1 and divmod(-1, 60) ==
    # (-1, 59), so it rendered "-1h 59m". decompose_hms clamps negatives to
    # zero, so duration_hm(-5) is "0m" -- fixed by this migration, pinned
    # here so it stays fixed.
    assert _formatter().duration_hm(-5) == "0m"


def test_duration_clamps_a_negative_sub_minute_delay_to_zero():
    # duration_hm(-5) clamped through decompose_hms from the first commit of
    # this migration, but duration()'s own sub-minute branch never reached
    # decompose_hms and so kept the sign: it rendered "-5s", and journald read
    # it that way through format_duration_human. One policy has to mean both
    # branches, not the one that happens to delegate.
    assert _formatter().duration(-5) == "0s"


def test_format_duration_human_clamps_a_negative_delay_to_zero():
    # The journal's renderer reads through Formatter.duration, so the clamp
    # above is what keeps a negative out of a greppable log line.
    assert format_duration_human(-5) == "0s"


def test_duration_floors_rather_than_rounds_a_sub_minute_value():
    # fmt_duration used f"{seconds:.0f}", which rounds: fmt_duration(45.6)
    # was "46s". decompose_hms's shared policy floors instead.
    assert _formatter().duration(45.6) == "45s"
