"""The shared height contract and its supported arithmetic."""

import pytest

from idasen_companion.core.clocks import WallInstant
from idasen_companion.core.display_prefs import (
    HeightUnit, from_display_height, to_display_height,
)
from idasen_companion.core.durations import Duration
from idasen_companion.core.lengths import Length


def test_length_factories_preserve_conversion_policy():
    assert type(Length.from_metres(1).metres) is int
    assert Length.from_metres(1.105).metres == 1.105
    assert Length.from_metres(10**400).metres == 10**400
    for unit, factory, value in (
        (HeightUnit.CENTIMETRES, Length.from_centimetres, 110.5),
        (HeightUnit.INCHES, Length.from_inches, 43.5),
    ):
        height = factory(value)
        assert height.metres == from_display_height(value, unit)
        assert height.to_display(unit) == to_display_height(height.metres, unit)


def test_length_arithmetic_and_typed_zero():
    a, b, zero = Length(2), Length(0.5), Length(0)
    assert a + b == Length(2.5)
    assert b - a == Length(-1.5)
    assert abs(b - a) == Length(1.5)
    assert a * 3 == 3 * a == Length(6)
    assert a / 2 == Length(1)
    assert a / b == 4
    assert zero < b <= a and a > b >= zero
    assert sum([a, b], zero) == Length(2.5)
    assert not zero and bool(Length(-1))
    assert len({Length(1), Length(1.0)}) == 1
    assert Length(1) != 1


def test_length_rejects_mixed_dimensions_and_raw_addition():
    height = Length(1)
    for operation in (
        lambda: height + 1, lambda: 1 + height, lambda: height < 1,
        lambda: Duration(1) < height,
        lambda: height - Duration(1), lambda: height * Duration(1),
        lambda: height / Duration(1), lambda: 1 / height,
        lambda: 1 - height, lambda: sum([height]),
    ):
        with pytest.raises(TypeError):
            operation()


async def test_mock_height_path_has_typed_domain_values():
    from idasen_companion.desk.mock import MockDesk

    desk = MockDesk()
    height = await desk.get_height()
    assert height == Length(0.62)
    from idasen_companion.core.machine import StateMachine
    from machine_helpers import make_config

    machine = StateMachine(make_config(), desk, now=WallInstant(0))
    await machine.start(WallInstant(0))
    assert machine.last_height == Length(0.62)
    assert await desk.move_to(Length(1.1)) is True
    assert desk.move_calls == [Length(1.1)]
    desk.height = Length(0)
    assert await desk.get_height() == Length(0)  # present zero is still a reading
    desk.height_unavailable = True
    assert await desk.get_height() is None
