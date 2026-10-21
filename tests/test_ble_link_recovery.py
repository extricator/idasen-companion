"""Startup robustness and connect-failure handling.

Written after a desk went unreachable for 45 minutes. Two real defects were
found and are covered here:
  1. signal handlers were installed *after* the blocking initial desk read, so
     a stop during startup skipped the shutdown path entirely — no disconnect,
     no stats flush;
  2. the initial read was unbounded, so an unreachable desk pinned the daemon
     in startup for minutes while it reported itself active with every timer
     at zero (the UI's permanent "0m left").

The connect-exhausted hook captures BlueZ state for diagnosis. It cannot
safely clear a device-wide link whose client owner is unknown.
"""

import asyncio
import os
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from idasen_companion.core.clocks import WallInstant
from idasen_companion.core.lengths import Length
from idasen_companion.daemon.idle import SEAT_BACKGROUND, SEAT_FOREGROUND, SEAT_NONE
from idasen_companion.daemon.accounting import ActiveTimeAccounting
from idasen_companion.daemon.stats import Stats
from idasen_companion.daemon import bluetooth as bluetooth_mod
from idasen_companion.daemon.bluetooth import BluetoothSupport
from idasen_companion.desk.ble import BleDesk


class FakeDesk:
    """Stand-in for the idasen library's Desk, refusing to connect."""

    def __init__(self, *, connect_ok=False):
        self.connect_ok = connect_ok
        self.connect_calls = 0
        self.is_connected = False

    async def connect(self):
        self.connect_calls += 1
        if not self.connect_ok:
            raise OSError("le-connection-abort-by-local")
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False


def _ble(on_exhausted=None, *, connect_ok=False):
    made = []

    def factory(mac, cb):
        desk = FakeDesk(connect_ok=connect_ok)
        made.append(desk)
        return desk

    ble = BleDesk("E1:B2:C3:D4:E5:F6", retry_delays=(0, 0),
                  desk_factory=factory, on_connect_exhausted=on_exhausted)
    ble.made = made
    return ble


async def test_failed_connect_records_snapshot_once_without_retrying():
    snapshots = []

    async def snapshot():
        snapshots.append(True)

    ble = _ble(on_exhausted=snapshot)
    assert await ble._ensure_connected() is False
    assert snapshots == [True]
    assert len(ble.made) == 1
    assert ble.made[0].connect_calls == 3


async def test_snapshot_is_not_taken_when_connect_succeeds():
    snapshots = []

    async def snapshot():
        snapshots.append(True)

    ble = _ble(on_exhausted=snapshot, connect_ok=True)
    assert await ble._ensure_connected() is True
    assert not snapshots


async def test_no_snapshot_hook_still_fails_cleanly():
    ble = _ble()
    assert await ble._ensure_connected() is False


# ----- the daemon releases the desk even when stopped during startup -----

def _bare_daemon(monkeypatch):
    """A Daemon with run()'s collaborators stubbed, so the test exercises the
    real ordering and the real try/finally rather than a re-creation of them."""
    from idasen_companion.core.config import AppConfig
    from idasen_companion.daemon import main as main_mod

    cfg = AppConfig()
    cfg.desk.mac = "E1:B2:C3:D4:E5:F6"
    cfg.presets = {"sit": 0.62, "stand": 1.10}

    d = main_mod.Daemon.__new__(main_mod.Daemon)

    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._ifaces = {}

    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.activity_log = MagicMock()
    d.bluetooth = BluetoothSupport(d.activity_log)
    d.stats = MagicMock()
    d.mock_mode = True
    from idasen_companion.daemon.config_file import ConfigFileStore
    d.config_file = MagicMock(spec=ConfigFileStore)
    d.config_file.path = Path("unused-config.toml")
    d.config_file.load_or_bootstrap.return_value = cfg
    d.accounting = MagicMock(spec=["start", "account", "flush"])
    d._stop_event = asyncio.Event()
    d._initial_read = None
    d.config = cfg
    d.desk = MagicMock()
    d.desk.disconnect = MagicMock(side_effect=lambda: asyncio.sleep(0))
    d._session = MagicMock()
    d._session.state = AsyncMock(return_value=SEAT_FOREGROUND)
    monkeypatch.setattr(d, "_unconfigured", lambda: False)
    monkeypatch.setattr(d, "_make_desk", lambda: d.desk)
    monkeypatch.setattr(main_mod, "set_language", lambda _l: None)
    return d


