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
from types import SimpleNamespace

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402

from idasen_companion.core.config import AppConfig  # noqa: E402
from idasen_companion.core.clocks import MonotonicInstant  # noqa: E402
from idasen_companion.core.durations import Duration  # noqa: E402
from idasen_companion.gui.pages import overview as overview_mod  # noqa: E402
from idasen_companion.gui.pages.overview import OverviewPage  # noqa: E402
from idasen_companion.gui.theme import theme  # noqa: E402


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

    # Button targets connected at build time.
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
def page(make_app_context):
    page = OverviewPage(make_app_context(
        FakeClient(), AppConfig(), load_config=False, tray_available=True))
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


def test_progress_receipt_ages_as_a_duration_before_widgets(page, monkeypatch):
    clock = 10.0
    monkeypatch.setattr(overview_mod, "time", SimpleNamespace(monotonic=lambda: clock))
    page.client.progressChanged.emit(1500.0, 1800.0)
    assert page._remaining == Duration(300.0)
    assert page._progress_stamp == MonotonicInstant(10.0)

    shown = []
    clock += 0.25
    render = page._update_countdown_text
    monkeypatch.setattr(page, "_update_countdown_text",
                        lambda remaining=None: (shown.append(remaining), render(remaining)))
    page._tick_countdown()

    assert shown == [Duration(299.75)]
    assert page.countdown_time_word.text() == "4:59"
    assert page.countdown_bar.value() == 1500


def test_position_signal_preserves_labels_and_direction(page):
    for raw, expected_label, expected_next in (
            ("sitting", "Sitting", "Next: Stand"),
            ("standing", "Standing", "Next: Sit"),
            ("", "Custom", "Next change"),
            ("custom", "Custom", "Next change"),
            (" Future-POSITION \t", " future-position \t", "Next change"),
            ("SITTING", "Sitting", "Next change")):
        page.client.positionChanged.emit(raw)
        assert page.position_label.text() == expected_label
        page.client.progressChanged.emit(1500.0, 1800.0)
        assert _header(page) == expected_next + " in 5:00 of active time"


def test_queued_failure_status_updates_overview(page, qapp):
    # Keep one application-level queued delivery check, rather than repeating
    # the full input matrix for Qt's delivery modes at every consumer.
    page.client.statusChanged.disconnect(page._on_status)
    page.client.statusChanged.connect(
        page._on_status, Qt.ConnectionType.QueuedConnection)
    page.client.statusChanged.emit("move-failed")
    qapp.processEvents()

    assert page.status_head_lbl.text() == "Last move failed"
    assert page.status_reason.text() == "couldn't reach the desk"
    assert not page._countdown_widget.isHidden()
    page.client.progressChanged.emit(2400.0, 1800.0)
    assert _header(page) == "Next: Stand Due now"
    assert page.countdown_bar.value() == page.countdown_bar.maximum()


@pytest.mark.parametrize("raw", ["", " Future-Status \t"])
def test_unfamiliar_status_keeps_text_and_pause_controls(
        page, monkeypatch, raw):
    calls = []
    monkeypatch.setattr(page.client, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(page.client, "resume", lambda: calls.append("resume"))
    page.client.statusChanged.emit(raw)

    assert page.status_head_lbl.text() == raw
    assert page.status_reason.text() == ""
    assert page.status_dot._color == theme().muted
    assert page._countdown_widget.isHidden()
    assert not page._cycle_controls.isHidden()
    assert page.enable_btn.isHidden()
    assert page.pause_btn.text() == "Pause"
    page.pause_btn.click()
    assert calls == ["pause"]


def test_known_status_actions_and_moving_override(page, monkeypatch):
    calls = []
    monkeypatch.setattr(page.client, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(page.client, "resume", lambda: calls.append("resume"))
    for raw in ("paused", "snoozed", "active", "move-failed"):
        page.client.statusChanged.emit(raw)
        page.pause_btn.click()
    assert calls == ["resume", "resume", "pause", "pause"]
    assert page.status_dot._color == theme().error

    page.client.statusChanged.emit("disabled")
    assert page._cycle_controls.isHidden()
    assert not page.enable_btn.isHidden()
    page.client.movingChanged.emit(True)
    assert page.position_label.text() == "Moving…"
    assert page.stop_btn.isEnabled()
    page.client.movingChanged.emit(False)
    assert page.position_label.text() == "Sitting"
    assert not page.stop_btn.isEnabled()
