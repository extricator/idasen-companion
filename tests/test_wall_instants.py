"""The operational wall-clock value and its deliberately narrow operators."""

from dataclasses import FrozenInstanceError

import pytest

from idasen_companion.core.clocks import WallInstant
from idasen_companion.core.durations import Duration
from idasen_companion.core.lengths import Length


def test_wall_readings_preserve_numbers_and_signed_differences():
    huge = 10**400
    assert type(WallInstant(huge).epoch_seconds) is int
    assert WallInstant(huge).epoch_seconds == huge
    assert type(WallInstant(1.25).epoch_seconds) is float
    old = WallInstant(2**30)
    later = WallInstant(2**30 + 2**-22)
    assert later - old == Duration(2**-22)
    assert old - later == Duration(-2**-22)
    assert WallInstant(huge + 1) - WallInstant(huge) == Duration(1)
    with pytest.raises(FrozenInstanceError):
        old.epoch_seconds = 0


def test_wall_offsets_ordering_and_zero_semantics():
    zero, early, late = WallInstant(0), WallInstant(1), WallInstant(2)
    assert early + Duration(1) == late
    assert early - Duration(2) == WallInstant(-1)
    assert zero < early <= late and late > early >= zero
    assert not zero and bool(WallInstant(-1))
    assert len({WallInstant(1), WallInstant(1.0)}) == 1
    assert early != 1 and early != Duration(1) and early != Length(1)


def test_wall_rejects_raw_offsets_and_other_domains():
    instant = WallInstant(1)
    for operation in (
        lambda: instant + 1, lambda: 1 + instant,
        lambda: instant - 1, lambda: 1 - instant,
        lambda: instant + instant, lambda: Duration(1) - instant,
        lambda: instant - Length(1), lambda: instant + Length(1),
        lambda: instant < 1, lambda: instant <= Duration(1),
        lambda: instant > Length(1), lambda: instant >= 1,
    ):
        with pytest.raises(TypeError):
            operation()
