# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared decoded records; transport adapters own JSON and failure policy."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import NamedTuple, TypeAlias, TypedDict, cast

JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
LogParams: TypeAlias = dict[str, JSONValue]


class LogEntry(TypedDict):
    """Decoded wall time, open severity/audience/id, JSON params and fallback text."""

    ts: float
    level: str
    channel: str
    msg_id: str
    params: LogParams
    text: str


def decode_timestamp(value: object, default: float | None = None) -> float | None:
    """Coerce finite, locally renderable seconds; retain negative/zero history."""
    try:
        timestamp = float(value)  # type: ignore[arg-type]
        if isfinite(timestamp):
            datetime.fromtimestamp(timestamp)
            return timestamp
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    return default


def decode_log_entry(value: object) -> LogEntry | None:
    """Decode a JSON object with legacy ring defaults and safe per-field recovery."""
    if not isinstance(value, dict):
        return None
    timestamp = decode_timestamp(value.get("ts", 0.0), 0.0)
    params = value.get("params")
    return LogEntry(
        ts=timestamp if timestamp is not None else 0.0,
        level=str(value.get("level", "info")),
        channel=str(value.get("channel", "activity")),
        msg_id=str(value.get("msg_id", "")),
        params=cast(LogParams, params) if isinstance(params, dict) else {},
        text=str(value.get("text", "")),
    )


def decode_log_entries(value: object) -> list[LogEntry]:
    """Decode a JSON list, retaining usable objects beside malformed neighbors."""
    if not isinstance(value, list):
        return []
    return [entry for raw in value if (entry := decode_log_entry(raw)) is not None]


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
        timestamp = decode_timestamp(row[0])
        if timestamp is None:
            continue
        result.append(TransitionRow(timestamp, str(row[1]), str(row[2]),
                                    str(row[3]), bool(row[4])))
    return result
