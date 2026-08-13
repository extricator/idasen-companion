"""BleDesk — the real desk over BLE, built on the idasen library (newAM).

Connection policy is on-demand by default: connect when there is work,
stay connected for a short linger window afterwards, then disconnect so
the desk stays free for other clients (idasen CLI, phone apps) and the
desktop Bluetooth indicator isn't permanently lit. Persistent mode keeps
the connection open and reconnects on drops.

Every operation is guarded against the transient BlueZ/adapter errors
the reference setup silenced via stderr redirection: connects retry with
backoff, and command errors surface as ``False``/``None`` returns plus a
callback for logging, never exceptions.

Height streaming: while connected we subscribe to the Linak position
characteristic, so movement produces live height callbacks. If the
notification subscription is unavailable, callers still get heights via
polling (``get_height``).
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    # Runtime import stays inside _default_desk_factory — importing idasen
    # pulls in bleak, which the mock and --help paths never need.
    from idasen import IdasenDesk

logger = logging.getLogger(__name__)

# Linak DPG position characteristic (notify): uint16 LE tenths-of-mm above
# minimum height, followed by a uint16 speed. Same UUID the idasen library
# and every other Idåsen client uses.
POSITION_UUID = "99fa0021-338a-1024-8a49-009c0215f78a"
MIN_HEIGHT = 0.62


def _decode_height(data: bytes) -> float:
    raw = struct.unpack("<H", data[:2])[0]
    return raw / 10_000 + MIN_HEIGHT


def _default_desk_factory(mac: str, disconnected_callback):
    from idasen import IdasenDesk

    return IdasenDesk(
        mac, exit_on_fail=False, disconnected_callback=disconnected_callback
    )


class BleDesk:
    """DeskPort implementation over BLE. Not thread-safe; single event loop."""

    def __init__(
        self,
        mac: str,
        *,
        connection_mode: str = "on-demand",
        linger: float = 15.0,
        retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
        wakeup_grace: float = 2.0,
        desk_factory: Callable = _default_desk_factory,
        on_height: Callable[[float], None] | None = None,
        on_connection_change: Callable[[bool], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_connect_exhausted: Callable[[], "asyncio.Future"] | None = None,
    ):
        self.mac = mac
        self.connection_mode = connection_mode
        self.linger = linger
        self._retry_delays = retry_delays
        self._wakeup_grace = wakeup_grace
        self._desk_factory = desk_factory
        self._on_height = on_height
        self._on_connection_change = on_connection_change
        self._on_error = on_error
        # Called when every connect attempt has failed, to record what the
        # Bluetooth stack looked like at that moment and optionally clear a
        # link that is in the way. Returns whether it changed anything worth
        # retrying for. Lives in the daemon, which owns a system-bus handle.
        self._on_connect_exhausted = on_connect_exhausted

        # None until the first connect builds one.
        self._desk: IdasenDesk | None = None
        self._lock = asyncio.Lock()
        self._linger_task: asyncio.Task | None = None
        self._notify_active = False
        self._notify_starting = False
        # Monotonic time the controller was last known awake — set by a
        # successful connect (idasen's connect() wakes it) and by an explicit
        # _wakeup(). None means "assume asleep". See _controller_awake.
        self._awake_since: float | None = None
        # True only while a move_to_target is actively driving the desk, so a
        # second move can preempt it (rather than queue behind the lock).
        self._move_in_flight = False
        self.last_error: str | None = None

    # ----- connection management -----

    @property
    def _handle(self) -> IdasenDesk:
        """The live desk handle.

        Every caller reaches this behind ``_ensure_connected`` or ``connected``,
        both of which guarantee the handle exists — an invariant that holds
        across a method call the type checker cannot follow through. Raising
        here rather than returning None keeps that assumption falsifiable
        instead of surfacing as an AttributeError three frames away.
        """
        desk = self._desk
        if desk is None:
            raise RuntimeError("BLE desk handle used before connect")
        return desk

    @property
    def connected(self) -> bool:
        return self._desk is not None and bool(getattr(self._desk, "is_connected", False))

    @property
    def _controller_awake(self) -> bool:
        """Whether the controller can be assumed still awake, so a move needs
        no wakeup first.

        This is deliberately time-based rather than "did we just connect".
        A single tray gesture is *two* desk operations — ``refresh_height()``
        then the move — and treating the second one as a reuse re-woke a
        controller that had been awake for a few hundred milliseconds, which
        defeated the whole optimisation on the most-used path. What actually
        matters is elapsed time: the grace window is long enough to span a
        read immediately followed by a move, and far shorter than any plausible
        doze timeout, so a genuine linger reuse still re-wakes.
        """
        return (self._awake_since is not None
                and time.monotonic() - self._awake_since < self._wakeup_grace)

    def _report_error(self, context: str, exc: Exception) -> None:
        message = f"{context}: {exc.__class__.__name__}: {exc}"
        self.last_error = message
        logger.debug(message)
        if self._on_error:
            self._on_error(message)

    def _forget_link_state(self) -> None:
        """Drop everything that was only true of a live link: the position
        notification subscription and the controller's wakeup grace."""
        self._notify_active = False
        self._notify_starting = False
        self._awake_since = None

    def _handle_disconnect(self, _client=None) -> None:
        self._forget_link_state()
        if self._on_connection_change:
            self._on_connection_change(False)

    async def _ensure_connected(self) -> bool:
        """Connect if needed, retrying with backoff. Returns success."""
        if not self.mac:
            # Unconfigured: fail quietly instead of retrying against an
            # empty address (which floods the log via the idasen library).
            self.last_error = "no desk address configured"
            return False
        self._cancel_linger()
        if self.connected:
            return True
        # Not connected: build a *fresh* desk instead of reusing the previous
        # one. Reconnecting a BleakClient that has already been through a BlueZ
        # disconnect is measurably slower from cold (~0.9s in local timing)
        # than connecting a brand-new one — which is how a one-shot `idasen`
        # invocation stays fast. Starting clean each time closes that gap. The
        # old object is already disconnected here, so dropping it just lets it
        # be collected.
        self._desk = self._desk_factory(self.mac, self._handle_disconnect)
        self._forget_link_state()

        if await self._connect_with_retries():
            return True

        # Every attempt failed. Hand off to the daemon to snapshot the stack
        # (that snapshot is the point — a repeat of the outage this hook was
        # written for should explain itself) and, if it finds something it can
        # safely clear, say so. Only then do we build a fresh client and try
        # once more.
        #
        # Note this is *defence, not diagnosis*: an unowned BlueZ link was the
        # suspected cause of a desk being unreachable for 45 minutes, but
        # reproducing that state showed a new client connects through it
        # perfectly well (BlueZ refcounts Device1.Connect per client). The real
        # cause is still unknown. This path costs nothing in the common case
        # and may help a genuinely wedged one; it is not a proven fix.
        if (self._on_connect_exhausted is not None
                and await self._on_connect_exhausted()):
            self._desk = self._desk_factory(self.mac, self._handle_disconnect)
            if await self._connect_with_retries():
                return True
        return False

    async def _connect_with_retries(self) -> bool:
        attempts = len(self._retry_delays) + 1
        for attempt in range(attempts):
            try:
                await self._handle.connect()
            except Exception as exc:  # BleakError, BleakDBusError, TimeoutError, OSError
                self._report_error(f"connect attempt {attempt + 1}/{attempts}", exc)
                if attempt < len(self._retry_delays):
                    await asyncio.sleep(self._retry_delays[attempt])
                continue
            # idasen's connect() issues the full controller wakeup itself.
            self._awake_since = time.monotonic()
            if self._on_connection_change:
                self._on_connection_change(True)
            # Subscribe to live heights off the critical path: the first move
            # or read shouldn't wait a BLE round-trip on the notification
            # subscription, which only feeds the GUI's live height display.
            self._schedule_notify()
            return True
        return False

    def _schedule_notify(self) -> None:
        if self._notify_active or self._notify_starting or self._on_height is None:
            return
        self._notify_starting = True
        asyncio.ensure_future(self._try_start_notify())

    async def _try_start_notify(self) -> None:
        """Subscribe to live position notifications; harmless if unsupported."""
        client = getattr(self._desk, "_client", None)
        # `_schedule_notify` already refuses to get here without a height
        # callback; bind it to a local so the closure below doesn't have to
        # re-prove that across the ensure_future boundary.
        on_height = self._on_height
        if client is None or on_height is None:
            self._notify_starting = False
            return

        def callback(_char, data: bytearray) -> None:
            try:
                on_height(_decode_height(bytes(data)))
            except Exception:
                logger.debug("bad position notification: %r", data)

        try:
            await client.start_notify(POSITION_UUID, callback)
            self._notify_active = True
        except Exception as exc:
            self._report_error("position notify subscription", exc)
        finally:
            self._notify_starting = False

    def _cancel_linger(self) -> None:
        if self._linger_task is not None:
            self._linger_task.cancel()
            self._linger_task = None

    def _schedule_release(self) -> None:
        if self.connection_mode == "persistent":
            return
        self._cancel_linger()
        self._linger_task = asyncio.ensure_future(self._linger_then_disconnect())

    async def _linger_then_disconnect(self) -> None:
        try:
            await asyncio.sleep(self.linger)
        except asyncio.CancelledError:
            return
        async with self._lock:
            await self._disconnect_locked()

    async def _disconnect_locked(self) -> None:
        if self._desk is None:
            return
        try:
            await self._desk.disconnect()
        except Exception as exc:
            self._report_error("disconnect", exc)
        self._forget_link_state()

    async def disconnect(self) -> None:
        """Disconnect immediately (shutdown, or config switch)."""
        self._cancel_linger()
        async with self._lock:
            await self._disconnect_locked()

    # ----- DeskPort -----

    async def get_height(self) -> float | None:
        async with self._lock:
            try:
                if not await self._ensure_connected():
                    return None
                height = await self._handle.get_height()
            except Exception as exc:
                self._report_error("get_height", exc)
                return None
            finally:
                self._schedule_release()
        if height is not None and self._on_height:
            self._on_height(height)
        return height

    async def move_to(self, height: float) -> bool:
        # If the desk is already being driven to a target, cancel that first so
        # the new target takes over at once instead of queuing behind it
        # (last-write-wins). stop() ends the in-flight move_to_target
        # cooperatively, which lets the current holder release the lock below.
        if self._move_in_flight:
            await self.stop()
        async with self._lock:
            try:
                if not await self._ensure_connected():
                    return False
                # A controller woken moments ago (by idasen's connect(), or by
                # the read that a tray gesture does first) needs no second
                # wakeup; only re-wake when the link has been idle long enough
                # that it may have dozed. Skipping the redundant wakeup drops
                # three GATT writes from the move path.
                if not self._controller_awake:
                    await self._wakeup()
                self._move_in_flight = True
                try:
                    await self._handle.move_to_target(height)
                finally:
                    self._move_in_flight = False
                return True
            except Exception as exc:
                self._report_error(f"move_to {height:.4f}m", exc)
                return False
            finally:
                self._schedule_release()

    async def stop(self) -> None:
        # Deliberately no _ensure_connected: stop only matters if a move is
        # in flight, which implies we're connected.
        if not self.connected:
            return
        try:
            await self._handle.stop()
        except Exception as exc:
            self._report_error("stop", exc)

    # ----- extras used by the daemon/GUI -----

    async def _wakeup(self) -> None:
        """Linak DPG1C controllers need a wakeup before movement commands."""
        wakeup = getattr(self._desk, "wakeup", None)
        if wakeup is None:
            return
        try:
            await wakeup()
        except Exception as exc:
            self._report_error("wakeup", exc)
        else:
            self._awake_since = time.monotonic()

    async def pair(self) -> bool:
        async with self._lock:
            try:
                if not await self._ensure_connected():
                    return False
                await self._handle.pair()
                return True
            except Exception as exc:
                self._report_error("pair", exc)
                return False
            finally:
                self._schedule_release()


async def discover_desks(timeout: float = 8.0) -> list[tuple[str, str]]:
    """Scan for nearby desks. Returns (name, mac) pairs, Idåsen-looking
    devices first. Exposed to the GUI's first-run wizard through ``Desk1.Discover``."""
    from bleak import BleakScanner

    devices = await BleakScanner.discover(timeout=timeout)
    named = [(d.name or "", d.address) for d in devices if d.name]
    named.sort(key=lambda item: (not item[0].lower().startswith("desk"), item[0]))
    return named


async def _smoke(mac: str) -> None:
    """Manual hardware smoke test: connect, read height, disconnect."""
    logging.basicConfig(level=logging.DEBUG)
    desk = BleDesk(mac, on_height=lambda h: print(f"  height update: {h:.4f} m"))
    height = await desk.get_height()
    print(f"height: {'N/A' if height is None else f'{height:.4f} m'}")
    print(f"connected: {desk.connected} (will linger {desk.linger}s then drop)")
    await desk.disconnect()


if __name__ == "__main__":
    import sys

    asyncio.run(_smoke(sys.argv[1]))
