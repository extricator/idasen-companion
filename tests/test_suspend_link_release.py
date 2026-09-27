"""Handing the desk back across a suspend.

The defect: nothing released the BLE link on the way into a sleep. logind's
PrepareForSleep(true) was only logged, so a machine suspended inside the linger
window held the desk's single connection slot for the whole night, and the desk
was still showing as connected the next morning.

The linger timer is not the failure and is deliberately not retested here: five
measured resumes showed asyncio's monotonic deadlines survive the freeze and
fire on their remaining interval (predicted 49.5s, observed 49.475s). What
fails is the release they trigger, on a link that has spent the sleep going
stale underneath it.

Two mechanisms for that staleness were left undistinguished: bleak's cached
connection flag going false while BlueZ still holds the link, and bleak's
per-connection bus stalling. The pre-sleep release is bounded; resume checks
BlueZ but only disconnects this daemon's own Bleak client, since BlueZ does
not identify the owner of a remaining device link.

No hardware, no BLE stack, no real suspend: the logind signal is delivered by
hand on both edges and every collaborator is a stub.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from idasen_companion.core.config import AppConfig
from idasen_companion.daemon import main as main_mod
from idasen_companion.daemon.inhibit import (
    DELAY_HEADROOM, MAX_BUDGET, MIN_BUDGET, SleepInhibitor,
)

DESK_MAC = "E1:B2:C3:D4:E5:F6"


class FakeInhibitor:
    """A sleep-delay lock that records the sequence instead of taking one."""

    def __init__(self, budget=0.05):
        self.budget = budget
        self.acquires = 0
        self.releases = 0
        self.held = False

    async def acquire(self):
        self.acquires += 1
        self.held = True
        return True

    def release(self):
        self.releases += 1
        self.held = False


def _daemon(monkeypatch, *, connected=True, bluez_connected=False):
    """A Daemon with only what the suspend/resume handler touches."""
    config = AppConfig()
    config.desk.mac = DESK_MAC
    config.presets = {"sit": 0.62, "stand": 1.10}

    daemon = main_mod.Daemon.__new__(main_mod.Daemon)
    daemon._tasks = set()
    daemon.config = config
    daemon.mock_mode = False
    daemon.desk_connected = connected
    daemon._system_bus = MagicMock()
    daemon.activity_log = MagicMock()
    daemon.machine = MagicMock()
    daemon.machine.cycle_target = MagicMock(return_value=0)
    daemon._idle = MagicMock()
    daemon._idle.probe = AsyncMock()
    daemon._sleep_inhibitor = FakeInhibitor()
    daemon.desk = MagicMock()
    daemon.desk.disconnect = AsyncMock()
    daemon.desk.forget_handle = MagicMock()
    monkeypatch.setattr(daemon, "_bluez_property",
                        AsyncMock(return_value=bluez_connected))
    return daemon


def _prepare_for_sleep(active):
    return MagicMock(interface="org.freedesktop.login1.Manager",
                     member="PrepareForSleep", body=[active])


async def _settle(daemon):
    """Run whatever the handler spawned to completion."""
    while daemon._tasks:
        await asyncio.gather(*list(daemon._tasks))


def _diagnostics(daemon):
    return " ".join(call.args[1] for call in daemon.activity_log.diag.call_args_list)


# ----- on the way in -----

async def test_the_link_is_released_before_the_machine_sleeps(monkeypatch):
    """The defect itself: PrepareForSleep(true) used to be logged and nothing
    more, so the desk kept this daemon's connection for the whole night."""
    daemon = _daemon(monkeypatch)
    daemon._on_system_message(_prepare_for_sleep(True))
    await _settle(daemon)
    assert daemon.desk.disconnect.await_count == 1


async def test_the_sleep_is_delayed_only_until_the_desk_is_back(monkeypatch):
    """The lock has to be dropped once the release is done. Held to logind's
    own timeout instead, every suspend would sit there for seconds."""
    daemon = _daemon(monkeypatch)
    daemon._on_system_message(_prepare_for_sleep(True))
    await _settle(daemon)
    assert daemon._sleep_inhibitor.releases == 1
    assert not daemon._sleep_inhibitor.held