async def test_signal_handlers_are_installed_before_anything_can_block(monkeypatch):
    """The root cause. Handlers registered after the initial read meant a
    SIGTERM during startup hit Python's default disposition and killed the
    process outright — no finally, no disconnect, orphaned link."""
    from idasen_companion.daemon import main as main_mod

    order = []

    class Recorder:
        def add_signal_handler(self, sig, cb):
            order.append("handlers")

    monkeypatch.setattr(main_mod.asyncio, "get_running_loop", lambda: Recorder())
    d = _bare_daemon(monkeypatch)
    d.config_file.load_or_bootstrap.side_effect = (
        lambda: (order.append("config"), _cfg_for(d))[1])

    async def setup_dbus():
        order.append("dbus")
        return False  # stop here; ordering is what's under test

    monkeypatch.setattr(d, "_setup_dbus", setup_dbus)
    await d.run()
    assert order[0] == "handlers", f"blocking work ran before handlers: {order}"
    assert "dbus" in order


def _cfg_for(d):
    from idasen_companion.core.config import AppConfig
    cfg = AppConfig()
    cfg.desk.mac = "E1:B2:C3:D4:E5:F6"
    cfg.presets = {"sit": 0.62, "stand": 1.10}
    return cfg


async def test_stop_during_the_initial_read_still_releases_the_desk(monkeypatch):
    """A stop arriving while the initial read is in flight must still run the
    shutdown path and hand the desk back."""
    d = _bare_daemon(monkeypatch)

    async def setup_dbus():
        return True

    async def run_until_stopped(now):
        d._stop_event.set()          # SIGTERM lands mid-read
        raise asyncio.CancelledError()

    monkeypatch.setattr(d, "_setup_dbus", setup_dbus)
    monkeypatch.setattr(d, "_run_until_stopped", run_until_stopped)
    with pytest.raises(asyncio.CancelledError):
        await d.run()
    assert d.desk.disconnect.called, "desk never released on a startup stop"
    d.stats.close.assert_called_once()


@pytest.mark.parametrize("break_step", ["ring", "stats"])
async def test_bookkeeping_failures_never_cost_the_desk_release(monkeypatch,
                                                                break_step):
    """The shutdown `finally` used to emit the stopping line and flush stats
    *before* releasing the desk, both unguarded. Either raising — a bus going
    away, a full disk — exited with a live BLE link, which is the half-open
    state that makes the controller refuse new connections. Restart=on-failure
    then brings up a daemon that connects against the abandoned link.
    """
    d = _bare_daemon(monkeypatch)
    boom = RuntimeError("bus is going away")

    async def setup_dbus():
        return True

    async def run_until_stopped(now):
        # Break it here, not at construction: the startup lines are emitted
        # before the try/finally, so failing those would test something else.
        if break_step == "ring":
            d.activity_log.emit = MagicMock(side_effect=boom)
        else:
            d.accounting.flush.side_effect = boom

    monkeypatch.setattr(d, "_setup_dbus", setup_dbus)
    monkeypatch.setattr(d, "_run_until_stopped", run_until_stopped)

    await d.run()  # must not raise

    assert d.desk.disconnect.called, "desk not released when bookkeeping failed"
    d.accounting.flush.assert_called_once_with()
    d.stats.close.assert_called_once_with()


async def test_the_desk_is_released_before_the_bookkeeping(monkeypatch):
    """Ordering, not just presence: anything ahead of the release is one more
    thing that can stop it happening."""
    d = _bare_daemon(monkeypatch)
    order = []
    d.desk.disconnect = MagicMock(
        side_effect=lambda: (order.append("disconnect"), asyncio.sleep(0))[1])
    d.activity_log.emit = MagicMock(
        side_effect=lambda *a, **k: order.append("activity_log"))
    d.stats.close = MagicMock(side_effect=lambda: order.append("stats"))
    d.accounting.flush.side_effect = lambda: order.append("accounting")

    async def setup_dbus():
        return True

    async def run_until_stopped(now):
        order.clear()  # ignore the startup lines; only shutdown order matters
        return

    monkeypatch.setattr(d, "_setup_dbus", setup_dbus)
    monkeypatch.setattr(d, "_run_until_stopped", run_until_stopped)
    await d.run()

    assert order[0] == "disconnect", f"released the desk too late: {order}"
    assert order[-3:] == ["activity_log", "accounting", "stats"]


