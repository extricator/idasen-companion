"""Login autostart via the Flatpak Background portal.

A sibling module controls the daemon's systemd **user** unit, but a Flatpak
sandbox has no host systemd — there is no unit to enable. The only mechanism
that both raises an OS-native permission dialog and writes a host autostart
entry is ``org.freedesktop.portal.Background.RequestBackground``. This module
owns that request; the systemd-path module stays exactly as it is, and
neither module imports the other.

Outside Flatpak this module is inert: :func:`is_flatpak` returns ``False``
and :func:`set_autostart` is a no-op, so the RPM's systemd unit keeps owning
autostart there.

**Why there is no readback.** ``RequestBackground`` and the status setter are
the portal's only two methods — nothing lets an app ask "is autostart
currently granted?" An app that wants to show or restore that state has to
persist it itself, which is what ``[ui] run_at_login`` (``core/config.py``) is
for: this module never reads it, it only acts on what it is told.

**Why QtDBus and not the daemon's own D-Bus stack.** The options and results
here are dictionaries of variants (``a{sv}``) — the variant-*wrapped* case
QtDBus demarshals natively, not the non-variant containers the project's D-Bus
wire-format note warns about. Calling synchronously from a nested event loop,
the same shape ``setup_wizard.py`` already uses to wait for the daemon, keeps
this a plain function call from a click handler's point of view, matching how
the systemd-path module's functions already behave, and keeps a second D-Bus
stack out of the GUI layer.

**Why the connect slot takes ``str``, not the ``bytes`` its stub advertises.**
``QDBusConnection.connect()``'s Python binding raises on every call whose
final ``slot`` argument is ``bytes``/``bytearray``/``memoryview`` — reproduced
here with a real cross-process signal, regardless of what the slot names or
its signature is. Passing the ``SLOT()`` helper's plain ``str`` result instead
works correctly, and is exactly what ``gui/dbus_client.py`` already does for
the daemon's own signals — this module follows that same, already-proven
idiom rather than the (apparently unreliable) typed overload.

**Why the request-object path is precomputed.** It is deterministic before
the call even returns — this connection's own unique bus name with the
leading colon dropped and dots replaced by underscores, then this call's own
token — so the response listener can be attached *before*
``RequestBackground`` is called, closing the race where the portal answers
before anyone is listening.

**Why ``dbus-activatable`` is always false.** The daemon also ships a D-Bus
activation file for on-demand startup (``data/*.service``), but that is a
*lazy* mechanism — it starts the daemon only once something talks to its bus
name. Autostart has to be *proactive*: the point is a running daemon at login
whether or not anything has talked to it yet, the same proactive intent the
systemd path's own enable-at-login already has. Asking the portal to
autostart via D-Bus activation instead of a direct command would quietly turn
that proactive launch into a lazy one.
"""

from __future__ import annotations

import os
import uuid

from PySide6.QtCore import QEventLoop, QObject, QTimer, SLOT, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

from ..core import journal, logmsg
from ..core.i18n import pgettext

_SERVICE = "org.freedesktop.portal.Desktop"
_PATH = "/org/freedesktop/portal/desktop"
_BACKGROUND_INTERFACE = "org.freedesktop.portal.Background"
_REQUEST_INTERFACE = "org.freedesktop.portal.Request"
_REQUEST_PATH_PREFIX = "/org/freedesktop/portal/desktop/request"

#: What the portal autostarts. Always this project's own daemon executable
#: name, a constant — never assembled from config or user input, since a
#: granted request is a host autostart entry that runs at every login.
_DAEMON_COMMANDLINE = ["idasen-companiond"]

#: Bounded so a portal that never answers — dead session, no backend, a user
#: who walks away from the permission dialog — can't block the caller
#: forever. Long enough that a slow read of that one-time dialog doesn't
#: masquerade as a denial.
_RESPONSE_DEADLINE_MS = 30_000

#: Exact text passed to both QDBusConnection.connect() and disconnect() for
#: the Response listener; kept in one place so the two calls can't drift.
_RESPONSE_SLOT = SLOT("on_response(uint,QVariantMap)")


def is_flatpak() -> bool:
    """True when running inside a Flatpak sandbox."""
    return os.path.exists("/.flatpak-info")


def _reason_text() -> str:
    """The text the OS shows in its own permission dialog for this request."""
    # Translators: What the desktop permission dialog says will start at login.
    text = pgettext("background-permission", "Start the desk automation automatically at login")
    return text


class _ResponseWaiter(QObject):
    """Captures the one Request.Response signal a single portal call gets."""

    def __init__(self) -> None:
        super().__init__()
        self.response: int | None = None
        self.results: dict[str, object] = {}
        self.loop = QEventLoop()

    @Slot("uint", "QVariantMap")
    def on_response(self, response: int, results: dict) -> None:
        self.response = response
        self.results = dict(results)
        self.loop.quit()


def _request_path(connection: QDBusConnection, token: str) -> str:
    """The Request object path this call's Response signal will arrive on.

    Computable before the call returns: the caller's own unique bus name with
    the leading colon dropped and dots replaced by underscores, then the
    token this call supplies.
    """
    sender = connection.baseService().lstrip(":").replace(".", "_")
    return f"{_REQUEST_PATH_PREFIX}/{sender}/{token}"


