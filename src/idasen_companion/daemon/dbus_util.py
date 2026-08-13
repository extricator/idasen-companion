"""Small helpers over dbus-fast for one-shot method calls."""

from __future__ import annotations

import asyncio

from dbus_fast import Message, MessageType


class DBusCallError(Exception):
    pass


# dbus-fast waits for a reply forever, and a desktop service that accepts a
# call but never answers is not hypothetical: a KDE session pushed to the
# background by a VT switch stops replying, which once parked the daemon's
# control loop for 41 minutes — no ticks, no logging, no automation, no
# indication anything was wrong. Every caller already handles DBusCallError
# with a safe fallback, so a deadline just routes a hang into that path.
DEFAULT_TIMEOUT = 5.0


async def call(bus, destination: str, path: str, interface: str, member: str,
               signature: str = "", body: list | None = None,
               timeout: float = DEFAULT_TIMEOUT) -> list:
    """One-shot D-Bus method call; raises DBusCallError on any error reply,
    or if no reply arrives within ``timeout`` seconds."""
    message = Message(
        destination=destination,
        path=path,
        interface=interface,
        member=member,
        signature=signature,
        body=body or [],
    )
    try:
        reply = await asyncio.wait_for(bus.call(message), timeout)
    except asyncio.TimeoutError:
        raise DBusCallError(
            f"{destination} {member}: no reply within {timeout:g}s") from None
    if reply is None or reply.message_type == MessageType.ERROR:
        error = reply.error_name if reply is not None else "no reply"
        raise DBusCallError(f"{destination} {member}: {error}")
    return reply.body