async def test_a_release_that_hangs_still_lets_the_machine_sleep(monkeypatch):
    """The bound is the point. A disconnect into a bus that has stopped
    answering must cost the budget, not logind's whole allowance."""
    daemon = _daemon(monkeypatch)

    async def never_answers():
        await asyncio.Event().wait()

    daemon.desk.disconnect = never_answers
    daemon._on_system_message(_prepare_for_sleep(True))
    await asyncio.wait_for(_settle(daemon), 2.0)
    assert daemon._sleep_inhibitor.releases == 1
    assert "0.05s" in _diagnostics(daemon), _diagnostics(daemon)


async def test_a_release_that_raises_still_lets_the_machine_sleep(monkeypatch):
    daemon = _daemon(monkeypatch)
    daemon.desk.disconnect = AsyncMock(side_effect=RuntimeError("bus is gone"))
    daemon._on_system_message(_prepare_for_sleep(True))
    await _settle(daemon)
    assert daemon._sleep_inhibitor.releases == 1
    assert "bus is gone" in _diagnostics(daemon)


# ----- on the way out -----

async def test_resume_releases_own_client_when_bluez_reports_connected(monkeypatch):
    daemon = _daemon(monkeypatch, bluez_connected=True)
    daemon._on_system_message(_prepare_for_sleep(False))
    await _settle(daemon)
    daemon.desk.disconnect.assert_awaited_once()
    assert "cannot identify the link's owner" in _diagnostics(daemon)


async def test_resume_leaves_ambiguous_link_alone_even_if_we_had_it_before_sleep(monkeypatch):
    """The other account may have connected while this one was suspended."""
    daemon = _daemon(monkeypatch, bluez_connected=True)
    daemon._on_system_message(_prepare_for_sleep(True))
    await _settle(daemon)
    daemon.desk.disconnect.reset_mock()
    daemon._on_system_message(_prepare_for_sleep(False))
    await _settle(daemon)
    daemon.desk.disconnect.assert_awaited_once()
    daemon.desk.forget_handle.assert_not_called()


async def test_resume_checks_bluez_even_when_our_client_says_disconnected(monkeypatch):
    daemon = _daemon(monkeypatch, connected=False, bluez_connected=True)
    daemon._on_system_message(_prepare_for_sleep(False))
    await _settle(daemon)
    assert daemon._bluez_property.await_count == 2
    assert "cannot identify the link's owner" in _diagnostics(daemon)


async def test_no_resume_cleanup_when_bluez_says_the_link_is_down(monkeypatch):
    daemon = _daemon(monkeypatch, bluez_connected=False)
    daemon._on_system_message(_prepare_for_sleep(False))
    await _settle(daemon)
    daemon.desk.disconnect.assert_not_awaited()


async def test_a_mock_desk_reconciles_nothing(monkeypatch):
    """--mock-desk has no BlueZ device to ask about, and the configured MAC is
    a fiction."""
    daemon = _daemon(monkeypatch, bluez_connected=True)
    daemon.mock_mode = True
    daemon._on_system_message(_prepare_for_sleep(False))
    await _settle(daemon)
    assert not daemon._bluez_property.called


async def test_the_lock_is_taken_again_for_the_next_sleep(monkeypatch):
    """It is dropped on the way into every sleep, so without this the second
    suspend of a session gets no delay at all."""
    daemon = _daemon(monkeypatch)
    daemon._on_system_message(_prepare_for_sleep(True))
    await _settle(daemon)
    assert not daemon._sleep_inhibitor.held
    daemon._on_system_message(_prepare_for_sleep(False))
    await _settle(daemon)
    assert daemon._sleep_inhibitor.held


async def test_a_lock_that_cannot_be_taken_is_reported(monkeypatch):
    daemon = _daemon(monkeypatch)
    daemon._sleep_inhibitor.acquire = AsyncMock(return_value=False)
    await daemon._rearm_sleep_inhibitor()
    assert "sleep-delay lock" in _diagnostics(daemon)


# ----- the lock itself -----

class FakeReply:
    def __init__(self, body, unix_fds, message_type=None):
        from dbus_fast import MessageType

        self.body = body
        self.unix_fds = unix_fds
        self.message_type = message_type or MessageType.METHOD_RETURN
        self.error_name = None


