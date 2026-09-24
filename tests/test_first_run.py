"""The first-run wizard has to open on an actual first run.

A fresh RPM install ships the systemd unit present but *disabled* (Fedora
policy — gui/service_ctl.py documents it), so at the moment the user first
launches the app the daemon is not running. Gating the wizard on the daemon
being reachable therefore skipped it in precisely the case it exists for, and
left a new user on the red "not running" banner with no route to setup except
finding Settings -> Desk connection unaided.
"""

import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
# Forced, not setdefault: a desktop session exports QT_QPA_PLATFORM=xcb and
# rpmbuild inherits it, then aborts on the display it cannot reach.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.config import AppConfig, ConfigWarning  # noqa: E402


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def run_main(monkeypatch, qapp, *, mac, daemon_available,
             load_config=None):
    """Drive gui.main.main() far enough to see the wizard decision."""
    import idasen_companion.gui.main as gui_main
    import idasen_companion.gui.setup_wizard as wizard_mod
    from unittest.mock import MagicMock

    cfg = AppConfig()
    cfg.desk.mac = mac

    client = MagicMock()
    client.available = daemon_available

    opened = []

    class FakeWizard:
        def __init__(self, *a, **kw):
            opened.append(self)
            self.accepted = MagicMock()

        def open(self):
            pass

    bus = MagicMock()
    bus.registerService.return_value = True

    monkeypatch.setattr(gui_main, "QApplication", lambda argv: qapp)
    monkeypatch.setattr(gui_main.appearance_portal, "read_appearance_preferences",
                        lambda: None)
    monkeypatch.setattr(gui_main, "load_config",
                        load_config or (lambda _p: cfg))
    monkeypatch.setattr(gui_main, "apply_language", lambda *a: None)
    monkeypatch.setattr(gui_main.QDBusConnection, "sessionBus", staticmethod(lambda: bus))
    monkeypatch.setattr(gui_main, "DaemonClient", lambda: client)
    monkeypatch.setattr(gui_main.QSystemTrayIcon, "isSystemTrayAvailable",
                        staticmethod(lambda: False))
    monkeypatch.setattr(gui_main, "MainWindow", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(gui_main, "SingleInstance", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(wizard_mod, "SetupWizard", FakeWizard)
    # Return from app.exec() immediately instead of entering the event loop.
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["idasen-companion"])

    gui_main.main()
    return opened


def test_wizard_opens_on_first_run_even_with_the_daemon_stopped(monkeypatch, qapp):
    opened = run_main(monkeypatch, qapp, mac="", daemon_available=False)
    assert len(opened) == 1, "no wizard on a fresh install — the exact first run"


def test_wizard_opens_on_first_run_with_the_daemon_running(monkeypatch, qapp):
    opened = run_main(monkeypatch, qapp, mac="", daemon_available=True)
    assert len(opened) == 1


@pytest.mark.parametrize("available", [True, False])
def test_no_wizard_once_a_desk_is_configured(monkeypatch, qapp, available):
    opened = run_main(monkeypatch, qapp, mac="AA:BB:CC:DD:EE:FF",
                      daemon_available=available)
    assert opened == []


def test_a_broken_config_still_launches_the_app(monkeypatch, qapp):
    """This read happens before the window exists, so a ConfigError meant the
    desktop launcher did nothing at all — no dialog, no window, a traceback on
    a stderr nobody is reading. Recognized malformed values still take this
    path; unknown newer keys now load with a visible warning."""
    import idasen_companion.gui.main as gui_main
    from idasen_companion.core.config import ConfigError

    def boom(_path):
        raise ConfigError("[ui] clock_format must be one of system, 12, 24")

    opened = run_main(monkeypatch, qapp, mac="AA:BB:CC:DD:EE:FF",
                      daemon_available=True, load_config=boom)
    # It launched — the assertion that matters is that main() returned at all
    # rather than raising. And it did *not* offer the wizard: falling back to
    # defaults leaves no MAC, which would otherwise look like a first run and
    # offer to overwrite the malformed config.
    assert opened == []


def test_unknown_config_data_is_visible_at_gui_startup(monkeypatch, qapp):
    import idasen_companion.gui.main as gui_main

    cfg = AppConfig()
    cfg.desk.mac = "AA:BB:CC:DD:EE:FF"
    cfg.warnings = (
        ConfigWarning(Path("/tmp/future.toml"), None, "future_root"),
        ConfigWarning(Path("/tmp/future.toml"), "ui", "future_theme"),
    )
    shown = []
    monkeypatch.setattr(
        gui_main.QMessageBox, "warning",
        staticmethod(lambda *args: shown.append(args)))

    run_main(monkeypatch, qapp, mac=cfg.desk.mac, daemon_available=True,
             load_config=lambda _path: cfg)

    assert len(shown) == 1
    assert shown[0][2].count("future_root") == 1
    assert shown[0][2].count("future_theme") == 1
    assert shown[0][2].index("future_root") < shown[0][2].index("future_theme")
    assert "preserved" in shown[0][2]


# ----- the CLI surface -----

@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_help_and_version_exit_rather_than_opening_a_window(flag):
    """`gui/main.py` hand-scanned argv for a fixed flag map and returned None
    for anything else, so `--help` and `--version` fell through and *launched
    the GUI*. This is the binary README documents as a keyboard-shortcut
    target, and the daemon has had proper argparse all along."""
    import idasen_companion.gui.main as gui_main

    with pytest.raises(SystemExit) as exc:
        gui_main._parse_argv(["idasen-companion", flag])
    assert exc.value.code == 0


def test_an_unknown_flag_is_an_error_not_a_window():
    import idasen_companion.gui.main as gui_main

    with pytest.raises(SystemExit) as exc:
        gui_main._parse_argv(["idasen-companion", "--sitt"])
    assert exc.value.code != 0


def test_window_is_the_only_gui_action_flag():
    import idasen_companion.gui.main as gui_main
    gui_main._parse_argv(["idasen-companion", "--window"])


@pytest.mark.parametrize("flag", ["--toggle", "--sit", "--stand", "--stop",
                                  "--preset"])
def test_legacy_command_flags_point_callers_to_the_cli(flag, capsys):
    import idasen_companion.gui.main as gui_main

    with pytest.raises(SystemExit) as exc:
        gui_main._parse_argv(["idasen-companion", flag])
    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
