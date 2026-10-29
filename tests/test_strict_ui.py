# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict feedback follows the daemon and never strands a physical escape."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dbus_fast.aio import MessageBus
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QLabel, QPushButton, QStyle, QStyleOptionComboBox

from idasen_companion import DBUS_NAME, DBUS_PATH
from idasen_companion.core.config import load_config, save_config
from idasen_companion.daemon.service import Automation1, Desk1
from idasen_companion.core.strict_state import StrictState
from idasen_companion.gui.dbus_client import DaemonClient
from idasen_companion.gui import restyle
from idasen_companion.gui.pages.automation import AutomationPage
from idasen_companion.gui.pages.overview import OverviewPage
from idasen_companion.gui.pages.presets import PresetsPage
from language_context import installed_language
from machine_helpers import Driver, SIT_H, STAND_H, make_config
from test_position_observation_dbus import settle
from test_strict_retry import daemon_for_driver
from test_tray_tooltip import FakeClient, _make_tray
from test_sidebar_width import FakeClient as WindowClient
from test_control_contrast import contrast


@pytest.mark.asyncio
async def test_arrived_click_refuses_then_fresh_departure_releases(qapp, monkeypatch, make_app_context):
    assert "/tmp/dbus-" in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    driver = Driver(make_config(strict_mode="standing", sync_interval=0), height=STAND_H)
    driver.m.start_without_desk_read(driver.now)
    assert driver.m.adopt_startup_height(STAND_H, driver.now, driver.m.startup_token())
    daemon = daemon_for_driver(driver)
    daemon.moving = False
    daemon._record_transition = MagicMock()
    auto, desk = Automation1(daemon), Desk1(daemon)
    daemon._ifaces = {"automation": auto, "desk": desk}
    driver.m._on_strict_changed = daemon._emit_strict_state
    bus = await MessageBus().connect()
    bus.export(DBUS_PATH, auto)
    bus.export(DBUS_PATH, desk)
    await bus.request_name(DBUS_NAME)
    monkeypatch.setattr(DaemonClient, "get_property", lambda *_: None)
    monkeypatch.setattr(DaemonClient, "list_presets", lambda *_: {})
    client = DaemonClient()
    ctx = make_app_context(client, driver.cfg, load_config=True, tray_available=True)
    page = OverviewPage(ctx)
    tray_fixture = _make_tray(client, SimpleNamespace(ctx=ctx))
    tray, _ = next(tray_fixture)
    errors = []
    client.commandFailed.connect(lambda name, message: errors.append((name, message)))
    try:
        await settle(qapp, lambda: client.strict_capability == "supported")
        assert client.strict_state.stage == "arrived"
        assert page.strict_status.text() == "Strict mode: Standing"
        assert "Strict mode: Standing" in tray.toolTip()
        sit = next(button for button in page.findChildren(QPushButton) if button.text() == "Sit")
        assert sit.isEnabled()
        before = (driver.m.strict_snapshot, driver.m.active_time, daemon._current_move_id,
                  driver.cfg.automation.strict_mode, list(driver.desk.move_calls))
        sit.click()
        await settle(qapp, lambda: bool(errors))
        assert errors[0][0].endswith("StrictEnforced")
        assert before == (driver.m.strict_snapshot, driver.m.active_time, daemon._current_move_id,
                          driver.cfg.automation.strict_mode, driver.desk.move_calls)
        driver.desk.height = SIT_H
        assert sit.isEnabled()
        sit.click()
        await settle(qapp, lambda: client.strict_state.stage == "released" and bool(driver.desk.move_calls))
        assert driver.desk.move_calls == [SIT_H]
        assert page.strict_status.text() == "Strict mode: Standing"
        assert tray._strict_action.text() == "Strict mode: Standing"
        await bus.release_name(DBUS_NAME)
        await settle(qapp, lambda: client.strict_capability == "unknown")
        assert page.strict_status.text() == "Strict mode: status unavailable."
        assert tray._strict_action.text() == "Strict mode: status unavailable."
    finally:
        next(tray_fixture, None)
        page.deleteLater()
        client.deleteLater()
        bus.disconnect()
        await asyncio.sleep(0)


class UIClient(FakeClient):
    heightChanged = Signal(float)
    strictStateChanged = Signal()

    def __init__(self):
        super().__init__(available=True)
        self.strict_state = StrictState("standing", "pending", "standing", 1.1)
        self.strict_capability = "supported"
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, args))


