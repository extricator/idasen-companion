"""Settings page: language, units, autostart, window & tray, desk connection.

How the *app* is set up — as opposed to how the automation behaves, which is
the Automation page. Both are forms over config.toml (SettingsFormPage).
"""

from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLineEdit, QMessageBox, QPushButton,
)

from ...core.config import AppConfig
from .. import background_portal, service_ctl
from ..i18n import SYSTEM, available_languages, language_display_name
from ..util import preset_label
from ..widgets import Card, SegmentedControl, section_label, separator
from .settings_form import SettingsFormPage


class SettingsPage(SettingsFormPage):
    def _build_cards(self, outer) -> None:
        # ----- GENERAL -----
        general = Card()
        general.body.addWidget(section_label(self.tr("General")))
        self.language_combo = self._themed_combo()
        # "System default" + a forced "English" (the source language, no
        # catalog needed) + every shipped catalog, self-named.
        self.language_combo.addItem(self.tr("System default"), SYSTEM)
        self.language_combo.addItem("English", "en")
        for code in available_languages():
            self.language_combo.addItem(language_display_name(code), code)
        general.body.addWidget(self._settings_row(
            self.tr("Language"), self.language_combo,
            self.tr("Applies after you restart the app")))
        # Unlike Language, this one applies on Apply: no string is baked at
        # construction for it, so the pages just redraw (see gui/context.py).
        self.units_combo = self._themed_combo()
        self.units_combo.addItem(self.tr("System default"), "system")
        self.units_combo.addItem(self.tr("Centimetres"), "cm")
        self.units_combo.addItem(self.tr("Inches"), "in")
        general.body.addWidget(self._settings_row(
            self.tr("Height units"), self.units_combo,
            self.tr("How heights are shown. The default follows your "
                    "region — the desk itself is unaffected")))
        # Autostart is systemd state, not config, so it is the one control on
        # this page that the footer does not govern — it acts on click. The
        # help line says so, because a staged-looking checkbox that Reset
        # can't undo would be worse than an obviously-immediate one.
        self.autostart_check = QCheckBox()
        self.autostart_check.toggled.connect(self._toggle_autostart)
        self._autostart_row = self._settings_row(
            self.tr("Start automatically at login"), self.autostart_check,
            self.tr("Runs the background service when you log in. Applies "
                    "immediately, not on Apply"))
        general.body.addWidget(self._autostart_row)
        # Only shown when the unit can't be managed from here (masked, not
        # installed, no systemd user manager — e.g. a sandboxed or venv run).
        self._autostart_note = self._muted_label()
        self._autostart_note.setVisible(False)
        general.body.addWidget(self._autostart_note)
        outer.addWidget(general)

        # ----- WINDOW & TRAY -----
        self._tray_card = Card()
        self._tray_card.body.addWidget(section_label(self.tr("Window & tray")))
        # One action per tray-icon gesture. "none" lets a gesture do nothing.
        self._tray_actions = [
            ("window", self.tr("Open window")),
            ("toggle", self.tr("Toggle sit / stand")),
            ("sit", preset_label("sit")),
            ("stand", preset_label("stand")),
            ("none", self.tr("Do nothing")),
        ]
        self.tray_left_combo = self._action_combo()
        self.tray_middle_combo = self._action_combo()
        self._tray_combos = {
            "tray_left_click": self.tray_left_combo,
            "tray_middle_click": self.tray_middle_combo,
        }
        self._tray_card.body.addWidget(self._settings_row(
            self.tr("Left click"), self.tray_left_combo))
        self._tray_card.body.addWidget(self._settings_row(
            self.tr("Middle click"), self.tray_middle_combo))
        self.repeat_move = SegmentedControl(
            [self.tr("Nothing"), self.tr("Stop"), self.tr("Return")])
        # This row sets the whole page's minimum width, so both halves of it
        # are kept short. A SegmentedControl pins each button to its bold text
        # advance and cannot elide, so its labels are a hard floor; and the row
        # title has no word wrap, so it is one too. "Repeat click" also matches
        # the two rows above it. What each segment does is on the help line
        # below, which wraps and therefore costs nothing.
        self._tray_card.body.addWidget(self._settings_row(
            self.tr("Repeat click"), self.repeat_move,
            segment_help=[
                self.tr("A repeat click during a move is ignored"),
                self.tr("Stops the desk where it is"),
                self.tr("Sends the desk back to where the move began"),
            ]))
        self._tray_card.body.addWidget(separator())
        self.close_action = SegmentedControl(
            [self.tr("Hide"), self.tr("Quit")])
        # "Hide" and "Quit" alone drop the "to tray" and "the app" that made
        # the old labels unambiguous. The help line carries them back, and it
        # wraps, so unlike the segments it costs no width.
        self._tray_card.body.addWidget(self._settings_row(
            self.tr("Close button"), self.close_action,
            segment_help=[
                self.tr("Closing the window hides it to the tray"),
                self.tr("Closing the window quits the app"),
            ]))
        self.minimize_tray_check = QCheckBox()
        self._tray_card.body.addWidget(self._settings_row(
            self.tr("Minimize to the tray"), self.minimize_tray_check,
            self.tr("Hide to the tray on minimize, not only on close")))
        self.start_min_check = QCheckBox()
        self._tray_card.body.addWidget(self._settings_row(
            self.tr("Start hidden in the tray"), self.start_min_check,
            self.tr("Launch to the tray without opening the window")))
        self._no_tray_note = self._muted_label(self.tr(
            "No system tray detected, so these have no effect this session."))
        self._no_tray_note.setVisible(not self.ctx.tray_available)
        self._tray_card.body.addWidget(self._no_tray_note)
        outer.addWidget(self._tray_card)

        # ----- DESK CONNECTION -----
        desk = Card()
        desk.body.addWidget(section_label(self.tr("Desk connection")))
        self.mac_edit = QLineEdit()
        # Input mask: type hex only, the colons are drawn and stepped over
        # automatically, each pair auto-advances. '>' forces upper case.
        self.mac_edit.setInputMask(">HH:HH:HH:HH:HH:HH;_")
        self.mac_edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        wizard_btn = QPushButton(self.tr("Find my desk…"))
        wizard_btn.clicked.connect(self._run_wizard)
        mac_row = QHBoxLayout()
        mac_row.setSpacing(8)
        mac_row.addWidget(self.mac_edit, 1)
        mac_row.addWidget(wizard_btn)
        desk.body.addWidget(self._settings_row(
            self.tr("Bluetooth address"), mac_row, stretch_control=True))
        desk.body.addWidget(separator())
        self.connection_mode = SegmentedControl(
            [self.tr("On demand"), self.tr("Persistent")])
        self.connection_mode.currentChanged.connect(self._update_dimming)
        desk.body.addWidget(self._settings_row(
            self.tr("Connection mode"), self.connection_mode,
            self.tr("On demand connects only while moving the desk")))
        self.linger_spin = self._seconds_spin(0, 300)
        self._linger_row = self._settings_row(
            self.tr("Linger after moving"), self.linger_spin)
        desk.body.addWidget(self._linger_row)
        outer.addWidget(desk)

    def _action_combo(self):
        """A tray-gesture action picker."""
        combo = self._themed_combo()
        for value, label in self._tray_actions:
            combo.addItem(label, value)
        return combo

    def _update_dimming(self, *_args) -> None:
        # Native dimming for dependent controls (the mock's .45-opacity
        # pattern): linger only matters on demand.
        self._linger_row.setEnabled(self.connection_mode.currentIndex() == 0)
        # Window/tray settings do nothing without a tray.
        for row in (self.tray_left_combo, self.tray_middle_combo,
                    self.repeat_move, self.close_action,
                    self.minimize_tray_check, self.start_min_check):
            row.setEnabled(self.ctx.tray_available)

    def _load_autostart(self) -> None:
        """Re-read the unit's enabled state from systemd.

        Always read, never cache: the unit can be enabled or disabled from a
        terminal behind our back, so a remembered value would go stale. Signals
        are blocked while setting the box so reloading doesn't look like a
        click and trigger a systemctl call.
        """
        if background_portal.is_flatpak():
            self._load_autostart_flatpak()
            return
        state = service_ctl.autostart_state()
        self.autostart_check.blockSignals(True)
        try:
            self.autostart_check.setChecked(state.on)
        finally:
            self.autostart_check.blockSignals(False)
        # Dim the whole row, matching how this page marks a control that has
        # no effect (see _update_dimming) — the explanatory note below stays at
        # normal contrast so it's still readable.
        self._autostart_row.setEnabled(state.manageable)
        notes = {
            "unavailable": self.tr(
                "systemd isn't managing this session, so this can't be "
                "changed here."),
            "not-found": self.tr(
                "The background service isn't installed, so this can't be "
                "changed here."),
            "masked": self.tr(
                "The service is masked. Allow it again with:\n"
                "  systemctl --user unmask %s") % service_ctl.UNIT,
            "no-install": self.tr(
                "This copy of the service can't be enabled (systemd reports "
                "it as \"%s\").") % state.state,
        }
        note = notes.get(state.problem, "")
        if state.problem and not note:  # e.g. "bad" — still say something
            note = self.tr("systemd reports the service as \"%s\".") % state.state
        self._autostart_note.setText(note)
        self._autostart_note.setVisible(bool(note))

    def _load_autostart_flatpak(self) -> None:
        """Build the toggle from the persisted grant, not a portal readback.

        ``RequestBackground`` and the status setter are the Background
        portal's only two methods — there is no getter for "is autostart
        currently granted?", so the always-read rule the systemd branch above
        follows does not transfer here: there is nothing to read. The config
        flag the portal module persists (``UiConfig.run_at_login``) is the
        only source of truth for what was last granted.
        """
        if self.ctx.cfg is None:
            self.ctx.reload_config()
        config = self.ctx.cfg
        checked = config is not None and config.ui.run_at_login
        self.autostart_check.blockSignals(True)
        try:
            self.autostart_check.setChecked(checked)
        finally:
            self.autostart_check.blockSignals(False)
        self._autostart_row.setEnabled(True)
        self._autostart_note.setText(self.tr(
            "Managed by your desktop's permission dialog, not by systemd."))
        self._autostart_note.setVisible(True)

    def _set_autostart(self, enable_autostart: bool) -> tuple[bool, str]:
        """Call whichever backend owns autostart; persist the Flatpak grant.

        Returns the (ok, error text) contract both backends already share.
        """
        if not background_portal.is_flatpak():
            return service_ctl.set_autostart(enable_autostart)
        succeeded, err = background_portal.set_autostart(enable_autostart)
        if succeeded:
            # The portal has no readback, so the persisted flag is the only
            # record of what was granted — and the one thing every config
            # write in the GUI goes through.
            def _persist_run_at_login(config: AppConfig) -> None:
                config.ui.run_at_login = enable_autostart

            self.ctx.write_config(_persist_run_at_login)
        return succeeded, err

    def _toggle_autostart(self, enable_autostart: bool) -> None:
        succeeded, err = self._set_autostart(enable_autostart)
        if not succeeded:
            QMessageBox.warning(
                self, self.tr("Idasen Companion"),
                self.tr("Could not change whether the service starts at "
                        "login:\n%s") % err)
        elif enable_autostart:
            self._status_message(
                self.tr("The service will start automatically at login."), 4000)
        else:
            # Disabling doesn't stop the running daemon (see service_ctl);
            # say so rather than let the user assume automation just stopped.
            self._status_message(
                self.tr("Autostart off. The service keeps running until you "
                        "log out."), 6000)
        # Re-read either way: on failure this snaps the box back to the truth
        # — a denied grant must never leave the box ticked — and on success it
        # confirms the change actually took effect.
        self._load_autostart()

    def load(self) -> None:
        # Autostart is systemd state, not config, so it is read regardless of
        # whether the config below loads.
        self._load_autostart()
        super().load()

    def _load(self, cfg: AppConfig) -> None:
        self._select_data(self.language_combo, cfg.ui.language)
        self._select_data(self.units_combo, cfg.ui.units)
        for key, combo in self._tray_combos.items():
            self._select_data(combo, getattr(cfg.ui, key))
        self.repeat_move.setCurrentIndex(
            {"off": 0, "stop": 1, "reverse": 2}.get(cfg.ui.tray_repeat_move, 1))
        self.close_action.setCurrentIndex(
            1 if cfg.ui.close_action == "quit" else 0)
        self.minimize_tray_check.setChecked(cfg.ui.minimize_to_tray)
        self.start_min_check.setChecked(cfg.ui.start_minimized)
        self.mac_edit.setText(cfg.desk.mac)
        self.connection_mode.setCurrentIndex(
            1 if cfg.desk.connection == "persistent" else 0)
        self.linger_spin.setValue(cfg.desk.linger)

    def _keep_on_defaults(self, target: AppConfig, source: AppConfig) -> None:
        # The Bluetooth address is which desk is yours, not a preference, and
        # nobody asking for the shipped defaults back means "forget my desk" —
        # that is what Find my desk… is for. Everything else on this page does
        # reset. (Autostart needs no entry here: it's systemd state rather than
        # config, so _load and _apply never see it.)
        target.desk.mac = source.desk.mac

    def _validate(self) -> str | None:
        # The MAC field is masked. A fully-typed address saves as-is, and a
        # completely empty field clears it (see _apply); a half-typed one is a
        # mistake — refuse rather than silently wiping a configured desk.
        if (not self.mac_edit.hasAcceptableInput()
                and any(c in "0123456789abcdefABCDEF"
                        for c in self.mac_edit.text())):
            return self.tr("The Bluetooth address is incomplete. Finish it "
                           "or clear it before applying.")
        return None

    def _apply(self, cfg: AppConfig) -> None:
        cfg.ui.language = self.language_combo.currentData()
        cfg.ui.units = self.units_combo.currentData()
        for key, combo in self._tray_combos.items():
            setattr(cfg.ui, key, combo.currentData())
        cfg.ui.tray_repeat_move = ("off", "stop", "reverse")[
            self.repeat_move.currentIndex()]
        cfg.ui.close_action = (
            "quit" if self.close_action.currentIndex() == 1 else "tray")
        cfg.ui.minimize_to_tray = self.minimize_tray_check.isChecked()
        cfg.ui.start_minimized = self.start_min_check.isChecked()
        # An unacceptable mask here can only be an empty one — _validate has
        # already refused a half-typed address — so this deliberately unsets.
        cfg.desk.mac = (self.mac_edit.text()
                        if self.mac_edit.hasAcceptableInput() else "")
        cfg.desk.connection = ("persistent"
                               if self.connection_mode.currentIndex() == 1
                               else "on-demand")
        cfg.desk.linger = self.linger_spin.value()

    def _run_wizard(self) -> None:
        from ..setup_wizard import SetupWizard

        # The wizard writes the address itself and we reload from disk after
        # it, so running it discards whatever is staged here — the same loss
        # every other way out of this page now asks about first. Reached by
        # duck-typing because importing MainWindow here would be circular.
        confirm = getattr(self.window(), "confirm_unapplied_edits", None)
        if confirm is not None and not confirm():
            return
        wizard = SetupWizard(self.client, self, ctx=self.ctx)
        if wizard.exec():
            self.load()
