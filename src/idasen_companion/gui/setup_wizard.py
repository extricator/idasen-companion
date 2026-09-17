"""First-run setup wizard.

Design goals for a user with zero prior setup:
- Starts the daemon itself if it isn't running yet.
- The device list is populated the moment the page opens: desks already
  paired via the system Bluetooth settings plus the daemon's cached
  startup scan (no clicking "scan" for the common case).
- Finishing performs a VERIFIED setup: the daemon connects, pairs
  (best-effort) and reads the height before the address is saved — so a
  completed wizard means a working desk, not just a string in a config.
- Automation is a question, not an assumption: the last page lets someone
  set the app up purely as a desk remote (presets, manual moves, stats).
- Finishing also makes the daemon start at login. Note the split: the
  first page only *starts* the service (it needs one to scan with), and
  the unit is *enabled* solely on success, once the user has actually
  committed to a desk. Enabling a background service for someone who
  abandons the wizard halfway is the same overreach as enabling the unit
  for every account on the machine, which the packaging preset used to do.
"""

from __future__ import annotations

from ..core.i18n import pgettext

import typing

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, Qt
from PySide6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QRadioButton, QVBoxLayout, QWizard, QWizardPage,
)

from ..core.presentation.formatter import Formatter
from . import service_ctl
from .context import AppContext
from .dbus_client import DaemonClient

# validatePage, initializePage and isComplete below are QWizardPage virtual
# overrides, dispatched by name from Qt's C++ meta-object machinery. Each
# carries its own inline naming-check suppression rather than a file-level one.


class WelcomePage(QWizardPage):
    def __init__(self, client: DaemonClient):
        super().__init__()
        self.client = client
        self.setTitle(pgettext('setup.welcome', "Set up your desk"))
        layout = QVBoxLayout(self)
        text = QLabel(pgettext('setup.welcome', "This wizard connects Idasen Companion to your Idåsen desk.\n\n"
            "If you already paired the desk in your system's Bluetooth "
            "settings, it will simply appear on the next page.\n\n"
            "Otherwise, put the desk in pairing mode first: press and hold "
            "the button on the control box under the desktop (next to the "
            "paddle) until its light starts flashing."))
        text.setWordWrap(True)
        layout.addWidget(text)
        self.daemon_label = QLabel()
        self.daemon_label.setWordWrap(True)
        layout.addWidget(self.daemon_label)

    def _wait_for_daemon(self, seconds: float) -> bool:
        """Block until the daemon claims its D-Bus name, or time out.

        ``validatePage`` has to answer synchronously, so a nested event loop
        is unavoidable — but it can be event-driven instead of a
        ``processEvents()``/``sleep()`` spin that ignores input in 100 ms
        chunks and reacts to the daemon appearing only on the next poll.
        """
        if self.client.available:
            return True
        loop = QEventLoop()
        self.client.availableChanged.connect(loop.quit)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        deadline.start(int(seconds * 1000))
        try:
            loop.exec()
        finally:
            deadline.stop()
            self.client.availableChanged.disconnect(loop.quit)
        return self.client.available

    def validatePage(self) -> bool:  # pylint: disable=invalid-name
        """Moving past this page requires a running daemon; start it.

        Only started, not enabled — see the module docstring for why the
        enable happens at the end instead.
        """
        if self.client.available:
            return True
        self.daemon_label.setText(pgettext('setup.welcome', "Starting the background service…"))
        # Paint that label before the blocking call below.
        QCoreApplication.processEvents()
        started, err = service_ctl.start()
        if started and self._wait_for_daemon(8):
            self.daemon_label.setText("")
            return True
        # A start that "succeeded" but never showed up on the bus has no
        # systemctl error to report, so supply a reason either way.
        self.daemon_label.setText(pgettext('setup.welcome', "The background service could not be started:\n%(error)s\n\n"
            "Try running this in a terminal, then continue:\n  %(command)s")
            % {"error": err or pgettext('setup.welcome', "it did not respond in time"),
               "command": service_ctl.START_CMD})
        return False