def test_status_reset_and_callable_controls(qapp, make_app_context):
    client = UIClient()
    ctx = make_app_context(client, make_config(), load_config=True, tray_available=True)
    page = OverviewPage(ctx)
    presets = PresetsPage(ctx)
    tray_fixture = _make_tray(client, SimpleNamespace(ctx=ctx))
    tray, _ = next(tray_fixture)
    try:
        page._on_status("active")
        assert page.strict_status.text() == "Strict mode: Standing"
        assert not tray._strict_action.isEnabled()
        assert tray._strict_action.text() == "Strict mode: Standing"
        page._on_moving(True)
        assert page.stop_btn.isEnabled()
        page.stop_btn.click()
        for label in ("Sit", "Stand", "Move", "Pause", "Skip next", "Snooze 10 min", "Turn off"):
            button = next(b for b in page.findChildren(QPushButton) if b.text() == label)
            assert button.isEnabled()
            button.click()
        assert {name for name, _ in client.calls} >= {
            "stop", "sit", "stand", "move_to_height", "pause", "skip_next", "snooze",
            "set_automation_enabled"}
        assert ("set_automation_enabled", (False,)) in client.calls
        row = presets._make_preset_row("stand", STAND_H)
        next(b for b in row.findChildren(QPushButton)
             if b.toolTip().startswith("Drive desk to")).click()
        tray._rebuild_presets({"stand": STAND_H.metres})
        tray._presets_menu.actions()[0].trigger()
        tray.run_tray_action("tray_middle_click", "toggle")
        assert client.calls.count(("move_to_preset", ("stand",))) == 2
        assert ("gesture_move", ("toggle",)) in client.calls
        client.strict_state = StrictState("off", "released", None, None)
        client.strictStateChanged.emit()
        assert page.strict_status.isHidden()
        assert not tray._strict_action.isVisible()
        assert "Strict mode" not in tray.toolTip()
        assert not tray.toolTip().endswith("\n")
        client.strict_state = StrictState("both", "released", None, None)
        client.strictStateChanged.emit()
        assert not page.strict_status.isHidden()
        assert page.strict_status.text() == "Strict mode: Both"
        assert tray._strict_action.isVisible()
        assert tray._strict_action.text() == "Strict mode: Both"
        ctx.cfg.automation.strict_mode = "both"
        client.strict_capability = "unsupported"
        client.strictStateChanged.emit()
        assert page.strict_status.text() == "Strict mode: service version unsupported."
        assert "unsupported" in tray._strict_action.text()
        client.strict_capability = "unknown"
        client.strict_state = None
        client.strictStateChanged.emit()
        assert page.strict_status.text() == "Strict mode: status unavailable."
        assert tray._strict_action.text() == "Strict mode: status unavailable."
        page._on_moving(False)
        assert not page.stop_btn.isEnabled()
    finally:
        next(tray_fixture, None)
        page.deleteLater()
        presets.deleteLater()


