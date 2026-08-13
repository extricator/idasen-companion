"""The automation state machine — a 1:1 port of the project's original
single-file script's control loop, extended with pause/snooze/skip-next/
schedule states.

Semantics preserved from that original script:

- Active time accumulates only while the user is not idle. "Idle" means
  the session is locked OR X/compositor idle time exceeds the *lenient*
  ``idle_threshold``.
- A pending transition only fires when input is more recent than the
  *strict* ``recent_input_threshold`` and the session is unlocked, so the
  desk never moves during the ambiguous window where the user may have
  stepped away without locking.
- Activity after an idle period resets the active-time accumulator, when
  the absence lasted at least ``idle_threshold``. Plain idleness always
  qualifies — it cannot be noticed until it has already run that long —
  but a lock or a session switch is noticed the instant it happens, so a
  brief one keeps the cycle instead of discarding it.
- A wall-clock jump in either direction larger than
  ``TIME_JUMP_THRESHOLD_SECONDS`` (suspend/resume, or a clock correction)
  resets the accumulator without moving the desk. That is an *absolute* 300s,
  deliberately not the reference script's ``5 * check_interval`` — see the
  constant for why the two were uncoupled.
- Each cycle's target duration is the base duration plus 0..N random
  whole minutes (N = ceil(variation/60)).
- Every ``sync_interval`` the actual desk height is read; if it disagrees
  with the internal state, the state is synchronized and timers reset.
- A transition is verified by comparing the resulting height to the
  intended preset target within ``movement_tolerance``; anything else is
  an interruption, handled per ``interruption_policy``. The reference
  script's behaviour is the "undo" default: return once to the *original*
  (start) height, never re-attempting the target.

Extensions (approved deviations):
- ``interruption_policy`` also offers "leave" (accept the height the desk
  stopped at) and "retry" (re-issue the move toward the target). Either
  way recovery is attempted exactly once.
- pause / snooze-until / outside-schedule freeze the active-time clock:
  no accumulation and no transitions while frozen; idle bookkeeping and
  periodic sync continue.
- being *away* (switched to another session on the seat) freezes the same
  clock and additionally suspends all desk IO: the desk is shared, and the
  session in front owns it. Returning reconciles unconditionally.
- skip-next consumes the next due transition without moving the desk and
  starts a fresh cycle in the current state.
- ``reset_after_resume()`` lets the daemon apply the time-jump reset
  eagerly on logind's PrepareForSleep signal.

The machine is pure with respect to time and randomness: callers supply
``now`` (epoch seconds) on every call and an ``rng`` at construction.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import NamedTuple

from .config import AppConfig
from .schedule import is_schedule_active

# A gap between ticks larger than this means the machine was almost certainly
# asleep (suspend/resume) rather than running — no plausible loop stall lasts
# this long. An absolute seconds value, deliberately *not* scaled off
# check_interval: the "was the machine off?" question has nothing to do with how
# often the loop ticks, and coupling them made a small check_interval trigger-
# happy and a large one sloppy. logind's PrepareForSleep catches the normal case
# deterministically; this is the fallback when that signal is unavailable.
TIME_JUMP_THRESHOLD_SECONDS = 300

# While held off-cycle, poll at least this often even when the periodic
# ``sync_interval`` is disabled (0), so the desk returning to a preset is
# still noticed and automation can resume without app interaction.
HELD_POLL_INTERVAL = 5 * 60


# StrEnum, not `str, Enum`: under the latter `str(DeskState.SITTING)` yields
# "DeskState.SITTING", so a single missed `.value` puts a Python repr into the
# journal *and* into the translated Activity Log — gui/log_catalog's `_state`
# falls through to `str(value)` for anything it doesn't recognize. The wire
# values are held out of the repr by roughly twenty hand-written `.value` calls
# in daemon/main.py; StrEnum makes forgetting one harmless. Every existing
# `.value` keeps working.
class DeskState(StrEnum):
    SITTING = "sitting"
    STANDING = "standing"

    @property
    def opposite(self) -> "DeskState":
        return DeskState.STANDING if self is DeskState.SITTING else DeskState.SITTING


_PRESET_FOR_STATE = {DeskState.SITTING: "sit", DeskState.STANDING: "stand"}


class Status(StrEnum):
    ACTIVE = "active"
    # The last scheduled move produced no evidence the desk moved: the command
    # *and* the height read-back both failed. This is not a claim about
    # current reachability — on-demand BLE means the daemon isn't polling and
    # won't find out until the next scheduled attempt — only that the last
    # attempt didn't happen.
    MOVE_FAILED = "move-failed"
    UNCONFIGURED = "unconfigured"  # no desk address yet; nothing to automate
    DISABLED = "disabled"  # [automation] enabled = false; manual use only
    PAUSED = "paused"
    SNOOZED = "snoozed"
    OUT_OF_SCHEDULE = "out-of-schedule"
    HELD = "held"  # desk parked off sit/stand; cycling paused (yield policy)
    # No graphical session for this account (headless, SSH, a daemon started
    # before login). Nothing to automate — there is no seat to sit at — and no
    # presence signal either, since the idle providers are all session-scoped.
    NO_SESSION = "no-session"
    AWAY = "away"  # switched to another session (VT / fast-user-switch)
    LOCKED = "locked"
    USER_IDLE = "user-idle"


# The states in which no cycle is running down: either there is nothing to
# automate, or the active-time clock is frozen. (Some of those freezes do have
# a scheduled end — snooze and out-of-schedule — but nothing is counting down
# meanwhile, which is what this set is about.) See
# :meth:`StateMachine.cycle_target`.
#
# Public because the GUI needs the same answer: any duration derived from
# ``active_time`` is a stopped clock in these states, so the tray tooltip has
# to know which they are. Kept here rather than restated over there — a second
# list would drift the first time a status is added.
NO_CYCLE_STATUSES = frozenset({
    Status.UNCONFIGURED, Status.DISABLED, Status.PAUSED, Status.SNOOZED,
    Status.OUT_OF_SCHEDULE, Status.HELD,
})

# The states a user can resume *from* by hand — what the tray's and Overview's
# Pause/Resume control toggles between.
RESUMABLE_STATUSES = frozenset({Status.PAUSED, Status.SNOOZED})

# The states in which a countdown is genuinely running down, so a remaining
# time is worth rendering. A failed last move does *not* stop the cycle — the
# next attempt is still coming — which is why MOVE_FAILED is in here and is
# the part that keeps getting forgotten when this is restated by hand.
COUNTDOWN_STATUSES = frozenset({Status.ACTIVE, Status.MOVE_FAILED})


# --- Events emitted by tick()/start() for logging, stats and D-Bus signals ---

@dataclass(frozen=True)
class Event:
    pass


@dataclass(frozen=True)
class IdleChanged(Event):
    idle: bool
    idle_ms: int
    # On the way back: whether the absence was long enough to abandon the
    # approach to the current target. A brief one keeps it (see ``tick``).
    reset: bool = False


@dataclass(frozen=True)
class AwayChanged(Event):
    """The user switched to another session (VT switch / fast-user-switch) or
    switched back. Emitted on the away edge instead of ``IdleChanged`` so the
    log names the real reason rather than a generic "now idle"."""
    away: bool
    reset: bool = False  # as IdleChanged.reset; only meaningful on the return


@dataclass(frozen=True)
class SeatChanged(Event):
    """This account gained or lost a graphical session. Without one there is
    no seat to sit at and no working presence signal, so automation stands
    down — explicit commands still work. Emitted instead of ``IdleChanged``
    on that edge, for the same reason ``AwayChanged`` is."""
    has_seat: bool
    reset: bool = False  # as IdleChanged.reset; only meaningful on the return


@dataclass(frozen=True)
class TransitionHeldForInput(Event):
    """A transition came due while the strict recent-input threshold said the
    user isn't at the keyboard, so the desk stayed put.

    Edge-triggered — emitted when the hold begins, not on every tick it lasts.
    The move is still due and the cycle length is unchanged; only its timing is
    now "whenever input returns", which is why this carries no target."""
    idle_ms: int
    threshold_seconds: int


@dataclass(frozen=True)
class TimeJumpDetected(Event):
    elapsed: float


@dataclass(frozen=True)
class TransitionSkipped(Event):
    state: DeskState
    next_target_duration: int


@dataclass(frozen=True)
class TransitionCompleted(Event):
    previous: DeskState
    intended: DeskState
    result: DeskState
    interrupted: bool
    # What was done about an interruption, per ``interruption_policy``:
    # "none" (nothing — either it wasn't interrupted, or the policy is
    # "leave"), "undo" (moved back toward the start height) or "retry"
    # (moved toward the target again). Never more than one recovery move.
    recovery: str
    final_height: float | None  # None = height unreadable, result assumed
    trigger: str  # "automation"
    # How long the cycle that starts here will run. Stamped by ``tick`` after
    # ``_begin_cycle`` rolls it, since the move resolves before the new cycle
    # exists; 0 on a directly-constructed event that never restarted a cycle.
    next_target_duration: int = 0


@dataclass(frozen=True)
class StateSynced(Event):
    previous: DeskState
    current: DeskState
    height: float
    next_target_duration: int = 0


@dataclass(frozen=True)
class HeldOffCycle(Event):
    """A sync found the desk at an off-cycle position (not within tolerance
    of any cycle preset) and the yield policy paused cycling."""
    height: float


@dataclass(frozen=True)
class ResumedOnCycle(Event):
    """The desk returned to a cycle preset after being held off-cycle;
    cycling resumes. ``previous`` is the state held before going off-cycle."""
    previous: DeskState
    current: DeskState
    height: float
    next_target_duration: int = 0


@dataclass(frozen=True)
class SyncFailed(Event):
    """Periodic sync could not read the desk height."""


@dataclass(frozen=True)
class MoveFailed(Event):
    """A scheduled move never happened: the move command failed *and* the
    height couldn't be read back, so there is no evidence the desk moved at
    all. Distinct from ``TransitionCompleted(final_height=None)``, which is the
    command-succeeded-but-unverifiable case that assumes the intended state."""
    previous: DeskState  # the state kept, since nothing moved
    intended: DeskState
    next_target_duration: int = 0


class _Presence(NamedTuple):
    """What one tick's presence inputs mean for the rest of that tick."""

    idle: bool  # accounting and movement are both suspended
    unentitled: bool  # away or seatless: desk IO is suspended too
    unentitled_edge: bool  # ...and this tick is the edge into or out of it
    events: list[Event]  # the idle/away/seat edges to report


