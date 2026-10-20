"""Shared decoded records; transport adapters own JSON and failure policy."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import NamedTuple


class DailyStatRow(NamedTuple):
    """Active seconds by calendar-day text and raw, open-ended desk state."""

    day: str
    state: str
    seconds: float


class TransitionRow(NamedTuple):
    """Unix wall time, raw states/trigger and whether movement was interrupted."""

    timestamp: float
    from_state: str
    to_state: str
    trigger: str
    interrupted: bool


def decode_daily_rows(value: object) -> list[DailyStatRow]:
    """Decode required prefixes, ignoring extra fields and unusable rows.

    Text is not normalized or restricted to known dates/states. Finite zero
    and negative seconds remain valid historical values.
    """
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            seconds = float(row[2])
        except (TypeError, ValueError, OverflowError):
            continue
        if isfinite(seconds):
            result.append(DailyStatRow(str(row[0]), str(row[1]), seconds))
    return result


def decode_transition_rows(value: object) -> list[TransitionRow]:
    """Decode renderable timestamps and open text without inventing fields.

    A required timestamp must be finite and accepted by the same local-time
    conversion used by consumers. Extra fields are ignored for wire evolution.
    """
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        try:
            timestamp = float(row[0])
            if not isfinite(timestamp):
                continue
            datetime.fromtimestamp(timestamp)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        result.append(TransitionRow(timestamp, str(row[1]), str(row[2]),
                                    str(row[3]), bool(row[4])))
    return result
