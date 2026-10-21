"""Discovery transitions characterized against Daemon before extraction.

All platform inputs are fake: these tests never contact BlueZ or scan BLE.
"""

import asyncio
import builtins
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from dbus_fast import MessageType, Variant
from dbus_fast.errors import DBusError

from idasen_companion.core import logmsg
from idasen_companion.core.clocks import WallInstant
from idasen_companion.daemon import main as main_mod
from idasen_companion.daemon import bluetooth as bluetooth_mod
from idasen_companion.daemon.bluetooth import BluetoothSupport
from idasen_companion.daemon.dbus_util import DBusCallError
from idasen_companion.daemon.idle import SEAT_FOREGROUND


PAIRED = ("Desk paired", "AA:BB:CC:DD:EE:FF")
SCANNED = ("Desk scanned", "11:22:33:44:55:66")
OLD = ("Desk old", "66:55:44:33:22:11")


class FakeBus:
    def __init__(self):
        self.messages = []

    async def call(self, message):
        self.messages.append(message)
        assert message.member == "GetManagedObjects"
        return SimpleNamespace(
            message_type=MessageType.METHOD_RETURN,
            body=[{"/paired": {"org.bluez.Device1": {
                "Name": Variant("s", PAIRED[0]),
                "Address": Variant("s", PAIRED[1]),
                "Paired": Variant("b", True),
            }}}],
        )


@pytest.fixture
def discovery(monkeypatch):
    daemon = main_mod.Daemon.__new__(main_mod.Daemon)
    daemon.mock_mode = False
    daemon.activity_log = MagicMock()
    daemon.bluetooth = BluetoothSupport(daemon.activity_log, FakeBus())
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(bluetooth_mod.time, "time", lambda: clock.now)
    scanner = AsyncMock(return_value=[SCANNED])
    monkeypatch.setitem(sys.modules, "idasen_companion.desk.ble",
                        SimpleNamespace(discover_desks=scanner))
    return daemon, clock, scanner


async def test_positive_timeout_always_scans_and_replaces_fresh_cache(discovery):
    daemon, clock, scanner = discovery
    daemon.bluetooth._scan_cache = (WallInstant(clock.now - 1), [OLD])
    assert await daemon.discover(99) == [PAIRED, SCANNED]
    scanner.assert_awaited_once_with(30)
    assert daemon.bluetooth._scan_cache == (WallInstant(clock.now), [SCANNED])
    daemon.activity_log.emit.assert_any_call(logmsg.SCAN_STARTED)
    daemon.activity_log.emit.assert_any_call(logmsg.SCAN_FINISHED, count=1)


@pytest.mark.parametrize("timeout", [0, -4])
async def test_zero_timeout_uses_fresh_cache_without_importing_scanner(
        discovery, monkeypatch, timeout):
    daemon, clock, scanner = discovery
    daemon.bluetooth._scan_cache = (WallInstant(clock.now - 59), [SCANNED])
    original_import = builtins.__import__

    def forbid_scanner(name, *args, **kwargs):
        assert name != "desk.ble", "zero timeout imported the scanner"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_scanner)
    assert await daemon.discover(timeout) == [PAIRED, SCANNED]
    scanner.assert_not_awaited()
    assert daemon.bluetooth._scan_cache == (WallInstant(clock.now - 59), [SCANNED])


async def test_expired_zero_timeout_returns_only_paired_and_keeps_cache(discovery):
    daemon, clock, scanner = discovery
    cache = (WallInstant(clock.now - 60), [OLD])
    daemon.bluetooth._scan_cache = cache
    assert await daemon.discover(0) == [PAIRED]
    assert daemon.bluetooth._scan_cache is cache
    scanner.assert_not_awaited()


async def test_zero_timeout_without_cache_returns_only_paired(discovery):
    daemon, _, scanner = discovery
    assert await daemon.discover(0) == [PAIRED]
    assert daemon.bluetooth._scan_cache is None
    scanner.assert_not_awaited()


async def test_backward_wall_step_keeps_typed_scan_cache_fresh(discovery):
    daemon, clock, scanner = discovery
    await daemon.discover(2)
    assert daemon.bluetooth._scan_cache[0] == WallInstant(clock.now)
    clock.now -= 5
    assert await daemon.discover(0) == [PAIRED, SCANNED]
    assert scanner.await_count == 1


