"""Resolve the independent clock preference through Babel's locale data."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from .locale_profile import locale_uses_twelve_hour_clock, normalize_locale
from .presentation.specs import TimeStyle


class ClockSetting(StrEnum):
    """What ``[ui] clock_format`` stores: a preference, not a clock."""

    SYSTEM = "system"
    TWELVE = "12"
    TWENTY_FOUR = "24"


def _system_time_locale(environ: Mapping[str, str]) -> str | None:
    """Resolve the POSIX time locale without using the selected app language."""
    for key in ("LC_ALL", "LC_TIME", "LANG"):
        value = environ.get(key)
        if value:
            # The first explicit time-locale input answers outright. C,
            # POSIX, invalid and unsupported values use the deterministic
            # 24-hour fallback rather than leaking into another category.
            return normalize_locale(value)
    return None


def resolve_clock_style(setting: ClockSetting, *, language: str,
                        environ: Mapping[str, str]) -> TimeStyle:
    """Resolve a setting once; ``language`` is retained for API compatibility.

    The accepted preference model intentionally does not consult ``language``
    for ``SYSTEM``. Changing the app's words and symbols must not silently
    change the user's hour cycle.
    """
    del language
    if setting is ClockSetting.TWELVE:
        return TimeStyle.HOUR_AND_MINUTE_12
    if setting is ClockSetting.TWENTY_FOUR:
        return TimeStyle.HOUR_AND_MINUTE_24
    locale_name = _system_time_locale(environ)
    if locale_name and locale_uses_twelve_hour_clock(locale_name):
        return TimeStyle.HOUR_AND_MINUTE_12
    return TimeStyle.HOUR_AND_MINUTE_24
