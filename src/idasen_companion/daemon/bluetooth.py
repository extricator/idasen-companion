"""Bluetooth discovery and observations, borrowing the daemon's optional bus.

This support object owns scan results, never a desk client or its lifecycle.
"""

from __future__ import annotations

import time

from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

from ..core import logmsg
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
        self._scan_cache: tuple[float, list[tuple[str, str]]] | None = None

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
                self.activity_log.emit(logmsg.SCAN_FINISHED, count=len(scanned))
            self._scan_cache = (time.time(), scanned)
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