async def test_shutdown_cancels_read_then_releases_and_flushes_real_credit(monkeypatch):
    d = _bare_daemon(monkeypatch)
    order = []
    flushed_rows = []
    d.stats = Stats(Path(":memory:"))
    d.accounting = ActiveTimeAccounting(d.stats)
    owner = d.accounting
    owner.start(WallInstant(0.0))
    real_flush = owner.flush
    real_close = d.stats.close

    def flush():
        order.append("flush")
        real_flush()
        flushed_rows.extend(d.stats.daily_totals(date.today(), date.today()))

    async def initial_read():
        try:
            await asyncio.Event().wait()
        finally:
            order.append("read cancelled")

    async def run_until_stopped(now):
        d._initial_read = asyncio.create_task(initial_read())
        await asyncio.sleep(0)
        owner.account("sitting", WallInstant(60), held=False, idle_ms=60000, absent=False,
                      idle_threshold_seconds=600)
        assert d.stats.daily_totals(date.today(), date.today()) == []
        raise asyncio.CancelledError

    monkeypatch.setattr(owner, "flush", MagicMock(side_effect=flush))
    monkeypatch.setattr(d.stats, "close", MagicMock(
        side_effect=lambda: (order.append("close"), real_close())))
    d.desk.disconnect = AsyncMock(side_effect=lambda: order.append("disconnect"))
    monkeypatch.setattr(d, "_setup_dbus", AsyncMock(return_value=True))
    monkeypatch.setattr(d, "_run_until_stopped", run_until_stopped)

    with pytest.raises(asyncio.CancelledError):
        await d.run()

    assert d.accounting is owner
    assert d._initial_read.cancelled()
    owner.flush.assert_called_once_with()
    assert order == ["read cancelled", "disconnect", "flush", "close"]
    assert flushed_rows == [(date.today().isoformat(), "sitting", 60.0)]


async def test_unreadable_desk_does_not_pin_startup(monkeypatch):
    """An unreachable desk must not hold the daemon in startup: it used to
    block for ~8 minutes while reporting Status="active" with every timer at 0,
    which is what the UI rendered as a permanent "0m left"."""
    from idasen_companion.core.durations import Duration
    from idasen_companion.core.machine import StateMachine

    reached_loop = asyncio.Event()

    class Hanging:
        async def get_height(self):
            await asyncio.sleep(3600)   # never answers

    d = _bare_daemon(monkeypatch)
    d.machine = StateMachine(_cfg_for(d), Hanging(), now=WallInstant(0.0))
    d.machine.unconfigured = False
    monkeypatch.setattr(d, "_tick", lambda: _set_and_stop(reached_loop, d))

    await asyncio.wait_for(d._run_until_stopped(WallInstant(0.0)), 1.0)
    assert reached_loop.is_set(), "control loop never started"
    # A seeded cycle, not the constructed 0 that can never fire.
    assert d.machine.target_duration > Duration.from_seconds(0)
    d._initial_read.cancel()


async def _set_and_stop(event, daemon):
    event.set()
    daemon._stop_event.set()


async def test_seeded_cycle_is_replaced_once_the_desk_answers():
    """The background read still adopts the real position when it lands."""
    from idasen_companion.core.durations import Duration
    from idasen_companion.core.machine import StateMachine
    from idasen_companion.core.config import AppConfig
    from idasen_companion.desk.mock import MockDesk

    cfg = AppConfig()
    cfg.presets = {"sit": 0.62, "stand": 1.10}
    machine = StateMachine(cfg, MockDesk(height=Length(1.10)), now=WallInstant(0.0))
    machine.start_without_desk_read(WallInstant(0.0))
    seeded = machine.target_duration
    assert seeded > Duration.from_seconds(0) and machine.state.value == "sitting"  # the default

    await machine.start(WallInstant(0.0))
    assert machine.state.value == "standing", "real position was never adopted"
    # Was `!= seeded or True`, a tautology. The real property is that adopting
    # the true position re-seeds the cycle from *that* state's duration: the
    # seed above was the sitting default, the desk is standing. The target is a
    # random draw within the configured variation, hence the range.
    a = cfg.automation
    assert Duration.from_seconds(a.stand_duration) <= machine.target_duration <= (
        Duration.from_seconds(a.stand_duration + a.stand_variation))
    assert not (Duration.from_seconds(a.sit_duration) <= machine.target_duration
                <= Duration.from_seconds(a.sit_duration + a.sit_variation)), "still on the sit cycle"


# ----- a shared desk is expected, not an anomaly -----

async def test_no_link_is_dropped_while_another_users_daemon_runs(monkeypatch):
    """One machine, several accounts, one desk is the normal arrangement. If
    another companion daemon is running, a connection we can't use is very
    likely one it is using — dropping it starts a tug of war instead of
    fixing anything."""
    d = _bare_daemon(monkeypatch)
    monkeypatch.setattr(d.bluetooth, "_other_companion_daemons", lambda: [4242])
    monkeypatch.setattr(d.bluetooth, "property",
                        lambda *a: _async(True))   # BlueZ says connected

    dropped = []
    monkeypatch.setattr("idasen_companion.daemon.bluetooth.call",
                        lambda *a, **k: dropped.append(a) or _async([]))
    assert await d.bluetooth.report_connect_exhausted(d.config.desk.mac) is None
    assert not dropped, "dropped a link another user's daemon was using"


