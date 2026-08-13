"""The Overview countdown when the clock has actually run out.

A cycle can sit at zero remaining for a while: the transition fires on the
next ``tick`` (up to a whole ``check_interval``), and only once the strict
recent-input gate says the user is really there. The sharpest way to land in
that state is to save a shorter interval than the time already accumulated —
``StateMachine.update_config`` keeps ``active_time`` and only recomputes the
target, so a 40-minute sit re-targeted to 30 minutes is due the instant the
daemon reloads.

Rendering that as "in 0:00 of active time" reads as a frozen clock, which is
the complaint these pin down: nothing is stale, the move is simply due.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

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
from idasen_companion.gui.pages.overview import OverviewPage  # noqa: E402


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

    # Button targets — connected at build time, never pressed here.
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


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(qapp, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    page = OverviewPage(AppContext(FakeClient(), tray_available=True))
    page.client.statusChanged.emit("active")
    page.client.positionChanged.emit("sitting")
    return page


def _header(page) -> str:
    """The countdown header as the user reads it, skipping hidden labels.

    ``isHidden`` rather than ``isVisible``: the page is never shown in these
    tests, and a child of an unshown parent is never ``isVisible`` whatever
    its own flag says.
    """
    return " ".join(
        lbl.text() for lbl in (page.countdown_next_lbl,
                               page.countdown_next_word,
                               page.countdown_in_lbl,
                               page.countdown_time_word,
                               page.countdown_of_lbl)
        if lbl.text() and not lbl.isHidden())


def test_a_running_cycle_counts_down(page):
    page.client.progressChanged.emit(1500.0, 1800.0)
    assert _header(page) == "Next: Stand in 5:00 of active time"


def test_a_shortened_interval_says_the_move_is_due(page):
    # 40 minutes accumulated, re-targeted to 30: the state really is zero.
    page.client.progressChanged.emit(2400.0, 1800.0)
    assert _header(page) == "Next: Stand Due now"
    assert page.countdown_time_word.text() == "Due now"


def test_zero_is_never_rendered_as_a_clock(page):
    # The whole last second rounds to 0:00 in fmt_countdown, so it has to read
    # as due too — otherwise the stall is just one second shorter.
    page.client.progressChanged.emit(1799.5, 1800.0)
    assert page.countdown_time_word.text() == "Due now"


def test_the_bar_still_reads_full_when_due(page):
    # "Due now" replaces the clock, not the progress: the interval really is
    # 100% elapsed, and the bar is what says so.
    page.client.progressChanged.emit(2400.0, 1800.0)
    assert page.countdown_bar.value() == page.countdown_bar.maximum()
    assert page.progress_caption.text() == "100% of this interval elapsed"


def test_a_fresh_cycle_puts_the_clock_back(page):
    page.client.progressChanged.emit(2400.0, 1800.0)
    page.client.progressChanged.emit(0.0, 1800.0)
    assert _header(page) == "Next: Stand in 30:00 of active time"
