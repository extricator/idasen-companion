"""Active-hours scheduling.

Automation is active when the current local time falls inside the
configured window on an enabled day. A window whose end is at or before
its start crosses midnight and belongs to the day it *started* (e.g.
days=["fri"], 22:00-02:00 covers Friday 22:00 through Saturday 02:00).
"""

from __future__ import annotations

from datetime import datetime

from .config import ScheduleConfig, VALID_DAYS

_DAY_INDEX = {name: i for i, name in enumerate(VALID_DAYS)}  # mon=0 .. sun=6


def _minutes(text: str) -> int:
    hour_text, minute_text = text.split(":")
    return int(hour_text) * 60 + int(minute_text)


def is_schedule_active(config: ScheduleConfig, when: datetime) -> bool:
    """True if automation should run at ``when`` under this schedule."""
    if not config.enabled:
        return True
    days = {_DAY_INDEX[d] for d in config.days}
    start = _minutes(config.start)
    end = _minutes(config.end)
    now_min = when.hour * 60 + when.minute
    today = when.weekday()

    if start < end:
        return today in days and start <= now_min < end
    # Overnight window (or start == end meaning a full 24h window from start)
    yesterday = (today - 1) % 7
    return (today in days and now_min >= start) or (yesterday in days and now_min < end)
