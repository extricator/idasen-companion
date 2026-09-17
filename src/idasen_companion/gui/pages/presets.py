"""Presets page: list, capture, rename, delete named desk heights."""

from __future__ import annotations

from ...core.i18n import pgettext

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from ...core.config import MAX_HEIGHT, MIN_HEIGHT
from .. import restyle
from ..theme import css, theme
from ..util import PROTECTED_PRESETS, preset_label, suffix_height
from ..widgets import (
    Card, RangeRail, ToolIconButton, card_scroll, clear_layout, emphasize,
    icon, pill, pill_css, section_label, segment_css, separator, tinted_icon,
)
from .base import Page


class PresetsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self._presets: dict[str, float] = {}
        self._preset_chips: list = []
        self._renaming = False
        self._live_height = 0.0

        self._build()

        self.client.presetsChanged.connect(self._on_presets)
        self.client.heightChanged.connect(self._on_height)
        # A live height is only live while there is a daemon to report it and
        # a link to the desk on the other end of it. Losing either means this
        # page no longer knows where the desk is, and neither loss arrives as
        # a height update — so watch for them directly. On-demand mode drops
        # the link a few seconds after every operation, which makes this the
        # ordinary case rather than a fault.
        self.client.connectedChanged.connect(self._on_connected)
        self.client.availableChanged.connect(self._on_available)
        # Every height on this page is drawn from cached state, so a units
        # change has to redraw them rather than wait for the next update.
        self.ctx.configChanged.connect(self._on_config_changed)

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(8)
        list_card = Card()
        self._presets_empty = QLabel(pgettext('presets', "No presets yet — capture the desk's current height below."))
        self._presets_empty.setWordWrap(True)

        def _restyle_presets_empty(target: QLabel = self._presets_empty) -> None:
            target.setStyleSheet(f"color: {css(theme().muted)}; border: none;")

        restyle.register(self._presets_empty, _restyle_presets_empty)
        scroll, scroll_body = card_scroll()
        self._presets_rows = QVBoxLayout()
        self._presets_rows.setSpacing(0)
        scroll_body.addWidget(self._presets_empty)
        scroll_body.addLayout(self._presets_rows)
        scroll_body.addStretch()
        list_card.body.addWidget(scroll)
        left.addWidget(list_card, 1)

        # Joined two-segment footer strip.
        strip = QHBoxLayout()
        strip.setSpacing(0)
        self._new_at_btn = QPushButton(pgettext('presets', "+ New preset"))
        self._new_at_btn.clicked.connect(self._capture_preset)
        add_btn = QPushButton(pgettext('presets', "✎ Add manually…"))
        add_btn.clicked.connect(self._add_preset)
        for i, btn in enumerate((self._new_at_btn, add_btn)):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

            def _restyle_footer_btn(
                target: QPushButton = btn, first: bool = i == 0,
                last: bool = i == 1,
            ) -> None:
                target.setStyleSheet(
                    segment_css(first, last, padding="5px 12px"))

            restyle.register(btn, _restyle_footer_btn)
            strip.addWidget(btn, 1)
        left.addLayout(strip)
        layout.addLayout(left, 1)

        rail_card = Card()
        rail_card.setFixedWidth(156)
        rail_card.body.addWidget(section_label(pgettext('presets', "Range")))
        self.range_rail = RangeRail(MIN_HEIGHT, MAX_HEIGHT, self.ctx)
        rail_card.body.addWidget(self.range_rail, 1)
        layout.addWidget(rail_card)

    def _make_preset_row(self, name: str, height: float) -> QWidget:
        preset_row = QWidget()
        hbox = QHBoxLayout(preset_row)
        hbox.setContentsMargins(4, 11, 4, 11)
        hbox.setSpacing(6)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        # Protected presets are ours and translate; a user-created one is
        # the user's own word and is shown verbatim.
        display = preset_label(name)
        name_edit = QLineEdit(display)
        name_edit.setToolTip(pgettext('presets', "Click to rename"))
        name_edit.setFont(emphasize(name_edit.font()))

        def _restyle_name_edit(target: QLineEdit = name_edit) -> None:
            tokens = theme()
            target.setStyleSheet(
                "QLineEdit { background: transparent; border: 1px solid"
                " transparent; border-radius: 3px; padding: 2px 4px; }"
                f"QLineEdit:hover {{ border-color: {css(tokens.separator)}; }}"
                f"QLineEdit:focus {{ border-color: {css(tokens.accent_border)};"
                f" background: {css(tokens.card_bg)}; }}")

        restyle.register(name_edit, _restyle_name_edit)
        if name in PROTECTED_PRESETS:
            name_edit.setReadOnly(True)
            name_edit.setToolTip(
                pgettext('presets', "The sit and stand presets keep their names"))
        else:
            name_edit.editingFinished.connect(
                lambda e=name_edit, n=name: self._rename_preset(n, e))
        height_row = QHBoxLayout()
        height_row.setSpacing(6)
        height_label = QLabel(self.ctx.fmt.height(height))

        def _restyle_height_label(target: QLabel = height_label) -> None:
            target.setStyleSheet(
                f"color: {css(theme().secondary)}; border: none;"
                " padding-left: 4px;")

        restyle.register(height_label, _restyle_height_label)
        height_row.addWidget(height_label)
        current_chip = pill(pgettext('presets', "current"), theme().success_text,
                            theme().success)
        current_chip.hide()

        def _restyle_current_chip(target: QLabel = current_chip) -> None:
            target.setStyleSheet(
                pill_css(theme().success_text, theme().success))

        restyle.register(current_chip, _restyle_current_chip)
        height_row.addWidget(current_chip)
        height_row.addStretch()
        text_col.addWidget(name_edit)
        text_col.addLayout(height_row)
        hbox.addLayout(text_col, 1)

        move_btn = ToolIconButton(
            tinted_icon(icon("media-playback-start", "go-next"), theme().accent),
            pgettext('presets', "Drive desk to %s") % self.ctx.fmt.height(height),
            fallback="▶")

        def _restyle_move_btn(target: ToolIconButton = move_btn) -> None:
            target.setIcon(tinted_icon(
                icon("media-playback-start", "go-next"), theme().accent))

        restyle.register(move_btn, _restyle_move_btn)
        move_btn.clicked.connect(lambda _=False, n=name:
                                 self.client.move_to_preset(n))
        set_btn = ToolIconButton(
            icon("crosshairs", "find-location", "zoom-fit-best"),
            pgettext('presets', "Set to current desk height"), fallback="⌖")
        set_btn.clicked.connect(lambda _=False, n=name: self._do_capture(n))
        del_btn = ToolIconButton(
            icon("edit-delete", "user-trash"), pgettext('presets', "Delete preset"),
            fallback="✕")
        del_btn.clicked.connect(lambda _=False, n=name:
                                self._delete_preset(n))
        del_btn.setEnabled(name not in PROTECTED_PRESETS)
        if not del_btn.isEnabled():
            del_btn.setToolTip(
                pgettext('presets', "The sit and stand presets can't be deleted"))
        for btn in (move_btn, set_btn, del_btn):
            hbox.addWidget(btn)
        self._preset_chips.append((height, current_chip))
        return preset_row

    @staticmethod
    def _preset_order(name: str):
        # Protected presets first, in their canonical order; user presets
        # below them, alphabetically.
        if name in PROTECTED_PRESETS:
            return (0, PROTECTED_PRESETS.index(name))
        return (1, name.lower())

    def _on_presets(self, presets: dict) -> None:
        self._presets = dict(presets)
        self.range_rail.set_presets(presets)

        clear_layout(self._presets_rows)
        self._preset_chips = []
        self._presets_empty.setVisible(not presets)
        for i, name in enumerate(sorted(presets, key=self._preset_order)):
            if i:
                self._presets_rows.addWidget(separator())
            self._presets_rows.addWidget(
                self._make_preset_row(name, presets[name]))
        self._update_presets_live()

    def _on_config_changed(self) -> None:
        self._on_presets(self._presets)
        self.range_rail.update()

    def _on_height(self, height: float) -> None:
        if height > 0:
            self._live_height = height
            self._update_presets_live()

    def _on_connected(self, connected: bool) -> None:
        if not connected:
            self._forget_live_height()

    def _on_available(self, available: bool) -> None:
        if not available:
            self._forget_live_height()

    def _forget_live_height(self) -> None:
        """Stop pointing at a height the page can no longer vouch for.

        The presets stay; what goes is the "and the desk is here right now"
        layer drawn over them. Keeping the last reading would be a guess, and
        this is the page where guesses get acted on: the capture button asks
        the daemon for a *fresh* height, so a stale number in its label is a
        claim about a height it will not deliver.
        """
        if self._live_height:
            self._live_height = 0.0
            self._update_presets_live()

    def _update_presets_live(self) -> None:
        height = self._live_height
        # Without a height the button drops back to its plain label, rather
        # than keeping the last one it happened to be given.
        text = (pgettext('presets', "+ New preset at %s") % self.ctx.fmt.height(height)
                if height > 0 else pgettext('presets', "+ New preset"))
        if self._new_at_btn.text() != text:
            self._new_at_btn.setText(text)
        self.range_rail.set_height(height)
        for preset_height, chip in self._preset_chips:
            chip.setVisible(height > 0 and
                            abs(preset_height - height) <= RangeRail.MATCH)

    def _rename_preset(self, old: str, edit: QLineEdit) -> None:
        if self._renaming:   # re-entry guard: dialogs below steal focus
            return
        new_name = edit.text().strip()
        if not new_name or new_name == old or old not in self._presets:
            edit.setText(old)
            return
        self._renaming = True
        try:
            if not self.client.available:
                edit.setText(old)
                self._status_message(
                    pgettext('presets', "The daemon is not running — rename discarded."),
                    5000)
                return
            if new_name in self._presets:
                QMessageBox.information(
                    self, pgettext('presets', "Idasen Companion"),
                    pgettext('presets', "A preset named '%s' already exists.")
                    % html.escape(new_name))
                edit.setText(old)
                return
            # One call, one daemon-side write: the rename either happened or
            # it didn't. There is no state where both names exist to explain
            # to the user, which is why the duplicate-preset path this used to
            # need is gone.
            renamed, err = self.client.rename_preset_sync(old, new_name)
            if not renamed:
                edit.setText(old)
                QMessageBox.warning(
                    self, pgettext('presets', "Idasen Companion"),
                    pgettext('presets', "Could not rename the preset:\n%s")
                    % html.escape(err))
        finally:
            self._renaming = False

    def _do_capture(self, name: str) -> None:
        """Capture current height into ``name``, with visible feedback."""
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            captured, result = self.client.capture_preset(name)
        finally:
            self.unsetCursor()
        if captured and isinstance(result, float):
            self._status_message(
                pgettext('presets', "Preset '%(name)s' set to %(height)s.")
                % {"name": name, "height": self.ctx.fmt.height(result)}, 5000)
        else:
            QMessageBox.warning(
                self, pgettext('presets', "Idasen Companion"),
                pgettext('presets', "Could not read the desk height:\n%s")
                % html.escape(str(result)))

    def _capture_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, pgettext('presets', "Capture preset"),
                                              pgettext('presets', "Preset name:"))
        if accepted and name.strip():
            self._do_capture(name.strip())

    def _add_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, pgettext('presets', "Add preset"),
                                              pgettext('presets', "Preset name:"))
        if not (accepted and name.strip()):
            return
        fmt = self.ctx.fmt
        height, accepted = QInputDialog.getDouble(
            self, pgettext('presets', "Add preset"),
            # The unit as a word, from the spin-box suffix so the two can
            # never disagree — its leading space is for setSuffix, which
            # inserts none, and is not wanted inside a sentence.
            pgettext('presets', "Height (%s):") % suffix_height(fmt.unit).strip(),
            fmt.to_display_height(1.0),
            fmt.to_display_height(MIN_HEIGHT), fmt.to_display_height(MAX_HEIGHT),
            fmt.height_decimals())
        if accepted:
            self.client.save_preset(
                name.strip(), fmt.from_display_height(height))

    def _delete_preset(self, name: str) -> None:
        if name in PROTECTED_PRESETS:
            QMessageBox.information(
                self, pgettext('presets', "Idasen Companion"),
                pgettext('presets', "The sit and stand presets can't be deleted."))
            return
        # A single trash-icon click is easy to hit by mistake and deleting
        # a preset is irreversible (re-creating it needs a live capture),
        # so confirm first.
        if QMessageBox.question(
                self, pgettext('presets', "Delete preset"),
                pgettext('presets', "Delete the preset '%s'?") % html.escape(name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.client.delete_preset(name)
