"""Number-preserving operational wall-clock readings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import overload

from .durations import Duration


@dataclass(frozen=True)
class WallInstant:
    """An epoch reading whose differences and offsets retain their domain."""

    epoch_seconds: int | float

    def __bool__(self) -> bool:
        return bool(self.epoch_seconds)

    def __add__(self, other: Duration) -> WallInstant:
        if not isinstance(other, Duration):
            return NotImplemented
        return WallInstant(self.epoch_seconds + other.seconds)

    @overload
    def __sub__(self, other: WallInstant) -> Duration: ...

    @overload
    def __sub__(self, other: Duration) -> WallInstant: ...

    def __sub__(self, other: WallInstant | Duration) -> Duration | WallInstant:
        if isinstance(other, WallInstant):
            return Duration.from_seconds(self.epoch_seconds - other.epoch_seconds)
        if isinstance(other, Duration):
            return WallInstant(self.epoch_seconds - other.seconds)
        return NotImplemented

    def __lt__(self, other: WallInstant) -> bool:
        if not isinstance(other, WallInstant):
            return NotImplemented
        return self.epoch_seconds < other.epoch_seconds

    def __le__(self, other: WallInstant) -> bool:
        if not isinstance(other, WallInstant):
            return NotImplemented
        return self.epoch_seconds <= other.epoch_seconds

    def __gt__(self, other: WallInstant) -> bool:
        if not isinstance(other, WallInstant):
            return NotImplemented
        return self.epoch_seconds > other.epoch_seconds

    def __ge__(self, other: WallInstant) -> bool:
        if not isinstance(other, WallInstant):
            return NotImplemented
        return self.epoch_seconds >= other.epoch_seconds