async def test_failed_positive_scan_replaces_success_with_fresh_empty_cache(discovery):
    daemon, clock, scanner = discovery
    assert await daemon.discover(2) == [PAIRED, SCANNED]
    clock.now += 10
    scanner.side_effect = OSError("scan failed")
    assert await daemon.discover(3) == [PAIRED]
    assert daemon.bluetooth._scan_cache == (WallInstant(clock.now), [])
    daemon.activity_log.emit.assert_any_call(logmsg.SCAN_FAILED, error="scan failed")
    assert await daemon.discover(0) == [PAIRED]
    assert scanner.await_args_list[-1].args == (3,)
    assert scanner.await_count == 2


async def test_paired_devices_precede_case_insensitive_scan_duplicates(discovery):
    daemon, _, scanner = discovery
    scanner.return_value = [("duplicate", PAIRED[1].lower()), SCANNED, SCANNED]
    assert await daemon.discover(1) == [PAIRED, SCANNED]


async def test_missing_bus_uses_scanner_only(discovery):
    daemon, _, _ = discovery
    daemon.bluetooth.bind_bus(None)
    assert await daemon.discover(0) == []
    assert await daemon.discover(1) == [SCANNED]


async def test_mock_mode_does_not_query_or_scan(discovery):
    daemon, _, scanner = discovery
    daemon.mock_mode = True
    assert await daemon.discover(30) == [("Desk 0000 (mock)", "00:11:22:33:44:55")]
    scanner.assert_not_awaited()
    assert daemon.bluetooth._system_bus.messages == []


async def test_support_can_discover_directly_and_reports_bluez_query_failure(monkeypatch):
    activity_log = MagicMock()
    support = BluetoothSupport(activity_log, FakeBus())
    assert await support.discover(0, mock_mode=False) == [PAIRED]
    monkeypatch.setattr(bluetooth_mod, "call", AsyncMock(side_effect=DBusCallError("offline")))
    assert await support.discover(0, mock_mode=False) == []
    activity_log.diag.assert_called_once_with("debug", "BlueZ device query failed: offline")


@pytest.mark.parametrize("connected,others", [(False, []), (True, []), (True, [4242])])
async def test_failure_snapshot_observes_bluez_without_disconnect(monkeypatch, connected, others):
    activity_log = MagicMock()
    bus = FakeBus()
    properties = {"Connected": connected, "Paired": True, "RSSI": -55,
                  "Powered": True, "Discovering": False}

    async def answer(message):
        bus.messages.append(message)
        assert message.member == "Get", "diagnostics must only read properties"
        interface, name = message.body
        assert interface == ("org.bluez.Adapter1" if name in ("Powered", "Discovering")
                             else "org.bluez.Device1")
        return SimpleNamespace(message_type=MessageType.METHOD_RETURN,
                               body=[SimpleNamespace(value=properties[name])])

    bus.call = answer
    support = BluetoothSupport(activity_log, bus)
    monkeypatch.setattr(support, "_other_companion_daemons", lambda: others)
    await support.report_connect_exhausted("aa:bb:cc:dd:ee:ff")
    assert [message.body[1] for message in bus.messages] == [
        "Connected", "Paired", "RSSI", "Powered", "Discovering"]
    assert bus.messages[0].path == "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
    snapshot = activity_log.diag.call_args_list[0].args
    assert snapshot == ("warning", (
        f"Could not reach the desk. BlueZ reports: connected={connected}, "
        "paired=True, rssi=-55, adapter powered=True, scanning=False; "
        f"other companion daemons running: {others or 'none'}."))
    if connected and others:
        activity_log.emit.assert_called_once_with(logmsg.DESK_HELD_BY_OTHER, pids="4242")
    else:
        activity_log.emit.assert_not_called()
    assert not hasattr(support, "desk")
    assert not hasattr(support, "disconnect")
    assert not hasattr(support, "connect")


