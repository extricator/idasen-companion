"""Simulated desk for unit tests and the daemon's --mock-desk mode."""

from __future__ import annotations


class MockDesk:
    """A desk that teleports to the requested height.

    Test hooks:
      - ``height`` may be set directly to simulate external movement.
      - ``interrupt_next_move_at``: the next move lands at this height
        instead of the target (simulates someone grabbing the paddle).
      - ``fail_next_move``: the next move returns False (command error).
      - ``height_unavailable``: get_height returns None while True.
      - ``last_error``: settable, so the daemon's failure-with-a-reason
        branch is reachable without a real desk.
      - ``get_height_calls`` counts reads, which is how "the desk was left
        alone" is asserted (a real read is a BLE connection on a desk that
        takes one client at a time).
    """

    def __init__(self, height: float = 0.62):
        self.height: float = height
        self.interrupt_next_move_at: float | None = None
        self.fail_next_move: bool = False
        self.height_unavailable: bool = False
        self.last_error: str | None = None
        self.move_calls: list[float] = []
        self.get_height_calls: int = 0

    async def get_height(self) -> float | None:
        self.get_height_calls += 1
        if self.height_unavailable:
            return None
        return self.height

    async def move_to(self, height: float) -> bool:
        self.move_calls.append(height)
        if self.fail_next_move:
            self.fail_next_move = False
            return False
        if self.interrupt_next_move_at is not None:
            self.height = self.interrupt_next_move_at
            self.interrupt_next_move_at = None
        else:
            self.height = height
        return True

    async def stop(self) -> None:
        pass

    async def disconnect(self) -> None:
        """Nothing to release: the mock holds no link. Present because
        DeskPort declares it and the daemon's shutdown path calls it."""