async def test_link_is_left_alone_when_we_are_the_only_daemon(monkeypatch):
    d = _bare_daemon(monkeypatch)
    monkeypatch.setattr(d.bluetooth, "_other_companion_daemons", lambda: [])
    monkeypatch.setattr(d.bluetooth, "property", lambda *a: _async(True))

    calls = []
    monkeypatch.setattr("idasen_companion.daemon.bluetooth.call",
                        lambda *a, **k: calls.append(a[-1]) or _async([]))
    assert await d.bluetooth.report_connect_exhausted(d.config.desk.mac) is None
    assert "Disconnect" not in calls
    logged = " ".join(c.args[1] for c in d.activity_log.diag.call_args_list)
    assert "cannot identify the link's owner" in logged


async def test_failure_is_always_recorded_even_when_nothing_is_dropped(monkeypatch):
    """The snapshot is the point: the original outage could not be explained
    afterwards because nothing recorded what BlueZ thought at the time."""
    d = _bare_daemon(monkeypatch)
    monkeypatch.setattr(d.bluetooth, "_other_companion_daemons", lambda: [])
    monkeypatch.setattr(d.bluetooth, "property", lambda *a: _async(False))
    assert await d.bluetooth.report_connect_exhausted(d.config.desk.mac) is None
    # Diagnostic channel: a real warning that means nothing to a desk user.
    logged = " ".join(c.args[1] for c in d.activity_log.diag.call_args_list)
    for field in ("connected=", "paired=", "adapter powered=", "scanning="):
        assert field in logged, f"{field} missing from the failure snapshot"
    assert all(c.args[0] == "warning"
               for c in d.activity_log.diag.call_args_list)


