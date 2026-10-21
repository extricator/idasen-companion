"""Operational monotonic readings retain numbers and their clock domain."""

from dataclasses import FrozenInstanceError

import pytest

from idasen_companion.core.clocks import MonotonicInstant, WallInstant
from idasen_companion.core.durations import Duration
from idasen_companion.core.lengths import Length


def test_monotonic_readings_preserve_numbers_and_signed_differences():
    huge = 10**400
    assert type(MonotonicInstant(huge).monotonic_seconds) is int
    assert MonotonicInstant(huge).monotonic_seconds == huge
    assert type(MonotonicInstant(1.25).monotonic_seconds) is float
    old = MonotonicInstant(2**30)
    later = MonotonicInstant(2**30 + 2**-22)
    assert later - old == Duration(2**-22)
    assert old - later == Duration(-2**-22)
    assert MonotonicInstant(huge + 1) - MonotonicInstant(huge) == Duration(1)
    with pytest.raises(FrozenInstanceError):
        old.monotonic_seconds = 0


def test_monotonic_offsets_ordering_and_zero_semantics():
    zero, early, late = MonotonicInstant(0), MonotonicInstant(1), MonotonicInstant(2)
    assert early + Duration(1) == late
    assert early - Duration(2) == MonotonicInstant(-1)
    assert early + Duration(0) == early - Duration(0) == early
    assert zero < early <= late and late > early >= zero
    assert early <= MonotonicInstant(1) and early >= MonotonicInstant(1)
    assert not zero and bool(MonotonicInstant(-1))
    assert len({MonotonicInstant(1), MonotonicInstant(1.0)}) == 1
    assert early != 1 and early != Duration(1) and early != WallInstant(1)


def test_monotonic_rejects_raw_offsets_and_other_domains():
    instant, wall = MonotonicInstant(1), WallInstant(1)
    for operation in (
        lambda: instant + 1, lambda: 1 + instant,
        lambda: instant - 1, lambda: 1 - instant,
        lambda: instant + instant, lambda: Duration(1) - instant,
        lambda: instant - Length(1), lambda: instant + Length(1),
        lambda: instant < 1, lambda: instant <= Duration(1),
        lambda: instant > Length(1), lambda: instant >= 1,
        lambda: instant - wall, lambda: wall - instant,
        lambda: instant < wall, lambda: wall >= instant,
    ):
        with pytest.raises(TypeError):
            operation()
