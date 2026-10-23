# SPDX-License-Identifier: GPL-3.0-or-later
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
    positionObservationChanged = Signal()
    transitionCompleted = Signal(str, str, bool)
    logEntry = Signal(float, str, str, str, dict, str)
    commandFailed = Signal(str, str)

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
    def position_observation_elapsed(self, position): return None

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


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


def test_observed_time_is_shared_while_active_countdown_freezes(page, monkeypatch):
    from PySide6.QtGui import QIcon
    import shiboken6
    from idasen_companion.gui.tray import TrayIcon

    clock = 10.0
    monkeypatch.setattr(overview_mod, "time", SimpleNamespace(monotonic=lambda: clock))
    monkeypatch.setattr(page.client, "position_observation_elapsed",
                        lambda position: Duration(clock - 10) if position == "sitting" else None)
    for name in ("toggle", "refresh_all", "quit_daemon"):
        monkeypatch.setattr(page.client, name, lambda: None, raising=False)
    monkeypatch.setattr(page.client, "available", True)
    monkeypatch.setattr(page.client, "get_daily_stats", lambda *_: [], raising=False)
    tray = TrayIcon(page.client, SimpleNamespace(ctx=page.ctx), QIcon())
    try:
        page.client.positionChanged.emit("sitting")
        page.client.positionObservationChanged.emit()
        assert page.position_label.accessibleName() == "Sitting for about 0s"
        assert tray.toolTip().splitlines()[1] == "Sitting for about 0s"
        clock += 600
        page.client.progressChanged.emit(600.0, 1800.0)
        page.client.statusChanged.emit("paused")
        clock += 1200
        page._tick_countdown()
        tray._tick()
        assert page.position_label.accessibleName() == tray.toolTip().splitlines()[1] == "Sitting for about 30m"
        assert page._remaining == Duration(1200)
        assert page.countdown_time_word.text() == "20:00"
        assert page.position_label.accessibleDescription() == (
            "Estimated from periodic desk observations; moves between samples may be missed.")
        page.client.movingChanged.emit(True)
        assert page.position_label.accessibleName() == "Moving…"
        assert "for about" not in tray.toolTip()
        page.client.movingChanged.emit(False)
        monkeypatch.setattr(page.client, "position_observation_elapsed", lambda position: None)
        page.client.positionObservationChanged.emit()
        assert page.position_label.accessibleName() == "Sitting"
        assert tray.toolTip().splitlines()[1] == "Sitting"
    finally:
        tray.setContextMenu(None)
        shiboken6.delete(tray)


