"""Both desk implementations must satisfy DeskPort — structurally, not just
in the two methods anyone happened to call.

Nothing bound BleDesk or MockDesk to the Protocol, so drift was invisible.
Three members the daemon depends on were *outside* the contract and reached
with `hasattr` / `getattr` / a `cast` instead — and MockDesk had no
`last_error` at all, which meant that under `--mock-desk` the daemon's
"move failed, and here is why" branch was unreachable and a whole catalogued
message (plus its Spanish translation) was exercised by nothing.
"""

import inspect

import pytest

from idasen_companion.desk.ble import BleDesk
from idasen_companion.desk.mock import MockDesk
from idasen_companion.desk.port import DeskPort

def make_mock():
    return MockDesk()


def make_ble():
    # Constructing it connects to nothing; the factory is never called until
    # an operation needs a client.
    return BleDesk("E1:B2:C3:D4:E5:F6", desk_factory=lambda mac, cb: None)


IMPLEMENTATIONS = [make_mock, make_ble]
IDS = ["MockDesk", "BleDesk"]


def port_members():
    return [n for n in vars(DeskPort) if not n.startswith("_")]


def test_the_protocol_declares_what_the_daemon_actually_uses():
    """Guard the guard: if someone trims DeskPort back, this file would keep
    passing while checking less."""
    assert set(port_members()) >= {
        "get_height", "move_to", "stop", "disconnect", "last_error"}


@pytest.mark.parametrize("make", IMPLEMENTATIONS, ids=IDS)
@pytest.mark.parametrize("member", port_members())
def test_every_implementation_has_every_member(make, member):
    # On an *instance*: last_error is set in __init__, not on the class.
    desk = make()
    assert hasattr(desk, member), f"{type(desk).__name__} is missing {member}"


@pytest.mark.parametrize("make", IMPLEMENTATIONS, ids=IDS)
@pytest.mark.parametrize("member", ["get_height", "move_to", "stop", "disconnect"])
def test_the_coroutine_members_are_coroutines_on_both(make, member):
    fn = getattr(make(), member)
    assert inspect.iscoroutinefunction(fn), f"{member} is not async"


async def test_the_mock_can_report_a_reason_for_a_failed_move():
    """The property that makes MANUAL_MOVE_FAILED_REASON reachable without
    hardware. Previously MockDesk had no last_error, so `getattr(..., None)`
    always took the reasonless branch under --mock-desk."""
    desk = MockDesk()
    assert desk.last_error is None

    desk.fail_next_move = True
    desk.last_error = "connect timed out"
    assert await desk.move_to(1.10) is False
    assert desk.last_error == "connect timed out"


async def test_the_mock_disconnect_is_a_no_op_that_can_be_awaited():
    desk = MockDesk(height=0.9)
    await desk.disconnect()      # must not raise
    assert desk.height == 0.9    # and must not disturb anything


def test_a_mock_desk_is_accepted_where_a_deskport_is_wanted():
    def wants_port(_d: DeskPort) -> None:
        pass

    wants_port(MockDesk())       # runtime is trivially fine; mypy is the check
