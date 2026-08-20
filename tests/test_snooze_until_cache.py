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
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.dbus_client import DaemonClient  # noqa: E402
from idasen_companion.gui.pages.overview import OverviewPage  # noqa: E402
from idasen_companion.gui.util import fmt_clock  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


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
    obj._snooze_until = 0.0
    obj.requests = []
    obj.get_property_async = lambda iface, name, then: obj.requests.append(
        (name, then))
    return obj


def test_a_snoozed_status_asks_for_the_deadline(client):
    client._note_status("snoozed")
    assert [name for name, _ in client.requests] == ["SnoozeUntil"]
    # Asked, not yet answered: nothing to report until the reply lands.
    assert client.snooze_until() == 0.0


def test_the_reply_lands_in_the_cache(client):
    seen = []
    client.snoozeUntilChanged.connect(seen.append)
    client._note_status("snoozed")
    _, deliver = client.requests[0]
    deliver(1800.0)
    assert client.snooze_until() == 1800.0
    assert seen == [1800.0]


def test_reading_the_deadline_is_never_a_round_trip(client):
    client._note_status("snoozed")
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
    client._note_status("snoozed")
    client.requests[0][1](1800.0)
    client.snoozeUntilChanged.connect(seen.append)
    client._note_status("snoozed")
    client.requests[1][1](1800.0)
    assert seen == []


def test_a_second_snooze_extends_it(client):
    seen = []
    client.snoozeUntilChanged.connect(seen.append)
    client._note_status("snoozed")
    client.requests[0][1](1800.0)
    client._note_status("snoozed")
    client.requests[1][1](2400.0)
    assert client.snooze_until() == 2400.0
    assert seen == [1800.0, 2400.0]


def test_leaving_the_snooze_clears_it_without_asking(client):
    client._note_status("snoozed")
    client.requests[0][1](1800.0)
    seen = []
    client.snoozeUntilChanged.connect(seen.append)
    client._note_status("active")
    assert client.snooze_until() == 0.0
    assert seen == [0.0]
    # A status that isn't snoozed has no deadline to fetch.
    assert len(client.requests) == 1


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
        self._snooze_until = 0.0

    def snooze_until(self):
        return self._snooze_until

    def deliver_snooze_until(self, value):
        self._snooze_until = value
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
        "Snoozed until %s" % fmt_clock(datetime(2026, 8, 3, 14, 30)))
