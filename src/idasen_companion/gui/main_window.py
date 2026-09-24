"""Main window shell: sidebar + page stack + daemon banner.

Each screen lives in its own module under ``gui/pages/`` as a ``Page``
(``QWidget``) that owns its widgets and subscribes to the daemon-client
signals it needs. This shell just holds the sidebar, the stacked pages,
and the cross-page bits (the connection footer, the daemon-down banner).
Everything the tray can do is reachable here too, because on GNOME
without AppIndicator there is no tray.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from . import restyle
from .context import AppContext
from .dbus_client import DaemonClient
from .pages import (
    AboutPage, ActivityLogPage, AutomationPage, OverviewPage, PresetsPage,
    SettingsPage, StatisticsPage,
)
from .pages.settings_form import SettingsFormPage
from .theme import (NAV_ICON_SIZE, NAV_ITEM_MARGIN_H, NAV_ITEM_PADDING_H, css,
                    theme)
from .util import connection_state, daemon_error_message
from .widgets import StatusDot, icon, selectable_icon, sidebar_width_for_labels
from ..core.i18n import pgettext
from ..core.i18n import P_

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


def _app() -> QApplication:
    """The running QApplication.

    ``QApplication.instance()`` is typed as returning the QCoreApplication
    base, and as optional. Every caller here runs from a window's event
    handler, so the application both exists and is the QApplication subclass
    that owns ``quitOnLastWindowClosed``.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        raise RuntimeError("no QApplication running")
    return app


# Sidebar entries: (label, theme icon candidates). Deferred ``P_`` keys retain
# a literal semantic context for extraction, then translate when the sidebar
# is built rather than freezing the import-time language.
NAV_ITEMS = [
    (P_("window-shell", "Overview"), ("go-home", "user-home")),
    # Second, right after Overview: Overview acts on the current cycle, this
    # configures every cycle. The repeat glyph reads as the sit/stand loop.
    (P_("window-shell", "Automation"),
     ("media-playlist-repeat", "chronometer", "view-refresh")),
    (P_("window-shell", "Presets"),
     ("bookmarks", "user-bookmarks", "bookmark-new")),
    (P_("window-shell", "Statistics"),
     ("view-statistics", "office-chart-bar",
      "utilities-system-monitor-symbolic")),
    (P_("window-shell", "Activity Log"),
     ("view-list-text", "format-list-unordered", "text-x-generic")),
    (P_("window-shell", "Settings"),
     ("configure", "preferences-system")),
    (P_("window-shell", "About"),
     ("help-about", "help-about-symbolic", "dialog-information")),
]


