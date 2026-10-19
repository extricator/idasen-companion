"""Discovery transitions characterized against Daemon before extraction.

All platform inputs are fake: these tests never contact BlueZ or scan BLE.
"""

import builtins
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from dbus_fast import MessageType, Variant

from idasen_companion.core import logmsg
from idasen_companion.daemon import main as main_mod


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
    daemon._system_bus = FakeBus()
    daemon._scan_cache = None
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(main_mod.time, "time", lambda: clock.now)
    scanner = AsyncMock(return_value=[SCANNED])
    monkeypatch.setitem(sys.modules, "idasen_companion.desk.ble",
                        SimpleNamespace(discover_desks=scanner))
    return daemon, clock, scanner


async def test_positive_timeout_always_scans_and_replaces_fresh_cache(discovery):
    daemon, clock, scanner = discovery
    daemon._scan_cache = (clock.now - 1, [OLD])
    assert await daemon.discover(99) == [PAIRED, SCANNED]
    scanner.assert_awaited_once_with(30)
    assert daemon._scan_cache == (clock.now, [SCANNED])
    daemon.activity_log.emit.assert_any_call(logmsg.SCAN_STARTED)
    daemon.activity_log.emit.assert_any_call(logmsg.SCAN_FINISHED, count=1)


@pytest.mark.parametrize("timeout", [0, -4, "0"])
async def test_zero_timeout_uses_fresh_cache_without_importing_scanner(
        discovery, monkeypatch, timeout):
    daemon, clock, scanner = discovery
    daemon._scan_cache = (clock.now - 59, [SCANNED])
    original_import = builtins.__import__

    def forbid_scanner(name, *args, **kwargs):
        assert name != "desk.ble", "zero timeout imported the scanner"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_scanner)
    assert await daemon.discover(timeout) == [PAIRED, SCANNED]
    scanner.assert_not_awaited()
    assert daemon._scan_cache == (clock.now - 59, [SCANNED])


@pytest.mark.parametrize("age", [60, 61])
async def test_expired_zero_timeout_returns_only_paired_and_keeps_cache(discovery, age):
    daemon, clock, scanner = discovery
    cache = (clock.now - age, [OLD])
    daemon._scan_cache = cache
    assert await daemon.discover(0) == [PAIRED]
    assert daemon._scan_cache is cache
    scanner.assert_not_awaited()


async def test_zero_timeout_without_cache_returns_only_paired(discovery):
    daemon, _, scanner = discovery
    assert await daemon.discover(0) == [PAIRED]
    assert daemon._scan_cache is None
    scanner.assert_not_awaited()


async def test_failed_positive_scan_replaces_success_with_fresh_empty_cache(discovery):
    daemon, clock, scanner = discovery
    assert await daemon.discover(2) == [PAIRED, SCANNED]
    clock.now += 10
    scanner.side_effect = OSError("scan failed")
    assert await daemon.discover(3) == [PAIRED]
    assert daemon._scan_cache == (clock.now, [])
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
    daemon._system_bus = None
    assert await daemon.discover(0) == []
    assert await daemon.discover(1) == [SCANNED]


async def test_mock_mode_does_not_query_or_scan(discovery):
    daemon, _, scanner = discovery
    daemon.mock_mode = True
    assert await daemon.discover(30) == [("Desk 0000 (mock)", "00:11:22:33:44:55")]
    scanner.assert_not_awaited()
    assert daemon._system_bus.messages == []
