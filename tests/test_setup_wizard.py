# SPDX-License-Identifier: GPL-3.0-or-later
"""Setup discovery and verified completion, without desktop or desk effects."""

from unittest.mock import Mock

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QDialog, QMessageBox  # noqa: E402

from idasen_companion.core.config import AppConfig  # noqa: E402
from idasen_companion.gui import service_ctl  # noqa: E402
from idasen_companion.gui.service_ctl import AutostartState  # noqa: E402
from idasen_companion.gui.setup_wizard import SetupWizard  # noqa: E402


DESK = ("My desk", "AA:BB:CC:DD:EE:01")
OTHER_DESK = ("Other desk", "AA:BB:CC:DD:EE:02")


class FakeClient:
    """Only the wizard's three calls; unscripted operations fail immediately."""

    available = True

    def __init__(self):
        self.discoveries = []
        self.setup_result = None
        self.allow_automation_write = False
        self.calls = []

    def discover(self, seconds):
        self.calls.append(("discover", seconds))
        assert self.discoveries, "unexpected discovery"
        return self.discoveries.pop(0)

    def setup(self, mac):
        self.calls.append(("setup", mac))
        assert self.setup_result is not None, "unexpected setup"
        return self.setup_result

    def set_automation_enabled(self, enabled):
        self.calls.append(("automation", enabled))
        assert self.allow_automation_write, "unexpected automation write"


@pytest.fixture
def wizard_client(qapp, make_app_context, tmp_path, monkeypatch):
    # Install guards before constructing widgets, showing them, or processing
    # events. Expected operations are replaced explicitly in the relevant test.
    for name in ("start", "autostart_state", "set_autostart"):
        monkeypatch.setattr(service_ctl, name, Mock(
            side_effect=AssertionError(f"unexpected service_ctl.{name}")))
    for name in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, name, Mock(
            side_effect=AssertionError(f"unexpected QMessageBox.{name}")))
    client = FakeClient()
    config = AppConfig()
    config.automation.enabled = False
    path = tmp_path / "wizard.toml"
    ctx = make_app_context(client, config, load_config=True,
                           tray_available=True, path=path)
    wizard = SetupWizard(client, ctx=ctx)
    yield wizard, client, path
    wizard.close()


def test_cached_single_desk_is_selected_without_active_scan(wizard_client):
    wizard, client, _path = wizard_client
    client.discoveries = [[DESK]]

    wizard.scan_page.initializePage()

    page = wizard.scan_page
    assert client.calls == [("discover", 0)]
    assert page.isComplete()
    assert page.selected_mac() == DESK[1]
    assert [item.data(Qt.ItemDataRole.UserRole)
            for item in page.device_list.selectedItems()] == [DESK[1]]
    assert "without scanning" in page.hint.text()


def test_empty_cache_scans_and_successful_retry_clears_hint(wizard_client):
    wizard, client, _path = wizard_client
    client.discoveries = [[], [], [DESK]]
    page = wizard.scan_page

    page.initializePage()

    assert client.calls == [("discover", 0), ("discover", 8)]
    assert not page.isComplete()
    assert page.selected_mac() == ""
    assert page.device_list.count() == 0
    assert "Nothing found" in page.hint.text()
    assert page.scan_btn.isEnabled()

    page.scan_btn.click()

    assert client.calls == [("discover", 0), ("discover", 8), ("discover", 8)]
    assert page.isComplete()
    assert page.selected_mac() == DESK[1]
    assert page.device_list.selectedItems()[0].data(Qt.ItemDataRole.UserRole) == DESK[1]
    assert page.hint.text() == ""
    assert page.scan_btn.isEnabled()


