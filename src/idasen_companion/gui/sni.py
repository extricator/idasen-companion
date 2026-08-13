"""A hand-served StatusNotifierItem, so the tray tooltip can have a title.

The SNI ``ToolTip`` property is a struct ``(icon-name, icon-pixmaps, title,
description)``; Plasma renders ``title`` as a bold heading and ``description``
as lighter secondary text (``DefaultToolTip.qml``: a ``Kirigami.Heading`` at
``textFormat: Text.PlainText``, then a ``Label`` at ``opacity: 0.75``). Because
the heading is *PlainText*, no markup in the string can fake the split — the
two fields are the only way in.

``QSystemTrayIcon.setToolTip(str)`` fills ``title`` with the whole string and
leaves ``description`` empty, and Qt exposes no API for the two: its
``updateToolTip()`` takes a single ``QString``, and the D-Bus property is
``access="read"`` so it can't be written from outside either.

**What makes this cheap** — and it is the thing to know before touching this
file — is that ``QDBusTrayIcon`` registers *both* ``/StatusNotifierItem`` and
its DBusMenu at ``/MenuBar`` on one *named* ``QDBusConnection``
(``org.kde.StatusNotifierItem-<pid>-<n>``, ``KDEItemFormat`` in
``qdbustrayicon.cpp``). ``QDBusConnection(name)`` hands that same live
connection back, so we can unregister Qt's SNI object, put ours at the same
path, and point our ``Menu`` property at Qt's untouched ``/MenuBar``. The tray
menu keeps working with no adapter of our own — which is what makes this a
small change rather than the DBusMenu rewrite it looks like.

Everything here is best-effort: any failure leaves the plain
``QSystemTrayIcon`` exactly as it was, which is also what GNOME-without-the-
extension and any future Qt rename get.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QCoreApplication, QMetaType, QTimer
from PySide6.QtDBus import (QDBusArgument, QDBusConnection, QDBusMessage,
                            QDBusObjectPath, QDBusVariant, QDBusVirtualObject)

SNI_IFACE = "org.kde.StatusNotifierItem"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
SNI_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

# The element type of the icon-pixmap array, a(iiay). Python can't register a
# C++ struct with D-Bus, but Qt already registered this one when the tray icon
# was constructed, so we borrow its id to marshal an (always empty) array with
# the right signature. Renamed in Qt 6.9; probe both spellings.
_PIXMAP_ELEMENT_TYPES = (b"QXdgDBusImageStruct", b"KDbusImageStruct")

# Qt numbers its tray connections from 1 per process. We only ever build one
# tray icon, but a couple of spares costs nothing and covers a GUI that built
# and dropped one earlier.
_MAX_TRAY_INSTANCES = 4

# Interface elements only, with no <node> wrapper: Qt wraps whatever
# introspect() returns in its own <node>, and returning a second one nests them
# into XML that D-Bus tools refuse to parse.
_INTROSPECT = f"""  <interface name="{SNI_IFACE}">
    <property access="read" type="s" name="Category"/>
    <property access="read" type="s" name="Id"/>
    <property access="read" type="s" name="Title"/>
    <property access="read" type="s" name="Status"/>
    <property access="read" type="i" name="WindowId"/>
    <property access="read" type="s" name="IconThemePath"/>
    <property access="read" type="o" name="Menu"/>
    <property access="read" type="b" name="ItemIsMenu"/>
    <property access="read" type="s" name="IconName"/>
    <property access="read" type="a(iiay)" name="IconPixmap"/>
    <property access="read" type="s" name="OverlayIconName"/>
    <property access="read" type="a(iiay)" name="OverlayIconPixmap"/>
    <property access="read" type="s" name="AttentionIconName"/>
    <property access="read" type="a(iiay)" name="AttentionIconPixmap"/>
    <property access="read" type="s" name="AttentionMovieName"/>
    <property access="read" type="(sa(iiay)ss)" name="ToolTip"/>
    <method name="ContextMenu">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="Activate">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="SecondaryActivate">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="Scroll">
      <arg direction="in" type="i" name="delta"/>
      <arg direction="in" type="s" name="orientation"/>
    </method>
    <method name="ProvideXdgActivationToken">
      <arg direction="in" type="s" name="token"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewMenu"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg type="s" name="status"/>
    </signal>
  </interface>
