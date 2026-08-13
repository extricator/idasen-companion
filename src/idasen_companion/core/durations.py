"""Duration parsing and formatting.

Parsing follows the reference script's grammar: a duration string is a
sequence of ``<int><unit>`` groups with units ``h``, ``m``, ``s``
(e.g. ``"45m"``, ``"1h30m"``, ``"90s"``). Unlike the reference script,
a string with no recognizable groups raises ``ValueError`` instead of
silently parsing to 0 — this only affects config validation, never
automation behavior.
"""

from __future__ import annotations

import re

_UNIT_TO_SECONDS = {"h": 3600, "m": 60, "s": 1}
_GROUP_RE = re.compile(r"(\d+)\s*([hms])")
_FULL_RE = re.compile(r"(?:\s*\d+\s*[hms])+\s*")


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


def format_duration_human(seconds: float | None) -> str:
    """Human-readable duration for logs, matching the reference script's style."""
    if seconds is None:
        return "N/A"
    if seconds >= 60:
        return f"{seconds / 60:.1f} minutes"
    return f"{seconds:.0f} seconds"
