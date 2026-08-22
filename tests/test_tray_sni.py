"""The tooltip's title/detail split, and the fallback that must survive it.

Plasma renders the SNI ``ToolTip`` struct's ``title`` as a bold heading and its
``description`` as lighter secondary text, but ``QSystemTrayIcon.setToolTip``
fills ``title`` with everything and leaves ``description`` empty. We take the
StatusNotifierItem object over to fill both — see ``gui/sni.py`` for how, and
why it costs so much less than it looks.

Two things are worth testing without a bus, and they are the two here:

* the **split** — which words become the title and which the detail. That is
  ordinary string logic and does not need D-Bus at all, so it is driven through
  a recorder standing in for the SNI object.
* the **fallback** — that a failed takeover changes nothing. This suite runs
  offscreen with no Qt tray connection to find, which *is* the failure path, so
  every test here doubles as evidence that the plain ``QSystemTrayIcon`` route
  still works when the takeover cannot happen.

What can't be tested here is the rendering itself, or the D-Bus marshalling:
both need a live session bus and a real tray host. Those were verified by hand
against Plasma (``docs/MANUAL-TESTING.md``).

Skipped where PySide6 is missing, for the same reason as
``tests/test_tray_tooltip.py``.
"""

import pytest

pytest.importorskip("PySide6")

import os
from datetime import date

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from types import SimpleNamespace  # noqa: E402

import shiboken6  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.presentation.english import EnglishTranslator  # noqa: E402
from idasen_companion.core.presentation.formatter import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.plain_locale import (  # noqa: E402
    PlainLocaleFormatter,
)
from idasen_companion.core.units import HeightUnit  # noqa: E402
from idasen_companion.gui.sni import (RichTooltip, StatusNotifierItem,  # noqa: E402
                                      find_tray_connection)
from idasen_companion.gui.tray import TrayIcon  # noqa: E402


class FakeClient(QObject):
    statusChanged = Signal(str)
    positionChanged = Signal(str)
    progressChanged = Signal(float, float)
    presetsChanged = Signal(dict)
    availableChanged = Signal(bool)
    connectedChanged = Signal(bool)
    movingChanged = Signal(bool)
    snoozeUntilChanged = Signal(float)

    def __init__(self, available=False, daily_rows=()):
        super().__init__()
        self.available = available
        self.daily_rows = list(daily_rows)

    def get_daily_stats(self, start, end):
        return self.daily_rows

    def __getattr__(self, name):
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
                locale=PlainLocaleFormatter(), translator=EnglishTranslator(),
                unit=HeightUnit.CENTIMETRES)))


class Recorder:
    """Stands in for the SNI object, capturing what would go on the wire."""

    def __init__(self):
        self.calls = []

    def update(self, title, description):
        self.calls.append((title, description))

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_tray(client):
    icon = TrayIcon(client, FakeWindow(), QIcon())
    yield icon, client
    # Same teardown as tests/test_tray_tooltip.py — a QSystemTrayIcon collected
    # after the offscreen platform is gone segfaults at exit.
    icon.hide()
    icon.setContextMenu(None)
    shiboken6.delete(icon)


@pytest.fixture
def tray(qapp):
    yield from _make_tray(FakeClient())


@pytest.fixture
def tray_with_stats(qapp):
    today = date.today().isoformat()
    yield from _make_tray(FakeClient(
        available=True,
        daily_rows=[(today, "sitting", 7080.0), (today, "standing", 3000.0)]))


def standing_and_active(icon):
    """Standing 43m into a 54m cycle, so 11m remain."""
    icon._on_position("standing")
    icon._on_status("active")
    icon._on_progress(2580.0, 3240.0)


# ----- the split -----

def test_app_name_is_the_title_and_everything_else_the_detail(tray):
    icon, _ = tray
    icon._rich = Recorder()

    standing_and_active(icon)

    title, description = icon._rich.last
    assert title == "Idasen Companion"
    assert description == "Standing for 43m\nSitting down in 11m"


def test_today_summary_joins_the_detail_not_the_title(tray_with_stats):
    # The summary is a third detail line, not a second heading — otherwise the
    # bold text would swallow the whole tooltip again, which is the bug.
    icon, _ = tray_with_stats
    icon._rich = Recorder()

    standing_and_active(icon)

    title, description = icon._rich.last
    assert title == "Idasen Companion"
    assert description == ("Standing for 43m\n"
                           "Sitting down in 11m\n"
                           "Today: 1h 58m sitting / 50m standing")


def test_title_is_constant_across_states(tray):
    # The title is an identity, not a status: it must not change as the desk
    # does, or the bold line flickers between words on every tick.
    icon, _ = tray
    icon._rich = Recorder()

    standing_and_active(icon)
    icon._on_status("paused")
    icon._on_position("sitting")

    assert {title for title, _ in icon._rich.calls} == {"Idasen Companion"}


def test_detail_survives_having_only_one_line(tray):
    # "Connecting…" is one clause with nothing else known yet. It is still
    # detail, not a title — the title never varies.
    icon, _ = tray
    icon._rich = Recorder()
    icon._on_connected(False)
    icon._on_moving(False)

    icon._run_action("toggle")

    assert icon._rich.last == ("Idasen Companion", "Connecting…")


def test_title_carries_no_newline(tray_with_stats):
    # A newline in the title would be rendered inside the bold heading, which
    # is precisely the uniform block this change exists to break up.
    icon, _ = tray_with_stats
    icon._rich = Recorder()

    standing_and_active(icon)

    assert "\n" not in icon._rich.last[0]


def test_plain_tooltip_is_still_set_alongside(tray_with_stats):
    # The fallback string stays correct even while the split is being published,
    # so a host that reads the Qt-shaped tooltip loses nothing.
    icon, _ = tray_with_stats
    icon._rich = Recorder()

    standing_and_active(icon)

    assert icon.toolTip().split("\n") == [
        "Idasen Companion",
        "Standing for 43m",
        "Sitting down in 11m",
        "Today: 1h 58m sitting / 50m standing"]


# ----- the fallback -----

def test_no_tray_connection_offscreen():
    # Nothing to take over without a real tray host; the lookup must say so
    # rather than raise or invent a connection.
    assert find_tray_connection() is None


def test_install_declines_without_a_connection(tray):
    icon, _ = tray

    assert RichTooltip.install(icon) is None


def test_tray_works_with_no_takeover(tray):
    # The whole fallback contract in one assertion: the takeover never happened
    # here, and the tooltip and menu entry are still exactly right.
    icon, _ = tray
    standing_and_active(icon)

    assert icon._rich is None
    assert icon.toolTip().startswith("Idasen Companion\nStanding for 43m")
    # The menu keeps its own shorter phrasing — see test_tray_tooltip.py.
    assert icon._status_action.text() == "Standing · 11m left"


def test_set_tooltip_reports_only_real_changes(qapp, tray):
    # Guards the NewToolTip signal from being emitted on every tick: the tray
    # refreshes its texts on each status/position/progress push, and most of
    # those leave the tooltip identical.
    icon, _ = tray
    item = StatusNotifierItem(icon, 0)

    assert item.set_tooltip("Title", "detail") is True
    assert item.set_tooltip("Title", "detail") is False
    assert item.set_tooltip("Title", "other") is True
