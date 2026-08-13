"""dbus_util.call() deadline behavior.

Regression cover for the failure that parked the daemon's control loop for 41
minutes: a session-bus service that accepts a call and never replies (which is
what a KDE session does once a VT switch pushes it to the background). Without
a deadline the daemon simply stopped ticking, silently.
"""

import asyncio

import pytest
from dbus_fast import MessageType

from idasen_companion.daemon.dbus_util import DBusCallError, call

# dbus-fast validates these at Message construction, so they must be real-looking.
DEST, PATH, IFACE = "org.example.Svc", "/org/example/Svc", "org.example.Iface"


class FakeReply:
    def __init__(self, message_type=MessageType.METHOD_RETURN, body=None,
                 error_name=None):
        self.message_type = message_type
        self.body = body if body is not None else []
        self.error_name = error_name


class FakeBus:
    """Bus whose replies we control, including "never answers"."""

    def __init__(self, reply=None, hang=False):
        self._reply = reply
        self._hang = hang
        self.cancelled = False

    async def call(self, message):
        if self._hang:
            try:
                await asyncio.Event().wait()  # never set
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return self._reply


async def test_successful_call_returns_body():
    bus = FakeBus(FakeReply(body=["ok"]))
    assert await call(bus, DEST, PATH, IFACE, "Method") == ["ok"]


async def test_error_reply_raises():
    bus = FakeBus(FakeReply(MessageType.ERROR, error_name="org.fd.Error.Foo"))
    with pytest.raises(DBusCallError, match="org.fd.Error.Foo"):
        await call(bus, DEST, PATH, IFACE, "Method")


async def test_silent_peer_times_out_instead_of_hanging():
    bus = FakeBus(hang=True)
    with pytest.raises(DBusCallError, match="no reply within"):
        await call(bus, DEST, PATH, IFACE, "Method", timeout=0.05)
    # The pending call is abandoned, not left dangling on the bus.
    assert bus.cancelled


async def test_timeout_is_bounded_by_the_deadline():
    """The whole point: a hung peer costs `timeout`, not the rest of the day."""
    bus = FakeBus(hang=True)
    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(DBusCallError):
        await call(bus, DEST, PATH, IFACE, "Method", timeout=0.05)
    assert loop.time() - started < 1.0
