"""Explicit, Qt-free locale value formatting backed by Babel.

``LocaleProfile`` is the application's sole renderer for app-owned numbers,
percentages, dates, times and units. It never reads or mutates process locale
state: callers resolve the selected app language once and pass it in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Mapping

from babel import Locale
from babel.dates import format_date, format_time, get_time_format
from babel.numbers import format_decimal, format_percent
from babel.units import format_unit

from .presentation.specs import DateStyle, IntegerSpec, NumberSpec, TimeStyle

_APP_LOCALE_ENVIRON = ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")


def normalize_locale(value: str) -> str | None:
    """Return a Babel-shaped identifier from a POSIX locale value."""
    candidate = value.split(":", 1)[0].split(".", 1)[0].split("@", 1)[0]
    candidate = candidate.replace("-", "_")
    if not candidate or candidate.upper() in {"C", "POSIX"}:
        return None
    try:
        return str(Locale.parse(candidate))
    except (ValueError, TypeError):
        return None


def resolve_app_locale(language: str, environ: Mapping[str, str]) -> str:
    """Resolve ``[ui] language`` without consulting mutable global locale."""
    if language != "system":
        return normalize_locale(language) or "en_US"
    for key in _APP_LOCALE_ENVIRON:
        identifier = normalize_locale(environ.get(key, ""))
        if identifier is not None:
            return identifier
    return "en_US"


def locale_uses_twelve_hour_clock(locale_name: str) -> bool:
    """Whether Babel's short time pattern for ``locale_name`` is 12-hour."""
    pattern = get_time_format("short", locale=locale_name).pattern
    quoted = False
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "'":
            if index + 1 < len(pattern) and pattern[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
        elif not quoted and character in "hK":
            return True
        elif not quoted and character in "Hk":
            return False
        index += 1
    return False


@dataclass(frozen=True)
class LocaleProfile:
    """Immutable formatting operations for one explicit app locale."""

    locale_name: str
    _locale: Locale = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        identifier = normalize_locale(self.locale_name)
        if identifier is None:
            raise ValueError(f"unsupported locale: {self.locale_name!r}")
        object.__setattr__(self, "locale_name", identifier)
        object.__setattr__(self, "_locale", Locale.parse(identifier))

    @property
    def numbering_system(self) -> str:
        """The CLDR default whose symbols Babel uses for this profile."""
        return self._locale.default_numbering_system

    def number(self, value: float, spec: NumberSpec) -> str:
        decimals = spec.decimals
        if spec.trim_trailing_zeroes and value == int(value):
            decimals = 0
        integer = "#,##0" if spec.grouping else "0"
        pattern = integer + ("." + "0" * decimals if decimals else "")
        return format_decimal(
            Decimal(str(value)), format=pattern, locale=self._locale,
            decimal_quantization=True, group_separator=spec.grouping,
            numbering_system="default")

    def integer(self, value: int, spec: IntegerSpec) -> str:
        zeroes = "0" * spec.min_digits
        pattern = ("#,##" if spec.grouping else "") + zeroes
        options = {"group_separator": True} if spec.grouping else {}
        return format_decimal(
            int(value), format=pattern, locale=self._locale,
            numbering_system="default", **options)

    def percent(self, value: float, *, decimals: int = 0,
                grouping: bool = False) -> str:
        integer = "#,##0" if grouping else "0"
        numeric = integer + ("." + "0" * decimals if decimals else "")
        pattern = self._locale.percent_formats[None].pattern.replace(
            "#,##0", numeric)
        return format_percent(
            Decimal(str(value)), format=pattern, locale=self._locale,
            group_separator=grouping, numbering_system="default")

    def time(self, value: datetime, style: TimeStyle) -> str:
        patterns = {
            TimeStyle.HOUR_AND_MINUTE_12: "h:mm a",
            TimeStyle.HOUR_AND_MINUTE_24: "HH:mm",
            TimeStyle.HOUR_MINUTE_AND_SECOND_12: "h:mm:ss a",
            TimeStyle.HOUR_MINUTE_AND_SECOND_24: "HH:mm:ss",
        }
        try:
            pattern = patterns[style]
        except KeyError as error:
            raise ValueError(f"unsupported time style: {style!r}") from error
        return format_time(value, format=pattern, locale=self._locale)

    def date(self, value: datetime, style: DateStyle) -> str:
        patterns = {
            DateStyle.WEEKDAY_AND_DAY: "EEE dd",
            DateStyle.WEEKDAY_DAY_MONTH_YEAR: "EEE dd MMM y",
        }
        try:
            pattern = patterns[style]
        except KeyError as error:
            raise ValueError(f"unsupported date style: {style!r}") from error
        return format_date(value, format=pattern, locale=self._locale)

    def unit(self, value: float, measurement_unit: str, *, decimals: int,
             length: Literal["short", "long", "narrow"] = "short") -> str:
        pattern = "0" + ("." + "0" * decimals if decimals else "")
        return format_unit(
            Decimal(str(value)), measurement_unit, length=length,
            format=pattern, locale=self._locale, numbering_system="default")

    def plural_category(self, value: int | float) -> str:
        """Return Babel's CLDR cardinal category for ``value``."""
        return str(self._locale.plural_form(value))
