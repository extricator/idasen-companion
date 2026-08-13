"""IdleMonitor fallback-chain behavior with fake providers."""

from idasen_companion.daemon import idle as idle_mod
from idasen_companion.daemon.idle import (
    DBusCallError, IdleMonitor, SEAT_BACKGROUND, SEAT_FOREGROUND, SEAT_NONE,
    SEAT_UNKNOWN, SessionActiveMonitor,
)


class FakeProvider:
    def __init__(self, name, idle_ms=1234, broken=False):
        self.name = name
        self.idle_ms = idle_ms
        self.broken = broken
        self.calls = 0

    async def get_idle_ms(self):
        self.calls += 1
        if self.broken:
            raise RuntimeError("provider broken")
        return self.idle_ms


async def test_first_working_provider_wins():
    broken = FakeProvider("broken", broken=True)
    good = FakeProvider("good", idle_ms=500)
    monitor = IdleMonitor([broken, good])
    await monitor.probe()
    assert monitor.active_provider is good
    assert await monitor.get_idle_ms() == 500
    assert monitor.provider_name == "good"


async def test_no_provider_assumes_active():
    monitor = IdleMonitor([FakeProvider("a", broken=True)])
    await monitor.probe()
    assert monitor.active_provider is None
    assert await monitor.get_idle_ms() == 0
    assert "assuming active" in monitor.provider_name


async def test_failure_triggers_reprobe_and_fallback():
    flaky = FakeProvider("flaky")
    backup = FakeProvider("backup", idle_ms=42)
    monitor = IdleMonitor([flaky, backup])
    await monitor.probe()
    assert monitor.active_provider is flaky

    flaky.broken = True
    # The failing call returns 0 (assume active) and re-probes the chain.
    assert await monitor.get_idle_ms() == 0
    assert monitor.active_provider is backup
    assert await monitor.get_idle_ms() == 42


# ----- SessionActiveMonitor (seat-foreground gate) -----

def _fake_logind(*, active=True, has_display=True, seat="seat0",
                 fail_getuser=False):
    """Stand in for the logind system-bus calls SessionActiveMonitor makes:
    GetUser -> user path, Get(User.Display) -> (session_id, path) struct,
    Get(Session.Seat) -> (seat_id, path) struct, Get(Session.Active) -> bool.

    Defaults mirror a normal desktop login (a session on seat0). ``seat=""``
    is the SSH/remote shape: logind still names it as the Display session, and
    still reports it Active, because it has no seat to be inactive on."""
    async def fake_call(bus, dest, path, iface, member, sig="", body=None):
        if member == "GetUser":
            if fail_getuser:
                raise DBusCallError("no such user")
            return ["/org/freedesktop/login1/user/_1000"]
        if member == "Get":
            prop = body[1]
            if prop == "Display":
                sid = "2" if has_display else ""
                return [[sid, "/org/freedesktop/login1/session/_32"]]
            if prop == "Seat":
                return [[seat, f"/org/freedesktop/login1/seat/{seat or 'none'}"]]
            if prop == "Active":
                return [active]
        raise AssertionError(f"unexpected call: {member} {body}")
    return fake_call


async def test_session_foreground_when_active(monkeypatch):
    monkeypatch.setattr(idle_mod, "call", _fake_logind(active=True))
    m = SessionActiveMonitor(system_bus=object(), uid=1000)
    assert await m.state() == SEAT_FOREGROUND
    assert m.available is True


async def test_session_backgrounded_when_switched_away(monkeypatch):
    monkeypatch.setattr(idle_mod, "call", _fake_logind(active=False))
    m = SessionActiveMonitor(system_bus=object(), uid=1000)
    # VT-switched away: the one verdict that stops this session using the desk.
    assert await m.state() == SEAT_BACKGROUND
    assert m.available is True


async def test_session_no_bus_is_unknown_not_a_verdict():
    m = SessionActiveMonitor(system_bus=None, uid=1000)
    assert await m.state() == SEAT_UNKNOWN  # never freeze automation
    assert m.available is False


async def test_session_resolve_failure_degrades(monkeypatch):
    monkeypatch.setattr(idle_mod, "call", _fake_logind(fail_getuser=True))
    m = SessionActiveMonitor(system_bus=object(), uid=1000)
    assert await m.state() == SEAT_UNKNOWN
    assert m.available is False


