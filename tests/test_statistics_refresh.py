"""When the Statistics page re-reads the daemon.

The daily totals are not a transition log. The daemon accrues active time on
every tick of the control loop, so today's sitting/standing seconds grow the
whole time you sit — which means the page can be badly stale without a single
transition having happened. That is exactly the case the old ``_dirty`` guard
missed: it was set only by ``transitionCompleted``, so opening the pane after
forty minutes at the desk re-rendered nothing while the tray tooltip, reading
the same ``get_daily_stats``, stayed current.

So the rule these pin is: re-read on the way in, every time. The cost the
guard was really protecting against — two blocking D-Bus reads and a row
rebuild — is only worth avoiding while the page is *hidden*; a user switching
to the page is already paying for a redraw.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

from datetime import date

import pytest

pytest.importorskip("PySide6")

import os

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.pages.statistics import StatisticsPage  # noqa: E402


class FakeClient(QObject):
    """The signals StatisticsPage subscribes to, plus the two reads it makes."""

    transitionCompleted = Signal(str, str, bool)
    availableChanged = Signal(bool)

    available = True

    def __init__(self):
        super().__init__()
        self.daily_reads = 0
        self.seconds = 0.0

    def get_daily_stats(self, start: str, end: str) -> list:
        self.daily_reads += 1
        # A day's totals that keep growing, so a stale render is visible in
        # the rendered chart and not just in the call count.
        #
        # Dated *today*, not a fixed 2026-08-03: the page renders a rolling
        # 14-day window, so a hardcoded date silently falls out of it — from
        # 2026-08-17 in that case — after which the row is dropped before it
        # reaches the chart and these tests keep passing while asserting
        # nothing about the render.
        return [[date.today().isoformat(), "sitting", self.seconds]]

    def get_transitions(self, limit: int = 50) -> list:
        return []


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(qapp, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    return StatisticsPage(AppContext(FakeClient(), tray_available=True))


def test_opening_the_page_re_reads_the_totals(page):
    # The bug: no transition ever happened, so nothing marked the page stale,
    # and the totals the daemon has been accruing all morning never arrived.
    page.on_shown()
    before = page.client.daily_reads
    page.client.seconds = 2400.0
    page.on_shown()
    assert page.client.daily_reads == before + 1


def test_reopening_it_again_re_reads_again(page):
    # Not a one-shot: every visit is a fresh read, because the numbers keep
    # moving between visits whether or not the desk does.
    page.on_shown()
    page.on_shown()
    page.on_shown()
    assert page.client.daily_reads == 3


def test_a_transition_while_hidden_costs_nothing(page):
    # The half of the old guard worth keeping: a hidden page does no D-Bus
    # work. It is never isVisible() here — the page is never shown.
    page.client.transitionCompleted.emit("sitting", "standing", False)
    assert page.client.daily_reads == 0


def test_a_transition_while_hidden_is_not_lost(page):
    # ...and the update it skipped is picked up on the way in, so dropping
    # the _dirty flag did not drop the transition with it.
    page.client.transitionCompleted.emit("sitting", "standing", False)
    page.client.seconds = 2400.0
    page.on_shown()
    assert page.client.daily_reads == 1


def test_a_dead_daemon_is_not_read(page):
    # _refresh's own guard: on_shown fires on every page switch, including
    # while the daemon is down, and the D-Bus reads would fail.
    page.client.available = False
    page.on_shown()
    assert page.client.daily_reads == 0


def test_the_growing_total_actually_reaches_the_chart(page):
    """The docstring on the fake says the totals grow "so a stale render is
    visible in the rendered chart and not just in the call count" — but every
    test here asserted only on daily_reads, so the `seconds` mutations were
    dead and nothing checked the render at all.
    """
    page.client.seconds = 3600.0
    page.on_shown()

    rows = page.daily_chart._rows
    assert len(rows) == 14, "the chart always draws a full 14-day window"
    _label, sit, stand, is_today = rows[-1]  # oldest first, today last
    assert is_today
    assert sit == 3600.0, f"today's total never reached the chart: {rows[-1]}"
    assert stand == 0.0

    # ...and it tracks a later read rather than sticking at the first value.
    page.client.seconds = 7200.0
    page.on_shown()
    assert page.daily_chart._rows[-1][1] == 7200.0
