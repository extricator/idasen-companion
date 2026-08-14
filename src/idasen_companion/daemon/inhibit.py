"""The logind sleep-delay lock that buys time to hand the desk back.

Releasing the BLE link takes about two seconds — 2.14s measured on real
hardware, from ``Device1.Disconnect`` to BlueZ actually dropping the link.
logind allows nothing like that on its own: in the case this was written for,
576 ms passed between ``PrepareForSleep(true)`` and this process being frozen.
A disconnect fired into that window freezes half-done, and a half-open link is
exactly what leaves the controller refusing new connections.

A *delay* inhibitor buys the time, and its shape has one consequence worth
stating up front: logind waits only for the delay locks that were already held
when it announced the sleep, so the lock cannot be taken in response to the
signal it exists to delay. It is taken at startup, dropped once the pre-sleep
work is done — which is what lets the sleep proceed immediately rather than
after logind's whole timeout — and taken again on resume.

logind hands the lock out as a file descriptor and releases it when that
descriptor is closed, including when the process holding it dies. So a crashed
daemon cannot wedge suspend, and nothing here needs an unwind path of its own.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from dbus_fast import Message, MessageType
from dbus_fast.errors import DBusError

from .dbus_util import DBusCallError, DEFAULT_TIMEOUT, call

logger = logging.getLogger(__name__)

_LOGIND = "org.freedesktop.login1"
_MANAGER_PATH = "/org/freedesktop/login1"

# logind.conf's shipped default for InhibitDelayMaxSec, used until logind says
# otherwise. Read rather than assumed at runtime because it is configurable,
# and the budget derived from it is the only thing between a stuck disconnect
# and a process frozen in the middle of one.
DEFAULT_MAX_DELAY = 5.0

# Left unspent out of logind's allowance. Overrunning it is not an error that
# can be caught — logind simply stops waiting and the machine goes down
# wherever the code happens to be. This is the margin in which bounded work
# gives up, and says so, while the machine is still running.
DELAY_HEADROOM = 1.0

# Floor and ceiling on the budget derived from logind's allowance. The floor
# keeps a machine configured down to a fraction of a second from producing a
# budget of zero; the ceiling says no configured allowance justifies holding a
# suspend up longer than this for work measured at roughly two seconds.
MIN_BUDGET = 1.0
MAX_BUDGET = 10.0


def _descriptor_from(reply) -> int | None:
    """The file descriptor an ``Inhibit`` reply carries, or None.

    D-Bus does not put descriptors in a message body: the body holds an *index*
    and the descriptors travel alongside it, so both halves have to line up
    before there is any lock to hold. Anything left over is closed here — an
    unclosed descriptor is not only a leak, it is a lock this object does not
    know it is holding, which would delay every future suspend by logind's
    whole timeout.
    """
    if reply is None or reply.message_type is not MessageType.METHOD_RETURN:
        logger.debug("logind granted no sleep-delay lock: %s",
                     getattr(reply, "error_name", "no reply"))
        return None
    spares = list(reply.unix_fds or ())
    try:
        granted = spares.pop(int(reply.body[0]))
    except (IndexError, TypeError, ValueError):
        logger.debug("logind's inhibitor reply carried no usable descriptor")
        granted = None
    for leftover in spares:
        with contextlib.suppress(OSError):
            os.close(leftover)
    return granted


class SleepInhibitor:
    """A held logind sleep-delay lock, and the time budget it buys.

    ``system_bus`` may be None — logind unreachable — in which case every
    acquire fails quietly and ``budget`` reports the shipped default. Callers
    get a working object that simply never delays anything, rather than an
    optional collaborator every reader has to guard.
    """

    def __init__(self, system_bus, *, who: str, why: str):
        self._bus = system_bus
        self._who = who
        self._why = why
        self._inhibitor_fd: int | None = None
        self._max_delay = DEFAULT_MAX_DELAY
        self._asked_logind = False

    @property
    def held(self) -> bool:
        """Whether a lock is held, i.e. whether a sleep will wait for us."""
        return self._inhibitor_fd is not None

    @property
    def budget(self) -> float:
        """Seconds pre-sleep work may take before logind stops waiting."""
        return min(MAX_BUDGET,
                   max(MIN_BUDGET, self._max_delay - DELAY_HEADROOM))

    async def acquire(self) -> bool:
        """Take a delay lock unless one is already held. Returns whether one is.

        Idempotent on purpose: the daemon re-takes a lock after every resume,
        and a sleep it was never told about leaves the previous one still held.
        """
        if self._inhibitor_fd is not None:
            return True
        if self._bus is None:
            return False
        await self._learn_max_delay()
        message = Message(
            destination=_LOGIND, path=_MANAGER_PATH,
            interface=f"{_LOGIND}.Manager", member="Inhibit",
            signature="ssss", body=["sleep", self._who, self._why, "delay"])
        # Sent through the bus directly rather than through dbus_util.call:
        # the lock arrives as a file descriptor, and that helper returns only
        # the reply body — which for an 'h' argument holds an index into the
        # descriptors the message carried, not a descriptor.
        try:
            reply = await asyncio.wait_for(self._bus.call(message),
                                           DEFAULT_TIMEOUT)
        except (asyncio.TimeoutError, DBusError, OSError) as error:
            logger.debug("logind refused a sleep-delay lock: %s", error)
            return False
        self._inhibitor_fd = _descriptor_from(reply)
        return self._inhibitor_fd is not None

    def release(self) -> None:
        """Close the lock, letting a pending sleep proceed at once."""
        descriptor = self._inhibitor_fd
        if descriptor is None:
            return
        self._inhibitor_fd = None
        try:
            os.close(descriptor)
        except OSError as error:
            logger.debug("could not close the sleep-delay lock: %s", error)

    async def _learn_max_delay(self) -> None:
        """Read logind's own delay allowance, once per process.

        Asked once rather than per acquire because this runs on the way into
        every resume, and the answer only changes when logind is reloaded.
        """
        if self._asked_logind or self._bus is None:
            return
        self._asked_logind = True
        try:
            body = await call(self._bus, _LOGIND, _MANAGER_PATH,
                              "org.freedesktop.DBus.Properties", "Get", "ss",
                              [f"{_LOGIND}.Manager", "InhibitDelayMaxUSec"])
            microseconds = getattr(body[0], "value", body[0])
        except (DBusCallError, DBusError, IndexError) as error:
            logger.debug("logind would not say its delay maximum (%s); "
                         "assuming %gs", error, DEFAULT_MAX_DELAY)
            return
        if isinstance(microseconds, int) and microseconds > 0:
            self._max_delay = microseconds / 1_000_000
