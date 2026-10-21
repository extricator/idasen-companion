"""Number-preserving operational readings with separate clock domains."""

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


@dataclass(frozen=True)
class MonotonicInstant:
    """A monotonic reading whose differences and offsets retain their domain."""

    monotonic_seconds: int | float

    def __bool__(self) -> bool:
        return bool(self.monotonic_seconds)

    def __add__(self, other: Duration) -> MonotonicInstant:
        if not isinstance(other, Duration):
            return NotImplemented
        return MonotonicInstant(self.monotonic_seconds + other.seconds)

    @overload
    def __sub__(self, other: MonotonicInstant) -> Duration: ...

    @overload
    def __sub__(self, other: Duration) -> MonotonicInstant: ...

    def __sub__(self, other: MonotonicInstant | Duration) -> Duration | MonotonicInstant:
        if isinstance(other, MonotonicInstant):
            return Duration.from_seconds(self.monotonic_seconds - other.monotonic_seconds)
        if isinstance(other, Duration):
            return MonotonicInstant(self.monotonic_seconds - other.seconds)
        return NotImplemented

    def __lt__(self, other: MonotonicInstant) -> bool:
        if not isinstance(other, MonotonicInstant):
            return NotImplemented
        return self.monotonic_seconds < other.monotonic_seconds

    def __le__(self, other: MonotonicInstant) -> bool:
        if not isinstance(other, MonotonicInstant):
            return NotImplemented
        return self.monotonic_seconds <= other.monotonic_seconds

    def __gt__(self, other: MonotonicInstant) -> bool:
        if not isinstance(other, MonotonicInstant):
            return NotImplemented
        return self.monotonic_seconds > other.monotonic_seconds

    def __ge__(self, other: MonotonicInstant) -> bool:
        if not isinstance(other, MonotonicInstant):
            return NotImplemented
        return self.monotonic_seconds >= other.monotonic_seconds
