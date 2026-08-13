#!/usr/bin/env python3
"""Capture the three screenshots the AppStream metainfo links to.

Builds the real ``MainWindow`` offscreen against a fake, never-available
daemon client — the same construction ``tests/test_window_reopen.py`` already
uses to exercise the whole window without a live D-Bus connection — and grabs
three of its pages: Overview, Statistics and Settings. Never touches BLE or a
running daemon.

Re-running this script overwrites the three PNGs; it is safe to run as often
as needed.
"""

from __future__ import annotations

import os

# Forced, not defaulted — a desktop session exports QT_QPA_PLATFORM (xcb
# here), which the app would then try, and fail, to actually reach.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import main_window as mw  # noqa: E402
from idasen_companion.gui import service_ctl  # noqa: E402
from idasen_companion.gui.pages.settings_form import (  # noqa: E402
    SettingsFormPage,
)

OUT_DIR = ROOT / "data" / "screenshots"

# Sidebar order, from MainWindow._pages / NAV_ITEMS.
OVERVIEW, STATISTICS, SETTINGS = 0, 3, 5

# (sidebar index, output filename) — the three views the metainfo lists.
PAGES = [
    (OVERVIEW, "main-window.png"),
    (STATISTICS, "statistics.png"),
    (SETTINGS, "settings.png"),
]

# A throwaway MAC, matching the fixture convention already used across the
# suite (tests/test_settings_form.py, tests/test_window_reopen.py) rather than
# a real device address.
MAC = "E1:B2:C3:D4:E5:F6"

WINDOW_SIZE = (900, 640)


class FakeClient(QObject):
    """Every signal MainWindow and its pages subscribe to, and nothing live.

    ``available`` stays False so no page attempts a D-Bus read while the
    window is built. Ported from ``tests/test_window_reopen.py``'s FakeClient.
    """

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

    def reload_config(self):  # pragma: no cover - unavailable, never nudged
        raise AssertionError("should not nudge an unavailable daemon")

    def __getattr__(self, name):
        # Every page's buttons connect to daemon calls this fake has no
        # business answering; nothing here is ever invoked, so a no-op
        # stands in for the rest of the client's surface.
        return lambda *args, **kwargs: None


def _stub_autostart():
    """The unit is installed and enabled — the banner's uninteresting case,
    and avoids shelling out to systemctl from this script."""
    return service_ctl.AutostartState("enabled", True, "")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.toml"
        cfg = AppConfig()
        cfg.desk.mac = MAC
        save_config(cfg, config_path)
        context_mod.DEFAULT_CONFIG_PATH = config_path
        service_ctl.autostart_state = _stub_autostart

        app = QApplication.instance() or QApplication([])
        window = mw.MainWindow(FakeClient(), tray_available=True)
        window.resize(*WINDOW_SIZE)
        window.show()
        app.processEvents()

        try:
            for index, filename in PAGES:
                window._nav.setCurrentRow(index)  # pylint: disable=protected-access
                app.processEvents()
                pixmap = window.grab()
                dest = OUT_DIR / filename
                if not pixmap.save(str(dest), "PNG"):
                    raise RuntimeError(f"failed to save {dest}")
                print(f"wrote {dest}")
        finally:
            # Settle any staged edits before closing — closeEvent asks about
            # them through a modal QMessageBox, and offscreen there is
            # nobody to answer.
            for page in window._pages:  # pylint: disable=protected-access
                if isinstance(page, SettingsFormPage):
                    page.discard_edits()
            window.close()


if __name__ == "__main__":
    main()