"""


def pixmap_element_type() -> int | None:
    """The metatype id for one ``(iiay)`` pixmap, or None if Qt hasn't one.

    Only valid once a ``QSystemTrayIcon`` has been constructed — registering it
    is a side effect of Qt building its own tray item.
    """
    for name in _PIXMAP_ELEMENT_TYPES:
        meta = QMetaType.fromName(name)
        if meta.isValid():
            return meta.id()
    return None


def find_tray_connection() -> QDBusConnection | None:
    """Qt's own tray connection, identified by the DBusMenu it carries.

    Keyed on ``/MenuBar`` rather than ``/StatusNotifierItem`` on purpose: the
    menu stays Qt's for the life of the process, while the SNI path is the one
    we take over — so this stays a reliable marker after the swap, and it also
    proves the menu we are about to point at actually exists.
    """
    pid = os.getpid()
    for instance in range(1, _MAX_TRAY_INSTANCES + 1):
        conn = QDBusConnection(f"org.kde.StatusNotifierItem-{pid}-{instance}")
        if conn.isConnected() and conn.objectRegisteredAt(MENU_PATH) is not None:
            return conn
    return None


def _empty_pixmaps(element_type: int) -> QDBusArgument:
    arg = QDBusArgument()
    arg.beginArray(element_type)
    arg.endArray()
    return arg


def build_tooltip(icon_name: str, title: str, description: str,
                  element_type: int) -> QDBusArgument:
    """The ``(sa(iiay)ss)`` ToolTip struct.

    We never send pixmaps — the tray icon is a themed name — so the array is
    always empty; it still has to carry the right element signature, which is
    the entire reason ``element_type`` is threaded down here.
    """
    arg = QDBusArgument()
    arg.beginStructure()
    arg.appendVariant(icon_name)
    arg.beginArray(element_type)
    arg.endArray()
    arg.appendVariant(title)
    arg.appendVariant(description)
    arg.endStructure()
    return arg


class StatusNotifierItem(QDBusVirtualObject):
    """Serves the SNI interface in place of Qt's own object."""

    def __init__(self, tray, element_type: int):
        super().__init__()
        self._tray = tray
        self._element_type = element_type
        self._title = ""
        self._description = ""

    # ----- state -----

    def set_tooltip(self, title: str, description: str) -> bool:
        """Store the split tooltip; True when it actually changed."""
        if (title, description) == (self._title, self._description):
            return False
        self._title, self._description = title, description
        return True

    def _icon_name(self) -> str:
        icon = self._tray.icon()
        return icon.name() if icon is not None else ""

    def _app_name(self) -> str:
        return QCoreApplication.applicationName() or "idasen-companion"

    def _property(self, name: str):
        if name == "ToolTip":
            return build_tooltip(self._icon_name(), self._title,
                                 self._description, self._element_type)
        if name in ("IconPixmap", "OverlayIconPixmap", "AttentionIconPixmap"):
            return _empty_pixmaps(self._element_type)
        if name == "Menu":
            return QDBusObjectPath(MENU_PATH)
        return {
            "Category": "ApplicationStatus",
            "Id": self._app_name(),
            "Title": self._app_name(),
            "Status": "Active",
            "WindowId": 0,
            "IconName": self._icon_name(),
            "IconThemePath": "",
            "OverlayIconName": "",
            "AttentionIconName": "",
            "AttentionMovieName": "",
            "ItemIsMenu": False,
        }.get(name)

    def _all_properties(self) -> dict:
        names = ("Category", "Id", "Title", "Status", "WindowId", "IconName",
                 "IconThemePath", "OverlayIconName", "AttentionIconName",
                 "AttentionMovieName", "ItemIsMenu", "Menu", "ToolTip",
                 "IconPixmap", "OverlayIconPixmap", "AttentionIconPixmap")
        return {name: self._property(name) for name in names}

    # ----- D-Bus -----

    def introspect(self, path: str) -> str:
        return _INTROSPECT

    # handleMessage is a QDBusVirtualObject virtual override, dispatched by
    # name from Qt's C++ meta-object machinery, so it carries its own inline
    # naming-check suppression rather than a file-level one.
    def handleMessage(self, message: QDBusMessage,  # pylint: disable=invalid-name
                      connection: QDBusConnection) -> bool:
        try:
            if message.interface() == PROPS_IFACE:
                return self._handle_property(message, connection)
            if message.interface() == SNI_IFACE:
                return self._handle_method(message, connection)
        except Exception:
            # A raised exception here would propagate into Qt's D-Bus
            # dispatcher; refusing the message just makes the host see an
            # unhandled member, which is survivable.
            return False
        return False

    def _handle_property(self, message, connection) -> bool:
        member = message.member()
        args = message.arguments()
        if member == "Get" and len(args) >= 2:
            value = self._property(args[1])
            if value is None:
                return connection.send(message.createErrorReply(
                    "org.freedesktop.DBus.Error.InvalidArgs", str(args[1])))
            return connection.send(message.createReply(QDBusVariant(value)))
        if member == "GetAll":
            return connection.send(
                message.createReply(self._all_properties()))
        if member == "Set":
            return connection.send(message.createErrorReply(
                "org.freedesktop.DBus.Error.PropertyReadOnly", "read-only"))
        return False

    def _handle_method(self, message, connection) -> bool:
        member = message.member()
        # Plasma talks to *us* now, so QSystemTrayIcon.activated no longer
        # fires for clicks — these calls are the only route left to the
        # configured gestures. Deferred onto the event loop so the reply goes
        # out before anything slow (a BLE move) starts.
        if member == "Activate":
            QTimer.singleShot(0, lambda: self._tray.run_tray_action(
                "tray_left_click", "window"))
        elif member == "SecondaryActivate":
            QTimer.singleShot(0, lambda: self._tray.run_tray_action(
                "tray_middle_click", "toggle"))
        elif member not in ("ContextMenu", "Scroll",
                            "ProvideXdgActivationToken"):
            return False
        # ContextMenu needs no work: the menu is served from /MenuBar, which is
        # what the host uses. Scroll has no configured action today.
        return connection.send(message.createReply())


