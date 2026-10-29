# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict feedback follows the daemon and never strands a physical escape."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dbus_fast.aio import MessageBus
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QPushButton

from idasen_companion import DBUS_NAME, DBUS_PATH
from idasen_companion.core.config import load_config, save_config
from idasen_companion.daemon.service import Automation1, Desk1
from idasen_companion.core.strict_state import StrictState
from idasen_companion.gui.dbus_client import DaemonClient
from idasen_companion.gui import restyle
from idasen_companion.gui.pages.automation import AutomationPage
from idasen_companion.gui.pages.overview import OverviewPage
from language_context import installed_language
from machine_helpers import Driver, SIT_H, STAND_H, make_config
from test_position_observation_dbus import settle
from test_strict_retry import daemon_for_driver
from test_tray_tooltip import FakeClient, _make_tray


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
        assert "standing interval enforced" in page.strict_status.text()
        assert "standing interval enforced" in tray.toolTip()
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
        assert "ordinary controls are available" in page.strict_status.text()
        assert "no interval enforced" in tray._strict_action.text()
        await bus.release_name(DBUS_NAME)
        await settle(qapp, lambda: client.strict_capability == "unknown")
        assert "currently unavailable" in page.strict_status.text()
        assert "status unavailable" in tray._strict_action.text()
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
    tray_fixture = _make_tray(client, SimpleNamespace(ctx=ctx))
    tray, _ = next(tray_fixture)
    try:
        page._on_status("active")
        assert "retry promptly" in page.strict_status.text()
        assert not tray._strict_action.isEnabled()
        assert "moving to standing" in tray._strict_action.text()
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
        assert page.strict_status.text().endswith("retry promptly.")
        client.strict_capability = "unsupported"
        client.strictStateChanged.emit()
        assert "background service version" in page.strict_status.text()
        assert "unsupported" in tray._strict_action.text()
        client.strict_capability = "unknown"
        client.strict_state = None
        client.strictStateChanged.emit()
        assert "currently unavailable" in page.strict_status.text()
        assert "status unavailable" in tray._strict_action.text()
        page._on_moving(False)
        assert not page.stop_btn.isEnabled()
    finally:
        next(tray_fixture, None)
        page.deleteLater()


def test_spanish_pending_text_and_enlarged_native_layout(qapp, make_app_context):
    client = UIClient()
    with installed_language("es"):
        config = make_config()
        config.ui.language = "es"
        ctx = make_app_context(client, config, load_config=True, tray_available=True)
        overview = OverviewPage(ctx)
        page = AutomationPage(ctx)
        page.load()
        font = QFont(page.font())
        font.setPointSizeF(font.pointSizeF() * 1.5)
        page.setFont(font)
        overview.setFont(font)
        page.resize(760, 600)
        overview.resize(760, 600)
        page.show()
        overview.show()
        page._scroll.ensureWidgetVisible(page.strict_mode)
        qapp.processEvents()
        assert overview.strict_status.wordWrap()
        assert "volverá a intentarlo pronto" in overview.strict_status.text()
        assert overview.strict_status.accessibleName() == overview.strict_status.text()
        assert overview.strict_status.height() >= overview.strict_status.fontMetrics().height()
        assert page.strict_mode.accessibleName() == "Modo estricto"
        assert page.strict_mode.accessibleDescription()
        assert page.strict_mode.isVisible() and page._apply_btn.isVisible()
        assert page.strict_mode.focusPolicy() and page.strict_mode.width() >= page.strict_mode.sizeHint().width()
        page.activateWindow()
        page.strict_mode.setFocus(Qt.FocusReason.TabFocusReason)
        qapp.processEvents()
        assert page.strict_mode.hasFocus()
        original_palette = QPalette(qapp.palette())
        try:
            dark = QPalette(original_palette)
            dark.setColor(QPalette.ColorRole.Window, QColor("#202326"))
            dark.setColor(QPalette.ColorRole.WindowText, QColor("#fcfcfc"))
            qapp.setPalette(dark)
            restyle.sweep()
            qapp.processEvents()
            assert overview.strict_status.accessibleName() == overview.strict_status.text()
            assert page._apply_btn.isVisible()
        finally:
            qapp.setPalette(original_palette)
            restyle.sweep()
        page.close()
        overview.close()


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
        assert "ordinary controls are available" in page.strict_status.text()
        assert (not daemon.config.automation.enabled if disable == "automation"
                else daemon.config.automation.strict_mode == "off")
    finally:
        page.deleteLater()
        settings.deleteLater()
        client.deleteLater()
        bus.disconnect()
        await asyncio.sleep(0)
