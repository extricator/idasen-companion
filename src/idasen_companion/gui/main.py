"""idasen-companion — the GUI application.

Single-instance: a second launch activates the existing window via
D-Bus. Tray-optional: with no StatusNotifier host (GNOME without the
AppIndicator extension), the window shows immediately and quitting the
window quits the app; with a tray, closing the window hides it.
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QEvent, QObject, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from .. import APP_ID, DBUS_NAME, __version__
from ..core.config import (
    AppConfig, ConfigError, DEFAULT_CONFIG_PATH, format_config_warning,
    load_config,
)
from ..core.i18n import pgettext
from . import appearance_portal, background_portal, restyle
from .dbus_client import DaemonClient
from .i18n import apply_language
from .main_window import MainWindow
from .style import ControlStyle

GUI_DBUS_NAME = f"{DBUS_NAME}.GUI"
GUI_DBUS_PATH = "/io/github/extricator/IdasenCompanion/GUI"

class SingleInstance(QObject):
    """Exports Activate() so a second launch can raise the first window."""

    def __init__(self, window):
        super().__init__()
        self._window = window

    # Activate is dispatched by exact name over the session bus by the
    # StatusNotifierItem host, so it carries its own inline naming-check
    # suppression rather than a file-level one.
    @Slot()
    def Activate(self) -> None:  # pylint: disable=invalid-name
        self._window.present()


def _parse_argv(argv: list[str]) -> None:
    """Handle GUI options and reject command flags owned by the CLI."""
    parser = argparse.ArgumentParser(
        prog="idasen-companion",
        description="Idasen Companion — sit/stand desk automation.",
        epilog="With no flags, opens the application window.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--window", action="store_true",
                        help="show the window even if it would start hidden "
                             "to the tray")
    parser.parse_args(argv[1:])


def main() -> int:
    # Validates the flags and handles --help/--version; exits for those.
    _parse_argv(sys.argv)
    application = QApplication(sys.argv)
    # Before any widget exists, so the connection is live for the very
    # first palette change whenever it arrives.
    restyle.follow_palette(application)
    application.setStyle(ControlStyle())
    application.setApplicationName("idasen-companion")
    # Install translators before any widget is built so tr() resolves. The
    # chosen language comes from config (default "system" = desktop locale).
    # A bad config must not stop the app launching. This read is unguarded no
    # longer: it happens before the window exists, so a ConfigError here meant
    # the desktop launcher did nothing at all — no dialog, no window, a
    # traceback on a stderr nobody is reading. Reachable without hand-editing
    # (downgrade the package and a config carrying a newer [ui] key trips the
    # unknown-option check), and glaring next to how carefully every *other*
    # config read in the GUI is handled. Running on defaults gets the user to
    # the Settings page, which reports the error and is the one place they can
    # fix it.
    try:
        startup_cfg = load_config(DEFAULT_CONFIG_PATH)
        config_ok = True
    except ConfigError as error:
        print(f"idasen-companion: {error}", file=sys.stderr)
        startup_cfg = AppConfig()
        config_ok = False
    apply_language(application, startup_cfg.ui.language)
    application.setApplicationDisplayName("Idasen Companion")
    application.setDesktopFileName(APP_ID)

    session_bus = QDBusConnection.sessionBus()
    if not session_bus.registerService(GUI_DBUS_NAME):
        # Another instance is running: activate it and exit.
        QDBusInterface(GUI_DBUS_NAME, GUI_DBUS_PATH).call("Activate")
        return 0

    # Read once at launch; nothing in the GUI consumes the values yet (D-13)
    # -- the module itself logs what it read, or that no portal answered.
    # Below the single-instance gate deliberately: a second launch exists to
    # raise the running window and exit, and paying two synchronous D-Bus
    # round trips for a value that is discarded three lines later is latency
    # on exactly the path that has to feel instant.
    appearance_portal.read_appearance_preferences()

    icon = QIcon.fromTheme(APP_ID, QIcon.fromTheme("input-tablet"))
    application.setWindowIcon(icon)

    client = DaemonClient()
    tray_available = QSystemTrayIcon.isSystemTrayAvailable()

    # Best-effort and silent, and a no-op outside Flatpak or when the user
    # never asked for it — see background_portal.py's docstring for why. Once
    # per launch, driven by the persisted intent rather than a portal
    # readback, since none exists.
    background_portal.reconcile_autostart(startup_cfg.ui.run_at_login)

    window = MainWindow(client, tray_available)
    if startup_cfg.warnings:
        QMessageBox.warning(
            window, pgettext('config-warning', "Idasen Companion"),
            pgettext(
                'config-warning',
                "Some configuration settings are not recognized by this "
                "version. They will be preserved:\n%s")
            % "\n".join(format_config_warning(warning)
                         for warning in startup_cfg.warnings))
    instance = SingleInstance(window)
    session_bus.registerObject(GUI_DBUS_PATH, instance,
                               QDBusConnection.RegisterOption.ExportAllSlots)

    tray = None
    if tray_available:
        from .tray import TrayIcon

        # The tray wants a monochrome symbolic icon the panel recolours
        # to match its theme, not the colourful launcher icon.
        tray_icon = QIcon.fromTheme(f"{APP_ID}-symbolic", icon)
        tray = TrayIcon(client, window, tray_icon)
        tray.show()
        application.setQuitOnLastWindowClosed(False)
    else:
        application.setQuitOnLastWindowClosed(True)

    def _on_about_to_quit() -> None:
        # Runs while the QApplication and platform integration are still alive.
        # Hide the tray now (destroying a QSystemTrayIcon after the platform is
        # gone is a common crash) and drop our exported D-Bus object/service.
        if tray is not None:
            tray.hide()
        session_bus.unregisterObject(GUI_DBUS_PATH)
        session_bus.unregisterService(GUI_DBUS_NAME)

    application.aboutToQuit.connect(_on_about_to_quit)

    # First run: no desk configured -> open window and offer the wizard.
    # Requires the config to have actually loaded: defaults have no MAC, so a
    # config we could not read would otherwise look like a first run and offer
    # to overwrite a file whose only fault may be one unknown key.
    first_run = config_ok and not startup_cfg.desk.mac
    # Start hidden to the tray only when one exists and the user opted in
    # (default). First run, no tray, or an explicit --window always show, so
    # the window is never unreachable.
    start_hidden = (tray_available and startup_cfg.ui.start_minimized
                    and not first_run and "--window" not in sys.argv)
    if not start_hidden:
        window.show()
    # Deliberately not gated on client.available. A fresh RPM install ships
    # the unit present but *disabled* (Fedora policy — see gui/service_ctl.py),
    # so on the very first launch the daemon is not running, which is exactly
    # when the wizard is needed. Its WelcomePage.validatePage exists to start a
    # stopped daemon and reports in-page if it can't, so gating on the bus here
    # only defeated the page written for this case: the user was left on the
    # red "not running" banner with no wizard and had to find Settings ->
    # Desk connection -> "Find my desk…" unaided.
    if first_run:
        from .setup_wizard import SetupWizard

        wizard = SetupWizard(client, window, ctx=window.ctx)
        wizard.accepted.connect(window.settings.load)
        wizard.open()

    exit_code = application.exec()

    # Tear down the Python-owned top-level Qt objects deterministically, before
    # this function returns and the interpreter finalizes. Left to Python's GC
    # they'd be destroyed in an undefined order relative to the QApplication and
    # its still-live QtDBus/xcb threads, and a Qt destructor would dereference
    # freed memory (SIGSEGV during Py_Finalize). deleteLater() needs a manual
    # flush because the event loop has already stopped.
    for obj in (tray, instance, window, client):
        if obj is not None:
            obj.deleteLater()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
