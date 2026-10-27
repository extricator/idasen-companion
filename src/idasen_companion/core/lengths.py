# SPDX-License-Identifier: GPL-3.0-or-later
"""Number-preserving lengths for physical desk-height domains."""

from __future__ import annotations

from dataclasses import dataclass
from typing import overload

from .display_prefs import HeightUnit, from_display_height, to_display_height


@dataclass(frozen=True)
class Length:
    """A signed count of metres, without physical bounds or coercion."""

    metres: int | float

    @classmethod
    def from_metres(cls, value: int | float) -> Length:
        return cls(value)

    @classmethod
    def from_centimetres(cls, value: int | float) -> Length:
        return cls.from_display(value, HeightUnit.CENTIMETRES)

    @classmethod
    def from_inches(cls, value: int | float) -> Length:
        return cls.from_display(value, HeightUnit.INCHES)

    @classmethod
    def from_display(cls, value: int | float, unit: HeightUnit) -> Length:
        return cls(from_display_height(value, unit))

    def to_display(self, unit: HeightUnit) -> float:
        return to_display_height(self.metres, unit)

    def __bool__(self) -> bool:
        return bool(self.metres)

    def __add__(self, other: Length) -> Length:
        if not isinstance(other, Length):
            return NotImplemented
        return Length(self.metres + other.metres)

    def __sub__(self, other: Length) -> Length:
        if not isinstance(other, Length):
            return NotImplemented
        return Length(self.metres - other.metres)

    def __mul__(self, other: int | float) -> Length:
        if not isinstance(other, (int, float)):
            return NotImplemented
        return Length(self.metres * other)

    def __rmul__(self, other: int | float) -> Length:
        return self.__mul__(other)

    @overload
    def __truediv__(self, other: Length) -> float: ...

    @overload
    def __truediv__(self, other: int | float) -> Length: ...

    def __truediv__(self, other: Length | int | float) -> Length | float:
        if isinstance(other, Length):
            return self.metres / other.metres
        if not isinstance(other, (int, float)):
            return NotImplemented
        return Length(self.metres / other)

    def __abs__(self) -> Length:
        return Length(abs(self.metres))

    def __lt__(self, other: Length) -> bool:
        if not isinstance(other, Length):
            return NotImplemented
        return self.metres < other.metres

    def __le__(self, other: Length) -> bool:
        if not isinstance(other, Length):
            return NotImplemented
        return self.metres <= other.metres

    def __gt__(self, other: Length) -> bool:
        if not isinstance(other, Length):
            return NotImplemented
        return self.metres > other.metres

    def __ge__(self, other: Length) -> bool:
        if not isinstance(other, Length):
            return NotImplemented
        return self.metres >= other.metres