async def test_properties_and_diagnostics_with_no_bus_degrade_to_unknown(monkeypatch):
    activity_log = MagicMock()
    support = BluetoothSupport(activity_log)
    monkeypatch.setattr(support, "_other_companion_daemons", lambda: [])
    assert await support.property("/device", "org.bluez.Device1", "Connected") is None
    await support.report_connect_exhausted("")
    activity_log.diag.assert_not_called()
    await support.report_connect_exhausted(PAIRED[1])
    assert "connected=None, paired=None, rssi=None" in activity_log.diag.call_args.args[1]


@pytest.mark.parametrize("error", [DBusCallError("offline"), DBusError("org.bluez.Error.Failed", "offline")])
async def test_property_query_errors_and_empty_replies_return_unknown(monkeypatch, error):
    support = BluetoothSupport(MagicMock(), FakeBus())
    query = AsyncMock(side_effect=error)
    monkeypatch.setattr(bluetooth_mod, "call", query)
    assert await support.property("/device", "org.bluez.Device1", "Connected") is None
    query.side_effect = None
    query.return_value = []
    assert await support.property("/device", "org.bluez.Device1", "Connected") is None


async def test_paired_discovery_works_while_signal_registration_is_pending(
        discovery, monkeypatch):
    daemon, _, scanner = discovery
    bus = daemon.bluetooth._system_bus
    daemon.bluetooth.bind_bus(None)
    daemon._system_bus = None
    registration_started = asyncio.Event()
    finish_registration = asyncio.Event()
    query_paired = bus.call

    async def answer(message):
        if message.member == "AddMatch":
            registration_started.set()
            await finish_registration.wait()
            return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[])
        return await query_paired(message)

    bus.call = answer
    bus.add_message_handler = MagicMock()
    connector = MagicMock()
    connector.connect = AsyncMock(return_value=bus)
    monkeypatch.setattr(main_mod, "MessageBus", MagicMock(return_value=connector))
    monkeypatch.setattr(main_mod, "SleepInhibitor", MagicMock())
    monkeypatch.setattr(daemon, "_rearm_sleep_inhibitor", AsyncMock())
    session = MagicMock()
    session.state = AsyncMock(return_value=SEAT_FOREGROUND)
    monkeypatch.setattr(main_mod, "SessionActiveMonitor", MagicMock(return_value=session))

    setup = asyncio.create_task(daemon._setup_system_bus())
    try:
        await asyncio.wait_for(registration_started.wait(), timeout=1)
        assert not setup.done()
        assert daemon._system_bus is bus
        assert await daemon.discover(0) == [PAIRED]
        scanner.assert_not_awaited()
    finally:
        finish_registration.set()
        await asyncio.wait_for(setup, timeout=1)
    bus.add_message_handler.assert_called_once_with(daemon._on_system_message)
    assert await daemon.discover(0) == [PAIRED]


@pytest.mark.parametrize("available,registered", [(True, True), (True, False), (False, False)])
async def test_system_bus_setup_binds_the_same_optional_bus(
        monkeypatch, available, registered):
    daemon = main_mod.Daemon.__new__(main_mod.Daemon)
    daemon.activity_log = MagicMock()
    daemon.bluetooth = BluetoothSupport(daemon.activity_log)
    daemon._system_bus = None
    bus = MagicMock()
    bus.call = AsyncMock(return_value=SimpleNamespace(
        message_type=MessageType.METHOD_RETURN, body=[]))
    if not registered:
        bus.call.side_effect = DBusCallError("signal registration failed")
    connector = MagicMock()
    connector.connect = AsyncMock(return_value=bus)
    if not available:
        connector.connect.side_effect = OSError("no system bus")
    monkeypatch.setattr(main_mod, "MessageBus", MagicMock(return_value=connector))
    monkeypatch.setattr(main_mod, "SleepInhibitor", MagicMock())
    monkeypatch.setattr(daemon, "_rearm_sleep_inhibitor", AsyncMock())
    session = MagicMock()
    session.state = AsyncMock(return_value=SEAT_FOREGROUND)
    monkeypatch.setattr(main_mod, "SessionActiveMonitor", MagicMock(return_value=session))
    await daemon._setup_system_bus()
    assert daemon.bluetooth._system_bus is (bus if available else None)
    assert daemon.bluetooth._system_bus is daemon._system_bus
    if available and registered:
        bus.add_message_handler.assert_called_once_with(daemon._on_system_message)
    else:
        bus.add_message_handler.assert_not_called()