class RichTooltip:
    """The takeover, and the handle the tray keeps to feed it."""

    def __init__(self, connection: QDBusConnection,
                 item: StatusNotifierItem):
        self._connection = connection
        self._item = item

    @classmethod
    def install(cls, tray) -> "RichTooltip | None":
        """Take over the SNI object, or return None and change nothing."""
        try:
            connection = find_tray_connection()
            if connection is None:
                return None
            element_type = pixmap_element_type()
            if element_type is None:
                return None
            item = StatusNotifierItem(tray, element_type)
            if not cls._register(connection, item):
                return None
            return cls(connection, item)
        except Exception:
            return None

    @staticmethod
    def _register(connection: QDBusConnection,
                  item: StatusNotifierItem) -> bool:
        connection.unregisterObject(SNI_PATH)
        return connection.registerVirtualObject(SNI_PATH, item)

    def update(self, title: str, description: str) -> None:
        """Publish a new title/description, re-taking the path if Qt reclaimed it."""
        try:
            # Change check first, so an update that says nothing new costs one
            # tuple comparison. The tray now calls this once a second to tick
            # its countdown, and most of those seconds are outside the final
            # minute where the rendered string actually differs.
            if not self._item.set_tooltip(title, description):
                return
            # Qt re-registers its own object whenever the StatusNotifierWatcher
            # reappears (a plasmashell restart, say). Its object is a real
            # QObject, ours is virtual and reports None, so a non-None answer
            # here means we were displaced and should take the path back.
            if self._connection.objectRegisteredAt(SNI_PATH) is not None:
                self._register(self._connection, self._item)
            self._connection.send(QDBusMessage.createSignal(
                SNI_PATH, SNI_IFACE, "NewToolTip"))
        except Exception:
            pass
