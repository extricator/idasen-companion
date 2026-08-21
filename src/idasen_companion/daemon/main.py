"""idasen-companiond — the automation daemon.

Owns the BLE connection, runs the state machine, and exposes the D-Bus
service. Runs as a systemd user service; logs to journald via stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal as unix_signal
import sys
import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, cast

from dbus_fast import BusType, Message
from dbus_fast.aio import MessageBus
from dbus_fast.constants import RequestNameReply
from dbus_fast.errors import DBusError

from .. import DBUS_NAME, DBUS_PATH, __version__
from ..core import journal, logmsg
from ..core.config import (
    AppConfig, ConfigError, DEFAULT_CONFIG_PATH, MAX_HEIGHT, MIN_HEIGHT,
    load_config, save_config,
)
from ..core.durations import format_duration_human
from ..core.i18n import _, set_language
from ..core.machine import (
    AwayChanged, COUNTDOWN_STATUSES, DeskState, HeldOffCycle, IdleChanged,
    MoveFailed,
    ResumedOnCycle, SeatChanged, StateMachine, StateSynced, SyncFailed,
    TIME_JUMP_THRESHOLD_SECONDS, TimeJumpDetected, TransitionCompleted,
    TransitionHeldForInput, TransitionSkipped,
)
from ..core.migration import import_idasen_cli_config
from ..desk.mock import MockDesk
from ..desk.port import DeskPort

from .bluez import merge_devices, parse_paired_desks
from .dbus_util import DBusCallError, call
from .i18n import human_delay
from .idle import (
    IdleMonitor, LockMonitor, SEAT_BACKGROUND, SEAT_NONE, SEAT_UNKNOWN,
    SessionActiveMonitor,
)
from .inhibit import SleepInhibitor
from .notify import Notifier
from .ringlog import RingLog
from .service import Automation1, Desk1, Log1, Presets1, Stats1
from .stats import Stats

if TYPE_CHECKING:
    # Runtime import stays deferred to its use sites — importing BleDesk pulls
    # in bleak, which the mock and --help paths have no reason to load.
    from ..desk.ble import BleDesk

logger = logging.getLogger(__name__)

# The notification button's delay. Named for the operation it invokes: this
# button, the tray's Snooze submenu and Overview's Snooze button all call
# Automation1.Snooze, and the app names one action one way.
SNOOZE_MINUTES = 5
HEIGHT_EMIT_INTERVAL = 0.5  # throttle for live height PropertiesChanged
# How long a BLE scan's results stay good enough to hand back without scanning
# again — the answer `Discover(0)` gives the setup wizard instantly.
SCAN_CACHE_SECONDS = 60


class Daemon:
    def __init__(self, config_path: Path, *, mock_desk: bool = False,
                 stats_path: Path | None = None):
        self.config_path = config_path
        self.mock_mode = mock_desk
        # Built by `run()` before anything can reach them: `run` assigns the
        # config and desk, then exports the D-Bus interfaces that are the only
        # other way in. Declared without a value rather than set to None, so
        # the annotation stops claiming a type the attribute does not yet hold.
        self.config: AppConfig
        self.desk: DeskPort
        # The exception: `cycle_target` reads this to answer a D-Bus property
        # and guards on None, which needs the attribute to exist pre-`run`.
        self.machine: StateMachine = None  # type: ignore[assignment]
        self.activity_log = RingLog()
        if stats_path is None and mock_desk:
            # Keep simulated runs out of the user's real statistics.
            from .stats import DEFAULT_DB_PATH
            stats_path = DEFAULT_DB_PATH.with_name("stats-mock.sqlite")
        # ``ring`` is already built above, so a store that cannot even open
        # reports through the normal diagnostic channel rather than raising
        # out of __init__ (which happens before the signal handlers exist).
        self.stats = Stats(
            stats_path,
            on_error=lambda msg: self.activity_log.diag(
                "error", f"Statistics unavailable: {msg}"))
        # Sit/stand time observed during silence, held back until presence is
        # settled one way or the other (see _tick). Keyed by (day, state).
        self._pending_credit: dict[tuple[date, str], float] = {}
        # Strong references to in-flight fire-and-forget tasks. CPython holds
        # only a *weak* reference to a running task, so an unreferenced one can
        # be collected mid-execution — which for the two that release BLE links
        # means the orphaned-link state this project treats as the worst
        # outcome. See _spawn.
        self._tasks: set[asyncio.Task] = set()
        # Serializes everything that drives or reconciles the desk. dbus-fast
        # dispatches every interface method as its own task, so Sit/Stand/
        # MoveToHeight/Setup ran *concurrently* with the automation tick. The
        # damaging interleaving: the machine's _execute_transition captures the
        # state, awaits a multi-second BLE move, the user's manual move
        # preempts it at the desk layer, and the automation path then reads
        # back a height that is not its target, classifies that as an
        # interruption and applies interruption_policy — which by default moves
        # the desk *back*, undoing what the user just asked for.
        # `_current_move_id` only ever arbitrated manual-vs-manual.
        #
        # Deliberately NOT taken by `stop_movement`: Stop must be able to
        # interrupt a move that holds this lock, which is the whole point of
        # it. Taken at exactly one level per path — `_manual_move` and the
        # tick's `machine.tick` — so the paths that funnel into `_manual_move`
        # (gesture_move, toggle_sit_stand, manual_move_to_preset) must not
        # take it themselves, or they would deadlock against it.
        self._desk_lock = asyncio.Lock()
        self.moving = False
        self.desk_connected = False
        # Repeat-gesture tracking (tray/CLI): the gesture action that started
        # the move currently in flight, and the height it began at (so a repeat
        # can reverse back to it). Authoritative here, not in the client, so the
        # decision can't be fooled by lagged movement state.
        self._gesture_action: str | None = None
        self._gesture_start_height: float | None = None
        # Bumped whenever a manual move starts *or* is deliberately stopped
        # (Stop, repeat-stop/reverse, or a superseding move). A move only
        # returns to its start on interruption if this hasn't changed during
        # it — i.e. the desk stopped short on its own (the physical paddle),
        # not because we told it to. That's how a software stop is told apart
        # from a paddle interruption.
        self._current_move_id = 0

        # All set by `_setup_dbus`, which runs before the D-Bus interfaces
        # that would let anything call in. Declared, not None-initialized.
        self._bus: MessageBus
        self._idle: IdleMonitor
        self._lock: LockMonitor
        self._session: SessionActiveMonitor
        self._sleep_inhibitor: SleepInhibitor
        self._notifier: Notifier
        # Genuinely optional: the system-bus connect sits in a try/except and
        # is skipped whenever logind is unavailable. Both readers guard on it.
        self._system_bus: MessageBus | None = None
        self._ifaces: dict = {}
        self._warned_this_cycle = False
        self._config_mtime: float | None = None
        self._scan_cache: tuple[float, list] | None = None
        self._last_height_emit = 0.0
        self._initial_read: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        # Whether this daemon's own link was up when the system last announced
        # a sleep. Recorded because after the resume there is no way left to
        # tell a leftover link of this daemon's from one belonging to another
        # account's daemon — BlueZ reports that the desk is connected, not to
        # whom — and dropping someone else's is exactly the tug of war the
        # connect-failure recovery already declines to start.
        self._held_link_at_sleep = False

    # ----- setup -----

    def _load_or_bootstrap_config(self) -> AppConfig:
        config = load_config(self.config_path)
        if not config.desk.mac and not self.config_path.exists():
            imported = import_idasen_cli_config()
            if imported:
                self.activity_log.emit(logmsg.SETUP_IMPORTED_CLI,
                               mac=imported.mac, presets=len(imported.presets))
                if imported.mac:
                    config.desk.mac = imported.mac
                for name, height in imported.presets.items():
                    config.presets[name] = height
                if imported.skipped:
                    self.activity_log.diag("warning",
                                   "idasen CLI positions outside this desk's "
                                   f"range, not imported: {', '.join(imported.skipped)}")
                # Never let the import wedge the first start. The file is only
                # written once save_config succeeds, so a rejected bootstrap
                # config used to fail identically on every subsequent start —
                # a crash loop under Restart=on-failure. Running on defaults
                # with the wizard still available is strictly better than not
                # running at all.
                try:
                    save_config(config, self.config_path)
                except (ConfigError, OSError) as error:
                    self.activity_log.diag("error",
                                   f"could not write the imported config: {error}")
                    return load_config(self.config_path)
        self._note_config_mtime()
        return config

    def _note_config_mtime(self) -> None:
        try:
            self._config_mtime = self.config_path.stat().st_mtime
        except OSError:
            self._config_mtime = None

    def _spawn(self, coro, what: str) -> asyncio.Task:
        """Run ``coro`` in the background, keeping it alive and audible.

        Two separate hazards this closes, both of which were per-call-site
        habits before and were forgotten at most of them:

        * CPython keeps only a weak reference to a running task, so a bare
          ``ensure_future(...)`` can be garbage-collected mid-flight. The
          worst cases here release BLE links (``_release_desk``, the old
          desk's ``disconnect`` after a MAC change) — vanishing silently
          leaves the orphaned link the shutdown path exists to prevent.
        * An exception in a detached task surfaces only as asyncio's
          "exception was never retrieved" on stderr, which the user never
          sees. ``_start_after_setup`` is the sharp one: it is the *only*
          thing that starts automation once the wizard supplies an address,
          so a failure there leaves the machine inert with no trace.
        """
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)

        def _done(finished_task: asyncio.Task) -> None:
            self._tasks.discard(finished_task)
            if finished_task.cancelled():
                return
            exc = finished_task.exception()
            if exc is not None:
                logger.exception("background task failed: %s", what,
                                 exc_info=exc)
                with contextlib.suppress(Exception):
                    self.activity_log.diag(
                        "warning", f"Could not finish {what}.")

        task.add_done_callback(_done)
        return task

    def _set_moving(self, moving: bool) -> None:
        """Publish `Desk1.Moving`, from either the automation or manual path.

        Only `_manual_move` used to touch this, so the flag was never true
        while *automation* drove the desk: the window and tray reported it
        stationary mid-travel, and `gesture_move`'s repeat-to-cancel could not
        cancel an automation move because it tests `self.moving` — it started a
        competing move instead.
        """
        if self.moving == moving:
            return
        self.moving = moving
        desk1 = self._ifaces.get("desk")
        if desk1 is not None:
            desk1.emit_properties_changed({"Moving": moving})
            desk1.MovingChanged(moving)

    def _on_idle_provider_lost(self) -> None:
        """The idle provider worked and then stopped — gnome-shell restarting,
        the KDE screensaver service going away.

        Same consequence as having none at startup, and the same catalogued
        line says it: ``get_idle_ms`` reports a flat 0 from here on, which
        reads as "at the keyboard right now", so the desk cycles on a plain
        schedule. Previously this reached nobody — the warning went to
        ``logger``, i.e. stdout, which ``journal.read_recent`` classes as
        diagnostic, so it was not in the D-Bus feed at all.
        """
        self.activity_log.emit(logmsg.IDLE_NO_PROVIDER)
        auto = self._ifaces.get("automation")
        if auto is not None:
            # ...and correct the label the Overview shows, which otherwise
            # goes on naming the dead provider indefinitely.
            auto.emit_properties_changed(
                {"IdleProvider": self._idle.provider_name})

    def _unconfigured(self) -> bool:
        """No desk address to drive (and not simulating one)."""
        return not self.mock_mode and not self.config.desk.mac

    def _make_desk(self):
        if self.mock_mode:
            self.desk_connected = True
            self.activity_log.diag(
                "info",
                "Running with a MOCK desk (--mock-desk); no BLE traffic.")
            return MockDesk()
        from ..desk.ble import BleDesk

        return BleDesk(
            self.config.desk.mac,
            connection_mode=self.config.desk.connection,
            linger=self.config.desk.linger,
            on_height=self._on_live_height,
            on_connection_change=self._on_connection_change,
            # A per-attempt BLE failure is genuinely a warning, and genuinely
            # not for the person wondering why their desk moved — most are
            # retried successfully. The diagnostic channel is what keeps it out
            # of their feed, so it no longer has to be mislabelled `debug` to
            # stay out of it. This is the case docs/LOGGING.md was written for.
            on_error=lambda msg: self.activity_log.diag(
                "warning", f"BLE: {msg}"),
            on_connect_exhausted=self._handle_connect_exhausted,
        )

    def _on_connection_change(self, connected: bool) -> None:
        self.desk_connected = connected
        desk1 = self._ifaces.get("desk")
        if desk1:
            desk1.emit_properties_changed({"Connected": connected})
            desk1.ConnectedChanged(connected)

    def _on_live_height(self, height: float) -> None:
        self.machine.last_height = height
        now = time.monotonic()
        if now - self._last_height_emit >= HEIGHT_EMIT_INTERVAL:
            self._last_height_emit = now
            desk1 = self._ifaces.get("desk")
            if desk1:
                desk1.emit_properties_changed({"Height": height})
                desk1.HeightChanged(height)

    async def _release_desk(self) -> None:
        """Hand the desk back, because this session is no longer in front.

        One machine, several accounts, one desk is the expected arrangement,
        and the Linak controller accepts exactly one client at a time. The
        seat's active session — logind's ``Session.Active``, which the kernel
        arbitrates so exactly one session holds it — is this app's lease on the
        desk. Losing it means dropping the link, not merely declining to move.

        On-demand mode would let the link go on its own once ``linger``
        expires; this makes it immediate, and covers persistent mode, which
        would otherwise hold the desk hostage for a user who isn't there. Safe
        during a move: ``BleDesk.disconnect`` takes the same lock ``move_to``
        holds, so it waits for a move in flight rather than cutting one short
        (severing a live BLE link is what wedges the controller).
        """
        await self.desk.disconnect()

    async def _setup_dbus(self) -> bool:
        """Set up the session-bus service. Returns False — having set nothing
        else up — when another instance already owns the well-known name, so a
        duplicate process exits instead of running a second automation loop."""
        self._bus = await MessageBus().connect()
        self._ifaces = {
            "desk": Desk1(self),
            "automation": Automation1(self),
            "presets": Presets1(self),
            "stats": Stats1(self),
            "log": Log1(self),
        }
        for iface in self._ifaces.values():
            self._bus.export(DBUS_PATH, iface)
        reply = await self._bus.request_name(DBUS_NAME)
        if reply is not RequestNameReply.PRIMARY_OWNER:
            self.activity_log.diag(
                "warning",
                f"Another idasen-companiond already owns {DBUS_NAME} "
                f"(request_name → {reply.name}); exiting to avoid a duplicate.")
            return False
        self._notifier = Notifier(self._bus)
        self.activity_log.on_entry = self._emit_log_entry

        self._idle = await IdleMonitor.create(
            self._bus, on_lost=self._on_idle_provider_lost)
        self._lock = LockMonitor(self._bus)
        if self._idle.active_provider is None:
            # Not a footnote: with no provider, get_idle_ms() returns a flat 0
            # forever, which reads as "at the keyboard, right now". The app's
            # central promise — never move the desk while you might be away —
            # cannot be kept, and the desk moves on a plain schedule instead.
            # Today this catches Wayland compositors that are neither GNOME nor
            # KDE (see TODO.md), where none of the three providers exist.
            self.activity_log.emit(logmsg.IDLE_NO_PROVIDER)
        else:
            # Which provider won changes no behavior — it only says which code
            # path got there. Diagnostic, unlike the absence of one above.
            self.activity_log.diag(
                "info", f"Idle provider: {self._idle.provider_name}")

        await self._setup_system_bus()
        return True

    async def _setup_system_bus(self) -> None:
        """Connect the system bus and set up its three users: suspend/resume
        detection, the sleep-delay lock that makes releasing the desk before a
        suspend possible, and the seat-foreground gate.

        All three degrade to a safe default when logind can't be reached —
        time-jump detection covers a missed resume, an unheld delay lock costs
        the pre-sleep release and leaves the resume-side reconciliation to
        catch up, and an unresolvable seat reads as "foreground" — so a
        failure here is a diagnostic line, not a startup error.
        """
        try:
            # Unix descriptors are negotiated because logind hands out its
            # inhibitor locks as one; without it the reply arrives with the
            # descriptor stripped and there is nothing to hold.
            self._system_bus = await MessageBus(
                bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
            await call(self._system_bus, "org.freedesktop.DBus",
                       "/org/freedesktop/DBus", "org.freedesktop.DBus", "AddMatch",
                       "s", ["type='signal',interface='org.freedesktop.login1.Manager',"
                             "member='PrepareForSleep'"])
            self._system_bus.add_message_handler(self._on_system_message)
        except (DBusCallError, DBusError, OSError) as error:
            self.activity_log.diag("warning",
                           f"logind PrepareForSleep unavailable ({error}); "
                           f"relying on time-jump detection only.")

        # Constructed even with no system bus, in which case it delays nothing
        # and reports the shipped budget — one fewer optional collaborator for
        # every reader. Taken now rather than when a sleep is announced:
        # logind waits only for the delay locks already held at the moment it
        # announces one, so a lock taken in answer to that signal is taken too
        # late to delay anything. See inhibit.py.
        self._sleep_inhibitor = SleepInhibitor(
            self._system_bus, who="idasen-companiond",
            why="Handing the desk's Bluetooth link back before the machine sleeps")
        await self._rearm_sleep_inhibitor()

        # Seat-foreground gate: the desk belongs to whichever session is in
        # front of the seat. logind arbitrates that (exactly one active session
        # per seat), so it doubles as this app's lease on a desk shared between
        # accounts — while switched away (VT switch / fast-user-switch) we
        # neither move the desk nor read it, and release the BLE link. The idle
        # providers can't see a backgrounded session at all. Uses the same
        # system bus; degrades to "foreground" when unavailable.
        self._session = SessionActiveMonitor(self._system_bus)
        # Resolve now so the line below reflects reality. A "no graphical
        # session" verdict is deliberately *not* announced here — the first
        # tick's SeatChanged says it, so there is one line rather than two.
        if await self._session.state() == SEAT_UNKNOWN:
            self.activity_log.diag(
                "info", "Seat-foreground gate inactive (logind could not say "
                        "which session is in front; desk access not gated on "
                        "it).")
        else:
            self.activity_log.diag(
                "info", "Seat-foreground gate active (the desk is left to "
                        "whichever session is in front).")

    def _on_system_message(self, message: Message):
        if (message.interface == "org.freedesktop.login1.Manager"
                and message.member == "PrepareForSleep" and message.body):
            if message.body[0]:
                # Recorded here, synchronously, while this daemon's own view of
                # the link is still fresh — the release below is about to
                # falsify it. It is what lets the resume-side reconciliation
                # tell a leftover link of its own from one belonging to another
                # account's daemon, which is never this daemon's to drop.
                self._held_link_at_sleep = self.desk_connected
                self.activity_log.emit(logmsg.SUSPEND_SUSPENDING)
                self._spawn(self._release_desk_before_sleep(),
                            "handing the desk back before the machine sleeps")
            else:
                # Reset first, then report: the line has to state the cycle the
                # user is now on, and that isn't known until the reset has run.
                self.machine.reset_after_resume()
                self.activity_log.emit(logmsg.SUSPEND_RESUMED,
                               next_target=self._scheduled_target())
                self._spawn(self._idle.probe(), "re-checking idle detection after resume")
                self._spawn(self._rearm_sleep_inhibitor(),
                            "re-taking the sleep-delay lock after resume")
                self._spawn(self._recover_link_after_resume(),
                            "reconciling the desk's link after resume")
        return None

    async def _rearm_sleep_inhibitor(self) -> None:
        """Take a fresh logind sleep-delay lock for the next suspend.

        The lock is dropped on the way into every sleep — that is what lets the
        sleep proceed as soon as the desk is released, rather than after
        logind's whole timeout — so it has to be taken again once the machine
        is back. Idempotent, so a sleep this daemon never heard about (which
        leaves the previous lock still held) costs nothing here.
        """
        if await self._sleep_inhibitor.acquire():
            return
        self.activity_log.diag(
            "warning",
            "No logind sleep-delay lock could be taken, so there is not "
            "enough time to release the desk's Bluetooth link before the "
            "machine sleeps; a link left up will be reconciled against BlueZ "
            "on resume instead.")

    async def _release_desk_before_sleep(self) -> None:
        """Hand the desk back while the machine is still awake.

        Nothing used to, and a sleep entered inside the linger window therefore
        held the desk's one connection slot for the whole night. Not because
        the linger timer failed — asyncio's monotonic deadlines survive the
        freeze and fire on their remaining interval, measured to within 25 ms
        across five resumes — but because by the time it fires, the link it
        means to release has spent the whole sleep going stale underneath it.
        Releasing on the way *in* is also what the on-demand connection policy
        asks for on its own terms: a suspended machine cannot use the link, and
        the desk takes one client at a time.

        Bounded, and the bound is the point. logind is waiting on the lock this
        drops in its ``finally``, so the cost of anything going wrong here is a
        delayed suspend — capped at that lock's budget rather than at logind's
        whole allowance.
        """
        budget = self._sleep_inhibitor.budget
        try:
            await asyncio.wait_for(self.desk.disconnect(), budget)
        except asyncio.TimeoutError:
            self.activity_log.diag(
                "warning",
                f"Could not hand the desk back within {budget:g}s of the "
                f"system announcing a sleep; the link may survive it, and "
                f"will be reconciled against BlueZ on resume.")
        except Exception as error:
            self.activity_log.diag(
                "warning",
                f"Could not hand the desk back before the machine sleeps: "
                f"{error}")
        finally:
            # Whatever happened, stop holding the suspend up.
            self._sleep_inhibitor.release()

    async def _recover_link_after_resume(self) -> None:
        """Reconcile the desk's Bluetooth link against BlueZ after a resume.

        The safety net for the two cases the pre-sleep release cannot cover: a
        sleep this daemon was never told about, and one where the release did
        not finish inside its budget.

        It asks BlueZ rather than the desk handle on purpose. One of the two
        ways a link can survive a sleep — deliberately left undistinguished,
        see the debug session — is bleak's cached connection flag going false
        while BlueZ still holds the link, and in that state bleak's own
        ``disconnect()`` sends nothing on the wire and reports success.
        ``Device1.Connected`` is the only account of the link that cannot be
        stale in that direction.
        """
        if self.mock_mode or not self.config.desk.mac:
            return
        path = self._bluez_device_path()
        if not await self._bluez_property(path, "org.bluez.Device1",
                                          "Connected"):
            return
        if not self._held_link_at_sleep and self._other_companion_daemons():
            # Not this daemon's to drop: another account's daemon is running
            # and this one has no record of holding the link when the machine
            # went down. Same restraint as the connect-failure recovery.
            self.activity_log.diag(
                "info",
                "The desk is connected after the resume but this daemon did "
                "not hold that link; leaving it to whoever does.")
            return
        self.activity_log.diag(
            "warning",
            "The desk's Bluetooth link survived the suspend; dropping it "
            "through BlueZ and starting the next connection fresh.")
        await self._drop_bluez_link(path)
        # Even had BlueZ refused, the handle describes a link that spent the
        # sleep out of this daemon's sight. Outside mock mode the desk is
        # always a BleDesk, the same narrowing reload_config makes.
        cast("BleDesk", self.desk).forget_handle()
        self._held_link_at_sleep = False

    def _scheduled_target(self) -> int:
        """The cycle length the user is now counting toward, or 0 if none is.

        The machine decides — pause, snooze and the schedule freeze the clock
        just as thoroughly as automation being off, and reading
        ``target_duration`` directly missed all three. See rule 1 in
        docs/LOGGING.md and ``StateMachine.cycle_target``.
        """
        if self.machine is None:
            return 0
        return self.machine.cycle_target(time.time())

    def _emit_log_entry(self, entry) -> None:
        log1 = self._ifaces.get("log")
        if log1:
            log1.Entry(entry.ts, entry.level, entry.channel, entry.msg_id,
                       journal.encode_params(entry.params), entry.text)

    # ----- main loop -----

    async def run(self) -> None:
        # Signal handlers go up FIRST, before anything that can block.
        # Previously they were installed only after the initial desk read, so a
        # SIGTERM arriving during startup — two `systemctl restart`s in quick
        # succession is enough — hit Python's default disposition and killed
        # the process outright: no exception, no `finally`, no BLE disconnect.
        # The desk's single connection slot was left owned by a process that no
        # longer existed, and since nothing reclaims an orphaned link, every
        # later connect failed until bluetoothd was restarted by hand.
        loop = asyncio.get_running_loop()
        for sig in (unix_signal.SIGINT, unix_signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop_event.set)

        self.config = self._load_or_bootstrap_config()
        # Localize notifications per the [ui] language setting (default
        # "system" = the daemon's environment locale).
        set_language(self.config.ui.language)
        self.activity_log.emit(logmsg.DAEMON_STARTING, version=__version__,
                       config=str(self.config_path))
        if self._unconfigured():
            self.activity_log.emit(logmsg.SETUP_NO_DESK)

        self.desk = self._make_desk()
        now = time.time()
        self.machine = StateMachine(self.config, self.desk, now=now,
                                    on_moving=self._set_moving)
        self.machine.unconfigured = self._unconfigured()
        if not await self._setup_dbus():
            return

        # Everything past this point runs under the shutdown path, so the desk
        # is always released — including on a stop during the initial read.
        try:
            await self._run_until_stopped(now)
        finally:
            # Releasing the BLE link is the one thing in here that must not be
            # skipped. A half-open link leaves the desk believing it still has
            # a client, and it then refuses new connections — often until the
            # Bluetooth stack is reset by hand. Everything else is bookkeeping
            # and any of it can raise: the session bus may already be going
            # away under `ring.emit`, and the stats store lives on the user's
            # disk. So the release goes first, behind only the initial-read
            # cancellation (which is *using* the desk), and every bookkeeping
            # step runs inside its own guard rather than in front of the line
            # that matters.
            with self._shutdown_step("stopping the initial desk read"):
                if self._initial_read is not None and not self._initial_read.done():
                    self._initial_read.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._initial_read
            await self.desk.disconnect()
            with self._shutdown_step("logging the shutdown"):
                self.activity_log.emit(logmsg.DAEMON_STOPPING)
            with self._shutdown_step("saving held-back desk time"):
                # Stopping is not evidence the user left, so commit whatever
                # silence was still being held back rather than dropping it.
                self._flush_pending_credit()
            with self._shutdown_step("closing the statistics store"):
                self.stats.close()

    @contextlib.contextmanager
    def _shutdown_step(self, what: str):
        """Run one shutdown step; log and continue if it fails.

        Shutdown is the last chance to release the desk, so no step may be
        allowed to abort the ones after it.
        """
        try:
            yield
        except Exception:
            logger.exception("shutdown step failed: %s", what)
            with contextlib.suppress(Exception):
                self.activity_log.diag("warning",
                               f"Could not finish {what} while stopping.")

    async def _run_until_stopped(self, now: float) -> None:
        """Adopt the desk's position, then run the control loop until stopped.

        Split out of ``run`` so that all of it — the initial read included —
        sits inside the shutdown ``finally`` that releases the desk."""
        # Seed a usable cycle *before* touching the desk, then read it in the
        # background. Bounding the read was the obvious fix and the wrong one:
        # an unreachable desk takes minutes to fail (the idasen library retries
        # internally, BleDesk retries around that), so any timeout short enough
        # to keep startup snappy also cuts off the stale-link recovery before
        # it can run. Not blocking at all is simpler and strictly better —
        # D-Bus is already served by this point, so all the wait ever bought
        # was the "Initial state:" line arriving sooner.
        self.machine.start_without_desk_read(now)
        self._initial_read = asyncio.ensure_future(self._adopt_initial_state())
        if self._stop_event.is_set():
            return

        while not self._stop_event.is_set():
            interval = self.config.automation.check_interval
            started = time.monotonic()
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A tick that raises used to unwind the control loop and exit,
                # which systemd restarts into a daemon that survives one tick
                # and dies again — a loop that never trips StartLimitBurst and
                # leaves the desk not moving. Keep ticking: the next one may
                # well succeed, and if it doesn't the log says so every time.
                logger.exception("control loop tick failed")
                self.activity_log.diag("error",
                               "A control-loop tick failed; automation will "
                               "retry on the next interval. See the daemon "
                               "log for the traceback.")
            # A tick that outruns its own interval means automation was
            # stalled — nothing moved, nothing was logged, and previously
            # the only trace was a bogus "time jump" once it recovered.
            overrun = time.monotonic() - started
            if overrun > interval:
                self.activity_log.diag(
                    "warning",
                    f"Control loop tick took "
                    f"{format_duration_human(overrun)} (check interval is "
                    f"{format_duration_human(interval)}); automation was "
                    f"stalled for that long.")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)

    async def _entitled_to_desk(self) -> bool:
        """Whether this session may touch the desk on its own initiative.

        True when it is in front of its seat, and also when logind could not
        say — uncertainty has always meant "carry on" here, and one hiccup must
        never be able to switch a working install off. False only on a definite
        answer: another session is in front, or this account has no graphical
        session at all."""
        return await self._session.state() not in (SEAT_BACKGROUND, SEAT_NONE)

    async def _adopt_initial_state(self) -> None:
        """Read the desk once and adopt its real position, off the critical
        path. ``start`` does this silently — no transition is recorded — and
        the line logged here is the user-facing report of it.

        Runs alongside the control loop, which is already ticking on the
        seeded default. The cost is that the loop may account one tick against
        that default before the real position lands; the alternative — holding
        the entire daemon while an unreachable desk finishes failing — is what
        made a stuck desk look like a stuck app.

        Skipped outright when the desk isn't ours to touch — another session is
        in front, or this account has no graphical session. A daemon starting
        into the background (a restart during someone else's session, an
        install scriptlet) must not open the shared desk's one connection slot
        just to seed a cycle it is barred from acting on. The edge back to
        entitlement reconciles instead, which is the same read a tick later.
        """
        if not await self._entitled_to_desk():
            self.activity_log.emit(logmsg.STARTUP_DESK_NOT_OURS)
            return
        try:
            await self.machine.start(time.time())
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.activity_log.emit(logmsg.STARTUP_READ_FAILED, error=str(error))
            return
        if self.machine.unconfigured:
            return  # reported at startup already; there is nothing to adopt
        height = self.machine.last_height
        if height is None:
            self.activity_log.emit(logmsg.STARTUP_HEIGHT_UNAVAILABLE)
        elif self.machine.held:
            self.activity_log.emit(logmsg.STARTUP_STATE_HELD, height=height)
        elif not self.config.automation.enabled:
            # No cycle is scheduled with automation off, so don't report a
            # "first target duration" of zero as if one were.
            self.activity_log.emit(logmsg.STARTUP_STATE_AUTOMATION_OFF,
                           state=self.machine.state.value, height=height)
        else:
            self.activity_log.emit(logmsg.STARTUP_STATE,
                           state=self.machine.state.value, height=height,
                           next_target=self._scheduled_target())
            # Only on this path: a cycle is actually running, so its clock is
            # the thing that just went back to zero. Not emitted from
            # _start_after_setup, where the first cycle is beginning rather
            # than restarting, and there is no lost progress to disclose.
            self.activity_log.emit(logmsg.STARTUP_CYCLE_RESET)
        self._emit_periodic_properties()

    async def _tick(self) -> None:
        self._check_config_file()

        tick_time = time.time()
        idle_ms = await self._idle.get_idle_ms()
        locked = await self._lock.is_locked()
        # This session's claim on the seat. A backgrounded session (VT switch /
        # fast-user-switch) and one with no graphical session at all both pause
        # accounting and block moves just like a lock; each is passed separately
        # (not folded into `locked`) so the machine can surface it as its own
        # status and log line. The idle providers can see neither: they are
        # session-scoped, so a session that isn't in front stops advancing its
        # counter, and no session at all reports a flat 0 — "assume active".
        seat = await self._session.state()
        away = seat == SEAT_BACKGROUND
        seatless = seat == SEAT_NONE

        state_before = self.machine.state
        held_before = self.machine.held
        last_check_before = self.machine._last_check
        # Held across the whole tick, not just the move: the machine's
        # transition captures state before its await and writes it back after,
        # so a manual move landing in between is what corrupted it.
        async with self._desk_lock:
            events = await self.machine.tick(tick_time, idle_ms, locked, away, seatless)

        self._account_desk_time(state_before.value, tick_time - last_check_before,
                                held=held_before, idle_ms=idle_ms,
                                absent=locked or away or seatless)

        for event in events:
            self._handle_event(event, trigger="automation")

        await self._maybe_warn(tick_time)
        self._emit_periodic_properties()

    def _account_desk_time(self, state: str, elapsed: float, *, held: bool,
                           idle_ms: int, absent: bool) -> None:
        """Attribute ``elapsed`` seconds to ``state``'s daily total.

        Real elapsed time goes to the position the desk was in, regardless of
        automation freeze states — pause and snooze stop the cycle, not the
        clock you are sitting through.

        Presence is a guess whenever there's no input: a silent stretch is
        either the user reading at the desk (real sit/stand time) or an empty
        chair, and the two look identical while they last. So a silent window
        is held back rather than credited, and settled only once something
        proves which it was — input inside a later window means the user was
        there for the silence too, while the away threshold (or a lock, a
        switched-away session, a suspend-sized gap — all of which arrive here
        as ``absent``) proves they weren't. Crediting silence outright is what
        used to bank ~idle_threshold of phantom "active" time on every break,
        permanently.
        """
        # Don't credit a suspend-sized gap to sit/stand totals (the stats-side
        # twin of the machine's time-jump reset); shared absolute threshold, and
        # the same both-directions rule — a backward clock step would otherwise
        # write negative seconds into a daily row, permanently.
        elapsed_is_plausible = 0 <= elapsed <= TIME_JUMP_THRESHOLD_SECONDS
        idle_threshold_ms = self.config.automation.idle_threshold * 1000
        if not elapsed_is_plausible or absent or idle_ms >= idle_threshold_ms:
            self._pending_credit.clear()
        elif held:
            pass  # off-cycle: the desk is at neither preset, so neither gets it
        elif idle_ms / 1000.0 < elapsed:
            # Input landed inside this window: the user is here now, which
            # settles the silence leading up to it as time at the desk.
            self._flush_pending_credit()
            self.stats.add_active_time(state, elapsed)
        else:
            key = (date.today(), state)
            self._pending_credit[key] = self._pending_credit.get(key, 0.0) + elapsed

    def _flush_pending_credit(self) -> None:
        """Commit time held back during silence, now that presence is proven.

        Keyed by day and state, not just totalled: a silent stretch can cross
        midnight or span a desk move, and each part belongs to the row it was
        actually spent in.
        """
        for (day, state), seconds in self._pending_credit.items():
            self.stats.add_active_time(state, seconds, day)
        self._pending_credit.clear()

    def _check_config_file(self) -> None:
        try:
            mtime = self.config_path.stat().st_mtime
        except OSError:
            return
        # A None mtime — the file did not exist at startup and does now —
        # compares unequal like any other change, so it reloads and adopts the
        # mtime. It must not be read as "watching disabled": the old guard
        # required a non-None mtime *and* never assigned one on that branch, so
        # once None it stayed None and hot-reload was dead for the rest of the
        # process's life — silently, on a fresh install with no config to
        # import, which is exactly when the user hand-writes their MAC into the
        # file the README says hot-reloads.
        if mtime == self._config_mtime:
            return
        self._config_mtime = mtime
        self.reload_config()

    async def _maybe_warn(self, now: float) -> None:
        ncfg = self.config.notifications
        remaining = self.machine.time_remaining()
        if not ncfg.enabled or self.machine.target_duration <= 0:
            return
        # Arm on the reliable window: at least one check_interval wide, so a tick
        # is guaranteed to land inside it. A bare lead_time window narrower than
        # the tick could be jumped clean over, silently dropping the warning.
        # Consequence: a lead_time shorter than check_interval effectively rounds
        # up to check_interval (the warning fires that far ahead, announcing the
        # real remaining time). Firing at exactly lead_time regardless of the
        # tick needs the timer-based rework tracked in TODO.md.
        window = max(ncfg.lead_time, self.config.automation.check_interval)
        if remaining > window:
            self._warned_this_cycle = False
            return
        # A failed last move doesn't stop the cycle — the next attempt is
        # still coming — so the pre-move warning must keep firing for it too;
        # otherwise it would silently switch off until the next success.
        if (self._warned_this_cycle
                or self.machine.status(now) not in COUNTDOWN_STATUSES):
            return
        self._warned_this_cycle = True
        to_state = self.machine.state.opposite
        seconds = max(1, int(remaining))
        self._ifaces["automation"].PreMoveWarning(to_state.value, seconds)
        delay = human_delay(seconds)
        # Full sentences (not "verb" + fragment) so translators control word order.
        if to_state is DeskState.STANDING:
            summary = _("Standing up in about %s") % delay
        else:
            summary = _("Sitting down in about %s") % delay
        # Fire and forget: whether a popup was drawn is none of the control
        # loop's business, and awaiting the notification server here puts a
        # third-party GUI process on the critical path of every move.
        self._spawn(self._notifier.send(
            summary,
            _("The desk will move once you're due."),
            actions={
                "snooze": (_("Snooze %d min") % SNOOZE_MINUTES,
                           lambda: self.snooze(SNOOZE_MINUTES)),
                "skip": (_("Skip this one"), self.skip_next),
            },
        ), "showing the pre-move warning")

    def _handle_event(self, event, trigger: str) -> None:
        if isinstance(event, IdleChanged):
            if event.idle:
                self.activity_log.emit(logmsg.PRESENCE_NOW_IDLE,
                               idle_time=event.idle_ms / 1000)
            else:
                self._on_presence_returned(event.reset,
                                           logmsg.PRESENCE_ACTIVE_RESET,
                                           logmsg.PRESENCE_ACTIVE_KEPT)
        elif isinstance(event, AwayChanged):
            if event.away:
                self.activity_log.emit(logmsg.PRESENCE_AWAY)
                self._spawn(self._release_desk(), "handing the desk back")
            else:
                self._on_presence_returned(event.reset,
                                           logmsg.PRESENCE_BACK_RESET,
                                           logmsg.PRESENCE_BACK_KEPT)
        elif isinstance(event, SeatChanged):
            if not event.has_seat:
                self.activity_log.emit(logmsg.PRESENCE_NO_SEAT)
                self._spawn(self._release_desk(), "handing the desk back")
            else:
                self._on_presence_returned(event.reset,
                                           logmsg.PRESENCE_SEAT_BACK_RESET,
                                           logmsg.PRESENCE_SEAT_BACK_KEPT)
        elif isinstance(event, TransitionHeldForInput):
            self.activity_log.emit(logmsg.TRANSITION_HELD_FOR_INPUT,
                           idle_time=event.idle_ms / 1000,
                           threshold=event.threshold_seconds)
        elif isinstance(event, TimeJumpDetected):
            # Forward and backward steps read as different events to a user, so
            # they get different sentences; the parameter is unsigned either way.
            line = (logmsg.TIME_JUMP if event.elapsed >= 0
                    else logmsg.TIME_STEPPED_BACK)
            self.activity_log.emit(line, elapsed=abs(event.elapsed),
                           next_target=self._scheduled_target())
        elif isinstance(event, TransitionSkipped):
            self.activity_log.emit(
                logmsg.CYCLE_SKIPPED, state=event.state.value,
                next_target=event.next_target_duration)
        elif isinstance(event, TransitionCompleted):
            self._on_transition(event)
        elif isinstance(event, StateSynced):
            self.activity_log.emit(logmsg.CYCLE_SYNCED,
                           previous=event.previous.value,
                           current=event.current.value, height=event.height,
                           next_target=event.next_target_duration)
            self._record_transition(event.previous, event.current, "external")
        elif isinstance(event, HeldOffCycle):
            self.activity_log.emit(logmsg.CYCLE_HELD_OFF, height=event.height)
            if self.config.notifications.enabled:
                self._spawn(self._notifier.send(
                    _("Automation paused"),
                    _("The desk was moved to an unrecognized position. It will "
                      "resume once the desk is back at sit or stand.")),
                    "showing the automation-paused notification")
        elif isinstance(event, ResumedOnCycle):
            self.activity_log.emit(
                logmsg.CYCLE_RESUMED_ON, current=event.current.value,
                height=event.height,
                next_target=event.next_target_duration)
            if event.previous is not event.current:
                self._record_transition(event.previous, event.current, "external")
        elif isinstance(event, SyncFailed):
            self.activity_log.emit(logmsg.CYCLE_SYNC_FAILED)
        elif isinstance(event, MoveFailed):
            self._on_move_failed(event)

    def _on_move_failed(self, event: MoveFailed) -> None:
        """The one place a genuine "the desk didn't move" becomes visible.

        Per-attempt BLE errors go to the diagnostic channel (noisy, and most
        are retried successfully), so carry the last one along as the reason —
        otherwise this warning says something failed but not why.
        """
        reason = self.desk.last_error
        if reason:
            self.activity_log.emit(logmsg.CYCLE_MOVE_FAILED_REASON,
                           intended=event.intended.value,
                           previous=event.previous.value, reason=str(reason),
                           next_target=event.next_target_duration)
        else:
            self.activity_log.emit(logmsg.CYCLE_MOVE_FAILED,
                           intended=event.intended.value,
                           previous=event.previous.value,
                           next_target=event.next_target_duration)
        if not self.config.notifications.problems:
            return
        # The cycle has already restarted, so a whole interval is now at stake
        # — and every existing record of that (activity log, journal, Overview,
        # tray tooltip) has to be gone and looked at. "Try now" is what makes
        # the lost interval something you choose to ignore rather than
        # something that happens to you. Its own field, not `enabled`: that one
        # announces what automation is about to *do*.
        standing = event.intended is DeskState.STANDING
        preset = "stand" if standing else "sit"
        # Full sentences (not "verb" + fragment) so translators control word
        # order.
        if standing:
            summary = _("The desk didn't stand up")
        else:
            summary = _("The desk didn't sit down")
        if reason:
            body = _("It didn't respond (%s). The next change is a "
                     "whole interval away.") % reason
        else:
            body = _("It didn't respond. The next change is a whole "
                     "interval away.")
        # Fire and forget, like the pre-move warning: whether a popup was drawn
        # is none of the control loop's business.
        self._spawn(self._notifier.send(
            summary, body,
            actions={"try-now": (
                _("Try now"),
                lambda: self._spawn(self._retry_failed_move(preset),
                                    "retrying the failed move"))},
        ), "showing the failed-move notification")

    def _on_presence_returned(self, reset: bool, reset_message: logmsg.Message,
                              kept_message: logmsg.Message) -> None:
        """The user is back — from plain idleness, another session, or no
        session at all. Whether the absence lasted long enough to abandon the
        cycle picks the line.

        One helper for all three because of what the reset branch has to carry:
        the accumulator went back to zero, so the line has to say what it is now
        counting toward, and the reset events carry no next_target_duration of
        their own — the cycle length is unchanged, only the progress was
        discarded — so it comes off the machine. See rule 1 in docs/LOGGING.md.
        """
        if reset:
            self.activity_log.emit(
                reset_message, next_target=self._scheduled_target())
        else:
            self.activity_log.emit(kept_message)

    async def _retry_failed_move(self, preset: str) -> None:
        """Move to ``preset`` because the user pressed "Try now".

        Wrapped rather than scheduled straight onto the loop: a retry that
        fails again raises ``DBusError`` with nobody to receive it, and a bare
        task turns that into an asyncio "exception was never retrieved"
        traceback. The move already logs its own outcome (``MANUAL_MOVE_FAILED``
        and friends), so the only job left here is not to crash the loop.

        No retry *policy* — one attempt, because the user asked for it. The
        desk layer already retries up to eight times over ~15s beneath this,
        so anything automatic here would be that count multiplied against a
        controller that accepts exactly one connection.
        """
        try:
            await self.manual_move_to_preset(preset)
        except Exception as error:
            self.activity_log.diag("warning",
                           f"'Try now' retry of the failed move to "
                           f"{preset!r} did not work either: {error}")

    def _on_transition(self, event: TransitionCompleted) -> None:
        common = dict(intended=event.intended.value, result=event.result.value,
                      height=event.final_height,
                      next_target=event.next_target_duration)
        if not event.interrupted:
            self.activity_log.emit(logmsg.TRANSITION_COMPLETED,
                           previous=event.previous.value,
                           result=event.result.value,
                           height=event.final_height,
                           next_target=event.next_target_duration)
        elif event.recovery == "undo":
            self.activity_log.emit(
                logmsg.TRANSITION_INTERRUPTED_UNDO, **common)
        elif event.recovery == "retry":
            self.activity_log.emit(
                logmsg.TRANSITION_INTERRUPTED_RETRY, **common)
        else:
            self.activity_log.emit(
                logmsg.TRANSITION_INTERRUPTED_LEFT, **common)
        self._record_transition(event.previous, event.result, event.trigger,
                                event.interrupted)
        self._warned_this_cycle = False

    def _record_transition(self, previous: DeskState, current: DeskState,
                           trigger: str, interrupted: bool = False) -> None:
        """Persist a position change and announce it on the bus.

        The two always go together — the row the Statistics page totals and the
        signal the Overview reacts to describe the same event — so they are
        issued from one place rather than being re-paired by hand at each of
        the four paths that can change the desk's classified position.
        """
        self.stats.record_transition(previous.value, current.value, trigger,
                                     interrupted)
        self._ifaces["automation"].TransitionCompleted(
            previous.value, current.value, interrupted)

    def _emit_automation_state(self) -> None:
        """Announce automation status/progress on the bus immediately.

        Called right after a control op (pause/resume/skip/snooze/reload) so
        clients update within the D-Bus round-trip instead of waiting up to a
        full ``check_interval`` for the next periodic tick."""
        auto = self._ifaces["automation"]
        auto.emit_properties_changed({
            "Enabled": self.config.automation.enabled,
            "Status": self.status_string(),
            "ActiveTime": self.machine.active_time,
            "TargetDuration": float(self.machine.target_duration),
            "TimeRemaining": self.machine.time_remaining(),
            "SnoozeUntil": self.machine.snooze_until or 0.0,
            "SkipNextPending": self.machine.skip_next,
        })
        auto.StatusChanged(self.status_string())
        auto.ProgressChanged(self.machine.active_time,
                             float(self.machine.target_duration))

    def _emit_periodic_properties(self) -> None:
        self._emit_automation_state()
        desk1 = self._ifaces["desk"]
        position = self.position_string()
        height = self.machine.last_height or 0.0
        desk1.emit_properties_changed({
            "Position": position,
            "Height": height,
            "Connected": self.desk_connected,
        })
        desk1.PositionChanged(position)
        desk1.HeightChanged(height)
        desk1.ConnectedChanged(self.desk_connected)

    # ----- control operations (called from D-Bus interfaces) -----

    def status_string(self) -> str:
        return self.machine.status(time.time()).value

    def position_string(self) -> str:
        """Wire desk position. Empty while held off-cycle: the desk isn't at a
        sit/stand preset, so reporting the stale last state would mislabel the
        Overview title and tray tooltip as "Sitting"/"Standing"."""
        return "" if self.machine.held else self.machine.state.value

    def idle_provider_name(self) -> str:
        """The idle provider in use, or "starting" before one is picked.

        ``getattr``, not ``self._idle``: the attribute is annotation-only until
        ``_setup_dbus`` builds the monitor, and that happens *after* the same
        method exports the interfaces and requests the name. So the window this
        fallback exists for is the one where the attribute does not exist yet,
        and a plain access raises AttributeError instead — which dbus-fast
        catches while emitting InterfacesAdded, dropping every Automation1
        property out of that signal.
        """
        idle = getattr(self, "_idle", None)
        return idle.provider_name if idle else "starting"

    def set_automation_enabled(self, enabled: bool) -> None:
        """Turn the sit/stand cycle on or off, persistently.

        Written to config rather than held in memory (that is what Pause is
        for): this is a preference that must survive a restart. Saving the file
        is also what makes it reach the GUI's Settings page, which reads config
        from disk. Follows save_preset's pattern — the daemon owns the write,
        clients ask over D-Bus."""
        # Pick up a hand edit first. `self.config` lags the file by up to one
        # check_interval, and `save_config` rewrites *every* key from memory —
        # so without this, editing the file and then toggling automation from
        # the tray within the same minute silently reverted the edit, and
        # nothing reloaded afterwards because we stamp our own mtime below.
        self._check_config_file()
        if self.config.automation.enabled == enabled:
            return
        previous = self.config.automation.enabled
        self.config.automation.enabled = enabled
        try:
            save_config(self.config, self.config_path)
        except (ConfigError, OSError) as error:
            # Mutating before writing left the daemon running on state that is
            # not on disk when the write failed — and reporting "disabled"
            # from status() while the machine still said enabled, because the
            # update_config below never ran.
            self.config.automation.enabled = previous
            raise DBusError(f"{DBUS_NAME}.Error.ConfigWriteFailed",
                            f"could not save the configuration: {error}") from error
        self._note_config_mtime()
        self.machine.update_config(self.config)
        self.activity_log.emit(logmsg.AUTOMATION_ENABLED if enabled
                       else logmsg.AUTOMATION_DISABLED)
        self._emit_automation_state()

    def pause(self) -> None:
        self.machine.pause()
        self.activity_log.emit(logmsg.AUTOMATION_PAUSED)
        self._emit_automation_state()

    def resume(self) -> None:
        self.machine.resume()
        self.activity_log.emit(logmsg.AUTOMATION_RESUMED)
        self._emit_automation_state()

    def skip_next(self) -> None:
        self.machine.request_skip_next()
        self.activity_log.emit(logmsg.AUTOMATION_SKIP_NEXT)
        self._emit_automation_state()

    def snooze(self, minutes: int) -> None:
        minutes = max(1, int(minutes))
        self.machine.snooze(minutes, time.time())
        self.activity_log.emit(logmsg.AUTOMATION_SNOOZED, minutes=minutes)
        self._emit_automation_state()

    def reload_config(self) -> None:
        try:
            new_config = load_config(self.config_path)
        except ConfigError as error:
            self.activity_log.emit(logmsg.CONFIG_RELOAD_FAILED, error=str(error))
            return
        previous_config = self.config
        # The activity channel records *changes*, not requests (rule 2 in
        # docs/LOGGING.md). The GUI nudges the daemon on every Save whether or
        # not the file differs, so an unconditional line filled the Activity
        # Log with an event that told the user nothing about their desk — 163
        # identical lines in one morning, from a test harness that wasn't even
        # pointed at this config.
        changed = new_config != previous_config
        # Re-rolling the cycle target is the same question wearing a different
        # hat: the target is a random draw from these four, so recomputing it
        # when they haven't changed re-randomizes the cycle the user is in.
        cycle_fields_changed = (
            (previous_config.automation.sit_duration, previous_config.automation.stand_duration,
             previous_config.automation.sit_variation, previous_config.automation.stand_variation)
            != (new_config.automation.sit_duration,
                new_config.automation.stand_duration,
                new_config.automation.sit_variation,
                new_config.automation.stand_variation))
        self.config = new_config
        set_language(new_config.ui.language)  # notifications follow the setting
        self.machine.update_config(new_config,
                                   reroll_target=cycle_fields_changed)
        was_unconfigured = self.machine.unconfigured
        self.machine.unconfigured = self._unconfigured()
        if not self.mock_mode:
            if new_config.desk.mac != previous_config.desk.mac:
                self.activity_log.emit(logmsg.CONFIG_DESK_MAC_CHANGED)
                self._swap_desk()
            else:
                # Outside mock mode the desk is always a BleDesk, and these
                # two are its own tuning knobs rather than part of DeskPort.
                desk = cast("BleDesk", self.desk)
                desk.connection_mode = new_config.desk.connection
                desk.linger = new_config.desk.linger
        if changed:
            self.activity_log.emit(logmsg.CONFIG_RELOADED)
        else:
            # It did happen, and someone chasing "did my config reach the
            # daemon?" wants to see it. It just isn't activity.
            self.activity_log.diag("debug", "Config reload requested; file is "
                                    "unchanged, nothing to apply.")
        if was_unconfigured and not self.machine.unconfigured:
            # The setup wizard just supplied an address. start() adopts the
            # desk's real position and rolls the first target, the same way it
            # does at boot — without it the machine would stay inert forever.
            self.activity_log.emit(logmsg.SETUP_STARTING_AUTOMATION)
            self._spawn(self._start_after_setup(), "starting automation after setup")
        self._note_config_mtime()
        # Durations may have changed the target/progress; announce now.
        self._emit_automation_state()

    async def _start_after_setup(self) -> None:
        await self.machine.start(time.time())
        self.activity_log.emit(
            logmsg.STARTUP_STATE, state=self.machine.state.value,
            height=self.machine.last_height,
            next_target=self._scheduled_target())
        self._emit_automation_state()

    async def manual_move_to_preset(self, name: str) -> None:
        height = self.config.presets.get(name)
        if height is None:
            raise DBusError(f"{DBUS_NAME}.Error.UnknownPreset",
                            f"no preset named {name!r}")
        # A preset/gesture move that's cut short by the physical paddle returns
        # to where the desk was (like the reference script and the automation
        # path), rather than parking off-cycle. Capture that position now.
        await self._manual_move(height, f"preset '{name}'",
                                return_to=self.machine.last_height)

    async def toggle_sit_stand(self, *, refresh: bool = True) -> None:
        """Move to whichever of sit/stand the desk is *not* at. Backs the tray
        toggle gesture and the ``--toggle`` CLI, so the decision lives here
        (authoritative height) rather than in each caller. Reads the real height
        first (the manual pre-decide sync) so an external move — e.g. onto a
        preset — is reflected before the direction is chosen; ``refresh=False``
        skips that read when the caller (``gesture_move``) already did it."""
        if refresh:
            await self.machine.refresh_height(time.time())
        await self.manual_move_to_preset(self.machine.toggle_target_preset())

    async def gesture_move(self, action: str) -> None:
        """A tray/keyboard *gesture* move (``toggle``/``sit``/``stand``) with
        repeat-to-cancel semantics, per ``[ui] tray_repeat_move``.

        Repeating the *same* gesture while its move is still running cancels it:
        ``stop`` halts the desk where it is, ``reverse`` sends it back to the
        height the move began at, ``off`` just re-issues the move. A *different*
        action redirects (the desk layer preempts the move in flight). The
        decision lives here rather than in the client so it can't be fooled by
        lagged movement state or the on-demand connect delay — the plain
        ``Sit``/``Stand``/``Toggle`` methods still move unconditionally."""
        if action not in ("toggle", "sit", "stand"):
            raise DBusError(f"{DBUS_NAME}.Error.UnknownGesture",
                            f"unknown gesture action {action!r}")
        repeat = self.config.ui.tray_repeat_move
        if self.moving and action == self._gesture_action and repeat != "off":
            # Bound to a local so the "a successor is coming" decision and the
            # height that successor uses cannot drift apart, and so the None
            # check narrows for the call below.
            reverse_to = (self._gesture_start_height
                          if repeat == "reverse" else None)
            self._gesture_action = None
            await self.stop_movement(expect_successor=reverse_to is not None)
            if reverse_to is not None:
                self.activity_log.emit(logmsg.GESTURE_REVERSE)
                await self.manual_move_to_height(reverse_to)
            else:
                self.activity_log.emit(logmsg.GESTURE_STOP)
            return
        self._gesture_action = action
        # A pre-move height read is a full BLE round-trip that delays the move,
        # so only do it when something actually needs the fresh position:
        #   - toggle must read to decide which way to go;
        #   - an explicit sit/stand already knows its target, and only needs an
        #     accurate reverse target when a repeat gesture will reverse to it.
        # In every other case we skip the read and start moving a round-trip
        # sooner, using the cached pre-move height as the (unused) start point.
        needs_read = action == "toggle" or self.config.ui.tray_repeat_move == "reverse"
        if needs_read:
            await self.machine.refresh_height(time.time())
        self._gesture_start_height = self.machine.last_height
        if action == "toggle":
            await self.toggle_sit_stand(refresh=False)
        else:
            await self.manual_move_to_preset(action)

    async def manual_move_to_height(self, height: float) -> None:
        if not (MIN_HEIGHT <= height <= MAX_HEIGHT):
            raise DBusError(f"{DBUS_NAME}.Error.OutOfRange",
                            f"height {height:.3f}m outside "
                            f"{MIN_HEIGHT}-{MAX_HEIGHT}m")
        await self._manual_move(height, f"{height:.3f}m")

    async def _manual_move(self, height: float, label: str,
                           *, return_to: float | None = None) -> None:
        """Move the desk to ``height``. If ``return_to`` is given and the move
        is cut short *on its own* (the physical paddle stops it before the
        target), return once to ``return_to`` — the same interruption handling
        the automation path uses, gated on ``interruption_policy``.

        Manual moves honour only "undo" (return) and "leave" (stay put);
        "retry" behaves as "leave" here. Automation retries because it is
        honouring a schedule you configured once and aren't watching, whereas
        a companion move you stop by hand is a live instruction to stop —
        re-issuing it would have the app pushing back against the paddle in
        your hand.
        A move ended by a deliberate stop (Stop, a repeat-stop/reverse gesture,
        or a superseding move) does *not* return: those bump
        ``_current_move_id``, and the return only runs while this move's id is
        still the current one. Callers that must not bounce back (the slider's
        explicit target, the reverse gesture) also leave ``return_to`` as
        None."""
        async with self._desk_lock:
            await self._manual_move_locked(height, label, return_to=return_to)

    async def _manual_move_locked(self, height: float, label: str,
                                  *, return_to: float | None = None) -> None:
        self._current_move_id += 1
        move_id = self._current_move_id
        self.activity_log.emit(logmsg.MANUAL_MOVE, target=label)
        self._set_moving(True)
        try:
            move_accepted = await self.desk.move_to(height)
            if not move_accepted:
                # The D-Bus error reaches whoever asked, but a tray gesture or
                # a CLI call can leave no one looking — log it too, at a level
                # that actually reaches journald.
                reason = self.desk.last_error
                if reason:
                    self.activity_log.emit(logmsg.MANUAL_MOVE_FAILED_REASON,
                                   target=label, reason=str(reason))
                else:
                    self.activity_log.emit(
                        logmsg.MANUAL_MOVE_FAILED, target=label)
                raise DBusError(f"{DBUS_NAME}.Error.MoveFailed",
                                "desk command failed; see daemon log")
            # The desk accepted this move, so it's demonstrably reachable —
            # clear a stale move-failed status now rather than waiting for the
            # next periodic tick, and announce the change immediately.
            if self.machine.move_failed:
                self.machine.move_failed = False
                self._emit_automation_state()
            # move_to returning True doesn't mean the target was reached; read
            # the height back to detect a *physical* interruption and, if
            # enabled, return once to where the desk started. Skip it when we
            # stopped or superseded this move ourselves (id changed) — that
            # keeps a software stop put and a redirect on its new target.
            if (return_to is not None
                    and self.config.automation.interruption_policy == "undo"
                    and move_id == self._current_move_id):
                actual = await self.desk.get_height()
                tolerance = self.config.advanced.movement_tolerance
                if actual is not None and abs(actual - height) > tolerance:
                    self.activity_log.emit(
                        logmsg.MANUAL_INTERRUPTED, target=label,
                        actual=actual, return_to=return_to)
                    await self.desk.move_to(return_to)
        finally:
            # Only the current move owns the shared "moving" flag. If a newer
            # move superseded this one (a preempt/redirect, or the reverse that
            # follows a repeat gesture), leave the flag True for that move to
            # clear — otherwise this move's exit would report the desk stopped
            # while it's still travelling, flickering the tray and letting the
            # next repeat gesture start a fresh move instead of cancelling.
            if move_id == self._current_move_id:
                self._set_moving(False)
        if move_id != self._current_move_id:
            # Superseded mid-move (preempt/redirect/reverse): skip our own
            # reconciliation. Reading the height now would catch the desk still
            # travelling under the newer move and could briefly flag it
            # off-cycle ("automation paused"); the move that replaced us reads
            # the real final position and reports it.
            return
        for event in await self.machine.force_sync(time.time()):
            # A manual move that changes the classified position (adopting a
            # new state, or resuming from a hold) is an intentional transition,
            # not an "external" one — record it as such. ResumedOnCycle may
            # land on the same state (previous == current); only a real change
            # is a transition.
            if isinstance(event, (StateSynced, ResumedOnCycle)):
                if event.previous is not event.current:
                    self.activity_log.emit(
                        logmsg.MANUAL_SYNCED, current=event.current.value,
                        height=event.height,
                        next_target=getattr(event, "next_target_duration", 0))
                    self._record_transition(event.previous, event.current,
                                            "manual")
            else:
                self._handle_event(event, trigger="manual")
        self._emit_periodic_properties()
        if self.machine.is_away:
            # An explicit request is honoured even from a backgrounded session
            # — you asked for it, over D-Bus or the CLI, so the desk moves —
            # but the link it opened is not this session's to keep while
            # someone else is in front. Hand it straight back. Read from the
            # machine's cached away flag so the manual path costs no extra
            # system-bus round trip.
            await self._release_desk()

    async def stop_movement(self, *, expect_successor: bool = False) -> None:
        """Stop the desk where it is.

        ``expect_successor`` says a follow-up move is about to be issued (the
        repeat-gesture reverse), so the "moving" flag should stay up for that
        move to own and clear. Everything else — Overview's Stop button,
        ``--stop``, ``Desk1.Stop`` from any client — is the end of the story
        and must tear the move state down here.
        """
        # Deliberate stop: invalidate any in-flight move's return-to-start so a
        # software stop stays put rather than bouncing back like an interruption.
        self._current_move_id += 1
        await self.desk.stop()
        self.activity_log.emit(logmsg.MANUAL_STOPPED)
        if expect_successor:
            return
        # Bumping the sequence above is exactly what stops the in-flight
        # `_manual_move` from clearing these in its own `finally`: it steps
        # aside for a successor that, on this path, never comes. Left set,
        # `moving` stays true forever (nothing else clears it, and the periodic
        # property emit does not include Moving), and the stale `moving` plus
        # `_gesture_action` pair makes the *next* gesture for the same
        # direction take the repeat-to-cancel branch — so pressing Stand a
        # second time reversed the desk down to the sit height instead.
        self._gesture_action = None
        self._set_moving(False)

    async def discover(self, timeout: int) -> list[tuple[str, str]]:
        """Known paired desks (from BlueZ) plus live scan results, paired
        first. timeout=0 returns paired devices + cached scan instantly."""
        if self.mock_mode:
            return [("Desk 0000 (mock)", "00:11:22:33:44:55")]

        known = await self._bluez_known_desks()

        timeout = max(0, int(timeout))
        if timeout == 0:
            # The age test and the subscript live in one expression so mypy can
            # narrow `cache` from `tuple[...] | None`. Held apart in a separate
            # boolean, the narrowing was lost by the time `cache[1]` was read
            # and mypy called the optional tuple not indexable.
            cache = self._scan_cache
            scanned = (cache[1]
                       if cache is not None
                       and time.time() - cache[0] < SCAN_CACHE_SECONDS
                       else [])
        else:
            from ..desk.ble import discover_desks

            self.activity_log.emit(logmsg.SCAN_STARTED)
            try:
                scanned = await discover_desks(min(timeout, 30))
            except Exception as error:
                self.activity_log.emit(logmsg.SCAN_FAILED, error=str(error))
                scanned = []
            else:
                self.activity_log.emit(
                    logmsg.SCAN_FINISHED, count=len(scanned))
            self._scan_cache = (time.time(), scanned)
        return merge_devices(known, scanned)

    def _bluez_device_path(self) -> str:
        """BlueZ object path for the configured desk (hci0 only, matching the
        rest of the app's single-adapter assumption)."""
        return f"/org/bluez/hci0/dev_{self.config.desk.mac.upper().replace(':', '_')}"

    def _other_companion_daemons(self) -> list[int]:
        """PIDs of other idasen-companiond processes on this machine.

        One desk, one machine, several accounts is the *expected* arrangement,
        not an anomaly — each logged-in user's session runs its own daemon and
        they all want the same desk. Ownership is settled by the seat lease
        (see ``_release_desk``), not by this scan; what this is for is the case
        where the lease has evidently not been honoured, so the recovery below
        can decline to drop a link that may still belong to someone else.
        """
        own_pid = os.getpid()
        found = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit() or int(entry.name) == own_pid:
                continue
            try:
                argv = (entry / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue  # exited, or another user's process we can't read
            if any(arg.rsplit(b"/", 1)[-1] == b"idasen-companiond"
                   for arg in argv if arg):
                found.append(int(entry.name))
        return found

    async def _bluez_property(self, path: str, iface: str, name: str):
        if self._system_bus is None:
            return None
        try:
            body = await call(self._system_bus, "org.bluez", path,
                              "org.freedesktop.DBus.Properties", "Get", "ss",
                              [iface, name])
        except (DBusCallError, DBusError):
            return None
        return body[0].value if body else None

    async def _handle_connect_exhausted(self) -> bool:
        """Every connect attempt failed. Record the state of the Bluetooth
        stack, then decide whether anything can safely be cleared.

        The snapshot is the primary job. A desk that went unreachable for 45
        minutes could not be explained afterwards because nothing recorded what
        BlueZ thought at the time; this makes a repeat diagnose itself.

        Returns whether something changed that is worth retrying for.
        """
        if not self.config.desk.mac:
            return False
        path = self._bluez_device_path()
        connected = await self._bluez_property(path, "org.bluez.Device1",
                                               "Connected")
        paired = await self._bluez_property(path, "org.bluez.Device1", "Paired")
        rssi = await self._bluez_property(path, "org.bluez.Device1", "RSSI")
        powered = await self._bluez_property("/org/bluez/hci0",
                                             "org.bluez.Adapter1", "Powered")
        discovering = await self._bluez_property("/org/bluez/hci0",
                                                 "org.bluez.Adapter1",
                                                 "Discovering")
        others = self._other_companion_daemons()
        # The snapshot exists so a repeat outage diagnoses itself. It is a real
        # warning and means nothing at all to a desk user, which is exactly the
        # combination the diagnostic channel is for.
        self.activity_log.diag(
            "warning",
            f"Could not reach the desk. BlueZ reports: connected={connected}, "
            f"paired={paired}, rssi={rssi}, adapter powered={powered}, "
            f"scanning={discovering}; other companion daemons running: "
            f"{others or 'none'}.")

        if not connected:
            return False  # nothing in the way; the failure is something else

        if others:
            # Shared desk: another account's daemon is running and BlueZ holds
            # a connection we can't use. Dropping it would just start a fight
            # neither side wins, and it is very likely being used right now —
            # a daemon releases the desk when its session leaves the seat, but
            # not instantly (a move in flight finishes first), so a link that
            # is on its way out looks exactly like one that is staying.
            # This one *is* activity: it says why the desk won't move for you,
            # and what to do about it is a real-world action.
            self.activity_log.emit(logmsg.DESK_HELD_BY_OTHER,
                           pids=", ".join(map(str, others)))
            return False

        self.activity_log.diag(
            "warning",
            "The desk is connected but unreachable from here, with no other "
            "companion daemon running; dropping that connection and retrying.")
        return await self._drop_bluez_link(path)

    async def _drop_bluez_link(self, path: str) -> bool:
        """Ask BlueZ itself to drop the desk's connection. Returns success.

        Deliberately not routed through the desk handle. Every caller is a
        case where the handle's own account of the link is the thing not to be
        trusted: one has no handle for that link at all, and the other has one
        that may believe it is already disconnected — in which case bleak
        sends nothing on the wire and reports success.
        """
        if self._system_bus is None:
            return False
        try:
            await call(self._system_bus, "org.bluez", path,
                       "org.bluez.Device1", "Disconnect")
        except (DBusCallError, DBusError) as error:
            self.activity_log.diag("warning",
                           f"Could not drop the desk connection: {error}")
            return False
        return True

    async def _bluez_known_desks(self) -> list[tuple[str, str]]:
        """Desks already paired via the system Bluetooth settings."""
        if self._system_bus is None:
            return []
        try:
            body = await call(self._system_bus, "org.bluez", "/",
                              "org.freedesktop.DBus.ObjectManager",
                              "GetManagedObjects")
        except (DBusCallError, DBusError) as error:
            self.activity_log.diag("debug", f"BlueZ device query failed: {error}")
            return []
        return parse_paired_desks(body[0])

    async def setup_desk(self, desk_mac: str) -> float:
        """First-run onboarding: verify we can actually talk to the desk
        (connect, best-effort pair, read height) BEFORE saving the MAC.
        Returns the current height on success."""
        desk_mac = desk_mac.strip()
        if not desk_mac:
            raise DBusError(f"{DBUS_NAME}.Error.SetupFailed", "empty address")

        if self.mock_mode:
            height = await self.desk.get_height()
            if height is None:
                raise DBusError(f"{DBUS_NAME}.Error.SetupFailed",
                                "mock desk reported no height")
        else:
            from ..desk.ble import BleDesk

            self.activity_log.emit(logmsg.SETUP_TESTING_DESK, mac=desk_mac)
            candidate = BleDesk(
                desk_mac, connection_mode="on-demand", linger=1,
                on_error=lambda m: self.activity_log.diag(
                    "debug", f"setup: {m}"))
            try:
                height = await candidate.get_height()
                if height is None:
                    raise DBusError(
                        f"{DBUS_NAME}.Error.SetupFailed",
                        "Could not connect to the desk. Make sure it is "
                        "powered, nearby, in pairing mode (hold the button "
                        "on the control box until the light flashes), and "
                        "that nothing else is connected to it.")
                await candidate.pair()  # best-effort; returns False on failure
            finally:
                await candidate.disconnect()

        previous_mac = self.config.desk.mac
        self.config.desk.mac = desk_mac
        save_config(self.config, self.config_path)
        self._note_config_mtime()
        if not self.mock_mode and desk_mac != previous_mac:
            self._swap_desk()
        self.activity_log.emit(
            logmsg.SETUP_DESK_CONFIGURED, mac=desk_mac, height=height)
        self._spawn(self._post_setup_sync(), "syncing the desk after setup")
        return float(height)

    async def _post_setup_sync(self) -> None:
        for event in await self.machine.force_sync(time.time()):
            self._handle_event(event, trigger="setup")
        self._emit_periodic_properties()

    def _swap_desk(self) -> None:
        """Replace the desk connection after the MAC changed."""
        old_desk = self.desk
        self.desk = self._make_desk()
        self.machine._desk = self.desk
        # No hasattr guard: ``disconnect`` is on the DeskPort contract precisely
        # so the link this project treats most carefully is never released by a
        # duck-typed check that a new implementation could quietly fail.
        self._spawn(old_desk.disconnect(), "releasing the previous desk")

    async def capture_current_preset(self, name: str) -> float:
        height = await self.desk.get_height()
        if height is None:
            raise DBusError(f"{DBUS_NAME}.Error.NoHeight",
                            "could not read desk height")
        self.save_preset(name, round(height, 4))
        return round(height, 4)

    def save_preset(self, name: str, height: float) -> None:
        if not name or not (MIN_HEIGHT - 0.01 <= height <= MAX_HEIGHT + 0.01):
            raise DBusError(f"{DBUS_NAME}.Error.InvalidPreset",
                            f"invalid preset {name!r} = {height}")
        self._check_config_file()   # don't clobber a hand edit; see below
        previous = dict(self.config.presets)
        self.config.presets[name] = round(height, 4)
        self._persist_presets(previous)
        self.activity_log.emit(logmsg.PRESET_SAVED, name=name, height=height)

    def rename_preset(self, old_name: str, new_name: str) -> None:
        """Rename in one write, which is what makes it atomic.

        A client cannot do this with Save + Delete: those are two calls with
        two config writes, so anything landing between them (a crash, a
        session ending, this daemon restarting) leaves both names pointing at
        one height. Here it is a single dict mutation followed by a single
        ``_persist_presets``.

        The key is swapped in place rather than popped and re-added, so the
        order ``List`` reports is unchanged. The config *file* still moves the
        renamed preset to the end of its table: tomlkit has no rename, so
        ``save_config`` drops the old key and appends the new one."""
        new_name = new_name.strip()
        self._check_config_file()
        if old_name in ("sit", "stand"):
            raise DBusError(f"{DBUS_NAME}.Error.InvalidPreset",
                            "the sit and stand presets cannot be renamed")
        if old_name not in self.config.presets:
            raise DBusError(f"{DBUS_NAME}.Error.InvalidPreset",
                            f"no preset named {old_name!r}")
        if not new_name:
            raise DBusError(f"{DBUS_NAME}.Error.InvalidPreset",
                            "a preset needs a name")
        if new_name == old_name:
            return
        if new_name in self.config.presets:
            raise DBusError(f"{DBUS_NAME}.Error.InvalidPreset",
                            f"a preset named {new_name!r} already exists")
        previous = dict(self.config.presets)
        self.config.presets = {(new_name if name == old_name else name): height
                               for name, height in self.config.presets.items()}
        self._persist_presets(previous)
        self.activity_log.emit(logmsg.PRESET_RENAMED, old=old_name, new=new_name)

    def delete_preset(self, name: str) -> None:
        if name in ("sit", "stand"):
            raise DBusError(f"{DBUS_NAME}.Error.InvalidPreset",
                            "the sit and stand presets cannot be deleted")
        self._check_config_file()
        previous = dict(self.config.presets)
        if self.config.presets.pop(name, None) is not None:
            self._persist_presets(previous)
            self.activity_log.emit(logmsg.PRESET_DELETED, name=name)

    def _persist_presets(self, previous: dict[str, float]) -> None:
        """Write the presets, restoring ``previous`` if the write fails.

        Callers mutate ``self.config.presets`` and then call this, so a failed
        write would otherwise leave the daemon serving presets that are not on
        disk, with no PresetsChanged and no log line to say so.
        """
        try:
            save_config(self.config, self.config_path)
        except (ConfigError, OSError) as error:
            self.config.presets = previous
            raise DBusError(f"{DBUS_NAME}.Error.ConfigWriteFailed",
                            f"could not save the configuration: {error}") from error
        self._note_config_mtime()  # don't treat our own write as a hot reload
        self._ifaces["presets"].PresetsChanged(json.dumps(self.config.presets))


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="idasen-companiond",
        description="Idasen Companion automation daemon")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH,
                        help=f"config file (default: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--mock-desk", action="store_true",
                        help="simulate a desk instead of using BLE (for testing)")
    parser.add_argument("--verbose", action="store_true",
                        help="debug logging")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    daemon = Daemon(args.config, mock_desk=args.mock_desk)
    try:
        asyncio.run(daemon.run())
    except ConfigError as error:
        logger.error("invalid configuration: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
