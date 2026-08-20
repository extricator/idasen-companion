"""Each surface Phase 11 converts renders the whole message a translator
owns, rather than fragments the code glued together.

Phase 11's conversions each replace an ``f"{translated} · {number}"`` or
``f"{a}: {b}"`` shape with a call through one marked helper in
``gui/util.py``. That is a claim about what the *code* does, already
covered by ``tests/test_translation_markers.py``'s AST checks. This module
covers the other half: what a *widget* actually paints once the call is in
place — the vertical rail's protected presets in the user's language rather
than a raw config key, and the daily chart's tooltip translated at all.

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
from PySide6.QtGui import QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui import service_ctl  # noqa: E402
from idasen_companion.gui.pages.about import AboutPage  # noqa: E402
from idasen_companion.gui.pages.overview import OverviewPage  # noqa: E402
from idasen_companion.gui.pages.statistics import StatisticsPage  # noqa: E402
from idasen_companion.gui.service_ctl import AutostartState  # noqa: E402
from idasen_companion.gui.setup_wizard import SetupWizard  # noqa: E402
from idasen_companion.gui.util import (  # noqa: E402
    fmt_height, fmt_hm, fmt_preset_tick, position_label, preset_label,
)
from idasen_companion.gui.widgets import DailyBarsChart, RangeRail  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeOverviewClient(QObject):
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


@pytest.fixture
def overview_page(qapp, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    return OverviewPage(AppContext(_FakeOverviewClient(), tray_available=True))


class _FakeStatisticsClient(QObject):
    """The signals StatisticsPage subscribes to, plus the two reads it makes."""

    transitionCompleted = Signal(str, str, bool)
    availableChanged = Signal(bool)

    available = True

    def __init__(self, daily_stats):
        super().__init__()
        self._daily_stats = daily_stats

    def get_daily_stats(self, start: str, end: str) -> list:
        return self._daily_stats

    def get_transitions(self, limit: int = 50) -> list:
        return []


class _FakeAboutClient(QObject):
    """The one call AboutPage._refresh makes when a daemon is available.

    ``available`` stays False so the desk-line assertion doesn't depend on
    the "Daemon" field, whose own message isn't this test's subject.
    """

    available = False

    def idle_provider(self): return "none"


def _about_page(qapp, tmp_path, monkeypatch, mac: str, connection: str):
    path = tmp_path / "config.toml"
    config = AppConfig()
    config.desk.mac = mac
    config.desk.connection = connection
    save_config(config, path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    ctx = AppContext(_FakeAboutClient(), tray_available=True)
    ctx.reload_config()
    return AboutPage(ctx)


def _statistics_page(qapp, tmp_path, monkeypatch, daily_stats):
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    return StatisticsPage(
        AppContext(_FakeStatisticsClient(daily_stats), tray_available=True))


def _drawn_texts(widget) -> list[str]:
    """Every string a widget's ``paintEvent`` hands to ``QPainter.drawText``.

    ``grab()`` forces a real paint through the offscreen platform's
    compositor, unlike calling ``paintEvent()`` directly, which runs against
    a ``QPainter`` with no active engine and prints "painter not active" for
    every call. The patch is applied and restored around a single ``grab()``
    rather than left in place, so it cannot leak into another test's paint.
    """
    texts: list[str] = []
    original = QPainter.drawText

    def _capture(self, *args):
        if args and isinstance(args[-1], str):
            texts.append(args[-1])
        return original(self, *args)

    QPainter.drawText = _capture
    try:
        widget.grab()
    finally:
        QPainter.drawText = original
    return texts


def test_range_rail_labels_its_presets_in_the_user_language(qapp):
    rail = RangeRail(0.6, 1.2)
    rail.resize(120, 300)
    rail.set_presets({"sit": 0.7, "stand": 1.1, "perch": 0.95})
    rail.set_height(0.7)  # exactly at "sit", so that tick shows the live height

    texts = _drawn_texts(rail)

    # The live preset ("sit") renders through the shared tick message, with
    # its name already translated -- not the raw dict key.
    assert fmt_preset_tick(preset_label("sit"), 0.7) in texts
    # The resting protected preset ("stand") is a bare translated label.
    assert preset_label("stand") in texts
    # A user-named preset is unaffected -- preset_label returns it verbatim.
    assert "perch" in texts


def test_daily_chart_tooltip_is_translated(qapp):
    chart = DailyBarsChart()
    chart.set_rows([
        ("Mon 17", 3600, 1800, False),  # has data
        ("Tue 18", 0, 0, False),        # no data
    ])

    with_data = chart._tooltip_for(0)  # pylint: disable=protected-access
    no_data = chart._tooltip_for(1)  # pylint: disable=protected-access

    assert with_data == (
        "Mon 17: sitting %s, standing %s" % (fmt_hm(3600), fmt_hm(1800)))
    assert no_data == "Tue 18: no data"


def test_statistics_footer_with_tracked_time_is_one_message(qapp, tmp_path, monkeypatch):
    from datetime import date

    today = date.today().isoformat()
    page = _statistics_page(
        qapp, tmp_path, monkeypatch,
        [[today, "sitting", 1800.0], [today, "standing", 1800.0]])
    page.on_shown()
    text = page.stats_footer.text()
    assert "14-day average: 50%." in text
    assert text.startswith(
        "Standing share = standing time / tracked time per day.")


def test_statistics_footer_without_tracked_time_has_no_average(
        qapp, tmp_path, monkeypatch):
    page = _statistics_page(qapp, tmp_path, monkeypatch, [])
    page.on_shown()
    assert page.stats_footer.text() == (
        "Standing share = standing time / tracked time per day.")


def test_transition_row_renders_position_words_as_one_message(
        qapp, tmp_path, monkeypatch):
    page = _statistics_page(qapp, tmp_path, monkeypatch, [])
    row = page._make_transition_row(  # pylint: disable=protected-access
        0.0, "sitting", "standing", "automation", False)
    labels = row.findChildren(QLabel)
    change_label = next(
        lbl for lbl in labels
        if lbl.text() not in ("",) and "→" in lbl.text())
    assert change_label.text() == (
        position_label("sitting") + " → " + position_label("standing"))


def test_about_desk_line_renders_mac_and_mode_as_one_message(
        qapp, tmp_path, monkeypatch):
    page = _about_page(
        qapp, tmp_path, monkeypatch,
        mac="AA:BB:CC:DD:EE:FF", connection="persistent")
    page.on_shown()
    assert page._fields["Desk"].text() == (  # pylint: disable=protected-access
        "AA:BB:CC:DD:EE:FF" + " · " + page.tr("persistent"))


def test_overview_status_reason_renders_from_a_translated_prefix(overview_page):
    overview_page.client.statusChanged.emit("paused")
    assert overview_page.status_reason.text() == (
        "— the desk won't move until you resume")

    overview_page.client.statusChanged.emit("does-not-exist")
    assert overview_page.status_reason.text() == ""


def test_setup_wizard_success_paragraphs_stay_three_whole_messages(
        qapp, monkeypatch):
    # Autostart already on, so _enable_autostart reads state and returns
    # without touching the real systemd user manager.
    monkeypatch.setattr(service_ctl, "autostart_state",
                        lambda: AutostartState("enabled", True, ""))
    wizard = SetupWizard(client=object())
    wizard.usage_page.automatic.setChecked(True)

    paragraphs = wizard._success_paragraphs(0.75)  # pylint: disable=protected-access

    assert len(paragraphs) == 3
    assert fmt_height(0.75) in paragraphs[0]
