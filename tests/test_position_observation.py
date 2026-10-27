# SPDX-License-Identifier: GPL-3.0-or-later
"""Finite sampled continuity uses typed clocks and explicit unknownness."""

import pytest

from idasen_companion.core.clocks import MonotonicInstant, WallInstant
from idasen_companion.core.durations import Duration
from idasen_companion.core.machine import DeskState, PositionObservationTracker


def test_zero_renewal_and_changed_position_have_distinct_starts():
    tracker = PositionObservationTracker(Duration(390))
    tracker.observe(DeskState.SITTING, WallInstant(0), MonotonicInstant(0))
    assert tracker.snapshot(WallInstant(0), MonotonicInstant(0)).started == WallInstant(0)
    tracker.observe(DeskState.SITTING, WallInstant(200), MonotonicInstant(200))
    renewed = tracker.snapshot(WallInstant(300), MonotonicInstant(300))
    assert renewed.elapsed == Duration(300)
    assert renewed.remaining == Duration(290)
    tracker.observe(DeskState.STANDING, WallInstant(301), MonotonicInstant(301))
    assert tracker.snapshot(WallInstant(301), MonotonicInstant(301)).elapsed == Duration(0)


@pytest.mark.parametrize("age,known", [(389.999, True), (390, False), (390.001, False)])
def test_lease_deadline_is_exclusive(age, known):
    tracker = PositionObservationTracker(Duration(390))
    tracker.observe(DeskState.SITTING, WallInstant(100), MonotonicInstant(0))
    # Wall clock stays within the independent strict jump boundary.
    assert (tracker.snapshot(WallInstant(101), MonotonicInstant(age)).position
            is not None) is known


def test_expired_same_position_restarts_and_unknown_breaks_chain():
    tracker = PositionObservationTracker(Duration(10))
    tracker.observe(DeskState.SITTING, WallInstant(1), MonotonicInstant(1))
    tracker.observe(DeskState.SITTING, WallInstant(11), MonotonicInstant(11))
    assert tracker.snapshot(WallInstant(11), MonotonicInstant(11)).started == WallInstant(11)
    tracker.observe(None, WallInstant(12), MonotonicInstant(12))
    assert tracker.snapshot(WallInstant(12), MonotonicInstant(12)).position is None
    tracker.observe(DeskState.SITTING, WallInstant(13), MonotonicInstant(13))
    assert tracker.snapshot(WallInstant(13), MonotonicInstant(13)).elapsed == Duration(0)


@pytest.mark.parametrize("wall,mono", [(-1, 1), (301, 1), (1, -1)])
def test_discontinuous_clocks_invalidate(wall, mono):
    tracker = PositionObservationTracker(Duration(390))
    tracker.observe(DeskState.SITTING, WallInstant(0), MonotonicInstant(0))
    assert tracker.snapshot(WallInstant(wall), MonotonicInstant(mono)).position is None