class ScanPage(QWizardPage):
    def __init__(self, client: DaemonClient):
        super().__init__()
        self.client = client
        self.setTitle(pgettext('setup.scan', "Select your desk"))
        layout = QVBoxLayout(self)
        self.device_list = QListWidget()
        self.device_list.itemSelectionChanged.connect(self.completeChanged)
        layout.addWidget(self.device_list)
        self.scan_btn = QPushButton(pgettext('setup.scan', "Scan for more devices"))
        self.scan_btn.clicked.connect(self._scan)
        layout.addWidget(self.scan_btn)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

    def initializePage(self) -> None:  # pylint: disable=invalid-name
        # Instant results: paired devices, plus a scan the daemon still has
        # cached from an earlier visit.
        self._populate(self.client.discover(0))
        if self.device_list.count():
            self.hint.setText(pgettext('setup.scan', "Found without scanning — if this is "
                                      "your desk, just continue."))
        else:
            # Nothing known yet. This is the first moment anyone actually
            # wants a device list, so scan now — the daemon deliberately does
            # not scan on its own while it is unconfigured. Pressing Scan is
            # the only useful thing to do here, so don't make the user do it.
            self._scan()

    def _fmt(self) -> Formatter:
        """The current :class:`Formatter`, read fresh from the wizard's
        context rather than stored.

        ``self.wizard().ctx.fmt`` is rebuilt on every config change, so
        reading it here at use time — never caching it onto ``self`` — is
        what lets a unit change reach the next render of this page instead
        of keeping a stale one around. The same idiom
        ``gui/tray.py``'s ``TrayIcon._fmt()`` uses.

        ``self.wizard()`` is typed as the base ``QWizard``, which has no
        ``ctx``; narrowed with :func:`typing.cast` to this module's own
        ``SetupWizard`` rather than by widening ``ScanPage.__init__``. It
        is non-``None`` and already a live ``SetupWizard`` at every call
        site that reaches this: :meth:`_scan` runs only from
        :meth:`initializePage` or the Scan button's ``clicked`` signal,
        and both fire after ``SetupWizard.__init__`` has already called
        ``self.addPage(self.scan_page)``.
        """
        return typing.cast("SetupWizard", self.wizard()).ctx.fmt

    def _scan(self) -> None:
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(pgettext('setup.scan', "Scanning… (about %(duration)s)") % {
            "duration": self._fmt().duration(10)})
        QCoreApplication.processEvents()
        try:
            devices = self.client.discover(8)
        finally:
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText(pgettext('setup.scan', "Scan again"))
        self._populate(devices)
        if devices:
            # The list speaks for itself — and a stale "Nothing found." from an
            # earlier attempt must not outlive the scan that succeeded.
            self.hint.clear()
        else:
            self.hint.setText(pgettext('setup.scan', "Nothing found. Is Bluetooth on and the "
                                      "desk in pairing mode? Try again."))

    def _populate(self, devices: list) -> None:
        selected = self.selected_mac()
        self.device_list.clear()
        for name, mac in devices:
            item = QListWidgetItem(f"{name}  ({mac})")
            item.setData(Qt.ItemDataRole.UserRole, mac)
            self.device_list.addItem(item)
            if mac == selected:
                item.setSelected(True)
        # One candidate: preselect it so setup is Next -> Finish.
        if self.device_list.count() == 1:
            self.device_list.item(0).setSelected(True)
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # pylint: disable=invalid-name
        return bool(self.device_list.selectedItems())

    def selected_mac(self) -> str:
        items = self.device_list.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else ""


class UsagePage(QWizardPage):
    """How the app should behave once the desk is connected.

    Asked *after* the desk is chosen, not before: a manual-only user still
    needs a working connection, so skipping the scan was never an option —
    the only thing on offer here is whether the timer runs."""

    def __init__(self):
        super().__init__()
        self.setTitle(pgettext('setup.usage', "How do you want to use it?"))
        layout = QVBoxLayout(self)
        self.automatic = QRadioButton(pgettext('setup.usage', "Move the desk for me"))
        self.automatic.setChecked(True)
        auto_note = QLabel(pgettext('setup.usage', "The desk alternates between your sit and stand presets while "
            "you're working. You can change the timings, pause it, or turn "
            "it off later in Settings."))
        self.manual = QRadioButton(pgettext('setup.usage', "Just let me move the desk"))
        manual_note = QLabel(pgettext('setup.usage', "No timer. Presets, the tray menu and the "
            "statistics all still work — the desk only moves when you say so."))
        for note in (auto_note, manual_note):
            note.setWordWrap(True)
            note.setIndent(22)
        layout.addWidget(self.automatic)
        layout.addWidget(auto_note)
        layout.addSpacing(12)
        layout.addWidget(self.manual)
        layout.addWidget(manual_note)

    def wants_automation(self) -> bool:
        return self.automatic.isChecked()


