"""Seam-level tests for ``core/presentation``: specs, styles and the facade.

This module imports no PySide6 and asserts nothing beyond what plan 12-01
lands: frozen specs and styles, and a ``Formatter`` that holds the context
it was built from. The real ``LocaleFormatter``/``Translator``
implementations (fakes and Qt backends) arrive in plan 12-07 and later
waves; a two-line stand-in stands in for the protocol slots here so this
test does not wait on them.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from idasen_companion.core.presentation.formatter import (
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.specs import (
    DateStyle, IntegerSpec, NumberSpec, TimeStyle,
)
from idasen_companion.core.units import HeightUnit


def test_number_spec_is_frozen():
    spec = NumberSpec(decimals=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.decimals = 2  # type: ignore[misc]


def test_integer_spec_is_frozen():
    spec = IntegerSpec(min_digits=2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.min_digits = 3  # type: ignore[misc]


@pytest.mark.parametrize("member", list(TimeStyle))
def test_time_style_members_are_strings(member):
    assert isinstance(member, str)


@pytest.mark.parametrize("member", list(DateStyle))
def test_date_style_members_are_strings(member):
    assert isinstance(member, str)


def test_time_style_has_expected_members():
    assert TimeStyle.HOUR_AND_MINUTE_12 == "hour_and_minute_12"
    assert TimeStyle.HOUR_AND_MINUTE_24 == "hour_and_minute_24"
    assert TimeStyle.HOUR_MINUTE_AND_SECOND_12 == "hour_minute_and_second_12"
    assert TimeStyle.HOUR_MINUTE_AND_SECOND_24 == "hour_minute_and_second_24"


def test_date_style_has_expected_members():
    assert DateStyle.WEEKDAY_AND_DAY == "weekday_and_day"
    assert DateStyle.WEEKDAY_DAY_MONTH_YEAR == "weekday_day_month_year"


class _StandInLocale:
    """A minimal stand-in for the LocaleFormatter slot — not a real fake.

    Plan 12-07 builds the real fakes; this exists only so
    ``PresentationContext`` can be constructed here without waiting on them.
    """

    def number(self, value: float, spec: NumberSpec) -> str:
        return f"{value:.{spec.decimals}f}"

    def integer(self, value: int, spec: IntegerSpec) -> str:
        return str(value).zfill(spec.min_digits)

    def time(self, value: datetime, style: TimeStyle) -> str:
        return value.isoformat()

    def date(self, value: datetime, style: DateStyle) -> str:
        return value.isoformat()


class _StandInTranslator:
    """A minimal stand-in for the Translator slot — see _StandInLocale."""

    def message(self, source: str, **values: object) -> str:
        return source % values if values else source


def _build_context() -> PresentationContext:
    return PresentationContext(
        locale=_StandInLocale(), translator=_StandInTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE_24)


def test_presentation_context_is_frozen():
    context = _build_context()
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.locale = _StandInLocale()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.unit = HeightUnit.INCHES  # type: ignore[misc]


def test_formatter_exposes_its_context():
    context = _build_context()
    formatter = Formatter(context)
    assert formatter.context is context
