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
``core/presentation/formatter.py`` and ``core/presentation/english.py``:
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
