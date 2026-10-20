"""Presence-based active-time attribution, separate from statistics storage."""

from __future__ import annotations

from datetime import date

from ..core.durations import Duration
from ..core.machine import TIME_JUMP_THRESHOLD_SECONDS
from .stats import Stats


class ActiveTimeAccounting:
    """Hold silent windows until presence or absence settles their credit.

    The observation clock and pending credit live here. Stats owns persistence, and the daemon
    supplies each tick's observations and current idle threshold.
    """

    def __init__(self, stats: Stats):
        self._stats = stats
        self._last_observation: float | None = None
        self._pending_credit: dict[tuple[date, str], Duration] = {}

    def start(self, now: float) -> None:
        """Seed the observation clock from the daemon's startup origin."""
        self._last_observation = now

    def account(self, state: str, now: float, *, held: bool,
                idle_ms: int, absent: bool, idle_threshold_seconds: int) -> None:
        """Attribute the window ending at ``now`` to ``state``'s daily total.

        Real elapsed time goes to the position the desk was in, regardless of
        automation freeze states — pause and snooze stop the cycle, not the
        clock you are sitting through.

        Presence is a guess whenever there's no input: a silent stretch is
        either the user reading at the desk (real sit/stand time) or an empty
        chair, and the two look identical while they last. So a silent window
        is held back rather than credited, and settled only once something
        proves which it was — input inside a later window means the user was
        there for the silence too, while the away threshold (or a lock, a
        switched-away session, a suspend-sized gap) proves they weren't.
        Crediting silence outright used to bank ~idle_threshold of phantom
        "active" time on every break, permanently.
        """
        last_observation = self._last_observation
        self._last_observation = now
        if last_observation is None:
            return
        elapsed = Duration.from_seconds(now - last_observation)
        # Don't credit a suspend-sized gap to sit/stand totals (the stats-side
        # twin of the machine's time-jump reset); shared absolute threshold, and
        # the same both-directions rule — a backward clock step would otherwise
        # write negative seconds into a daily row, permanently.
        elapsed_is_plausible = (Duration.from_seconds(0) <= elapsed
                                <= Duration.from_seconds(TIME_JUMP_THRESHOLD_SECONDS))
        idle_threshold_ms = idle_threshold_seconds * 1000
        if not elapsed_is_plausible or absent or idle_ms >= idle_threshold_ms:
            self._pending_credit.clear()
        elif held:
            pass  # off-cycle: the desk is at neither preset, so neither gets it
        elif Duration.from_milliseconds(idle_ms) < elapsed:
            # Input landed inside this window: the user is here now, which
            # settles the silence leading up to it as time at the desk.
            self.flush()
            self._stats.add_active_time(state, elapsed)
        else:
            key = (date.today(), state)
            self._pending_credit[key] = (
                self._pending_credit.get(key, Duration.from_seconds(0)) + elapsed)

    def flush(self) -> None:
        """Commit held time to the day and state it was actually spent in."""
        for (day, state), seconds in self._pending_credit.items():
            self._stats.add_active_time(state, seconds, day)
        self._pending_credit.clear()
