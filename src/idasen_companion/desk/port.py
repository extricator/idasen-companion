# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk port: the interface the automation core talks to.

Implementations: BleDesk (real desk over BLE) and MockDesk
(tests and --mock-desk mode).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, overload

from ..core.lengths import Length

MoveGuard = Callable[[], Awaitable[bool]]


class DeskPort(Protocol):
    async def get_height(self) -> Length | None:
        """Current height in meters, or None if unavailable."""
        ...

    @overload
    async def move_to(self, height: Length, *, guard: None = None) -> bool: ...

    @overload
    async def move_to(self, height: Length, *, guard: MoveGuard) -> bool | None: ...

    async def move_to(self, height: Length, *, guard: MoveGuard | None = None) -> bool | None:
        """Move to ``height`` (meters). Returns False if the command errored.

        A True return does NOT guarantee the target was reached — callers
        verify by reading the height back, exactly like the reference
        script does with the CLI.

        A guard runs after preparation, immediately before the first command.
        None means admission was deferred before issuing any command; ordinary
        unguarded callers retain their bool result.
        """
        ...

    async def stop(self) -> None:
        """Stop any in-progress movement."""
        ...

    async def disconnect(self) -> None:
        """Release the desk. A no-op for an implementation that holds nothing.

        On the contract because the daemon *depends* on it: the shutdown path
        must hand the BLE link back, and it was reaching around the Protocol
        with ``hasattr(self.desk, "disconnect")`` at three sites to do so. A
        duck-typed check repeated three times is a missing contract, and the
        one thing it guards is the link this project treats most carefully.
        """
        ...

    @property
    def last_error(self) -> str | None:
        """Why the last operation failed, for a user-facing message.

        None when nothing has failed. The daemon reads this to put a reason on
        its "move failed" line — per-attempt BLE errors are diagnostic, so
        without it the warning says something failed but not why. It was
        reached with ``getattr(self.desk, "last_error", None)``, which meant
        MockDesk silently never supplied one: under ``--mock-desk`` the
        reasoned branch was unreachable and a whole catalogued message, plus
        its Spanish translation, was exercised by nothing.
        """
        ...
