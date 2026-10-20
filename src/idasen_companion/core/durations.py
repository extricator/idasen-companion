"""Duration parsing and compact config-file formatting.

Parsing follows the reference script's grammar: a duration string is a
sequence of ``<int><unit>`` groups with units ``h``, ``m``, ``s``
(e.g. ``"45m"``, ``"1h30m"``, ``"90s"``). Unlike the reference script,
a string with no recognizable groups raises ``ValueError`` instead of
silently parsing to 0 — this only affects config validation, never
automation behavior.

This module owns the arithmetic every duration renderer in the app shares
(PRES-03's one policy): the below-a-minute threshold
(:data:`SUB_MINUTE_THRESHOLD_SECONDS`) and the hours/minutes/seconds
decomposition (:func:`decompose_hms`). The *rendering* — including the
journal's own English — sits one layer up, in
``core/presentation.py`` and ``core/presentation.py``:
this module supplies only the numbers, never a translated string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_UNIT_TO_SECONDS = {"h": 3600, "m": 60, "s": 1}
_GROUP_RE = re.compile(r"(\d+)\s*([hms])")
_FULL_RE = re.compile(r"(?:\s*\d+\s*[hms])+\s*")

#: Below this many seconds, a compact duration renders the count as seconds
#: rather than flooring it to "0m" — the split point every compact renderer
#: in the app shares.
SUB_MINUTE_THRESHOLD_SECONDS = 60


@dataclass(frozen=True, eq=False)
class Duration:
    """A number-preserving count of seconds used inside timing domains."""

    seconds: int | float

    @classmethod
    def from_seconds(cls, value: int | float) -> "Duration":
        return cls(value)

    @classmethod
    def from_milliseconds(cls, value: int | float) -> "Duration":
        return cls(value / 1000.0)

    @classmethod
    def from_minutes(cls, value: int | float) -> "Duration":
        return cls(value * 60)

    @classmethod
    def from_microseconds(cls, value: int | float) -> "Duration":
        return cls(value / 1_000_000.0)

    def __bool__(self) -> bool:
        return bool(self.seconds)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Duration) and self.seconds == other.seconds

    def _other_duration(self, other: object) -> "Duration":
        if not isinstance(other, Duration):
            raise TypeError("duration arithmetic requires Duration operands")
        return other

    def _scalar(self, other: object) -> int | float:
        if isinstance(other, bool) or not isinstance(other, (int, float)):
            raise TypeError("duration scaling requires a numeric scalar")
        return other

    def __add__(self, other: object) -> "Duration":
        return Duration(self.seconds + self._other_duration(other).seconds)

    def __sub__(self, other: object) -> "Duration":
        return Duration(self.seconds - self._other_duration(other).seconds)

    def __mul__(self, other: object) -> "Duration":
        return Duration(self.seconds * self._scalar(other))

    def __rmul__(self, other: object) -> "Duration":
        return self * other

    def __truediv__(self, other: object) -> "Duration | float":
        if isinstance(other, Duration):
            return self.seconds / other.seconds
        return Duration(self.seconds / self._scalar(other))

    def __abs__(self) -> "Duration":
        return Duration(abs(self.seconds))

    def __lt__(self, other: object) -> bool:
        return self.seconds < self._other_duration(other).seconds

    def __le__(self, other: object) -> bool:
        return self.seconds <= self._other_duration(other).seconds

    def __gt__(self, other: object) -> bool:
        return self.seconds > self._other_duration(other).seconds

    def __ge__(self, other: object) -> bool:
        return self.seconds >= self._other_duration(other).seconds


def parse_duration(text: str) -> int:
    """Parse a duration string like ``45m``, ``1h30m`` or ``90s`` into seconds.

    The entire string must consist of duration groups — partial matches
    like ``"4.5m"`` (which the reference script would read as 5m) are
    rejected rather than silently misread.
    """
    normalized = text.lower()
    if not _FULL_RE.fullmatch(normalized):
        raise ValueError(f"invalid duration: {text!r} (expected e.g. '45m', '1h30m', '90s')")
    groups = _GROUP_RE.findall(normalized)
    return sum(int(value) * _UNIT_TO_SECONDS[unit] for value, unit in groups)


def format_duration_compact(seconds: int) -> str:
    """Format seconds as a compact duration string suitable for config files."""
    seconds = int(seconds)
    if seconds <= 0:
        return "0s"
    parts = []
    for unit, size in (("h", 3600), ("m", 60), ("s", 1)):
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount}{unit}")
    return "".join(parts)


@dataclass(frozen=True)
class DurationParts:
    """A count of seconds split into whole hours, minutes and seconds."""

    hours: int
    minutes: int
    seconds: int


def decompose_hms(total_seconds: float) -> DurationParts:
    """Split ``total_seconds`` into whole hours, minutes and seconds.

    Floor semantics — a fractional second is dropped, not rounded, matching
    ``fmt_hm``'s existing ``int(seconds) // 60``. A negative value clamps to
    zero rather than raising, matching ``fmt_countdown``'s existing
    ``max(0, int(seconds))``: a countdown that has run out is still a valid
    duration to render, not an error.
    """
    whole = max(0, int(total_seconds))
    minutes, seconds = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    return DurationParts(hours=hours, minutes=minutes, seconds=seconds)