@pytest.mark.parametrize(("language", "scale"), [("en", 1.0), ("es", 1.5)])
def test_strict_layout_in_minimum_window(qapp, monkeypatch, tmp_path, language, scale):
    from idasen_companion.gui import context as context_mod, main_window, service_ctl

    class StrictWindowClient(WindowClient):
        strictStateChanged = Signal()
        strict_state = StrictState("standing", "pending", "standing", 1.1)
        strict_capability = "supported"

    config = make_config()
    config.ui.language = language
    path = tmp_path / "config.toml"
    save_config(config, path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    monkeypatch.setattr(service_ctl, "autostart_state",
                        lambda: service_ctl.AutostartState("enabled", True, ""))
    original_font, original_palette = QFont(qapp.font()), QPalette(qapp.palette())
    font = QFont(original_font)
    font.setPointSizeF(font.pointSizeF() * scale)
    qapp.setFont(font)

    def bounds_in(widget, ancestor):
        return QRect(widget.mapTo(ancestor, widget.rect().topLeft()), widget.size())

    def text_fits(label):
        rect = label.contentsRect()
        needed = label.fontMetrics().boundingRect(
            QRect(0, 0, rect.width(), 10000),
            Qt.TextFlag.TextWordWrap, label.text())
        assert needed.height() <= rect.height()
        assert needed.width() <= rect.width()

    try:
        palette = QPalette(original_palette)
        colors = ("#202326", "#141618", "#fcfcfc") if language == "es" else (
            "#f0f0f0", "#ffffff", "#000000")
        for role, color in zip((QPalette.ColorRole.Window, QPalette.ColorRole.Base,
                                QPalette.ColorRole.WindowText), colors):
            palette.setColor(role, QColor(color))
        qapp.setPalette(palette)
        with installed_language(language):
            window = main_window.MainWindow(StrictWindowClient(), tray_available=True)
            window.resize(window.minimumSize())
            window.show()
            qapp.processEvents()
            assert window._sidebar.width() > 0
            assert window._stack.width() < window.width()
            status = window.overview.strict_status
            assert status.wordWrap() and status.accessibleName() == status.text()
            text_fits(status)
            assert window.overview.rect().contains(bounds_in(status, window.overview))
            from idasen_companion.gui.theme import theme
            assert contrast(theme().secondary, theme().card_bg) >= 4.5

            window._nav.setCurrentRow(1)
            page = window.automation
            row = page.strict_mode.parentWidget()
            page._scroll.ensureWidgetVisible(row)
            qapp.processEvents()
            labels = row.findChildren(QLabel)
            title = next(label for label in labels if label.text() == page.strict_mode.accessibleName())
            help_label = next(label for label in labels if label.text() == page.strict_mode.accessibleDescription())
            text_fits(title)
            text_fits(help_label)
            viewport = page._scroll.viewport()
            for widget in (title, help_label, page.strict_mode):
                assert viewport.rect().contains(bounds_in(widget, viewport))
            assert not bounds_in(title, row).intersects(bounds_in(page.strict_mode, row))
            assert not bounds_in(help_label, row).intersects(bounds_in(page.strict_mode, row))
            assert page.strict_mode.width() >= page.strict_mode.sizeHint().width()
            option = QStyleOptionComboBox()
            page.strict_mode.initStyleOption(option)
            text_rect = page.strict_mode.style().subControlRect(
                QStyle.ComplexControl.CC_ComboBox, option,
                QStyle.SubControl.SC_ComboBoxEditField, page.strict_mode)
            for index in range(page.strict_mode.count()):
                assert page.strict_mode.fontMetrics().horizontalAdvance(
                    page.strict_mode.itemText(index)) <= text_rect.width()
            for button in (page._apply_btn, page._reset_btn, page._defaults_btn):
                assert page.rect().contains(bounds_in(button, page))
                assert not bounds_in(page._scroll, page).intersects(bounds_in(button, page))
            buttons = (page._apply_btn, page._reset_btn, page._defaults_btn)
            for index, button in enumerate(buttons):
                for other in buttons[index + 1:]:
                    assert not bounds_in(button, page).intersects(bounds_in(other, page))
            window.activateWindow()
            page.strict_mode.setFocus(Qt.FocusReason.TabFocusReason)
            qapp.processEvents()
            assert page.strict_mode.hasFocus()
            window.close()
    finally:
        qapp.setFont(original_font)
        qapp.setPalette(original_palette)
        restyle.sweep()


@pytest.mark.asyncio
@pytest.mark.parametrize("disable", ["strict", "automation"])
async def test_disable_controls_release_only_after_daemon_update(qapp, monkeypatch, make_app_context, disable):
    assert "/tmp/dbus-" in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    driver = Driver(make_config(strict_mode="standing"), height=STAND_H)
    driver.m.start_without_desk_read(driver.now)
    assert driver.m.adopt_startup_height(STAND_H, driver.now, driver.m.startup_token())
    daemon = daemon_for_driver(driver)
    daemon.moving = False
    daemon.mock_mode = True
    daemon._unconfigured = lambda: driver.m.unconfigured
    daemon._report_config_warnings = MagicMock()
    daemon._emit_automation_state = MagicMock()
    auto = Automation1(daemon)
    daemon._ifaces = {"automation": auto}
    driver.m._on_strict_changed = daemon._emit_strict_state
    bus = await MessageBus().connect()
    bus.export(DBUS_PATH, auto)
    await bus.request_name(DBUS_NAME)
    monkeypatch.setattr(DaemonClient, "get_property", lambda *_: None)
    monkeypatch.setattr(DaemonClient, "list_presets", lambda *_: {})
    client = DaemonClient()
    ctx = make_app_context(client, driver.cfg, load_config=True, tray_available=True)
    from idasen_companion.gui import context as context_mod
    path = context_mod.DEFAULT_CONFIG_PATH
    daemon.config_file = SimpleNamespace(load=lambda: load_config(path),
                                         save=lambda cfg: save_config(cfg, path),
                                         note_mtime=lambda: None)
    page = OverviewPage(ctx)
    settings = AutomationPage(ctx)
    settings.load()
    try:
        await settle(qapp, lambda: client.strict_capability == "supported")
        assert client.strict_state.stage == "arrived"
        if disable == "strict":
            settings._select_data(settings.strict_mode, "off")
            assert client.strict_state.stage == "arrived"
            assert settings.apply_edits()
        else:
            page._on_status("active")
            button = next(b for b in page.findChildren(QPushButton) if b.text() == "Turn off")
            assert button.isEnabled()
            button.click()
        assert client.strict_state.stage == "arrived"
        await settle(qapp, lambda: client.strict_state.stage == "released")
        assert driver.m.strict_snapshot is None
        if disable == "strict":
            assert page.strict_status.isHidden()
            assert page.strict_status.text() == ""
        else:
            assert page.strict_status.text() == "Strict mode: Standing"
        assert (not daemon.config.automation.enabled if disable == "automation"
                else daemon.config.automation.strict_mode == "off")
    finally:
        page.deleteLater()
        settings.deleteLater()
        client.deleteLater()
        bus.disconnect()
        await asyncio.sleep(0)