def _request_background(connection: QDBusConnection, token: str, enable: bool) -> str:
    """Dispatch RequestBackground; "" once it is lodged, else a short error.

    Every call restates every option, in both directions — the portal decides
    autostart together with the rest of this request, and a call that
    silently dropped one while changing another could revoke it.
    """
    iface = QDBusInterface(_SERVICE, _PATH, _BACKGROUND_INTERFACE, connection)
    options = {
        "handle_token": token,
        "reason": _reason_text(),
        "autostart": enable,
        "commandline": _DAEMON_COMMANDLINE,
        "dbus-activatable": False,
    }
    reply = iface.call("RequestBackground", "", options)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        return reply.errorMessage() or "the portal call failed"
    return ""


def _await_response(waiter: _ResponseWaiter) -> None:
    """Run one deadline-guarded pass of the event loop for `waiter`.

    Skips the loop entirely if the response already arrived. A synchronous
    ``QDBusInterface.call()`` spins the Qt event loop internally while it
    waits on its own reply, so the connected listener can fire — and call
    ``QEventLoop.quit()`` — before this function is ever reached. Quitting a
    loop before it has started `exec()` does not make the *next* `exec()`
    return; it is simply too late, and entering it here would then wait on a
    signal that has already come and gone.
    """
    if waiter.response is not None:
        return
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(waiter.loop.quit)
    deadline.start(_RESPONSE_DEADLINE_MS)
    try:
        waiter.loop.exec()
    finally:
        deadline.stop()


def _judge(waiter: _ResponseWaiter, enable: bool) -> tuple[bool, str]:
    """Turn a captured Response into this function's (ok, error) contract.

    Judged against the *requested* value, never a hardcoded true — a disable
    call that succeeds gets back ``autostart: False``, and a one-directional
    check would read that as a failure.
    """
    if waiter.response is None:
        return False, "the portal did not respond in time"
    if waiter.response == 1:
        return False, "the request was cancelled"
    if waiter.response != 0:
        return False, "the portal request failed"
    if bool(waiter.results.get("autostart")) != enable:
        return False, "the portal did not apply the requested autostart state"
    _record_autostart(enable)
    return True, ""


def set_autostart(enable: bool) -> tuple[bool, str]:
    """Ask the Background portal to enable or disable login autostart.

    Mirrors the systemd path's own autostart function's ``(ok, error text)``
    contract, so a call site can branch on either path without reshaping its
    error handling. A no-op outside Flatpak, for either value of `enable`.

    There is no separate revoke method: disabling sends this same request
    with ``autostart`` false rather than omitted. A response the portal
    genuinely answered — granted, denied, or the flag flipped the other way —
    is a normal, non-raising outcome; only a deadline expiry or a portal that
    is absent or refuses at the bus is worth a broad catch here, so that a
    live desktop's own quirks degrade to a declined request rather than a
    crash.
    """
    if not is_flatpak():
        return True, ""
    connection: QDBusConnection | None = None
    connected = False
    request_path = ""
    waiter = _ResponseWaiter()
    try:
        connection = QDBusConnection.sessionBus()
        if not connection.isConnected():
            return False, "no session bus connection"
        token = uuid.uuid4().hex
        request_path = _request_path(connection, token)
        # The stub for this overload demands bytes for `slot`, but that
        # overload raises unconditionally at runtime (reproduced with a real
        # cross-process signal); the str SLOT() actually returns is what
        # works, matching gui/dbus_client.py's own subscribe() helper.
        connected = connection.connect(  # type: ignore[call-overload]
            _SERVICE, request_path, _REQUEST_INTERFACE, "Response",
            waiter, _RESPONSE_SLOT)
        if not connected:
            return False, "could not listen for the portal's response"
        error = _request_background(connection, token, enable)
        if error:
            return False, error
        _await_response(waiter)
    except Exception as exc:  # boundary: see the docstring above
        return False, str(exc)
    finally:
        if connected and connection is not None:
            connection.disconnect(  # type: ignore[call-overload]
                _SERVICE, request_path, _REQUEST_INTERFACE, "Response",
                waiter, _RESPONSE_SLOT)
    return _judge(waiter, enable)


def _record_autostart(enable: bool) -> None:
    """Leave a trace that autostart was toggled, mirroring the systemd-path
    module's own helper of the same name — see its docstring for why the GUI
    writes this to the journal itself rather than leaving no trace at all.
    """
    message = logmsg.AUTOSTART_ENABLED if enable else logmsg.AUTOSTART_DISABLED
    journal.send(logmsg.render(message, {}, logmsg.ENGLISH_FORMATTERS),
                 message.level, channel=message.channel.value,
                 msg_id=message.id)


def reconcile_autostart(want_autostart: bool) -> None:
    """Re-assert the portal grant to match the persisted config, once.

    The autostart entry is a host file the portal writes on this app's
    behalf, outside the sandbox and outside anything Flatpak tracks — a
    reinstall, or a grant the portal reset on uninstall, can drop it while
    the config still says ``run_at_login = true``, leaving the toggle checked
    but inert. Called once at GUI startup so the config stays the single
    source of truth. Only the enabled direction is reconciled: re-requesting
    on every launch of the (default) disabled case would nag users with
    needless portal traffic for no benefit. Best-effort and silent — a
    failure here must not disrupt launch — and a no-op outside Flatpak.
    """
    if not want_autostart or not is_flatpak():
        return
    try:
        set_autostart(True)
    except Exception:  # a launch must not be disrupted by this, ever
        pass