class SetupWizard(QWizard):
    def __init__(self, client: DaemonClient, parent=None, *, ctx: AppContext):
        super().__init__(parent)
        self.setWindowTitle(pgettext('setup', "Idasen Companion setup"))
        self.client = client
        # Keyword-only, and stored rather than threaded through every page,
        # matching gui/pages/base.py's Page. _success_paragraphs reads
        # self.ctx.fmt fresh at use time rather than snapshotting a
        # Formatter, which is what lets a config change reach the next
        # render of this page.
        self.ctx = ctx
        self.addPage(WelcomePage(client))
        self.scan_page = ScanPage(client)
        self.addPage(self.scan_page)
        self.usage_page = UsagePage()
        self.addPage(self.usage_page)

    def _automation_note(self) -> str:
        if self.usage_page.wants_automation():
            return pgettext('setup', "It will move the desk between sit and stand "
                           "while you work.")
        return pgettext('setup', "Automation is off — the desk will only move when you "
                       "ask it to. You can turn it on any time in Settings.")

    def _enable_autostart(self) -> str:
        """Make the daemon start at login; return a line about the outcome.

        Best-effort on purpose: the desk is configured and working whether or
        not this succeeds, so a failure is a note in the success dialog, not
        an error that undoes a verified setup. *Why* it can't be enabled
        (masked, not installed, no systemd user manager) is spelled out by
        the Settings toggle, which reads the same state — no point
        duplicating that in a dialog the user sees once.
        """
        state = service_ctl.autostart_state()
        enabled = state.on
        if not enabled and state.manageable:
            enabled = service_ctl.set_autostart(True)[0]
        if enabled:
            return pgettext('setup', "It will start automatically when you log in.")
        return pgettext('setup', "It will not start automatically when you log in — "
                       "you can turn that on in Settings.")

    def _success_paragraphs(self, height: float) -> list[str]:
        """The success dialog's body, as independent whole lines.

        Each entry is already a complete, translator-owned sentence, and
        stacking them with a blank line between is the same layout shape the
        tray tooltip and the About page's copy blob use — only their order is
        fixed here, not their wording. Produced inside this helper rather
        than where they are joined, so the shape stays structurally the same
        as those two sites end to end, not just in how it reads.

        Say plainly what that costs: written inline at the join, this list
        would be flagged — the check traces into a list literal, and the
        first entry resolves to translated text. It passes because the join's
        argument is a method call, which the check declines to follow into on
        purpose. So the method boundary is the whole reason this site is
        silent, and a list that genuinely did build a sentence out of pieces
        would be just as silent behind one. The judgement above is a human's,
        and the next stacked-lines site needs the same one made again rather
        than read off a green suite.
        """
        return [
            pgettext('setup', "Success! Your desk is set up and currently at "
                    "%s.") % self.ctx.fmt.height(height),
            self._automation_note(),
            self._enable_autostart(),
        ]

    def accept(self) -> None:
        mac = self.scan_page.selected_mac()
        if not mac:
            super().accept()
            return
        self.setEnabled(False)
        self.setCursor(Qt.CursorShape.WaitCursor)
        QCoreApplication.processEvents()
        try:
            verified, result = self.client.setup(mac)
        finally:
            self.unsetCursor()
            self.setEnabled(True)
        if verified and isinstance(result, float):
            # Only ever *turn off* from here. The daemon default is on, so a
            # user who picked automatic movement needs no call — and one that
            # wrote the config would clobber a value set by hand before setup.
            if not self.usage_page.wants_automation():
                self.client.set_automation_enabled(False)
            QMessageBox.information(
                self, pgettext('setup', "Desk connected"),
                "\n\n".join(self._success_paragraphs(result)))
            super().accept()
        else:
            QMessageBox.warning(
                self, pgettext('setup', "Could not reach the desk"),
                pgettext('setup', "%s\n\nThe address was not saved — pick a device "
                        "and try again.") % result)
