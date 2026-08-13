"""Idle-time and lock detection, DE-agnostic.

Replaces the reference script's xssstate/gdbus shell-outs with native
D-Bus (and a ctypes X11 fallback). Providers are probed once at startup;
if the active provider starts failing, the chain re-probes.

Idle time providers, in preference order:
  1. GNOME Mutter IdleMonitor (works on GNOME X11 and Wayland)
  2. org.freedesktop.ScreenSaver GetSessionIdleTime (KDE X11 and Wayland)
  3. X11 XScreenSaver extension via ctypes (any X11 session)

Lock detection: org.freedesktop.ScreenSaver.GetActive (KDE and most DEs)
with org.gnome.ScreenSaver as the GNOME variant. Errors mean "unlocked",
matching the reference script's graceful fallback.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
from collections.abc import Callable

from .dbus_util import DBusCallError, call

logger = logging.getLogger(__name__)


class MutterIdleProvider:
    name = "GNOME Mutter IdleMonitor"

    def __init__(self, bus):
        self._bus = bus

    async def get_idle_ms(self) -> int:
        body = await call(
            self._bus,
            "org.gnome.Mutter.IdleMonitor",
            "/org/gnome/Mutter/IdleMonitor/Core",
            "org.gnome.Mutter.IdleMonitor",
            "GetIdletime",
        )
        return int(body[0])


class ScreenSaverIdleProvider:
    """KDE implements GetSessionIdleTime on the freedesktop name.

    The spec says the return value is in seconds, but KDE's implementation
    (backed by KIdleTime) returns milliseconds — verified empirically: the
    value grows by 1000 per second of wall time. Treat it as milliseconds;
    KDE is the only real-world implementer of this method.
    """

    name = "freedesktop ScreenSaver (KDE)"

    def __init__(self, bus):
        self._bus = bus

    async def get_idle_ms(self) -> int:
        body = await call(
            self._bus,
            "org.freedesktop.ScreenSaver",
            "/ScreenSaver",
            "org.freedesktop.ScreenSaver",
            "GetSessionIdleTime",
        )
        return int(body[0])


class X11IdleProvider:
    """XScreenSaver extension via ctypes; no external tools needed."""

    name = "X11 XScreenSaver extension"

    class _XScreenSaverInfo(ctypes.Structure):
        _fields_ = [
            ("window", ctypes.c_ulong),
            ("state", ctypes.c_int),
            ("kind", ctypes.c_int),
            ("til_or_since", ctypes.c_ulong),
            ("idle", ctypes.c_ulong),
            ("eventMask", ctypes.c_ulong),
        ]

    def __init__(self):
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("no DISPLAY")
        xlib_name = ctypes.util.find_library("X11")
        xss_name = ctypes.util.find_library("Xss")
        if not xlib_name or not xss_name:
            raise RuntimeError("libX11/libXss not found")
        self._xlib = ctypes.cdll.LoadLibrary(xlib_name)
        self._xss = ctypes.cdll.LoadLibrary(xss_name)
        self._xlib.XOpenDisplay.restype = ctypes.c_void_p
        self._xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self._xlib.XDefaultRootWindow.restype = ctypes.c_ulong
        self._xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(self._XScreenSaverInfo)
        self._xss.XScreenSaverQueryInfo.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(self._XScreenSaverInfo)
        ]
        self._display = self._xlib.XOpenDisplay(None)
        if not self._display:
            raise RuntimeError("XOpenDisplay failed")
        self._root = self._xlib.XDefaultRootWindow(self._display)
        self._info = self._xss.XScreenSaverAllocInfo()

    async def get_idle_ms(self) -> int:
        if not self._xss.XScreenSaverQueryInfo(self._display, self._root, self._info):
            raise RuntimeError("XScreenSaverQueryInfo failed")
        return int(self._info.contents.idle)


class IdleMonitor:
    """Probes providers in order and delegates to the first that works.

    A failing provider is dropped and the chain re-probed; that call reports 0
    idle ("assume active") and the replacement is used from the next call on.
    If no provider works at all, every call reports 0 — which reads as "at the
    keyboard, right now", so ``on_lost`` exists to make that visible rather
    than let automation quietly fall back to a plain schedule.
    """

    def __init__(self, providers: list, on_lost: Callable[[], None] | None = None):
        self._providers = list(providers)
        self.active_provider = None
        self._on_lost = on_lost
        #: Whether a provider has *ever* worked. ``get_idle_ms`` clears
        #: ``active_provider`` before re-probing, so that field cannot tell
        #: "never had one" (startup) from "had one and lost it" (the edge worth
        #: reporting) — which is why the warning here used to be unreachable
        #: from the failure path that needed it most.
        self._ever_worked = False

    @classmethod
    async def create(cls, session_bus,
                     on_lost: Callable[[], None] | None = None) -> "IdleMonitor":
        providers = [MutterIdleProvider(session_bus), ScreenSaverIdleProvider(session_bus)]
        try:
            providers.append(X11IdleProvider())
        except (RuntimeError, OSError) as error:
            logger.debug("X11 idle provider unavailable: %s", error)
        monitor = cls(providers, on_lost=on_lost)
        await monitor.probe()
        return monitor

    async def probe(self) -> bool:
        """Find a working provider. Returns whether one was found."""
        for provider in self._providers:
            try:
                await provider.get_idle_ms()
            except (DBusCallError, RuntimeError, OSError) as error:
                logger.debug("idle provider %s unavailable: %s", provider.name, error)
                continue
            if self.active_provider is not provider:
                logger.info("using idle provider: %s", provider.name)
            self.active_provider = provider
            self._ever_worked = True
            return True
        self.active_provider = None
        if self._ever_worked:
            # Had one, lost it: gnome-shell restarted, the KDE screensaver
            # service went away. Startup's own no-provider case is reported by
            # the daemon instead, which has the activity log and the
            # catalogued line.
            logger.warning("no working idle provider; assuming user is active")
            self._ever_worked = False  # report the edge once, not per tick
            if self._on_lost is not None:
                self._on_lost()
        return False

    async def get_idle_ms(self) -> int:
        if self.active_provider is None:
            return 0
        try:
            return await self.active_provider.get_idle_ms()
        except (DBusCallError, RuntimeError, OSError) as error:
            logger.warning("idle provider %s failed (%s); re-probing",
                           self.active_provider.name, error)
            self.active_provider = None
            await self.probe()
            return 0

    @property
    def provider_name(self) -> str:
        return self.active_provider.name if self.active_provider else "none (assuming active)"


def _unwrap(value):
    """dbus-fast wraps property values in a Variant; unwrap defensively."""
    return getattr(value, "value", value)


# What logind can tell us about this user's claim on the seat. The two
# "no session path" outcomes are deliberately distinct: SEAT_NONE is a clean
# answer that the user has no graphical session (certainty about absence),
# SEAT_UNKNOWN is no information at all. Only the first is grounds to stand
# down — treating a failed call as an answer would let one logind hiccup
# switch a working install off.
SEAT_FOREGROUND = "foreground"   # in front of the seat: the desk is ours
SEAT_BACKGROUND = "background"   # switched away; someone else is in front
SEAT_NONE = "no-session"         # no session on a seat: not at this machine
SEAT_UNKNOWN = "unknown"         # could not ask; assume the best, as before


class SessionActiveMonitor:
    """Whether the user's graphical session is the foreground one on its seat.

    A raw VT switch (Ctrl+Alt+F<n>) or fast-user-switch *backgrounds* the
    session without locking it, and the idle providers can't see that: a
    compositor that isn't in front stops advancing its idle counter, so idle
    time reads low and a move can fire while the user is away in another
    session. logind's per-session ``Active`` flag is the reliable "is this the
    session in front right now" signal — read it on the *system* bus (the
    session/screensaver buses can't answer it).

    The daemon runs under the user *manager* session (no seat), so its own PID's
    session is the wrong one to check. Resolve the user's primary graphical
    session via ``User.Display`` instead, then read that session's ``Active``.

    A genuine *failure* — no system bus, logind unavailable, the ``Active``
    read erroring — yields ``SEAT_UNKNOWN``, which callers treat as foreground,
    so a logind hiccup can never freeze automation. A definite "this account
    has no session on a seat" is ``SEAT_NONE``, and that *does* stand
    automation down: ``_entitled_to_desk`` blocks moves, skips the startup desk
    read and releases the BLE link. Conflating the two is exactly the bug the
    SEAT_* constants exist to avoid — see their definitions above. The Display
    session is re-resolved whenever it is unknown or a read fails, so a daemon
    that started before login (or across a re-login) still picks it up.
    """

    _LOGIND = "org.freedesktop.login1"
    _MANAGER_PATH = "/org/freedesktop/login1"

    def __init__(self, system_bus, uid: int | None = None):
        self._bus = system_bus
        self._uid = os.getuid() if uid is None else uid
        self._session_path: str | None = None
        self._has_seat: bool = False

    async def _resolve_session(self) -> tuple[str | None, bool, bool]:
        """``(session path, session is on a seat, logind answered)`` for the
        user's primary (Display) session.

        The path is None both when logind reports no session and when the call
        failed, so the third element says which — see the SEAT_* constants for
        why conflating them is the bug worth avoiding here.

        The seat matters because ``User.Display`` is *not* necessarily
        graphical: logind prefers a graphical session but falls back to a tty
        one, so an SSH login lands here too. Verified on a live system."""
        if self._bus is None:
            return None, False, False
        try:
            user = await call(self._bus, self._LOGIND, self._MANAGER_PATH,
                              f"{self._LOGIND}.Manager", "GetUser", "u", [self._uid])
            user_path = _unwrap(user[0])
            display = await call(self._bus, self._LOGIND, user_path,
                                 "org.freedesktop.DBus.Properties", "Get", "ss",
                                 [f"{self._LOGIND}.User", "Display"])
            # Display is a struct (session_id: s, path: o); an empty id means
            # the user has no session at all.
            session_id, session_path = _unwrap(display[0])
            if not session_id:
                return None, False, True
            # Seat is a struct (seat_id: s, path: o); empty means the session
            # isn't attached to any physical seat. A session's seat is fixed for
            # its lifetime, so this is resolved once and cached with the path.
            seat = await call(self._bus, self._LOGIND, session_path,
                              "org.freedesktop.DBus.Properties", "Get", "ss",
                              [f"{self._LOGIND}.Session", "Seat"])
            seat_id, _seat_path = _unwrap(seat[0])
            return session_path, bool(seat_id), True
        except (DBusCallError, IndexError, ValueError, TypeError) as error:
            logger.debug("could not resolve the user's session: %s", error)
            return None, False, False

    async def state(self) -> str:
        """This session's claim on the seat, as one of the SEAT_* constants.

        Re-resolves the Display session whenever it is unknown, so a daemon
        that started before login (or one whose user logs in later) picks the
        session up rather than staying stuck at SEAT_NONE."""
        if self._bus is None:
            return SEAT_UNKNOWN
        if self._session_path is None:
            self._session_path, self._has_seat, answered = await self._resolve_session()
            if self._session_path is None:
                return SEAT_NONE if answered else SEAT_UNKNOWN
        if not self._has_seat:
            # Not physically at this machine (SSH, a remote shell). Reading
            # Active here would be worse than useless: logind's
            # session_is_active() is "no seat, OR I am my seat's active
            # session", so *every* seatless session reports Active=true and an
            # SSH login would be taken for someone sitting at the desk.
            return SEAT_NONE
        try:
            active = await call(self._bus, self._LOGIND, self._session_path,
                                "org.freedesktop.DBus.Properties", "Get", "ss",
                                [f"{self._LOGIND}.Session", "Active"])
        except (DBusCallError, IndexError) as error:
            # Session likely gone (logout/switch of the display session); forget
            # it so the next check re-resolves, and claim nothing meanwhile.
            logger.debug("session Active read failed (%s); will re-resolve", error)
            self._session_path = None
            return SEAT_UNKNOWN
        return SEAT_FOREGROUND if bool(_unwrap(active[0])) else SEAT_BACKGROUND

    @property
    def available(self) -> bool:
        """Whether a graphical session was resolved to gate on (for logging)."""
        return self._session_path is not None


class LockMonitor:
    """Session lock via ScreenSaver GetActive; errors mean unlocked."""

    _CANDIDATES = (
        ("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver"),
        ("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver"),
    )

    def __init__(self, bus):
        self._bus = bus
        self._working: tuple | None = None

    async def is_locked(self) -> bool:
        candidates = (self._working,) if self._working else self._CANDIDATES
        for dest, path, iface in candidates:
            try:
                body = await call(self._bus, dest, path, iface, "GetActive")
            except DBusCallError:
                continue
            self._working = (dest, path, iface)
            return bool(body[0])
        # Failing open is right — a screensaver hiccup must not freeze
        # automation — but it was previously invisible: no line at any level on
        # either channel, so the desk moving while the screen was locked left
        # no trace that lock detection had stopped working. Log the
        # *transition* only, so a machine that simply has no screensaver
        # service does not get a line per tick forever.
        if self._working is not None:
            logger.warning("lock detection stopped working (%s no longer "
                           "answers); assuming unlocked", self._working[0])
        self._working = None
        return False