class StateMachine:
    def __init__(
        self,
        config: AppConfig,
        desk,
        *,
        now: float,
        rng: random.Random | None = None,
        on_moving: Callable[[bool], None] | None = None,
    ):
        self._cfg = config
        self._desk = desk
        self._rng = rng or random.Random()
        #: Called True when an automation move starts and False when it has
        #: finished (including its interruption recovery). The daemon owns the
        #: `Desk1.Moving` property, but only it and the *manual* move path knew
        #: about it, so the flag was never true while automation drove the
        #: desk: the GUI and tray reported it stationary mid-travel, and the
        #: repeat-to-cancel gesture could not cancel an automation move — it
        #: started a competing one instead.
        self._on_moving = on_moving

        self.state: DeskState = DeskState.SITTING
        self.active_time: float = 0.0
        self.target_duration: int = 0
        self.is_idle: bool = False
        self.is_away: bool = False
        # No graphical session for this account: nothing to automate, and no
        # claim on a desk that belongs to whoever does have one.
        self.is_seatless: bool = False
        self.paused: bool = False
        self.snooze_until: float | None = None
        self.skip_next: bool = False
        # Held off-cycle: the desk is parked away from sit/stand and the
        # yield policy has paused cycling until it returns to a preset.
        self.held: bool = False
        # No desk address configured yet (fresh install, setup wizard not run).
        # Set by the daemon from config. Without it the machine happily runs a
        # full phantom cycle against a desk that isn't there — rolling targets,
        # firing pre-move notifications and recording transitions — which is
        # both useless and, on a multi-user machine, other people's problem.
        self.unconfigured: bool = False
        # Set when a scheduled move produced no evidence the desk moved
        # (command and read-back both failed); cleared by the next move that
        # reaches the desk, automation or manual.
        self.move_failed: bool = False
        self.last_height: float | None = None

        self._enabled = config.automation.enabled
        self._last_check = now
        self._last_sync = now
        self._last_idle_ms = 0
        # Edge latch for TransitionHeldForInput: a hold lasts as long as the
        # user is away, and one line per tick for an hour is not a log.
        self._held_for_input = False
        self._last_locked = False
        self._last_away = False
        self._last_seatless = False
        # When the current absence began (None while present). Decides whether
        # returning keeps the accumulated cycle or starts over — see ``tick``.
        self._idle_since: float | None = None
        # Whether this cycle has already had its pre-decide height read (so
        # we sync once, not every tick, inside the lead window).
        self._synced_before_decide = False

    # ----- lifecycle -----

    async def start(self, now: float) -> list[Event]:
        """Adopt the desk's actual position as the initial state.

        This is *initialization*, not a transition: we seed ``state`` from
        the current height directly, **without** emitting an event. Emitting
        one here would record a phantom ``sitting -> <actual> external``
        transition into stats and the Activity Log on every restart (the
        seeded default is SITTING). The daemon reports the adopted state
        separately via its "Initial state: ..." log line, so nothing is lost.

        If the desk boots off-cycle (not at a sit/stand preset) under the
        yield policy, we start **held** — no cycling until it returns to a
        preset. Under the adopt policy we classify to the nearer preset and
        run, as before. Genuine external moves are still detected/labelled by
        the periodic sync in ``tick``/``_sync``.
        """
        if self.unconfigured:
            # Nothing to adopt and nothing to cycle: stay inert rather than
            # reading a desk that isn't there and seeding a cycle against it.
            self._seed_cycle(now)
            return []
        height = await self._desk.get_height()
        if height is not None:
            self.last_height = height
            cycle_state = self._cycle_state_for_height(height)
            if cycle_state is not None:
                self.state = cycle_state
            else:
                # Off-cycle at boot: seed state from the nearer preset so a
                # toggle-while-held reflects the real position rather than the
                # bare SITTING default. Under yield we still hold (no cycling);
                # under adopt we classify and run.
                self.state = self._classify(height)
                if (self._cfg.automation.enabled
                        and self._cfg.automation.external_move_policy != "adopt"):
                    self.held = True
        self._seed_cycle(now)
        return []

    def start_without_desk_read(self, now: float) -> None:
        """Initialize without reading the desk — the same end state ``start``
        reaches on an unreadable height, minus the read.

        Lets the daemon seed a cycle immediately and adopt the real position
        from a background read. Without it ``target_duration`` would stay at
        its constructed 0, which never fires a transition and shows as a
        permanent "0m left" in the UI."""
        self._seed_cycle(now)

    def _seed_cycle(self, now: float) -> None:
        """Arm the first cycle and the tick/sync clocks, shared by both
        ``start`` paths so they cannot drift.

        Nothing is scheduled when there is no desk configured, when the desk
        is held off-cycle, or when automation is switched off — seeding a live
        countdown for a cycle that isn't running would contradict the status
        the UI is showing."""
        self.target_duration = (
            0 if (self.unconfigured or self.held
                  or not self._cfg.automation.enabled)
            else self._next_target_duration(self.state))
        self._synced_before_decide = False
        self._last_check = now
        self._last_sync = now

    async def tick(self, now: float, idle_ms: int, locked: bool,
                   away: bool = False, seatless: bool = False) -> list[Event]:
        """One iteration of the control loop. Call every check_interval.

        ``away`` — the user switched to another session (VT / fast-user-switch).
        It gates accounting and movement exactly like ``locked`` (time stops,
        no move), but is surfaced separately: its own status (``AWAY``) and its
        own edge event (``AwayChanged``) instead of the generic ``IdleChanged``.
        Unlike ``locked`` it also suspends *reading* the desk, because away
        means another session may be driving it — see ``_periodic_sync``.

        ``seatless`` — this account has no graphical session at all (headless,
        SSH, a daemon started before login). Gates identically to ``away``:
        there is no seat to sit at, so there is nothing to automate, and the
        desk belongs to whoever does have one. Kept a separate argument for the
        same reason ``away`` is — so the status and the log name the real
        reason. The two are mutually exclusive: you cannot be switched away
        from a session you do not have.
        """
        config = self._cfg.automation
        events: list[Event] = []
        self._last_idle_ms, self._last_locked, self._last_away = (
            idle_ms, locked, away)
        self._last_seatless = seatless

        if self.unconfigured:
            # No desk to drive: no accounting, no syncing, no notifications
            # (target_duration stays 0, which is what gates the daemon's
            # pre-move warning) until the setup wizard supplies an address.
            self._last_check = now
            return []

        time_elapsed = now - self._last_check

        # Suspend/resume detection by wall-clock jump. ``now`` is wall clock, so
        # the step can also go *backwards* (an NTP correction after a long
        # offline stretch, a dual-boot RTC fix, a restored VM snapshot). A
        # negative elapsed is never a real tick, and letting it through would
        # subtract from active_time — silently pushing the next move further
        # out, with nothing logged. Treat either direction as a jump.
        is_time_jump = not (0 <= time_elapsed <= TIME_JUMP_THRESHOLD_SECONDS)
        if is_time_jump:
            events.append(TimeJumpDetected(time_elapsed))
            self._reset_accumulator()

        presence = self._update_presence(now, idle_ms, locked, away, seatless)
        events.extend(presence.events)

        frozen = self._frozen(now)

        if (not presence.idle and not is_time_jump and not frozen
                and not self.held):
            self.active_time += time_elapsed

        # Transition check: gated by the strict recent-input threshold and
        # not while frozen/held, or while this session isn't entitled to the
        # desk. Seatless also means idle_ms is meaningless (every provider is
        # session-scoped and reports 0, "assume active"), so without this gate
        # the strict threshold would wave every move through.
        recently_active = ((not locked) and (not presence.unentitled)
                           and (idle_ms < config.recent_input_threshold * 1000))

        def can_act() -> bool:
            return (not frozen and not self.held and recently_active
                    and self.target_duration > 0)

        # Report the gate, once per hold. Only when the move is otherwise ready
        # to go: a hold that nothing was waiting on isn't news, and frozen/held
        # already have their own lines saying why nothing is happening.
        if (not frozen and not self.held and self.target_duration > 0
                and self.active_time >= self.target_duration
                and not recently_active):
            if not self._held_for_input:
                self._held_for_input = True
                events.append(TransitionHeldForInput(
                    idle_ms, config.recent_input_threshold))
        elif recently_active:
            self._held_for_input = False

        # Sync-before-decide: once a transition enters its lead window (or is
        # due), read the real desk height *before* warning or moving, so a
        # decision is never made on a position up to sync_interval out of
        # date. Reconciling here may adopt an external move (resetting the
        # cycle) or hold off-cycle (yield) — either way the transition below
        # is re-evaluated against fresh reality.
        if (can_act() and not self._synced_before_decide
                and self.time_remaining() <= self._sync_lead_time()):
            self._synced_before_decide = True
            events.extend(await self._sync(now))
            frozen = self._frozen(now)

        if can_act() and self.active_time >= self.target_duration:
            if self.skip_next:
                self.skip_next = False
                self._begin_cycle(self.state)
                events.append(TransitionSkipped(self.state, self.target_duration))
            else:
                moved = await self._execute_transition(now)
                self._begin_cycle(self.state)
                # A move's events are stamped with the new cycle length here,
                # not at construction: the cycle can only be rolled once the
                # move has resolved (its outcome decides which state we're
                # starting a cycle in), so the number doesn't exist yet inside
                # _execute_transition.
                events.extend(
                    replace(e, next_target_duration=self.target_duration)
                    for e in moved)

        events.extend(await self._periodic_sync(now, presence))

        self._last_check = now
        return events

    def _update_presence(self, now: float, idle_ms: int, locked: bool,
                         away: bool, seatless: bool) -> _Presence:
        """Fold this tick's presence inputs into the idle/away/seat state, and
        report the edges the rest of the tick and the log care about."""
        config = self._cfg.automation
        events: list[Event] = []

        # Entitlement edges (switched to another session; gained or lost a
        # graphical session). Tracked separately from idle so the log names the
        # real reason rather than "now idle", and so the idle edge below can be
        # guarded against double-logging it. The events themselves are emitted
        # after the idle block, which is what decides whether the cycle
        # survived the absence.
        away_edge = away != self.is_away
        seat_edge = seatless != self.is_seatless
        if away_edge:
            self.is_away = away
        if seat_edge:
            self.is_seatless = seatless
        # Both suspend the desk entirely; only the reported reason differs.
        unentitled, unentitled_edge = (away or seatless), (away_edge or seat_edge)

        # Idle bookkeeping (lenient threshold; lock, away and seatless count as
        # idle for accounting/movement). When the idle edge is caused by one of
        # the latter two, suppress IdleChanged — AwayChanged / SeatChanged
        # already reported the transition.
        currently_idle = (locked or unentitled
                          or (idle_ms >= config.idle_threshold * 1000))
        progress_reset = False
        if currently_idle and not self.is_idle:
            self.is_idle = True
            # Backdate to when the user actually left, not when we noticed.
            # Plain idleness is only spotted once idle_ms crosses the threshold,
            # so it is already that far in the past; a lock or a session switch
            # is seen the moment it happens.
            self._idle_since = now - (
                0.0 if (locked or unentitled) else idle_ms / 1000.0)
            if not unentitled_edge:
                events.append(IdleChanged(True, idle_ms))
        elif not currently_idle and self.is_idle:
            # Coming back. A real break abandons the approach to the current
            # target — the reference script's rule, and the right one after a
            # genuine absence. A *brief* interruption does not: locking the
            # screen to answer the door, or a minute in another account, used
            # to throw away three quarters of an hour of accumulated sitting,
            # because lock and away flip the idle flag instantly with no
            # duration attached. Plain idleness is unaffected either way: it
            # cannot be noticed until it has already run past the threshold.
            absence = now - self._idle_since if self._idle_since is not None else 0.0
            progress_reset = absence >= config.idle_threshold
            if progress_reset:
                self._reset_accumulator()
            else:
                self.is_idle = False
                # Re-arm regardless: the pre-decide read taken before the
                # absence describes a desk nobody was watching while it lasted.
                self._synced_before_decide = False
            self._idle_since = None
            if not unentitled_edge:
                events.append(IdleChanged(False, idle_ms, reset=progress_reset))

        if away_edge:
            events.append(AwayChanged(away, reset=progress_reset))
        if seat_edge:
            events.append(SeatChanged(not seatless, reset=progress_reset))

        return _Presence(currently_idle, unentitled, unentitled_edge, events)

    async def _periodic_sync(self, now: float, presence: _Presence) -> list[Event]:
        """Poll the actual desk height on the sync interval (``sync_interval``
        0 disables it, but a held desk still polls at ``HELD_POLL_INTERVAL`` so
        it can notice a return to a preset and resume).

        Suspended entirely while away, because the desk is shared. One machine
        with several accounts is the expected arrangement, the Linak controller
        accepts exactly one client at a time, and the session in front of the
        seat is the one entitled to it. Polling from the background would
        compete for that single slot to learn a position this session is barred
        from acting on anyway. What replaces it is the read on the way back:
        unconditional, not on the interval timer, since whoever was in front may
        have moved the desk however brief the switch."""
        if presence.unentitled:
            self._last_sync = now  # no sync debt to discharge on return
            return []
        if presence.unentitled_edge:
            return await self._sync(now)

        interval = self._cfg.automation.sync_interval
        if self.held and (interval <= 0 or interval > HELD_POLL_INTERVAL):
            # Held recovery must not lag: poll at least this often to notice a
            # return to a preset, whether periodic polling is off (0) or set
            # slower than HELD_POLL_INTERVAL.
            interval = HELD_POLL_INTERVAL
        if interval > 0 and now - self._last_sync >= interval:
            return await self._sync(now)
        return []

    # ----- controls -----

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        """Clears both pause and snooze."""
        self.paused = False
        self.snooze_until = None

    def snooze(self, minutes: int, now: float) -> None:
        self.snooze_until = now + minutes * 60

    def request_skip_next(self) -> None:
        self.skip_next = True

    def reset_after_resume(self) -> None:
        """Applied by the daemon on logind PrepareForSleep(false) — same
        effect as the time-jump heuristic, just triggered deterministically."""
        self._reset_accumulator()

    async def force_sync(self, now: float) -> list[Event]:
        """Immediate height sync (used by the daemon after manual moves so
        internal state and timers adopt the new position right away)."""
        return await self._sync(now)

    def update_config(self, config: AppConfig, *,
                      reroll_target: bool = True) -> None:
        """Hot reload. Keeps accumulated active time; recomputes the current
        cycle's target so new durations take effect immediately. A held desk
        stays held (target 0) until a sync finds it back at a preset.

        Switching automation on or off is the exception: it begins a fresh
        cycle rather than resuming the old one. Coming back on mid-cycle with
        the accumulator where it was could move the desk seconds after the
        toggle — not what "turn automation on" should feel like.

        ``reroll_target=False`` keeps the current cycle's target as it is. The
        target is a *random* draw from the configured base plus variation, so
        recomputing it when the durations did not change silently re-randomizes
        the cycle the user is already in. The daemon nudges this method on
        every config reload and the GUI nudges the daemon on every Save, so
        unconditional re-rolling meant a Save that changed nothing still moved
        the goalposts. Only the caller can tell — it holds both the old and new
        config; the machine may be handed the same object mutated in place."""
        # Tracked on the machine rather than diffed against the old config:
        # callers may hand back the *same* AppConfig object mutated in place,
        # in which case the "previous" value is already the new one.
        was_enabled = self._enabled
        self._enabled = config.automation.enabled
        self._cfg = config
        if was_enabled != config.automation.enabled:
            self._begin_cycle(self.state)
            if not config.automation.enabled:
                # Nothing is scheduled while off: leave no stale countdown for
                # the UI to show or an event to report as the "next change".
                self.target_duration = 0
            return
        if not self.held and reroll_target:
            self.target_duration = self._next_target_duration(self.state)

    # ----- introspection -----

    def status(self, now: float) -> Status:
        # Outranks everything: with no desk address there is nothing to pause,
        # snooze or schedule, and reporting "active" would be a lie.
        if self.unconfigured:
            return Status.UNCONFIGURED
        # Ranks above pause/snooze/schedule because it subsumes them: with the
        # cycle switched off there is no timer for them to act on, and the UI
        # hides their controls accordingly.
        if not self._cfg.automation.enabled:
            return Status.DISABLED
        if self.paused:
            return Status.PAUSED
        if self.snooze_until is not None and now < self.snooze_until:
            return Status.SNOOZED
        if not is_schedule_active(self._cfg.schedule, datetime.fromtimestamp(now)):
            return Status.OUT_OF_SCHEDULE
        if self.held:
            return Status.HELD
        # Outranks away and lock: with no graphical session there is nothing to
        # switch away from and no screen to lock, and both of those flags are
        # derived from providers that cannot answer here anyway.
        if self._last_seatless:
            return Status.NO_SESSION
        # Away is more specific than lock when both are true (a backgrounded
        # session can also report locked), so it wins.
        if self._last_away:
            return Status.AWAY
        if self._last_locked:
            return Status.LOCKED
        if self.is_idle:
            return Status.USER_IDLE
        # Displaces ACTIVE because reporting "active" while the last scheduled
        # move never happened is the same lie UNCONFIGURED guards against —
        # but it stays below pause/snooze/schedule/idle, where the user's own
        # intent is the more useful truth.
        if self.move_failed:
            return Status.MOVE_FAILED
        return Status.ACTIVE

    def time_remaining(self) -> float:
        return max(0.0, self.target_duration - self.active_time)

    def cycle_target(self, now: float) -> int:
        """The cycle length the user is counting toward, or 0 if none is.

        The one thing a log line needs before it can say "next change after
        ..." (rule 1 in ``docs/LOGGING.md``). Zero whenever nothing is
        counting down at all — no desk configured, automation off, the desk
        held off-cycle, or a pause / snooze / out-of-schedule freeze — so a
        line never promises a change that isn't coming.

        Deliberately *not* zero for idle, lock or away: those stop the
        accumulator advancing, but the cycle in progress is still this one and
        its length is still the answer to "when next?".
        """
        if self.status(now) in NO_CYCLE_STATUSES:
            return 0
        return int(self.target_duration or 0)

    # ----- internals -----

    def _frozen(self, now: float) -> bool:
        """Whether the active-time clock and transitions are suspended.

        Deliberately *not* a reason to skip the periodic sync: a frozen
        machine still tracks where the desk is, which is what stats are
        attributed to. Automation being switched off is the longest-lived
        freeze of all, but it is still just a freeze."""
        if not self._cfg.automation.enabled:
            return True
        if self.paused:
            return True
        if self.snooze_until is not None:
            if now < self.snooze_until:
                return True
            self.snooze_until = None
        return not is_schedule_active(self._cfg.schedule, datetime.fromtimestamp(now))

    def _classify(self, height: float) -> DeskState:
        # Split at the midpoint between the two cycle presets, so the boundary
        # tracks the user's actual sit/stand heights instead of a fixed
        # constant. Used only for off-cycle heights (recording/seeding the
        # nearer state); "am I at a preset" is the tolerance-band check in
        # _cycle_state_for_height.
        midpoint = (self._preset_height(DeskState.SITTING)
                    + self._preset_height(DeskState.STANDING)) / 2
        return DeskState.SITTING if height <= midpoint else DeskState.STANDING

    def _cycle_state_for_height(self, height: float) -> DeskState | None:
        """The cycle preset (sit/stand) the desk is *at*, within
        ``movement_tolerance`` of that preset's target — or None when the
        desk is off-cycle (an arbitrary height or a non-cycle preset).

        Unlike ``_classify`` (a bare threshold split that always returns a
        state), this is the primitive that distinguishes "at a known cycle
        position" from "parked somewhere the user chose". The cycle presets
        are exactly ``sit`` and ``stand`` today; when presets become
        first-class this set grows and the same check extends to it."""
        tolerance = self._cfg.advanced.movement_tolerance
        for state in (DeskState.SITTING, DeskState.STANDING):
            if abs(height - self._preset_height(state)) <= tolerance:
                return state
        return None

    def _preset_height(self, state: DeskState) -> float:
        return self._cfg.presets[_PRESET_FOR_STATE[state]]

    def toggle_target_preset(self) -> str:
        """Cycle preset name (``"sit"``/``"stand"``) a manual toggle should
        move to: the opposite of where the desk *is*.

        Keyed off the tracked cycle state, not a bare height threshold: if the
        desk is *at* a cycle preset (tolerance band) that preset wins — an
        external move onto sit/stand is picked up — otherwise the tracked
        ``state`` decides. That state is the position the desk came from (so an
        interrupted move resumes toward its intended target) and is seeded from
        the real height at startup, never a meaningless default. Callers read a
        fresh height first (``toggle_sit_stand``), so "at a preset" reflects the
        desk's true position. Drives the tray toggle gesture (``Desk1.Toggle``)
        and the ``--toggle`` CLI."""
        base = self.state
        if self.last_height is not None:
            at_preset = self._cycle_state_for_height(self.last_height)
            if at_preset is not None:
                base = at_preset
        return _PRESET_FOR_STATE[base.opposite]

    async def refresh_height(self, now: float) -> None:
        """Read the desk height into ``last_height`` with no other side effects,
        so a manual decision (which way to toggle) is made from the desk's real
        position — the manual counterpart of the automation pre-decide sync."""
        await self._read_height(now)

    def _reset_accumulator(self) -> None:
        """Restart the approach to the current target: zero the active-time
        clock, clear the idle flag, and re-arm the pre-decide sync. Applied
        by the idle->active edge, the time-jump heuristic, and resume-from-
        suspend — anything that abandons the accumulated progress. Re-arming
        the pre-decide flag is essential: without it a cycle that already
        read the desk before the reset would skip the read on its real due
        transition and move on a stale position."""
        self.active_time = 0.0
        self.is_idle = False
        self._synced_before_decide = False

    def _begin_cycle(self, state: DeskState) -> None:
        """Start a fresh cycle in ``state``: reset the accumulator, roll a
        new target duration, and re-arm the pre-decide sync."""
        self.state = state
        self.held = False
        self.active_time = 0.0
        self.target_duration = self._next_target_duration(state)
        self._synced_before_decide = False

    def _sync_lead_time(self) -> float:
        """How far ahead of a due transition to read the real desk height.

        With warnings on, at least the notification lead time (so the warning
        is based on fresh state), and never less than one check interval so a
        tick reliably lands inside the window before the move is due.

        With warnings off there is nothing to serve ahead of time, so the read
        collapses into the move tick itself (window 0): the reconcile still runs
        right before the move — the move block re-evaluates after it — but
        on-demand BLE connects once, at the move, instead of lighting up a tick
        early for no user-visible benefit."""
        if not self._cfg.notifications.enabled:
            return 0.0
        return max(self._cfg.notifications.lead_time,
                   self._cfg.automation.check_interval)

    def _next_target_duration(self, state: DeskState) -> int:
        config = self._cfg.automation
        if state is DeskState.SITTING:
            base, variation = config.sit_duration, config.sit_variation
        else:
            base, variation = config.stand_duration, config.stand_variation
        max_minutes = math.ceil(variation / 60)
        return base + self._rng.randint(0, max_minutes) * 60

    async def _read_height(self, now: float) -> float | None:
        height = await self._desk.get_height()
        if height is not None:
            self.last_height = height
        return height

    async def _execute_transition(self, now: float) -> list[
            MoveFailed | TransitionCompleted]:
        """Port of the reference script's run_command(): move, verify against
        the preset target within tolerance, and on interruption apply
        ``interruption_policy`` — "undo" back to the original (start) height
        (the reference's behaviour), "leave" the desk where it stopped, or
        "retry" once more toward the target."""
        self._note_moving(True)
        try:
            return await self._drive_transition(now)
        finally:
            self._note_moving(False)

    def _note_moving(self, moving: bool) -> None:
        if self._on_moving is not None:
            self._on_moving(moving)

    async def _drive_transition(self, now: float) -> list[
            MoveFailed | TransitionCompleted]:
        tolerance = self._cfg.advanced.movement_tolerance
        policy = self._cfg.automation.interruption_policy
        original = self.state
        intended = original.opposite
        intended_h = self._preset_height(intended)

        def completed(result: DeskState, *, interrupted: bool, recovery: str,
                      final_height: float | None
                      ) -> list[MoveFailed | TransitionCompleted]:
            """Land on ``result`` and report the move that got us there."""
            self.state = result
            return [TransitionCompleted(original, intended, result,
                                        interrupted=interrupted,
                                        recovery=recovery,
                                        final_height=final_height,
                                        trigger="automation")]

        moved = await self._desk.move_to(intended_h)
        height = await self._read_height(now)
        # Single derived assignment so set and clear can never drift apart:
        # every path below this point is a move that reached the desk (the
        # command went through, or the height read-back proves it), so the
        # same assignment that sets the flag on the both-failed case is what
        # clears it on every other path.
        self.move_failed = height is None and not moved
        if self.move_failed:
            # Both the command and the read-back failed — nothing says the
            # desk moved, and it usually means it was unreachable. Assuming
            # success here would flip the state, log a completed transition
            # and record it in stats, all for a move that never happened.
            return [MoveFailed(original, intended)]
        if height is None:
            # Command went through but can't be verified; assume the intended
            # state (reference behavior).
            return completed(intended, interrupted=False, recovery="none",
                             final_height=None)

        if abs(height - intended_h) <= tolerance:
            return completed(intended, interrupted=False, recovery="none",
                             final_height=height)

        # Interrupted: the desk stopped short of the target.
        if policy == "leave":
            return completed(self._classify(height), interrupted=True,
                             recovery="none", final_height=height)

        # Exactly one recovery move — "undo" back to the start height, "retry"
        # onward to the target. It is deliberately not a loop: whatever stopped
        # the desk (your hand on the paddle, a chair in the way) is likely to
        # stop it again, and a second failure is accepted wherever it left the
        # desk rather than fought. Under the "yield" external-move policy the
        # next sync then holds automation there, which is the right end state.
        recovery_h = self._preset_height(original) if policy == "undo" else intended_h
        recovered = original if policy == "undo" else intended
        await self._desk.move_to(recovery_h)
        height = await self._read_height(now)
        if height is None:
            return completed(recovered, interrupted=True, recovery=policy,
                             final_height=None)
        landed = (recovered if abs(height - recovery_h) <= tolerance
                  else self._classify(height))
        return completed(landed, interrupted=True, recovery=policy,
                         final_height=height)

    async def _sync(self, now: float) -> list[Event]:
        """Read the desk and reconcile against it, restarting the sync clock.

        The stamp lives here rather than at each call site: every caller —
        periodic, pre-decide, on the way back from another session, or the
        daemon's ``force_sync`` — did it immediately afterwards, and a sync is
        a sync however it came to be run."""
        height = await self._read_height(now)
        self._last_sync = now
        if height is None:
            return [SyncFailed()]
        return self._reconcile(height)

    def _reconcile(self, height: float) -> list[Event]:
        """Bring internal state in line with a freshly-read desk height.

        Three outcomes, keyed on whether the desk is at a *cycle* preset:
        - at the current cycle preset -> nothing to do;
        - at the *other* cycle preset (external move between sit/stand) ->
          adopt and continue with a fresh cycle (``StateSynced``);
        - off-cycle -> under "yield" hold and pause cycling
          (``HeldOffCycle``); under "adopt" classify to the nearer preset and
          continue (``StateSynced``, the legacy behaviour).
        A held desk that has returned to a cycle preset resumes
        (``ResumedOnCycle``). With automation disabled the off-cycle branch
        always classifies (never holds): a desk parked wherever the user likes
        is the normal case in manual use, not a condition to report."""
        cycle_state = self._cycle_state_for_height(height)
        if cycle_state is not None:
            return self._adopt(cycle_state, height)

        # Off-cycle. With automation switched off there is no cycle to be off
        # of, so "held" is meaningless — track the nearer preset for stats and
        # say nothing, rather than announcing that a stopped cycle is paused.
        if (not self._cfg.automation.enabled
                or self._cfg.automation.external_move_policy == "adopt"):
            return self._adopt(self._classify(height), height)

        # Yield policy: hold where the user put it.
        if self.held:
            return []
        self.held = True
        self.target_duration = 0
        return [HeldOffCycle(height)]

    def _adopt(self, state: DeskState, height: float) -> list[Event]:
        """Start a fresh cycle in ``state``, reporting how we got there.

        A hold always ends with ``ResumedOnCycle``, never ``StateSynced``, so a
        classify that lands back on the held state doesn't record a phantom
        X->X transition. Otherwise only a genuine change of state is news."""
        previous = self.state
        if self.held:
            self._begin_cycle(state)
            return [ResumedOnCycle(previous, state, height, self.target_duration)]
        if state == previous:
            return []
        self._begin_cycle(state)
        return [StateSynced(previous, state, height, self.target_duration)]
