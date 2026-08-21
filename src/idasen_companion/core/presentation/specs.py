"""Frozen request specs and style enums for the presentation seam.

A formatting request names what the product wants, never how a backend
should achieve it. Two shapes carry that intent instead of a boolean pile
or a strftime-shaped pattern (BACK-05): a frozen ``@dataclass`` for a number
or integer request, and a ``StrEnum`` for a date/time *style*. A pattern
argument (``"%H:%M"``, ``"ddd dd"``) would let a caller push locale
mechanics — which characters mean what, in which order — back across the
seam the protocols in :mod:`.protocols` exist to hold. A spec or style,
by contrast, is answered entirely on the backend's side: the product says
*what*, the backend decides *how*.

Each member below is anchored to the real call it must serve, not derived
in the abstract:

- ``NumberSpec(decimals=1)`` and ``NumberSpec(decimals=2)`` are the two
  height cases — centimetres shown to one decimal, inches to two, because
  one inch (2.54 cm) is coarser than the desk's own millimetre resolution.
- ``NumberSpec.trim_trailing_zeroes`` is the chart-label brevity
  ``gui/util.py``'s ``fmt_number`` provides today through its ``trim``
  argument: a whole value like ``110`` renders without a trailing ``.0``.
- ``NumberSpec.grouping`` defaults to ``False`` because heights and
  durations never reach four digits in this app; a digit-group separator
  appearing there would be a locale mechanism answering a product question
  nobody asked.
- ``IntegerSpec(min_digits=2)`` is ``fmt_hm``'s zero-padded minutes
  (``"1h 05m"``, never ``"1h 5m"``).
- ``TimeStyle.HOUR_AND_MINUTE`` is ``fmt_clock`` — a wall-clock time such
  as "14:32" or, in a 12-hour locale, "2:32 PM".
- ``DateStyle.WEEKDAY_AND_DAY`` is ``fmt_day_label`` — a short day marker
  such as "Mon 03".
- ``DateStyle.WEEKDAY_DAY_MONTH_YEAR`` is ``fmt_day_heading`` — a full
  calendar heading such as "Mon 17 Aug 2026".

The styles are named for what the product is asking for, not for a Qt
format code or a strftime directive — a backend is free to render
``TimeStyle.HOUR_AND_MINUTE`` as ``"14:32"`` or ``"2:32 PM"``, and neither
name leaks that choice back to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class NumberSpec:
    """A request to render a floating-point number.

    ``decimals`` is the number of places to show; ``trim_trailing_zeroes``
    drops them for a whole value (chart-label brevity); ``grouping``
    switches on a locale's digit-group separator and defaults off, because
    no value this app renders is ever wide enough to need one.
    """

    decimals: int
    trim_trailing_zeroes: bool = False
    grouping: bool = False


@dataclass(frozen=True)
class IntegerSpec:
    """A request to render a whole number.

    ``min_digits`` zero-pads to at least that many digits (``fmt_hm``'s
    ``"05"`` minutes); ``grouping`` switches on a locale's digit-group
    separator and defaults off, for the same reason as :class:`NumberSpec`.
    """

    min_digits: int = 1
    grouping: bool = False


class TimeStyle(StrEnum):
    """A wall-clock time style. See the module docstring for the anchor call."""

    HOUR_AND_MINUTE = "hour_and_minute"


class DateStyle(StrEnum):
    """A calendar date style. See the module docstring for the anchor calls."""

    WEEKDAY_AND_DAY = "weekday_and_day"
    WEEKDAY_DAY_MONTH_YEAR = "weekday_day_month_year"
