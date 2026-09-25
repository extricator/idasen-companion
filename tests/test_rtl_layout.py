"""Structural right-to-left coverage for the GUI's asymmetric boundaries.

No RTL translation ships yet.  These tests force Qt's direction directly and
protect the geometry that must already be ready before a translator supplies
the first real catalog.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, QRectF, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QStyle  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.core.locale_profile import LocaleProfile  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import service_ctl  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.main_window import MainWindow  # noqa: E402
from idasen_companion.gui.pages.activity_log import ActivityLogPage  # noqa: E402
from idasen_companion.gui.pages.overview import OverviewPage  # noqa: E402
from idasen_companion.gui.pages.presets import PresetsPage  # noqa: E402
from idasen_companion.gui.theme import CONTROL_RADIUS  # noqa: E402
from idasen_companion.gui.widgets import (  # noqa: E402
    DailyBarsChart, HeightRail, RangeRail, segment_css,
)


class FakeClient(QObject):
    """Every signal the tested pages subscribe to, with no live daemon."""

    availableChanged = Signal(bool)
    heightChanged = Signal(float)
    positionChanged = Signal(str)
    connectedChanged = Signal(bool)
    movingChanged = Signal(bool)
    statusChanged = Signal(str)
    progressChanged = Signal(float, float)
    transitionCompleted = Signal(str, str, bool)
    snoozeUntilChanged = Signal(float)
    presetsChanged = Signal(dict)
    logEntry = Signal(float, str, str, str, dict, str)
    commandFailed = Signal(str, str)

    available = False

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restore_direction(qapp):
    original = qapp.layoutDirection()
    yield
    qapp.setLayoutDirection(original)
    qapp.processEvents()


@pytest.fixture
def app_context(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    ctx = AppContext(FakeClient(), tray_available=True)
    ctx.reload_config()
    return ctx


@pytest.mark.parametrize(
    ("direction", "wanted", "rejected"),
    [
        (Qt.LayoutDirection.LeftToRight, "border-right", "border-left"),
        (Qt.LayoutDirection.RightToLeft, "border-left", "border-right"),
    ],
)
def test_sidebar_divider_stays_on_the_content_edge(
        qapp, tmp_path, monkeypatch, direction, wanted, rejected):
    qapp.setLayoutDirection(direction)
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    monkeypatch.setattr(
        service_ctl, "autostart_state",
        lambda: service_ctl.AutostartState("enabled", True, ""))
    window = MainWindow(FakeClient(), tray_available=True)
    try:
        rule = window._sidebar.styleSheet()  # pylint: disable=protected-access
        assert wanted in rule
        assert rejected not in rule
    finally:
        window.close()


def test_move_control_uses_logical_forward_and_trailing_alignment(
        qapp, app_context):
    qapp.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    page = OverviewPage(app_context)
    move = next(button for button in page.findChildren(QPushButton)
                if button.text() == "Move")
    expected = move.style().standardIcon(
        QStyle.StandardPixmap.SP_ArrowForward, None, move)
    assert move.icon().pixmap(16, 16).toImage() == expected.pixmap(16, 16).toImage()
    assert page.progress_caption.alignment() & Qt.AlignmentFlag.AlignTrailing


@pytest.mark.parametrize("direction", [
    Qt.LayoutDirection.LeftToRight,
    Qt.LayoutDirection.RightToLeft,
])
def test_journal_chip_inherits_the_selected_direction(
        qapp, app_context, direction):
    qapp.setLayoutDirection(direction)
    page = ActivityLogPage(app_context)
    assert page._journal_chip.layoutDirection() == direction  # pylint: disable=protected-access


def test_preset_leading_padding_moves_to_the_right_in_rtl(qapp, app_context):
    qapp.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    page = PresetsPage(app_context)
    page.client.presetsChanged.emit({"work": 0.8})
    # The footer segments use symmetric padding; a preset row's height label
    # is the sole deliberately asymmetric inset and must be on logical leading.
    label_rules = [widget.styleSheet() for widget in page.findChildren(QLabel)
        if "padding-right: 4px" in widget.styleSheet()]
    assert label_rules


def test_joined_segments_map_outer_corners_and_shared_edge():
    ltr_first = segment_css(True, False, direction=Qt.LayoutDirection.LeftToRight)
    rtl_first = segment_css(True, False, direction=Qt.LayoutDirection.RightToLeft)
    assert f"border-top-left-radius: {CONTROL_RADIUS}px" in ltr_first
    assert "border-top-right-radius: 0" in ltr_first
    assert "border-top-left-radius: 0" in rtl_first
    assert f"border-top-right-radius: {CONTROL_RADIUS}px" in rtl_first

    ltr_second = segment_css(False, True, direction=Qt.LayoutDirection.LeftToRight)
    rtl_second = segment_css(False, True, direction=Qt.LayoutDirection.RightToLeft)
    assert "border-left: none" in ltr_second
    assert "border-right: none" in rtl_second


def test_height_rail_paint_and_hit_mapping_mirror_together(app_context):
    rail = HeightRail(0.6, 1.2, app_context)
    rail.resize(300, 46)
    rail.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    assert rail._x(0.6) < rail._x(1.2)  # pylint: disable=protected-access
    assert rail._meters(10) == pytest.approx(0.6)  # pylint: disable=protected-access

    rail.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    assert rail._x(0.6) > rail._x(1.2)  # pylint: disable=protected-access
    assert rail._meters(290) == pytest.approx(0.6)  # pylint: disable=protected-access
    assert rail._meters(10) == pytest.approx(1.2)  # pylint: disable=protected-access


def test_vertical_range_rail_moves_to_logical_leading(app_context):
    rail = RangeRail(0.6, 1.2, app_context)
    rail.resize(156, 240)
    rail.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    assert rail._track_x() == 10  # pylint: disable=protected-access
    assert rail._tick_text_x(30) > rail._track_x()  # pylint: disable=protected-access

    rail.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    assert rail._track_x() == 146  # pylint: disable=protected-access
    assert rail._tick_text_x(30) < rail._track_x()  # pylint: disable=protected-access


def test_daily_bar_rectangles_mirror_without_changing_size(app_context):
    chart = DailyBarsChart(app_context)
    chart.resize(400, 100)
    logical = QRectF(64, 4, 120, 12)
    chart.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    assert chart._visual_rect(logical) == logical  # pylint: disable=protected-access

    chart.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    visual = chart._visual_rect(logical)  # pylint: disable=protected-access
    assert visual == QRectF(216, 4, 120, 12)


def test_arabic_layout_keeps_babels_observed_numbering_behavior():
    """Direction and number glyph policy are separate, both pinned explicitly."""
    profile = LocaleProfile("ar_EG")
    # Babel 2.18 supplies Arabic separators but Latin digit glyphs here.  Do
    # not turn structural RTL readiness into an unsupported native-digit claim.
    assert profile.number(1234.5, decimals=1, grouping=True) == "1٬234٫5"
    assert profile.percent(0.375) == "38%"