# showEvent, closeEvent and changeEvent below are QWidget virtual overrides,
# dispatched by name from Qt's C++ meta-object machinery. Each carries its own
# inline naming-check suppression rather than a file-level one.
class MainWindow(QMainWindow):
    def __init__(self, client: DaemonClient, tray_available: bool):
        super().__init__()
        self.client = client
        self.ctx = AppContext(client, tray_available)
        self.setWindowTitle(pgettext('window-shell', "Idasen Companion"))
        self.setMinimumSize(760, 600)
        self.resize(860, 660)

        self._connected = False
        # The page the sidebar is on. Tracked rather than read back from the
        # nav, because a vetoed page switch has to restore it (_on_nav_changed).
        self._page_index = 0

        # One page per sidebar entry, in NAV_ITEMS order. Each subscribes to
        # the client signals it needs from within its own constructor.
        self.overview = OverviewPage(self.ctx)
        self.automation = AutomationPage(self.ctx)
        self.presets = PresetsPage(self.ctx)
        self.statistics = StatisticsPage(self.ctx)
        self.activity_log = ActivityLogPage(self.ctx)
        self.settings = SettingsPage(self.ctx)
        self.about = AboutPage(self.ctx)
        self._pages = [self.overview, self.automation, self.presets,
                       self.statistics, self.activity_log, self.settings,
                       self.about]

        stack = QStackedWidget()
        for page in self._pages:
            stack.addWidget(page)
        self._stack = stack

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 12, 16, 12)
        self._daemon_banner = QLabel()
        restyle.register(self, self._restyle_daemon_banner)
        # The disabled-unit wording is a full sentence, and roughly 30% longer
        # again in es — without wrapping it stretches the banner row past the
        # window's default width instead of growing taller.
        self._daemon_banner.setWordWrap(True)
        self._daemon_banner.hide()
        banner_row = QHBoxLayout()
        banner_row.addWidget(self._daemon_banner, 1)
        self._start_daemon_btn = QPushButton(pgettext('window-shell', "Start daemon"))
        self._start_daemon_btn.clicked.connect(self._start_daemon)
        self._start_daemon_btn.hide()
        # Whether that button is currently offering to enable the unit at login
        # rather than just start it; set from systemd each time the banner is
        # raised (see _on_available).
        self._autostart_offer = False
        banner_row.addWidget(self._start_daemon_btn)
        layout.addLayout(banner_row)
        layout.addWidget(stack)
        if not tray_available:
            hint = QLabel(pgettext('window-shell', "No system tray detected (on GNOME, install the AppIndicator "
                "extension). Closing this window keeps the app running in the "
                "background; automation runs in the daemon either way."))
            hint.setWordWrap(True)

            def _restyle_hint(target: QLabel = hint) -> None:
                target.setStyleSheet(f"color: {css(theme().muted)};")

            restyle.register(hint, _restyle_hint)
            layout.addWidget(hint)

        container = QWidget()
        shell = QHBoxLayout(container)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._build_sidebar())
        shell.addWidget(content, 1)
        self.setCentralWidget(container)

        # Cross-page wiring: the banner and footer live in the shell.
        client.availableChanged.connect(self._on_available)
        client.connectedChanged.connect(self._on_connected)
        client.commandFailed.connect(self._on_command_failed)
        self.ctx.configChanged.connect(self._update_conn_footer)

        # Drive the initial state now that every page has subscribed: the
        # client may have gone live before the window existed, so its
        # startup signals were emitted into the void. Re-emitting reaches
        # the shell (banner/footer) and every page's availableChanged slot.
        client.availableChanged.emit(client.available)
        if client.available:
            client.refresh_all()
        # Loads config into the context and, via configChanged, refreshes the
        # footer and the overview status/chip that quote config values. Both
        # settings-class pages are primed here rather than waiting for their
        # first on_shown, so neither can be displayed holding widget defaults.
        self.automation.load()
        self.settings.load()

    def _on_command_failed(self, name: str, detail: str) -> None:
        """Report a command the daemon refused.

        These are fire-and-forget calls whose error replies were discarded, so
        pressing Sit with the desk unreachable simply did nothing visible:
        no dialog, no status change (``machine.move_failed`` is set only by the
        automation path), nothing in the window at all. The message is composed
        here from the error *name* so it can be translated — the daemon's own
        body crosses the wire in English and is in neither catalog.
        """
        QMessageBox.warning(self, pgettext('window-shell', "Idasen Companion"),
                            daemon_error_message(name, detail))

    def _restyle_daemon_banner(self) -> None:
        tokens = theme()
        self._daemon_banner.setStyleSheet(
            f"background: {css(tokens.error)}; color: {css(tokens.error_text)};"
            f" padding: 6px; border-radius: 4px;")

    # ================= Sidebar shell =================

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setAutoFillBackground(True)
        sidebar.setObjectName("Sidebar")
        self._sidebar = sidebar
        vbox = QVBoxLayout(sidebar)
        vbox.setContentsMargins(0, 8, 0, 10)
        vbox.setSpacing(0)

        nav_list = QListWidget()
        nav_list.setFrameShape(QListWidget.Shape.NoFrame)
        nav_list.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for label, _icon_names in NAV_ITEMS:
            nav_list.addItem(QListWidgetItem(pgettext(label.context, label)))
        self._nav = nav_list
        nav_list.setCurrentRow(0)
        # One slot rather than three connections: switching pages can now be
        # *vetoed* (a settings page with unapplied edits asks first), and a
        # veto has to leave the stack, the highlight and the sidebar selection
        # all on the old page. That is only reliable if one place owns them.
        nav_list.currentRowChanged.connect(self._on_nav_changed)
        self._bold_selected_nav(nav_list.currentRow())
        vbox.addWidget(nav_list, 1)

        # Persistent connection footer, visible on every screen.
        footer = QWidget()
        row = QHBoxLayout(footer)
        row.setContentsMargins(14, 6, 8, 0)
        row.setSpacing(7)
        self._conn_dot = StatusDot()
        self._conn_footer = QLabel()
        row.addWidget(self._conn_dot)
        row.addWidget(self._conn_footer, 1)
        vbox.addWidget(footer)

        restyle.register(self, self._restyle_sidebar)
        restyle.register(self, self._resize_sidebar)
        restyle.register(self, self._update_conn_footer)
        return sidebar

    def _restyle_sidebar(self) -> None:
        tokens = theme()
        divider_side = "left" if self.isRightToLeft() else "right"
        self._sidebar.setStyleSheet(
            f"QWidget#Sidebar {{ background: {css(tokens.sidebar_bg)};"
            f" border-{divider_side}: 1px solid {css(tokens.separator)}; }}")
        self._nav.setStyleSheet(
            "QListWidget { background: transparent; outline: none; }"
            "QListWidget::item {"
            f" padding: 6px {NAV_ITEM_PADDING_H}px;"
            f" margin: 1px {NAV_ITEM_MARGIN_H}px;"
            " border-radius: 4px; }"
            f"QListWidget::item:selected {{ background: {css(tokens.accent)};"
            f" color: {css(tokens.selection_text)}; font-weight: bold; }}"
            f"QListWidget::item:hover:!selected"
            f" {{ background: {css(tokens.hover)}; }}")
        for index, (_label, icon_names) in enumerate(NAV_ITEMS):
            # The selected glyph takes the same colour as the selected
            # label, not the accent: the row behind it *is* the accent at
            # full strength, so an accent-tinted glyph would be drawn on
            # top of its own colour. Measured on a dark palette,
            # `accent_text` on the accent is 1.38:1.
            self._nav.item(index).setIcon(
                selectable_icon(icon(*icon_names), tokens.selection_text,
                                tokens.text))
        self._conn_footer.setStyleSheet(f"color: {css(tokens.secondary)};")

    def _resize_sidebar(self) -> None:
        """Size the sidebar to the widest label it is actually showing.

        Reads the rendered text back off the built list rather than
        re-translating ``NAV_ITEMS``, so this measures exactly what
        ``_build_sidebar`` put on screen and cannot drift from it. Recomputed
        on every restyle sweep because a palette or font change moves the
        metrics this depends on. Deliberately never persisted: a language
        change applies on restart and the labels are baked in at
        construction, so a construction-time computation is consistent with
        the rest of this window's existing behaviour.

        Registration order against ``_restyle_sidebar`` does not matter. The
        chrome this width allows for comes from ``gui/theme.py``'s constants,
        which both this and the stylesheet read directly -- neither waits on
        the other, and nothing here queries a stylesheet that may not be
        applied yet.
        """
        labels = [self._nav.item(i).text() for i in range(self._nav.count())]
        self._sidebar.setFixedWidth(
            sidebar_width_for_labels(labels, self._nav.font()))

    def _on_nav_changed(self, index: int) -> None:
        # currentRowChanged can emit -1 (no selection); ignore it rather than
        # wrap around.
        if not 0 <= index < len(self._pages):
            return
        if index != self._page_index and not self.confirm_unapplied_edits():
            # Vetoed. Put the sidebar selection back without re-entering here.
            blocked = self._nav.blockSignals(True)
            self._nav.setCurrentRow(self._page_index)
            self._nav.blockSignals(blocked)
            return
        self._page_index = index
        self._stack.setCurrentIndex(index)
        self._bold_selected_nav(index)
        # Pages that reload lazily (any page overriding on_shown) refresh
        # themselves as they become the current tab.
        self._pages[index].on_shown()

    def _bold_selected_nav(self, index: int) -> None:
        for i in range(self._nav.count()):
            item = self._nav.item(i)
            font = item.font()
            font.setWeight(QFont.Weight.DemiBold if i == index
                           else QFont.Weight.Normal)
            item.setFont(font)

    def _update_conn_footer(self) -> None:
        color, footer, _chip = connection_state(
            theme(), self._connected, self.client.available, self.ctx.persistent)
        self._conn_dot.set_color(color)
        self._conn_footer.setText(footer)

    def _on_connected(self, connected: bool) -> None:
        self._connected = connected
        self._update_conn_footer()

    def _on_available(self, available: bool) -> None:
        from . import background_portal, service_ctl

        if available:
            self._daemon_banner.hide()
            self._start_daemon_btn.hide()
        else:
            # A merely-stopped daemon and one that is switched off need
            # different remedies, and offering the wrong one is worse than it
            # sounds: starting a disabled unit clears the banner, looks like a
            # fix, and is gone again at the next login. So ask systemd which
            # case this is and label the button for what it will actually do —
            # the button still does exactly what it says, which is why this
            # changes the wording rather than making "Start" quietly enable.
            # A Flatpak has no host systemd unit to ask, and enabling autostart
            # there is Settings' job (the portal dialog), not this banner's.
            self._autostart_offer = (
                not background_portal.is_flatpak()
                and service_ctl.autostart_state().offer_enable)
            if self._autostart_offer:
                self._daemon_banner.setText(pgettext('window-shell', "The Idasen Companion daemon is not running, and is not "
                    "set to start when you log in."))
                self._start_daemon_btn.setText(pgettext('window-shell', "Start at login"))
            else:
                self._daemon_banner.setText(
                    pgettext('window-shell', "The Idasen Companion daemon is not running."))
                self._start_daemon_btn.setText(pgettext('window-shell', "Start daemon"))
            self._daemon_banner.show()
            self._start_daemon_btn.show()
        self._update_conn_footer()

    def _start_daemon(self) -> None:
        """Act on the "not running" banner, doing what its button offered.

        Either start the daemon for this session, or — when the unit is
        installed but switched off, so a plain start would not survive logout —
        enable it at login as well. Never more than the button said: turning on
        autostart behind the user's back isn't what they clicked, which is why
        the offer is made in the label rather than assumed here.
        """
        from . import service_ctl

        if self._autostart_offer:
            started, err = service_ctl.set_autostart(True)  # enable --now
            command = service_ctl.ENABLE_CMD
        else:
            started, err = service_ctl.start()
            command = service_ctl.START_CMD
        if not started:
            # startDetached() used to swallow this, leaving the banner up with
            # no hint as to why nothing happened.
            QMessageBox.warning(
                self, pgettext('window-shell', "Idasen Companion"),
                pgettext('window-shell', "The background service could not be started:\n%(error)s\n\n"
                        "Try running this in a terminal:\n  %(command)s")
                % {"error": err, "command": command})

    # ================= window behavior =================

    def showEvent(self, event) -> None:  # pylint: disable=invalid-name
        super().showEvent(event)
        # Coming back from the tray is the current page being shown again, and
        # the lazily-reloading pages only ever heard about that through
        # _on_nav_changed — which a hide/show cycle is not. So the window used
        # to reopen on whatever page it was left on still holding whatever that
        # page read when it was last *navigated* to, however long ago: opening
        # the next day showed yesterday's daily totals until you changed panes.
        self._pages[self._page_index].on_shown()

    def present(self) -> None:
        """Bring the window to the front from hidden, minimised, or behind
        another window. Used by the tray and the single-instance Activate so
        a window parked in the tray (incl. via minimise-to-tray) restores as a
        normal window rather than reappearing minimised."""
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _ui_pref(self, name: str, default):
        # Read a [ui] behaviour setting, tolerating an unreadable config.
        config = self.ctx.cfg
        return getattr(config.ui, name) if config is not None else default

    def confirm_unapplied_edits(self) -> bool:
        """Settle any staged settings edits before leaving them behind.

        Returns False when the caller should abandon what it was about to do.
        Only the current page can be dirty — this same check is what stops you
        navigating off one — so there is never more than one page to ask about.

        Minimising to the tray deliberately does *not* come through here: the
        window is put away, not dismissed, and the edits are still plainly
        marked as unapplied by the footer when it comes back.
        """
        page = self._pages[self._page_index]
        if not isinstance(page, SettingsFormPage) or not page.is_dirty():
            return True
        # Asked from the tray, the window may not be on screen; nobody can
        # answer a question about a page they can't see.
        if not self.isVisible():
            self.present()
        answer = QMessageBox.warning(
            self, pgettext('window-shell', "Idasen Companion"),
            pgettext('window-shell', "This page has changes you haven't applied yet."),
            QMessageBox.StandardButton.Apply
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Apply)
        if answer == QMessageBox.StandardButton.Apply:
            # Applying can still be refused — a half-typed Bluetooth address —
            # in which case stay put rather than silently dropping the edit.
            return page.apply_edits()
        if answer == QMessageBox.StandardButton.Discard:
            page.discard_edits()
            return True
        return False

    def request_quit(self) -> None:
        """Quit, after settling any staged settings edits. Used by the tray,
        whose menu bypasses closeEvent by calling quit() directly."""
        if self.confirm_unapplied_edits():
            _app().quit()

    def closeEvent(self, event) -> None:  # pylint: disable=invalid-name
        if not self.confirm_unapplied_edits():
            event.ignore()
            return
        event.accept()
        # No tray (quitOnLastWindowClosed True): closing exits, as before.
        if _app().quitOnLastWindowClosed():
            return
        # Tray present: honour the user's choice — hide to the tray or quit.
        if self._ui_pref("close_action", "tray") == "quit":
            _app().quit()
        else:
            self.hide()

    def changeEvent(self, event) -> None:  # pylint: disable=invalid-name
        if (event.type() == QEvent.Type.WindowStateChange
                and self.isMinimized()
                and not _app().quitOnLastWindowClosed()
                and self._ui_pref("minimize_to_tray", False)):
            # Drop the window to the tray instead of the taskbar. Deferred so
            # the minimise settles first; clear the minimised bit as we hide so
            # a later show() restores a normal window rather than a hidden one.
            QTimer.singleShot(0, self._hide_to_tray)
        super().changeEvent(event)

    def _hide_to_tray(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.hide()