@pytest.fixture
def observed_window(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QFont, QPalette
    from idasen_companion.core import i18n
    from idasen_companion.core.config import save_config
    from idasen_companion.gui import context, restyle, service_ctl
    from idasen_companion.gui.main_window import MainWindow

    palette, font = QPalette(qapp.palette()), QFont(qapp.font())
    path = tmp_path / "config.toml"
    config = AppConfig()
    config.ui.language = "en"
    save_config(config, path)
    monkeypatch.setattr(context, "DEFAULT_CONFIG_PATH", path)
    monkeypatch.setattr(service_ctl, "autostart_state",
                        lambda: service_ctl.AutostartState("enabled", True, ""))
    windows = []

    def build(language):
        config.ui.language = language
        save_config(config, path)
        i18n.set_language(language)
        window = MainWindow(FakeClient(), tray_available=True)
        windows.append(window)
        window.client.positionChanged.emit("standing")
        window.client.heightChanged.emit(1.1)
        window.client.statusChanged.emit("active")
        window.client.progressChanged.emit(600, 1800)
        window.resize(window.minimumSize())
        window.show()
        qapp.processEvents()
        qapp.processEvents()
        return window

    yield build
    for window in windows:
        window.hide()
        window.deleteLater()
    qapp.setPalette(palette)
    qapp.setFont(font)
    i18n.set_language(i18n.SYSTEM)
    restyle.sweep()
    qapp.processEvents()


def _position_document(page):
    from PySide6.QtGui import QTextDocument
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setDefaultFont(page.position_label.font())
    doc.setHtml(page.position_label.text())
    return doc


def _assert_overview_bounds(window):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QPushButton
    page = window.overview
    bounds = window.rect()
    header = [page.position_label, page.height_label, page.connection_chip]
    rects = [QRect(widget.mapTo(window, widget.rect().topLeft()), widget.size())
             for widget in header]
    for rect in rects:
        assert bounds.contains(rect)
    assert all(not left.intersects(right) for i, left in enumerate(rects)
               for right in rects[i + 1:])
    for control in [page.height_spin, *page.findChildren(QPushButton)]:
        if control.isVisible():
            assert bounds.contains(QRect(control.mapTo(window, control.rect().topLeft()), control.size()))
            assert control.width() >= control.minimumSizeHint().width()
    doc = _position_document(page)
    assert doc.idealWidth() <= page.position_label.contentsRect().width() + 1
    assert doc.firstBlock().layout().lineCount() == 1
    assert page.position_label.focusPolicy() == Qt.FocusPolicy.NoFocus
    return doc


@pytest.mark.parametrize("language", ["en", "es"])
def test_observed_phrase_fits_real_shell_and_elides_secondary_first(
        qapp, observed_window, monkeypatch, language):
    window = observed_window(language)
    page = window.overview
    original_minimum = window.minimumSize()
    elapsed = Duration(1800)
    monkeypatch.setattr(page.client, "position_observation_elapsed", lambda position: elapsed)
    position = page.ctx.fmt.position_or_custom(page._position)
    for seconds in (1800, 3900):
        elapsed = Duration(seconds)
        page.client.positionObservationChanged.emit()
        qapp.processEvents()
        doc = _assert_overview_bounds(window)
        assert doc.toPlainText() == page.ctx.fmt.position_observation(position, elapsed)
        assert window.size() == original_minimum
    # Unusually long values must yield inside the same finite geometry, while
    # the complete phrase and explanation stay available to accessibility.
    elapsed = Duration(1e30)
    page.client.positionObservationChanged.emit()
    qapp.processEvents()
    doc = _assert_overview_bounds(window)
    assert position in doc.toPlainText()
    assert doc.toPlainText() != page.position_label.accessibleName()
    assert page.position_label.accessibleName() == page.ctx.fmt.position_observation(position, elapsed)
    assert page.position_label.accessibleDescription() == page.ctx.fmt.position_observation_description()
    assert window.size() == original_minimum


def test_observed_phrase_tracks_larger_font_and_palette(qapp, observed_window, monkeypatch):
    from PySide6.QtGui import QColor, QFont, QPalette
    from idasen_companion.gui import restyle
    from idasen_companion.gui.theme import css

    window = observed_window("es")
    page = window.overview
    monkeypatch.setattr(page.client, "position_observation_elapsed", lambda position: Duration(3900))
    body = QFont(qapp.font())
    body.setPointSizeF(body.pointSizeF() * 1.4)
    heading = QFont(body)
    heading.setPointSizeF(body.pointSizeF() * 2)
    heading.setWeight(QFont.Weight.DemiBold)
    page.position_label.setFont(heading)
    palette = QPalette(qapp.palette())
    palette.setColor(QPalette.ColorRole.Window, QColor("#202326"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#fcfcfc"))
    qapp.setPalette(palette)
    restyle.sweep()
    page.client.positionObservationChanged.emit()
    qapp.processEvents()
    doc = _assert_overview_bounds(window)
    assert "De pie" in doc.toPlainText()
    assert page.position_label.accessibleName() == "De pie desde hace unos 1 h 05 min"
    assert page.position_label.accessibleDescription() == page.ctx.fmt.position_observation_description()
    assert css(theme().secondary) in page.position_label.text()
    fragment = doc.begin().begin()
    point_sizes = []
    while not fragment.atEnd():
        point_sizes.append(fragment.fragment().charFormat().font().resolve(doc.defaultFont()).pointSizeF())
        fragment += 1
    assert min(point_sizes) == pytest.approx(body.pointSizeF())
    assert max(point_sizes) == pytest.approx(heading.pointSizeF())


def test_observed_phrase_preserves_translated_order_and_escapes_markup(
        qapp, observed_window, monkeypatch):
    from dataclasses import replace
    from idasen_companion.core.presentation import EnglishTranslator, Formatter

    class Reordered(EnglishTranslator):
        def message(self, source, **values):
            if source == "%(position)s for about %(duration)s":
                return "<b>About %(duration)s</b>: %(position)s &" % values
            return super().message(source, **values)

    window = observed_window("en")
    window.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    page = window.overview
    page.ctx.fmt = Formatter(replace(page.ctx.fmt.context, translator=Reordered()))
    monkeypatch.setattr(page.client, "position_observation_elapsed", lambda position: Duration(60))
    page.client.positionObservationChanged.emit()
    qapp.processEvents()
    doc = _assert_overview_bounds(window)
    assert doc.toPlainText() == page.position_label.accessibleName() == "<b>About 1m</b>: Standing &"
    assert page.position_label.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert "&lt;b&gt;" in page.position_label.text()
