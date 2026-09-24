"""The tray's "Connecting…" feedback while a click waits on the BLE link.

With on-demand Bluetooth the link is dropped a few seconds after every
operation, so most tray clicks pay a cold connect before anything happens —
measured between 2 and 12 seconds on real hardware, essentially all of it
inside BlueZ's link establishment. Until the desk started moving the click
produced no feedback whatsoever, which reads as "the click didn't register".

What these pin is when the label appears and, more importantly, when it does
*not*: a warm click completes in milliseconds, and a repeat click during a
move is the cancel gesture, so neither should flash "Connecting…".

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import pytest

pytest.importorskip("PySide6")

import os

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from types import SimpleNamespace  # noqa: E402

import shiboken6  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.presentation import EnglishTranslator  # noqa: E402
from idasen_companion.core.presentation import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.locale_profile import TimeStyle
from idasen_companion.core.locale_profile import (  # noqa: E402
    LocaleProfile,
)
from idasen_companion.core.display_prefs import HeightUnit  # noqa: E402
from idasen_companion.gui.tray import TrayIcon  # noqa: E402


class FakeClient(QObject):
    """The signals TrayIcon subscribes to, plus the calls it makes."""

    statusChanged = Signal(str)
    positionChanged = Signal(str)
    progressChanged = Signal(float, float)
    presetsChanged = Signal(dict)
    availableChanged = Signal(bool)
    connectedChanged = Signal(bool)
    movingChanged = Signal(bool)
    snoozeUntilChanged = Signal(float)

    available = False

    def __init__(self):
        super().__init__()
        self.gestures = []

    def gesture_move(self, action):
        self.gestures.append(action)

    def __getattr__(self, name):
        # Menu entries wire up toggle/sit/stand/stop/... at construction; none
        # of them are exercised here beyond existing.
        return lambda *a, **kw: None


class _NullSignal:
    """Stands in for a Qt signal ``TrayIcon.__init__`` connects to, without
    a real ``QObject`` behind it."""

    def connect(self, *args, **kwargs):
        pass


class FakeWindow:
    """A ``ctx`` carrying only what ``TrayIcon`` reaches for -- ``cfg``
    stays ``None`` so ``TrayIcon._action`` still falls back to its
    defaults, exactly as it did before ``_fmt()`` had a caller."""

    def __init__(self):
        self.ctx = SimpleNamespace(
            cfg=None,
            configChanged=_NullSignal(),
            fmt=Formatter(PresentationContext(
                locale=LocaleProfile("en_US"), translator=EnglishTranslator(),
                unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE_24)))


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tray(qapp):
    client = FakeClient()
    icon = TrayIcon(client, FakeWindow(), QIcon())
    yield icon, client
    # Destroy it here rather than letting Python drop the last reference
    # whenever it feels like it: a QSystemTrayIcon collected after the offscreen
    # QPA platform has been torn down segfaults the interpreter at exit, which
    # fails the RPM build's %check even with every test passing.
    icon.hide()
    icon.setContextMenu(None)
    shiboken6.delete(icon)


def label(tray):
    return tray._status_action.text()


def test_cold_click_shows_connecting_and_still_sends_the_request(tray):
    icon, client = tray
    icon._on_connected(False)
    icon._on_moving(False)

    icon._run_action("toggle")

    assert label(icon) == "Connecting…"
    assert "Connecting…" in icon.toolTip()
    # Feedback is cosmetic — it must not swallow or delay the actual move.
    assert client.gestures == ["toggle"]


def test_movement_starting_clears_connecting(tray):
    icon, client = tray
    icon._on_connected(False)
    icon._on_moving(False)
    icon._run_action("toggle")
    assert label(icon) == "Connecting…"

    icon._on_moving(True)

    assert label(icon) != "Connecting…"
    assert not icon._connecting_timer.isActive()


def test_connecting_waits_for_movement_not_for_the_link(tray):
    # The link coming up is still ~1.5s of service discovery and a height read
    # short of anything the user can see, so the label must survive it.
    icon, _ = tray
    icon._on_connected(False)
    icon._on_moving(False)
    icon._run_action("toggle")

    icon._on_connected(True)

    assert label(icon) == "Connecting…"


def test_warm_click_does_not_flash_connecting(tray):
    # Already connected: the move starts in tens of milliseconds. A label that
    # appears and vanishes within a frame is noise, not feedback.
    icon, client = tray
    icon._on_connected(True)
    icon._on_moving(False)

    icon._run_action("toggle")

    assert label(icon) != "Connecting…"
    assert client.gestures == ["toggle"]


def test_repeat_click_while_moving_does_not_show_connecting(tray):
    # A second press during a move is the cancel gesture (stop/reverse), not a
    # new connection.
    icon, _ = tray
    icon._on_connected(True)
    icon._on_moving(True)

    icon._run_action("toggle")

    assert label(icon) != "Connecting…"


def test_move_failed_clears_connecting(tray):
    # The desk never moves in this case, so nothing else would take the label
    # down before the backstop timer.
    icon, _ = tray
    icon._on_connected(False)
    icon._on_moving(False)
    icon._run_action("toggle")

    icon._on_status("move-failed")

    assert label(icon) != "Connecting…"


def test_daemon_going_away_clears_connecting(tray):
    icon, _ = tray
    icon._on_connected(False)
    icon._on_moving(False)
    icon._run_action("toggle")

    icon._on_available(False)

    assert not icon._connecting
    assert label(icon) == "Daemon not running"