async def test_exhaustion_callback_reads_current_mac_after_desk_construction(monkeypatch):
    from idasen_companion.desk import ble as ble_mod

    daemon = _bare_daemon(monkeypatch)
    daemon.mock_mode = False
    captured = {}

    def make_desk(_mac, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(ble_mod, "BleDesk", make_desk)
    monkeypatch.setattr(daemon.bluetooth, "_other_companion_daemons", lambda: [])
    query = AsyncMock(return_value=False)
    monkeypatch.setattr(daemon.bluetooth, "property", query)
    from idasen_companion.daemon.main import Daemon
    Daemon._make_desk(daemon)
    daemon.config.desk.mac = "AA:BB:CC:DD:EE:FF"
    await captured["on_connect_exhausted"]()
    query.assert_any_await("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF",
                           "org.bluez.Device1", "Connected")


def test_own_process_is_not_counted_as_another_daemon(monkeypatch, tmp_path):
    own = tmp_path / str(os.getpid())
    own.mkdir()
    (own / "cmdline").write_bytes(b"idasen-companiond\0")
    monkeypatch.setattr(bluetooth_mod, "Path", lambda _: tmp_path)
    support = BluetoothSupport(MagicMock())
    assert support._other_companion_daemons() == []


def test_other_daemon_started_with_python_module_is_detected(monkeypatch, tmp_path):
    candidate = tmp_path / "12345"
    candidate.mkdir()
    (candidate / "cmdline").write_bytes(
        b"/usr/bin/python3\0-I\0-m\0idasen_companion.daemon.main\0")
    unrelated = tmp_path / "12346"
    unrelated.mkdir()
    (unrelated / "cmdline").write_bytes(b"/usr/bin/python3\0other.py\0")
    monkeypatch.setattr(bluetooth_mod, "Path", lambda _: tmp_path)
    support = BluetoothSupport(MagicMock())
    assert support._other_companion_daemons() == [12345]


# ----- the seat's active session is the lease on the desk -----

async def test_leaving_the_seat_releases_the_desk(monkeypatch):
    """logind guarantees one active session per seat, so foreground *is* the
    lease. Losing it has to drop the link, not just decline to move: on-demand
    mode would take a whole linger window to let go, and persistent mode would
    hold a shared desk hostage for a user who isn't even there."""
    from idasen_companion.core.machine import AwayChanged

    d = _bare_daemon(monkeypatch)
    d._handle_event(AwayChanged(True), trigger="automation")
    await asyncio.sleep(0)  # the release is scheduled, not awaited inline
    assert d.desk.disconnect.called, "kept the desk after leaving the seat"


async def test_handoff_leaves_ambiguous_bluez_link_alone(monkeypatch):
    d = _bare_daemon(monkeypatch)
    d.mock_mode = False
    d.desk.connected = False
    d.desk.disconnect = AsyncMock()
    d.bluetooth.property = AsyncMock(return_value=True)

    await d._release_desk()
    d.desk.disconnect.assert_awaited_once()
    d.bluetooth.property.assert_awaited_once_with(
        d.bluetooth.device_path(d.config.desk.mac), "org.bluez.Device1", "Connected")
    d.activity_log.diag.assert_called_once()


async def test_returning_to_the_seat_does_not_drop_the_link(monkeypatch):
    from idasen_companion.core.machine import AwayChanged

    d = _bare_daemon(monkeypatch)
    d._handle_event(AwayChanged(False), trigger="automation")
    await asyncio.sleep(0)
    assert not d.desk.disconnect.called


async def test_startup_leaves_the_desk_alone_from_the_background(monkeypatch):
    """A daemon starting into a backgrounded session — a restart during
    someone else's session, or an RPM scriptlet — must not open the shared
    desk's one connection slot just to seed a cycle it cannot act on."""
    d = _bare_daemon(monkeypatch)
    d.machine = MagicMock()
    d.machine.start = AsyncMock()
    d._session.state = AsyncMock(return_value=SEAT_BACKGROUND)

    await d._adopt_initial_state()
    assert not d.machine.start.called, "read the desk from a background session"


async def test_startup_leaves_the_desk_alone_with_no_graphical_session(monkeypatch):
    """Same for a daemon with no seat at all — headless, SSH, or started
    before anyone logged in. There is nothing for it to automate, so opening
    the shared desk's connection slot is pure contention."""
    d = _bare_daemon(monkeypatch)
    d.machine = MagicMock()
    d.machine.start = AsyncMock()
    d._session.state = AsyncMock(return_value=SEAT_NONE)

    await d._adopt_initial_state()
    assert not d.machine.start.called, "read the desk with no graphical session"


async def test_a_logind_hiccup_is_never_grounds_to_stand_down(monkeypatch):
    """The one way fix A could break a working install: treating 'could not
    ask logind' as 'you have no desktop'. Uncertainty must still read as
    entitled, exactly as it did before."""
    from idasen_companion.daemon.idle import SEAT_UNKNOWN

    d = _bare_daemon(monkeypatch)
    d._session.state = AsyncMock(return_value=SEAT_UNKNOWN)
    assert await d._entitled_to_desk() is True


async def test_a_move_asked_for_from_the_background_does_no_desk_io(monkeypatch):
    """A request from the old session must not borrow the foreground user's desk."""
    from dbus_fast.errors import DBusError

    d = _bare_daemon(monkeypatch)
    d._current_move_id = 0
    d.moving = False
    d._ifaces = {"desk": MagicMock(), "automation": MagicMock()}
    d.desk.move_to = AsyncMock(return_value=True)
    d._session.state = AsyncMock(return_value=SEAT_BACKGROUND)
    d.machine = MagicMock()
    d.machine.is_away = True
    d.machine.force_sync = AsyncMock(return_value=[])
    monkeypatch.setattr(d, "_emit_periodic_properties", MagicMock())

    with pytest.raises(DBusError):
        await d._manual_move(Length(1.10), "stand")
    d.desk.move_to.assert_not_awaited()
    d.desk.disconnect.assert_not_called()


async def _async(value):
    return value


async def test_seeding_respects_automation_being_switched_off():
    """The two branches that met here were developed apart: the background-read
    seeding predates [automation] enabled. Seeding a live countdown while the
    UI reports "Automation off" would contradict itself."""
    from idasen_companion.core.config import AppConfig
    from idasen_companion.core.durations import Duration
    from idasen_companion.core.machine import StateMachine
    from idasen_companion.desk.mock import MockDesk

    cfg = AppConfig()
    cfg.presets = {"sit": 0.62, "stand": 1.10}
    cfg.automation.enabled = False
    machine = StateMachine(cfg, MockDesk(height=Length(0.62)), now=WallInstant(0.0))
    machine.start_without_desk_read(WallInstant(0.0))
    assert machine.target_duration == Duration.from_seconds(0)

    cfg.automation.enabled = True
    machine = StateMachine(cfg, MockDesk(height=Length(0.62)), now=WallInstant(0.0))
    machine.start_without_desk_read(WallInstant(0.0))
    assert machine.target_duration > Duration.from_seconds(0)
