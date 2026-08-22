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
from PySide6.QtDBus import QDBus, QDBusConnection, QDBusInterface, QDBusMessage
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .. import APP_ID, DBUS_NAME, DBUS_PATH, __version__
from ..core.config import (
    AppConfig, ConfigError, DEFAULT_CONFIG_PATH, load_config,
)
from . import appearance_portal, background_portal, restyle, util
from .dbus_client import IFACE_DESK, DaemonClient
from .i18n import apply_language
from .main_window import MainWindow
from .style import ControlStyle

GUI_DBUS_NAME = f"{DBUS_NAME}.GUI"
GUI_DBUS_PATH = "/io/github/extricator/IdasenCompanion/GUI"

# One-shot command flags: fire a Desk1 method at the running daemon and exit,
# without building the GUI. These are what global keyboard shortcuts and
# scripts bind to (e.g. `idasen-companion --toggle`). The move flags go through
# GestureMove, so pressing the same shortcut again mid-move stops or reverses it
# (per [ui] tray_repeat_move) — the same behaviour as the tray gestures.
# --window is handled separately (it *shows* the GUI) and is deliberately not in
# this map. `--preset NAME` (or `--preset=NAME`) takes an argument.
_COMMAND_FLAGS = {
    "--toggle": ("GestureMove", ["toggle"]),
    "--sit": ("GestureMove", ["sit"]),
    "--stand": ("GestureMove", ["stand"]),
    "--stop": ("Stop", []),
}


def _command_from_argv(argv: list[str]) -> tuple[str, list] | None:
    """Map command-line flags to a (Desk1 method, args) pair, or None when no
    command flag is present (so the GUI launches as usual)."""
    args = argv[1:]
    for i, arg in enumerate(args):
        if arg in _COMMAND_FLAGS:
            member, cmd_args = _COMMAND_FLAGS[arg]
            return member, list(cmd_args)
        if arg == "--preset":
            return "MoveToPreset", [args[i + 1] if i + 1 < len(args) else ""]
        if arg.startswith("--preset="):
            return "MoveToPreset", [arg.split("=", 1)[1]]
    return None


def _send_command(member: str, args: list) -> int:
    """Send one Desk1.<member> call to the daemon and return an exit code.
    Blocks until the daemon replies (a move finishes) so the exit status is
    meaningful; the shortcut/script that launched us runs detached, so the
    wait is invisible."""
    from PySide6.QtCore import QCoreApplication

    if member == "MoveToPreset" and not args[0]:
        print("idasen-companion: --preset needs a preset name, "
              "e.g. --preset stand", file=sys.stderr)
        return 2

    QCoreApplication(sys.argv)  # QtDBus needs an application/event dispatcher
    session_bus = QDBusConnection.sessionBus()
    if not session_bus.isConnected():
        print("idasen-companion: cannot connect to the session bus",
              file=sys.stderr)
        return 1
    message = QDBusMessage.createMethodCall(
        DBUS_NAME, DBUS_PATH, IFACE_DESK, member)
    if args:
        message.setArguments(list(args))
    # The daemon only replies once the move finishes, and a full-range move
    # (plus an on-demand BLE connect, or a retry after an interruption) can
    # run well past QtDBus's default 25 s timeout — which would return a
    # spurious error even though the desk is moving. Allow two minutes.
    reply = session_bus.call(message, QDBus.CallMode.Block, 120000)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        print(f"idasen-companion: {member} failed: "
              f"{reply.errorMessage() or 'no reply from daemon'}\n"
              f"Is the daemon running? "
              f"(systemctl --user start idasen-companion.service)",
              file=sys.stderr)
        return 1
    return 0


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
    """Handle --help/--version and reject unknown flags, then return.

    Only these two: the command flags below still short-circuit before any Qt
    object exists, which is what keeps `--toggle` a fast one-shot. Without
    this, `--help` and `--version` fell through the flag scan and *launched
    the window* — as did any typo, so `--sitt` silently opened the GUI instead
    of saying it was not a flag. The daemon has had proper argparse all along;
    this is the binary the README documents as a keyboard-shortcut target.

    argparse exits the process for --help/--version/unknown, which is what we
    want here.
    """
    parser = argparse.ArgumentParser(
        prog="idasen-companion",
        description="Idasen Companion — sit/stand desk automation.",
        epilog="With no flags, opens the application window.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--window", action="store_true",
                        help="show the window even if it would start hidden "
                             "to the tray")
    group = parser.add_argument_group("one-shot commands (sent to the daemon)")
    group.add_argument("--toggle", action="store_true",
                       help="sit <-> stand (the opposite of where it is)")
    group.add_argument("--sit", action="store_true", help="move to the sit preset")
    group.add_argument("--stand", action="store_true", help="move to the stand preset")
    group.add_argument("--stop", action="store_true", help="stop the desk where it is")
    group.add_argument("--preset", metavar="NAME",
                       help="move to a named preset (e.g. sit, stand, focus)")
    parser.parse_args(argv[1:])


def main() -> int:
    # Validates the flags and handles --help/--version; exits for those.
    _parse_argv(sys.argv)
    # One-shot command flags short-circuit before any GUI is built.
    command = _command_from_argv(sys.argv)
    if command is not None:
        return _send_command(*command)

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
    # After the translators, which set the default QLocale that "system"
    # units resolve against; before any widget, since the height spin box is
    # shaped for its unit at construction. Kept current from here on by
    # AppContext (see gui/context.py).
    util.set_height_unit(startup_cfg.ui.units)
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

        wizard = SetupWizard(client, window)
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
