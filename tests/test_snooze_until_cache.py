# SPDX-License-Identifier: GPL-3.0-or-later
"""The snooze deadline is cached, not fetched on the GUI thread.

``SnoozeUntil`` is a D-Bus *property*, and the Overview used to read it with a
blocking ``Properties.Get`` every time it drew the snoozed state — a
synchronous round-trip on the thread that paints the window, repeated once per
status announcement for as long as the snooze lasted.

``PropertiesChanged`` is not available as a fix: its ``sa{sv}as`` signature is
exactly the container QtDBus cannot demarshal, which is why the daemon carries
flat signals in the first place. So the client re-reads the property when the
status says it may have moved, asynchronously, and serves every reader from
cache.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import pytest

pytest.importorskip("PySide6")

import os
from datetime import datetime

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtDBus import QDBusMessage  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.core.clocks import WallInstant  # noqa: E402
from idasen_companion.core.machine import Status  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.dbus_client import DaemonClient  # noqa: E402
from idasen_companion.gui.pages.overview import OverviewPage  # noqa: E402


# ----- the client's cache -----


@pytest.fixture
def client(qapp):
    """A DaemonClient with none of its constructor run.

    ``__init__`` opens the session bus, subscribes to signals and pings the
    live daemon — so building one properly would make these tests depend on a
    bus and on whatever the real daemon happens to be doing. Everything under
    test here is pure state handling around one injected call.
    """
    obj = DaemonClient.__new__(DaemonClient)
    QObject.__init__(obj)
    obj._snooze_until = WallInstant(0.0)
    # This fixture isolates snooze-property requests from observation transport.
    obj._refresh_position_observation = lambda: None
    obj.requests = []
    obj.get_property_async = lambda iface, name, then: obj.requests.append(
        (name, then))
    return obj


def test_a_snoozed_status_asks_for_the_deadline(client):
    client._note_status(Status.SNOOZED)
    assert [name for name, _ in client.requests] == ["SnoozeUntil"]
    # Asked, not yet answered: nothing to report until the reply lands.
    assert client.snooze_until() == WallInstant(0.0)


def test_the_reply_lands_in_the_cache(client):
    seen = []
    client.snoozeUntilChanged.connect(seen.append)
    client._note_status(Status.SNOOZED)
    _, deliver = client.requests[0]
    deliver(1800.0)
    assert client.snooze_until() == WallInstant(1800.0)
    assert seen == [1800.0]
    assert type(seen[0]) is float


def test_reading_the_deadline_is_never_a_round_trip(client):
    client._note_status(Status.SNOOZED)
    client.requests[0][1](1800.0)
    before = len(client.requests)
    for _ in range(10):
        client.snooze_until()
    assert len(client.requests) == before


def test_an_unchanged_deadline_does_not_redraw(client):
    # The daemon re-announces the status every check_interval while snoozed,
    # so an unconditional emit would repaint the page once a minute for
    # nothing.
    seen = []
    client._note_status(Status.SNOOZED)
    client.requests[0][1](1800.0)
    client.snoozeUntilChanged.connect(seen.append)
    client._note_status(Status.SNOOZED)
    client.requests[1][1](1800.0)
    assert seen == []


def test_a_second_snooze_extends_it(client):
    seen = []
    client.snoozeUntilChanged.connect(seen.append)
    client._note_status(Status.SNOOZED)
    client.requests[0][1](1800.0)
    client._note_status(Status.SNOOZED)
    client.requests[1][1](2400.0)
    assert client.snooze_until() == WallInstant(2400.0)
    assert seen == [1800.0, 2400.0]


def test_leaving_the_snooze_clears_it_without_asking(client):
    client._note_status(Status.SNOOZED)
    client.requests[0][1](1800.0)
    seen = []
    client.snoozeUntilChanged.connect(seen.append)
    client._note_status(Status.ACTIVE)
    assert client.snooze_until() == WallInstant(0.0)
    assert seen == [0.0]
    # A status that isn't snoozed has no deadline to fetch.
    assert len(client.requests) == 1


@pytest.mark.parametrize("entry", ["live", "refresh"])
def test_status_paths_update_snooze_cache_before_emitting_raw_strings(
        client, monkeypatch, entry):
    observed = []
    client.statusChanged.connect(
        lambda raw: observed.append((raw, type(raw), len(client.requests),
                                     client.snooze_until())))
    current = [None]
    monkeypatch.setattr(client, "get_property",
                        lambda iface, name: current[0] if name == "Status" else None)
    monkeypatch.setattr(client, "list_presets", lambda: {})

    def announce(raw):
        if entry == "live":
            message = QDBusMessage.createSignal("/desk", "test.Desk", "StatusChanged")
            message.setArguments([raw])
            client._on_status(message)
        else:
            current[0] = raw
            client.refresh_all()

    announce("snoozed")
    assert observed[-1] == ("snoozed", str, 1, WallInstant(0.0))
    client.requests[-1][1](1800.0)
    announce("snoozed")
    assert observed[-1] == ("snoozed", str, 2, WallInstant(1800.0))
    client.requests[-1][1](2400.0)

    for raw in ("active", " Future Status ", ""):
        announce(raw)
        assert observed[-1] == (raw, str, 2, WallInstant(0.0))

    if entry == "refresh":
        before = (len(observed), len(client.requests))
        announce(None)
        assert (len(observed), len(client.requests)) == before


# ----- what the Overview does with it -----


class FakeClient(QObject):
    """The signals and call targets OverviewPage wires up, and nothing else."""

    heightChanged = Signal(float)
    positionChanged = Signal(str)
    connectedChanged = Signal(bool)
    movingChanged = Signal(bool)
    statusChanged = Signal(str)
    progressChanged = Signal(float, float)
    presetsChanged = Signal(dict)
    availableChanged = Signal(bool)
    snoozeUntilChanged = Signal(float)

    available = False

    def __init__(self):
        super().__init__()
        self._snooze_until = WallInstant(0.0)

    def snooze_until(self):
        return self._snooze_until

    def deliver_snooze_until(self, value):
        self._snooze_until = WallInstant(value)
        self.snoozeUntilChanged.emit(value)

    def sit(self): ...
    def stand(self): ...
    def stop(self): ...
    def pause(self): ...
    def resume(self): ...
    def skip_next(self): ...
    def snooze(self, minutes): ...
    def move_to_height(self, height): ...
    def set_automation_enabled(self, enabled): ...
    def idle_provider(self): return "none"


@pytest.fixture
def page(qapp, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    return OverviewPage(AppContext(FakeClient(), tray_available=True))


def test_the_deadline_redraws_the_page_when_it_arrives(page):
    page.client.statusChanged.emit("snoozed")
    # One round-trip behind the status, so the first draw can only say this.
    assert page.status_head_lbl.text() == "Snoozed until later"
    when = datetime(2026, 8, 1, 14, 30)
    page.client.deliver_snooze_until(when.timestamp())
    assert page.status_head_lbl.text() == (
        "Snoozed until %s" % page.ctx.fmt.clock(
            datetime(2026, 8, 3, 14, 30)))
