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

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, Qt
from PySide6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QRadioButton, QVBoxLayout, QWizard, QWizardPage,
)

from . import service_ctl
from .dbus_client import DaemonClient
from .util import fmt_height

# validatePage, initializePage and isComplete below are QWizardPage virtual
# overrides, dispatched by name from Qt's C++ meta-object machinery. Each
# carries its own inline naming-check suppression rather than a file-level one.


class WelcomePage(QWizardPage):
    def __init__(self, client: DaemonClient):
        super().__init__()
        self.client = client
        self.setTitle(self.tr("Set up your desk"))
        layout = QVBoxLayout(self)
        text = QLabel(self.tr(
            "This wizard connects Idasen Companion to your Idåsen desk.\n\n"
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
        self.daemon_label.setText(self.tr("Starting the background service…"))
        # Paint that label before the blocking call below.
        QCoreApplication.processEvents()
        started, err = service_ctl.start()
        if started and self._wait_for_daemon(8):
            self.daemon_label.setText("")
            return True
        # A start that "succeeded" but never showed up on the bus has no
        # systemctl error to report, so supply a reason either way.
        self.daemon_label.setText(self.tr(
            "The background service could not be started:\n%s\n\n"
            "Try running this in a terminal, then continue:\n  %s")
            % (err or self.tr("it did not respond in time"),
               service_ctl.START_CMD))
        return False


class ScanPage(QWizardPage):
    def __init__(self, client: DaemonClient):
        super().__init__()
        self.client = client
        self.setTitle(self.tr("Select your desk"))
        layout = QVBoxLayout(self)
        self.device_list = QListWidget()
        self.device_list.itemSelectionChanged.connect(self.completeChanged)
        layout.addWidget(self.device_list)
        self.scan_btn = QPushButton(self.tr("Scan for more devices"))
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
            self.hint.setText(self.tr("Found without scanning — if this is "
                                      "your desk, just continue."))
        else:
            # Nothing known yet. This is the first moment anyone actually
            # wants a device list, so scan now — the daemon deliberately does
            # not scan on its own while it is unconfigured. Pressing Scan is
            # the only useful thing to do here, so don't make the user do it.
            self._scan()

    def _scan(self) -> None:
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(self.tr("Scanning… (about 10 s)"))
        QCoreApplication.processEvents()
        try:
            devices = self.client.discover(8)
        finally:
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText(self.tr("Scan again"))
        self._populate(devices)
        if devices:
            # The list speaks for itself — and a stale "Nothing found." from an
            # earlier attempt must not outlive the scan that succeeded.
            self.hint.clear()
        else:
            self.hint.setText(self.tr("Nothing found. Is Bluetooth on and the "
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
        self.setTitle(self.tr("How do you want to use it?"))
        layout = QVBoxLayout(self)
        self.automatic = QRadioButton(self.tr("Remind me to sit and stand"))
        self.automatic.setChecked(True)
        auto_note = QLabel(self.tr(
            "The desk alternates between your sit and stand presets while "
            "you're working. You can change the timings, pause it, or turn "
            "it off later in Settings."))
        self.manual = QRadioButton(self.tr("Just let me move the desk"))
        manual_note = QLabel(self.tr(
            "No timer and no reminders. Presets, the tray menu and the "
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
    def __init__(self, client: DaemonClient, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Idasen Companion setup"))
        self.client = client
        self.addPage(WelcomePage(client))
        self.scan_page = ScanPage(client)
        self.addPage(self.scan_page)
        self.usage_page = UsagePage()
        self.addPage(self.usage_page)

    def _automation_note(self) -> str:
        if self.usage_page.wants_automation():
            return self.tr("It will remind you to alternate sit and stand "
                           "while you work.")
        return self.tr("Automation is off — the desk will only move when you "
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
            return self.tr("It will start automatically when you log in.")
        return self.tr("It will not start automatically when you log in — "
                       "you can turn that on in Settings.")

    def _success_paragraphs(self, height: float) -> list[str]:
        """The success dialog's body, as independent whole lines.

        Each entry is already a complete, translator-owned sentence, and
        stacking them with a blank line between is the same layout shape the
        tray tooltip and the About page's copy blob use — only their order is
        fixed here, not their wording. Produced inside this helper rather
        than where they are joined, so the shape stays structurally the same
        as those two sites end to end, not just in how it reads.
        """
        return [
            self.tr("Success! Your desk is set up and currently at "
                    "%s.") % fmt_height(height),
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
            # user who picked the reminder option needs no call — and one that
            # wrote the config would clobber a value set by hand before setup.
            if not self.usage_page.wants_automation():
                self.client.set_automation_enabled(False)
            QMessageBox.information(
                self, self.tr("Desk connected"),
                "\n\n".join(self._success_paragraphs(result)))
            super().accept()
        else:
            QMessageBox.warning(
                self, self.tr("Could not reach the desk"),
                self.tr("%s\n\nThe address was not saved — pick a device "
                        "and try again.") % result)