def test_multiple_desks_require_selection_and_preserve_it_on_refresh(wizard_client):
    wizard, client, _path = wizard_client
    client.discoveries = [[DESK, OTHER_DESK], [OTHER_DESK, DESK]]
    page = wizard.scan_page

    page.initializePage()

    assert page.device_list.count() == 2
    assert not page.device_list.selectedItems()
    assert not page.isComplete()
    assert page.selected_mac() == ""

    page.device_list.setCurrentRow(1)

    assert page.isComplete()
    assert page.selected_mac() == OTHER_DESK[1]
    assert page.device_list.selectedItems() == [page.device_list.item(1)]

    page.scan_btn.click()

    assert client.calls == [("discover", 0), ("discover", 8)]
    assert page.isComplete()
    assert page.selected_mac() == OTHER_DESK[1]
    assert page.device_list.selectedItems() == [page.device_list.item(0)]


@pytest.mark.parametrize("manual", [True, False], ids=["manual", "automatic"])
def test_verified_finish_applies_usage_without_overwriting_config(
        wizard_client, monkeypatch, manual):
    wizard, client, path = wizard_client
    client.discoveries = [[DESK]]
    client.setup_result = (True, 0.75)
    client.allow_automation_write = manual
    information = Mock()
    monkeypatch.setattr(QMessageBox, "information", information)
    state = Mock(return_value=AutostartState("enabled", True, ""))
    monkeypatch.setattr(service_ctl, "autostart_state", state)
    original_config = path.read_bytes()
    wizard.show()
    wizard.next()
    wizard.next()
    wizard.usage_page.manual.setChecked(manual)

    wizard.accept()

    expected = [("discover", 0), ("setup", DESK[1])]
    if manual:
        expected.append(("automation", False))
    assert client.calls == expected
    assert wizard.result() == QDialog.DialogCode.Accepted
    assert wizard.isEnabled()
    information.assert_called_once()
    QMessageBox.warning.assert_not_called()
    state.assert_called_once_with()
    service_ctl.set_autostart.assert_not_called()
    assert wizard.ctx.cfg.automation.enabled is False
    assert path.read_bytes() == original_config


def test_failed_verification_keeps_selection_for_retry_without_side_effects(
        wizard_client, monkeypatch):
    wizard, client, path = wizard_client
    client.discoveries = [[DESK]]
    client.setup_result = (False, "desk unavailable")
    warning = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warning)
    original_config = path.read_bytes()
    wizard.show()
    wizard.next()
    wizard.next()
    wizard.usage_page.manual.setChecked(True)

    wizard.accept()

    assert client.calls == [("discover", 0), ("setup", DESK[1])]
    assert wizard.result() == QDialog.DialogCode.Rejected
    assert wizard.isVisible()
    assert wizard.isEnabled()
    assert wizard.scan_page.isComplete()
    assert wizard.scan_page.selected_mac() == DESK[1]
    warning.assert_called_once()
    QMessageBox.information.assert_not_called()
    service_ctl.autostart_state.assert_not_called()
    service_ctl.set_autostart.assert_not_called()
    assert wizard.ctx.cfg.automation.enabled is False
    assert path.read_bytes() == original_config


@pytest.mark.parametrize(
    "state,enable_result,starts_at_login",
    [
        (AutostartState("enabled", True, ""), None, True),
        (AutostartState("disabled", False, ""), (True, ""), True),
        (AutostartState("masked", False, "masked"), None, False),
        (AutostartState("disabled", False, ""), (False, "denied"), False),
    ],
    ids=["already-on", "enable-success", "unmanageable", "enable-failure"],
)
def test_autostart_outcome_reports_login_behavior(
        wizard_client, monkeypatch, state, enable_result, starts_at_login):
    wizard, _client, _path = wizard_client
    read_state = Mock(return_value=state)
    monkeypatch.setattr(service_ctl, "autostart_state", read_state)
    if enable_result is not None:
        monkeypatch.setattr(service_ctl, "set_autostart", Mock(return_value=enable_result))

    note = wizard._enable_autostart()

    read_state.assert_called_once_with()
    if enable_result is None:
        service_ctl.set_autostart.assert_not_called()
    else:
        service_ctl.set_autostart.assert_called_once_with(True)
    if starts_at_login:
        assert "will start automatically" in note
    else:
        assert "will not start automatically" in note
        assert "Settings" in note
