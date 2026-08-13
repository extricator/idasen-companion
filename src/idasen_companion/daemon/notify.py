"""Desktop notifications via org.freedesktop.Notifications, sent by the
daemon so pre-move warnings work even when the GUI isn't running."""

from __future__ import annotations

import logging
from typing import Callable

from dbus_fast import Message

from .dbus_util import DBusCallError, call

logger = logging.getLogger(__name__)

NOTIFY_DEST = "org.freedesktop.Notifications"
NOTIFY_PATH = "/org/freedesktop/Notifications"
NOTIFY_IFACE = "org.freedesktop.Notifications"


class Notifier:
    def __init__(self, bus, app_name: str = "Idasen Companion"):
        self._bus = bus
        self._app_name = app_name
        self._last_id = 0
        # `object` return, not None: callers pass lambdas that hand back an
        # ensure_future Task, and the notifier ignores whatever comes back.
        self._actions: dict[str, Callable[[], object]] = {}
        self._match_added = False

    async def _ensure_signal_subscription(self) -> None:
        if self._match_added:
            return
        rule = f"type='signal',interface='{NOTIFY_IFACE}',member='ActionInvoked'"
        await call(self._bus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
                   "org.freedesktop.DBus", "AddMatch", "s", [rule])
        self._bus.add_message_handler(self._on_message)
        self._match_added = True

    def _on_message(self, message: Message):
        if (message.interface == NOTIFY_IFACE and message.member == "ActionInvoked"
                and message.body and message.body[0] == self._last_id):
            action = self._actions.get(message.body[1])
            if action:
                action()
        return None  # not handled exclusively

    async def send(self, summary: str, body: str = "", *,
                   actions: dict[str, tuple[str, Callable[[], object]]] | None = None,
                   timeout_ms: int = 15_000) -> bool:
        """Send a notification. ``actions`` maps action keys to
        (button label, callback). Returns False if no notification service
        answered (daemon carries on fine without one).

        Always replaces the notifier's previous popup (``_last_id``) rather
        than stacking a new one: every message this sends is about the same
        one desk, so a second is a correction, not an addition."""
        action_list: list[str] = []
        self._actions = {}
        for key, (label, callback) in (actions or {}).items():
            action_list.extend([key, label])
            self._actions[key] = callback
        try:
            if actions:
                await self._ensure_signal_subscription()
            result = await call(
                self._bus, NOTIFY_DEST, NOTIFY_PATH, NOTIFY_IFACE, "Notify",
                "susssasa{sv}i",
                [self._app_name,
                 self._last_id,
                 "input-tablet",  # stock icon on purpose: a notification should not
                 # depend on our own theme icon being installed
                 summary, body, action_list, {}, timeout_ms],
            )
            self._last_id = result[0]
            return True
        except DBusCallError as error:
            logger.debug("notification failed: %s", error)
            return False