async def test_a_session_with_no_seat_is_not_at_this_machine(monkeypatch):
    """The SSH case, and the one this nearly got wrong. ``User.Display`` is not
    necessarily graphical — logind prefers a graphical session but falls back to
    a tty one, so a remote login lands there too — and *every* seatless session
    reports Active=true, because session_is_active() is "no seat, OR I am my
    seat's active session". Reading Active alone would take an SSH login for
    someone sitting at the desk. Both verified against a live logind."""
    monkeypatch.setattr(idle_mod, "call", _fake_logind(seat="", active=True))
    assert await SessionActiveMonitor(object(), uid=1000).state() == SEAT_NONE

    # A local text console *does* have a seat, so it is gated on Active like
    # any other session — switched away rather than absent.
    monkeypatch.setattr(idle_mod, "call", _fake_logind(seat="seat0", active=False))
    assert await SessionActiveMonitor(object(), uid=1000).state() == SEAT_BACKGROUND


async def test_no_graphical_session_is_told_apart_from_a_failed_call(monkeypatch):
    """The distinction the whole stand-down rule rests on. Both leave the
    session path unresolved, but only one is an *answer*: logind saying this
    user has no desktop is grounds to stand down, while a failed call is no
    information and must never be."""
    monkeypatch.setattr(idle_mod, "call", _fake_logind(has_display=False))
    assert await SessionActiveMonitor(object(), uid=1000).state() == SEAT_NONE

    monkeypatch.setattr(idle_mod, "call", _fake_logind(fail_getuser=True))
    assert await SessionActiveMonitor(object(), uid=1000).state() == SEAT_UNKNOWN

    # No system bus at all is the same kind of nothing.
    assert await SessionActiveMonitor(None, uid=1000).state() == SEAT_UNKNOWN


async def test_session_reresolves_after_active_read_fails(monkeypatch):
    monkeypatch.setattr(idle_mod, "call", _fake_logind(active=True))
    m = SessionActiveMonitor(system_bus=object(), uid=1000)
    assert await m.state() == SEAT_FOREGROUND
    assert m.available is True  # resolved and cached

    resolve_ok = _fake_logind(active=True)

    async def active_fails(bus, dest, path, iface, member, sig="", body=None):
        if member == "Get" and body[1] == "Active":
            raise DBusCallError("session gone")
        return await resolve_ok(bus, dest, path, iface, member, sig, body)

    monkeypatch.setattr(idle_mod, "call", active_fails)
    assert await m.state() == SEAT_UNKNOWN   # degrades on the read failure
    assert m.available is False              # cached path forgotten -> re-resolve


async def test_losing_every_provider_is_reported_once():
    """The condition startup treats as too important to be a footnote, arriving
    later: gnome-shell restarts, the KDE screensaver service goes away. From
    then on get_idle_ms() reports a flat 0 — "at the keyboard right now" — and
    the desk cycles on a plain schedule.

    The old warning here was unreachable from the failure path: get_idle_ms
    cleared active_provider *before* calling probe(), whose report was guarded
    on it being non-None.
    """
    lost = []
    provider = FakeProvider("kde", idle_ms=500)
    monitor = IdleMonitor([provider], on_lost=lambda: lost.append(True))
    await monitor.probe()
    assert monitor.active_provider is provider
    assert lost == []

    provider.broken = True
    assert await monitor.get_idle_ms() == 0
    assert monitor.active_provider is None
    assert lost == [True], "losing the provider reached nobody"

    # ...and not once per tick from then on.
    for _ in range(5):
        await monitor.get_idle_ms()
    assert lost == [True]


async def test_never_having_a_provider_is_not_reported_as_losing_one():
    """Startup's own no-provider case is reported by the daemon, which has the
    ring and the config; reporting it here too would double-log it."""
    lost = []
    monitor = IdleMonitor([FakeProvider("x", broken=True)],
                          on_lost=lambda: lost.append(True))
    await monitor.probe()
    assert monitor.active_provider is None
    assert lost == []


async def test_a_provider_returning_after_a_loss_can_be_lost_again():
    lost = []
    provider = FakeProvider("kde", idle_ms=500)
    monitor = IdleMonitor([provider], on_lost=lambda: lost.append(True))
    await monitor.probe()

    provider.broken = True
    await monitor.get_idle_ms()
    assert lost == [True]

    provider.broken = False
    await monitor.probe()
    assert monitor.active_provider is provider

    provider.broken = True
    await monitor.get_idle_ms()
    assert lost == [True, True], "a second outage went unreported"