class FakeBus:
    """Answers the two calls SleepInhibitor makes, and hands out real pipe
    descriptors so closing one can be observed."""

    def __init__(self, max_delay_usec=5_000_000):
        self.max_delay_usec = max_delay_usec
        self.inhibit_calls = []
        self.granted = []

    async def call(self, message):
        if message.member == "Get":
            return FakeReply([_variant(self.max_delay_usec)], [])
        assert message.member == "Inhibit"
        self.inhibit_calls.append(list(message.body))
        readable, writable = os.pipe()
        os.close(writable)
        self.granted.append(readable)
        # A body index of 0 into a one-element descriptor array, which is the
        # shape logind actually replies with (verified against the live bus).
        return FakeReply([0], [readable])


def _variant(value):
    holder = MagicMock()
    holder.value = value
    return holder


def _inhibitor(bus):
    return SleepInhibitor(bus, who="test", why="test")


async def test_the_lock_is_a_descriptor_pulled_out_by_index():
    """D-Bus carries descriptors alongside the body, not in it: the body holds
    an index. Reading the body value as if it were a descriptor would close
    file 0 on release."""
    bus = FakeBus()
    inhibitor = _inhibitor(bus)
    assert await inhibitor.acquire() is True
    assert inhibitor.held
    assert inhibitor._inhibitor_fd == bus.granted[0]
    assert bus.inhibit_calls[0][0] == "sleep"
    assert bus.inhibit_calls[0][3] == "delay", "not a delay lock"


async def test_releasing_closes_the_descriptor():
    """Closing it is what releases the lock; logind is watching the other end."""
    bus = FakeBus()
    inhibitor = _inhibitor(bus)
    await inhibitor.acquire()
    inhibitor.release()
    assert not inhibitor.held
    with pytest.raises(OSError):
        os.fstat(bus.granted[0])


async def test_taking_a_lock_twice_takes_one_lock():
    """A sleep this daemon never heard about leaves the previous lock held, and
    the resume path re-takes unconditionally. Two would leak one."""
    bus = FakeBus()
    inhibitor = _inhibitor(bus)
    assert await inhibitor.acquire() is True
    assert await inhibitor.acquire() is True
    assert len(bus.inhibit_calls) == 1
    inhibitor.release()


async def test_the_budget_leaves_logind_room_to_stop_waiting():
    """Overrunning logind's allowance cannot be caught — the machine simply
    goes down mid-call. The budget has to expire first."""
    bus = FakeBus(max_delay_usec=5_000_000)
    inhibitor = _inhibitor(bus)
    await inhibitor.acquire()
    assert inhibitor.budget == 5.0 - DELAY_HEADROOM
    inhibitor.release()


async def test_the_budget_is_bounded_at_both_ends():
    tiny = _inhibitor(FakeBus(max_delay_usec=100_000))
    await tiny.acquire()
    assert tiny.budget == MIN_BUDGET
    tiny.release()

    huge = _inhibitor(FakeBus(max_delay_usec=600_000_000))
    await huge.acquire()
    assert huge.budget == MAX_BUDGET
    huge.release()


async def test_logind_is_asked_for_its_allowance_once():
    """It runs on the way into every resume, and the answer only changes when
    logind is reloaded."""
    bus = FakeBus()
    inhibitor = _inhibitor(bus)
    await inhibitor.acquire()
    inhibitor.release()
    await inhibitor.acquire()
    inhibitor.release()
    assert inhibitor._asked_logind


async def test_no_bus_degrades_to_delaying_nothing():
    """A machine without logind must still start. It just cannot delay a
    sleep, which the resume-side reconciliation then has to cover."""
    inhibitor = _inhibitor(None)
    assert await inhibitor.acquire() is False
    assert not inhibitor.held
    assert inhibitor.budget > 0
    inhibitor.release()  # must not raise


async def test_an_error_reply_grants_no_lock():
    from dbus_fast import MessageType

    bus = FakeBus()

    async def refuse(_message):
        return FakeReply([], [], message_type=MessageType.ERROR)

    bus.call = refuse
    inhibitor = _inhibitor(bus)
    assert await inhibitor.acquire() is False
    assert not inhibitor.held


async def test_a_reply_without_the_descriptor_grants_no_lock():
    """dbus-fast strips descriptors unless the connection negotiated them, so
    this is what a bus connected without negotiate_unix_fd looks like."""
    bus = FakeBus()

    async def stripped(message):
        if message.member == "Get":
            return FakeReply([_variant(5_000_000)], [])
        return FakeReply([0], [])

    bus.call = stripped
    inhibitor = _inhibitor(bus)
    assert await inhibitor.acquire() is False
    assert not inhibitor.held
