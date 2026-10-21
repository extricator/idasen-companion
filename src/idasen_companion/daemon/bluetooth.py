"""Bluetooth discovery and observations, borrowing the daemon's optional bus.

This support object owns scan results, never a desk client or its lifecycle.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

from ..core import logmsg
from ..core.clocks import WallInstant
from ..core.durations import Duration
from .bluez import merge_devices, parse_paired_desks
from .dbus_util import DBusCallError, call
from .ringlog import RingLog

# How long scan results can answer Discover(0) without another scan.
SCAN_CACHE_SECONDS = 60


class BluetoothSupport:
    """Own discovery state and inspect BlueZ without controlling its links."""

    def __init__(self, activity_log: RingLog,
                 system_bus: MessageBus | None = None):
        self.activity_log = activity_log
        self._system_bus = system_bus
        self._scan_cache: tuple[WallInstant, list[tuple[str, str]]] | None = None

    def bind_bus(self, bus: MessageBus | None) -> None:
        """Borrow the bus after daemon setup; its lifetime stays with Daemon."""
        self._system_bus = bus

    async def discover(self, timeout: int, *, mock_mode: bool) -> list[tuple[str, str]]:
        """Return paired desks first, then current scan or fresh cached results."""
        if mock_mode:
            return [("Desk 0000 (mock)", "00:11:22:33:44:55")]

        known = await self._known_desks()
        timeout = max(0, int(timeout))
        if timeout == 0:
            cache = self._scan_cache
            scanned = (cache[1]
                       if cache is not None
                       and WallInstant(time.time()) - cache[0]
                       < Duration.from_seconds(SCAN_CACHE_SECONDS)
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
                self.activity_log.emit(logmsg.SCAN_FINISHED, count=len(scanned))
            self._scan_cache = (WallInstant(time.time()), scanned)
        return merge_devices(known, scanned)

    async def _known_desks(self) -> list[tuple[str, str]]:
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

    @staticmethod
    def device_path(mac: str) -> str:
        """BlueZ object path for a desk (hci0 only, matching the
        rest of the app's single-adapter assumption)."""
        return f"/org/bluez/hci0/dev_{mac.upper().replace(':', '_')}"

    def _other_companion_daemons(self) -> list[int]:
        """PIDs of other idasen-companiond processes on this machine.

        One desk, one machine, several accounts is the *expected* arrangement,
        not an anomaly — each logged-in user's session runs its own daemon and
        they all want the same desk. Ownership is settled by the seat lease
        (see Daemon's ``_release_desk``), not by this scan. The PID list gives
        useful context in a failed-connect diagnostic; it cannot prove link ownership.
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
            if any(arg == b"idasen_companion.daemon.main"
                   or arg.rsplit(b"/", 1)[-1] == b"idasen-companiond"
                   for arg in argv if arg):
                found.append(int(entry.name))
        return found

    async def property(self, path: str, interface: str, name: str):
        if self._system_bus is None:
            return None
        try:
            body = await call(self._system_bus, "org.bluez", path,
                              "org.freedesktop.DBus.Properties", "Get", "ss",
                              [interface, name])
        except (DBusCallError, DBusError):
            return None
        return body[0].value if body else None

    async def report_connect_exhausted(self, mac: str) -> None:
        """Every connect attempt failed. Record the Bluetooth stack state.

        The snapshot is the primary job. A desk that went unreachable for 45
        minutes could not be explained afterwards because nothing recorded what
        BlueZ thought at the time; this makes a repeat diagnose itself.

        A BlueZ link has no discoverable client owner, so this hook only logs.
        """
        if not mac:
            return
        path = self.device_path(mac)
        connected = await self.property(path, "org.bluez.Device1",
                                        "Connected")
        paired = await self.property(path, "org.bluez.Device1", "Paired")
        rssi = await self.property(path, "org.bluez.Device1", "RSSI")
        powered = await self.property("/org/bluez/hci0",
                                      "org.bluez.Adapter1", "Powered")
        discovering = await self.property("/org/bluez/hci0",
                                          "org.bluez.Adapter1", "Discovering")
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
            return  # nothing in the way; the failure is something else

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
            return

        self.activity_log.diag(
            "warning",
            "The desk is connected but unreachable from here. BlueZ cannot "
            "identify the link's owner, so it was left alone.")
