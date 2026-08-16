"""Coverage for the Settings autostart toggle's Flatpak/systemd branching.

``tests/test_background_portal.py`` already covers every branch of the portal
call itself, mocked at the D-Bus boundary; this file covers what sits on top
of it -- which backend the page calls, and whether a Flatpak grant actually
gets persisted -- by monkeypatching ``background_portal.is_flatpak`` and
``background_portal.set_autostart``, never a filesystem marker and never a
bus.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import sys

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

# Forced, not defaulted -- see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import background_portal  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.pages.settings import SettingsPage  # noqa: E402

MAC = "E1:B2:C3:D4:E5:F6"


class FakeClient:
    """Enough DaemonClient for AppContext: never available, so no D-Bus."""

    available = False


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_ctx(qapp, tmp_path, monkeypatch):
    """Build an AppContext backed by a throwaway config file."""
    def _make(run_at_login: bool = False) -> AppContext:
        path = tmp_path / "config.toml"
        cfg = AppConfig()
        cfg.desk.mac = MAC
        cfg.ui.run_at_login = run_at_login
        save_config(cfg, path)
        monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
        return AppContext(FakeClient(), tray_available=True)
    return _make


@pytest.fixture
def silent_dialogs(monkeypatch):
    """Swallow the modal warning, recording that it fired instead of
    blocking the run on a dialog nobody is there to click."""
    calls = []

    def _warn(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_warn))
    return calls


# ----- outside Flatpak: the systemd path is untouched -----

def test_outside_flatpak_reads_systemd_and_never_touches_the_portal(
        monkeypatch, make_ctx):
    monkeypatch.setattr(background_portal, "is_flatpak", lambda: False)
    calls = []
    monkeypatch.setattr(background_portal, "set_autostart",
                        lambda enable: calls.append(enable))
    page = SettingsPage(make_ctx())
    page.load()
    assert calls == []
    # service_ctl degrades to "unavailable" under the suite's subprocess ban
    # (conftest.no_real_subprocesses), which dims the row -- the dimming is
    # what proves the systemd branch ran, not a Flatpak one that would leave
    # the row enabled regardless of the persisted flag.
    assert not page._autostart_row.isEnabled()


# ----- inside Flatpak: the loader reads the persisted flag, not systemd -----

def test_flatpak_with_the_flag_off_is_unchecked_and_enabled(monkeypatch, make_ctx):
    monkeypatch.setattr(background_portal, "is_flatpak", lambda: True)
    page = SettingsPage(make_ctx(run_at_login=False))
    page.load()
    assert page.autostart_check.isChecked() is False
    assert page._autostart_row.isEnabled(), "manageable, unlike a dimmed systemd row"


def test_flatpak_with_the_flag_on_is_checked(monkeypatch, make_ctx):
    monkeypatch.setattr(background_portal, "is_flatpak", lambda: True)
    page = SettingsPage(make_ctx(run_at_login=True))
    page.load()
    assert page.autostart_check.isChecked() is True


# ----- toggling on: a granted request persists; a denied one must not -----

def test_toggling_on_with_a_granted_response_persists_and_stays_checked(
        monkeypatch, make_ctx):
    monkeypatch.setattr(background_portal, "is_flatpak", lambda: True)
    monkeypatch.setattr(background_portal, "set_autostart",
                        lambda enable: (True, ""))
    ctx = make_ctx(run_at_login=False)
    page = SettingsPage(ctx)
    page.load()
    page.autostart_check.setChecked(True)
    assert ctx.cfg.ui.run_at_login is True
    assert page.autostart_check.isChecked() is True


def test_toggling_on_with_a_denial_does_not_persist_and_unchecks(
        monkeypatch, make_ctx, silent_dialogs):
    monkeypatch.setattr(background_portal, "is_flatpak", lambda: True)
    monkeypatch.setattr(background_portal, "set_autostart",
                        lambda enable: (False, "the request was cancelled"))
    ctx = make_ctx(run_at_login=False)
    page = SettingsPage(ctx)
    page.load()
    page.autostart_check.setChecked(True)
    # The specific failure this plan exists to prevent: a denied dialog must
    # not leave the box ticked or the intent persisted.
    assert ctx.cfg.ui.run_at_login is False
    assert page.autostart_check.isChecked() is False
    assert silent_dialogs, "the user must be told, not left to guess why"


# ----- toggling off persists the flag off, not just the enable direction -----

def test_toggling_off_persists_the_flag_off(monkeypatch, make_ctx):
    monkeypatch.setattr(background_portal, "is_flatpak", lambda: True)
    monkeypatch.setattr(background_portal, "set_autostart",
                        lambda enable: (True, ""))
    ctx = make_ctx(run_at_login=True)
    page = SettingsPage(ctx)
    page.load()
    page.autostart_check.setChecked(False)
    assert ctx.cfg.ui.run_at_login is False


# ----- the one startup reconcile call in gui/main.py -----
#
# Drives the *real* background_portal.reconcile_autostart through gui/main.py's
# one call site, mocking only set_autostart -- unlike
# tests/test_background_portal.py, which calls reconcile_autostart directly
# and never through main()'s startup sequence.

def _run_main(monkeypatch, qapp, *, run_at_login, flatpak):
    """Drive gui.main.main() far enough to see whether it reasserted."""
    import idasen_companion.gui.main as gui_main
    from unittest.mock import MagicMock

    cfg = AppConfig()
    cfg.desk.mac = MAC
    cfg.ui.run_at_login = run_at_login

    client = MagicMock()
    client.available = False

    bus = MagicMock()
    bus.registerService.return_value = True

    monkeypatch.setattr(gui_main, "QApplication", lambda argv: qapp)
    monkeypatch.setattr(gui_main.appearance_portal, "read_appearance_preferences",
                        lambda: None)
    monkeypatch.setattr(gui_main, "load_config", lambda _path: cfg)
    monkeypatch.setattr(gui_main, "install_translators", lambda *a: None)
    monkeypatch.setattr(gui_main.util, "set_height_unit", lambda _u: None)
    monkeypatch.setattr(gui_main.QDBusConnection, "sessionBus",
                        staticmethod(lambda: bus))
    monkeypatch.setattr(gui_main, "DaemonClient", lambda: client)
    monkeypatch.setattr(gui_main.QSystemTrayIcon, "isSystemTrayAvailable",
                        staticmethod(lambda: False))
    monkeypatch.setattr(gui_main, "MainWindow", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(gui_main, "SingleInstance", lambda *a, **kw: MagicMock())
    # Return from app.exec() immediately instead of entering the event loop.
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["idasen-companion"])

    monkeypatch.setattr(background_portal, "is_flatpak", lambda: flatpak)
    calls = []

    def _fake_set_autostart(enable):
        calls.append(enable)
        return True, ""

    monkeypatch.setattr(background_portal, "set_autostart", _fake_set_autostart)
    gui_main.main()
    return calls


def test_startup_reasserts_once_with_the_persisted_flag_on_under_flatpak(
        monkeypatch, qapp):
    assert _run_main(monkeypatch, qapp, run_at_login=True, flatpak=True) == [True]


def test_startup_does_not_reassert_when_the_persisted_flag_is_off(
        monkeypatch, qapp):
    assert _run_main(monkeypatch, qapp, run_at_login=False, flatpak=True) == []


def test_startup_does_not_reassert_outside_flatpak(monkeypatch, qapp):
    assert _run_main(monkeypatch, qapp, run_at_login=True, flatpak=False) == []
