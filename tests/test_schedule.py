from datetime import datetime

from idasen_companion.core.config import ScheduleConfig, VALID_DAYS
from idasen_companion.core.schedule import is_schedule_active

# 2026-07-17 is a Friday, 2026-07-18 a Saturday.
FRI = datetime(2026, 7, 17)
SAT = datetime(2026, 7, 18)


def cfg(**kw):
    return ScheduleConfig(enabled=True, **kw)


def test_disabled_schedule_is_always_active():
    assert is_schedule_active(ScheduleConfig(enabled=False), SAT.replace(hour=3))


def test_inside_window():
    c = cfg(days=["mon", "tue", "wed", "thu", "fri"], start="09:00", end="17:00")
    assert is_schedule_active(c, FRI.replace(hour=9, minute=0))
    assert is_schedule_active(c, FRI.replace(hour=12, minute=30))
    assert is_schedule_active(c, FRI.replace(hour=16, minute=59))


def test_outside_window_same_day():
    c = cfg(days=["fri"], start="09:00", end="17:00")
    assert not is_schedule_active(c, FRI.replace(hour=8, minute=59))
    assert not is_schedule_active(c, FRI.replace(hour=17, minute=0))  # end exclusive
    assert not is_schedule_active(c, FRI.replace(hour=23, minute=0))


def test_day_not_enabled():
    c = cfg(days=["mon", "tue", "wed", "thu", "fri"], start="09:00", end="17:00")
    assert not is_schedule_active(c, SAT.replace(hour=12))


def test_overnight_window_belongs_to_start_day():
    c = cfg(days=["fri"], start="22:00", end="02:00")
    assert is_schedule_active(c, FRI.replace(hour=23))
    assert is_schedule_active(c, SAT.replace(hour=1))  # spillover from Friday
    assert not is_schedule_active(c, SAT.replace(hour=3))
    assert not is_schedule_active(c, SAT.replace(hour=23))  # Saturday not enabled
    assert not is_schedule_active(c, FRI.replace(hour=21))


# ----- boundaries, exactly on the minute -----

def test_the_window_is_start_inclusive_and_end_exclusive():
    c = cfg(days=["fri"], start="09:00", end="17:00")
    assert is_schedule_active(c, FRI.replace(hour=9, minute=0))
    assert not is_schedule_active(c, FRI.replace(hour=8, minute=59))
    assert not is_schedule_active(c, FRI.replace(hour=17, minute=0))
    assert is_schedule_active(c, FRI.replace(hour=16, minute=59))


def test_overnight_boundaries_are_exact():
    # The existing overnight test stays an hour clear of every edge, so both
    # `>=` -> `>` and `<` -> `<=` survived it.
    c = cfg(days=["fri"], start="22:00", end="02:00")
    assert is_schedule_active(c, FRI.replace(hour=22, minute=0))
    assert not is_schedule_active(c, FRI.replace(hour=21, minute=59))
    assert is_schedule_active(c, SAT.replace(hour=1, minute=59))
    assert not is_schedule_active(c, SAT.replace(hour=2, minute=0))


# ----- the two shapes the module documents but nothing exercised -----

def test_start_equal_to_end_is_a_full_day_from_start():
    """Documented at the top of schedule.py as "a full 24h window from start",
    and reachable: _validate only checks the HH:MM format."""
    c = cfg(days=["fri"], start="09:00", end="09:00")
    assert is_schedule_active(c, FRI.replace(hour=9, minute=0))
    assert is_schedule_active(c, FRI.replace(hour=23, minute=59))
    assert is_schedule_active(c, SAT.replace(hour=8, minute=59))  # spillover
    assert not is_schedule_active(c, SAT.replace(hour=9, minute=0))
    assert not is_schedule_active(c, FRI.replace(hour=8, minute=59))


def test_no_days_selected_is_never_active():
    """Accepted by validation, so it has to mean something definite. It leaves
    the machine permanently OUT_OF_SCHEDULE — which is what the GUI's
    "no days" string exists to render."""
    c = cfg(days=[], start="09:00", end="17:00")
    for hour in range(24):
        assert not is_schedule_active(c, FRI.replace(hour=hour))
        assert not is_schedule_active(c, SAT.replace(hour=hour))


def test_every_day_selected_with_an_overnight_window_is_always_active():
    c = cfg(days=list(VALID_DAYS), start="22:00", end="02:00")
    assert is_schedule_active(c, FRI.replace(hour=23))
    assert is_schedule_active(c, SAT.replace(hour=1))
    assert not is_schedule_active(c, SAT.replace(hour=12))


# ----- DST (conftest pins TZ=America/New_York, which observes it) -----

def test_a_spring_forward_gap_inside_the_window_stays_active():
    """2026-03-08 02:00 EST jumps straight to 03:00 EDT — there is no 02:30
    that day. The schedule compares naive local wall-clock minutes, which is
    the right design (the user's "09:00" is their 09:00, whatever the offset),
    and the property that matters is that the missing hour does not punch a
    hole in an otherwise-active window.
    """
    c = cfg(days=["sun"], start="01:00", end="23:00")
    sunday = datetime(2026, 3, 8)
    assert is_schedule_active(c, sunday.replace(hour=1, minute=30))   # EST
    assert is_schedule_active(c, sunday.replace(hour=3, minute=30))   # EDT
    assert is_schedule_active(c, sunday.replace(hour=12))


def test_a_fall_back_repeated_hour_is_active_both_times():
    """2026-11-01 01:00-02:00 happens twice. Both are inside a window that
    contains 01:30, and naive comparison treats them identically — which is
    what the user means by "runs from 01:00".
    """
    c = cfg(days=["sun"], start="01:00", end="23:00")
    sunday = datetime(2026, 11, 1)
    assert is_schedule_active(c, sunday.replace(hour=1, minute=30))
    assert is_schedule_active(c, sunday.replace(hour=2, minute=30))


def test_an_overnight_window_across_spring_forward_still_spills_over():
    c = cfg(days=["sat"], start="22:00", end="04:00")
    assert is_schedule_active(c, datetime(2026, 3, 7, 23, 0))   # Sat, EST
    assert is_schedule_active(c, datetime(2026, 3, 8, 3, 30))   # Sun, EDT
    assert not is_schedule_active(c, datetime(2026, 3, 8, 4, 0))
