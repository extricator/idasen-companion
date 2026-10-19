"""Distinct open domains for interpreting raw desk and automation values."""

from dataclasses import dataclass
from typing import TypeAlias

from .machine import DeskState, Status


@dataclass(frozen=True)
class UnknownPosition:
    """A position the current application does not recognize, kept verbatim."""

    raw: str


@dataclass(frozen=True)
class UnknownStatus:
    """An automation status the current application does not recognize."""

    raw: str


PositionValue: TypeAlias = DeskState | UnknownPosition
StatusValue: TypeAlias = Status | UnknownStatus


def parse_position(raw: str) -> PositionValue:
    """Interpret a known position without changing unfamiliar or empty text."""
    try:
        return DeskState(raw)
    except ValueError:
        return UnknownPosition(raw)


def parse_status(raw: str) -> StatusValue:
    """Interpret a known status without changing unfamiliar or empty text."""
    try:
        return Status(raw)
    except ValueError:
        return UnknownStatus(raw)
