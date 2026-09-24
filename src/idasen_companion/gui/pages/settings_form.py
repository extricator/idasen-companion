"""Shared scaffolding for the settings-class pages.

Two pages are forms over ``config.toml`` — Settings (how the app is set up)
and Automation (how the cycle behaves). They share their whole shape: a
scrolling column of ``Card``s, label-plus-control rows, and a button footer
that commits the page through :meth:`AppContext.write_config`. Only the cards
differ, so that shape lives here and each page supplies:

- ``_build_cards(outer)`` — add its ``Card``s to the scrolling column
- ``_load(config)`` — copy config into its widgets
- ``_apply(config)`` — copy its widgets back onto config
- ``_update_dimming()`` — re-evaluate which of its rows are live
- ``_validate()`` — optionally refuse the apply with a message
- ``_keep_on_defaults(target, source)`` — fields Restore Defaults must not touch

**Editing is staged, and the footer is a ``QDialogButtonBox``.** This follows
the settings dialogs of mainstay Qt apps (Okular, Konsole): edits accumulate in
the widgets and land only when you press Apply, and Apply lights up only once
something has actually changed. Three buttons:

- **Apply** — write this page's fields through ``AppContext.write_config``
- **Reset** — throw the staged edits away and re-read from disk
- **Restore Defaults** — stage the ``core.config`` dataclass defaults, so
  Reset can still undo it before anything is written

They are a button *box* rather than a hand-laid row on purpose. We declare
roles and Qt's current style decides the placement, which is what keeps the
app from hardcoding one desktop's convention: ``KdeLayout`` and ``GnomeLayout``
put Reset and Restore Defaults at the leading end with Apply at the trailing
one, ``MacLayout`` groups all three at the leading end. The labels come from
Qt's own ``qtbase`` catalog (installed in ``gui/i18n.py``), so they are
translated everywhere Qt is without an entry in ours.

**The footer sits outside the scroll area**, so the cards scroll under a
stationary button row. Both pages are taller than the window's 600px minimum,
which would otherwise put the commit action permanently below the fold —
something to go looking for rather than something to hand. Its right inset
tracks the scrollbar so its edge stays over the cards' edge, not the
scrollbar's track.

There is deliberately no OK and no Cancel. Both are dialog verbs — "apply and
*close*", "discard and *close*" — and these are pages in the main window's
stack, with nothing to close. Cancel's discard half is Reset; its close half
has no meaning here.

Apply is explicit and per-page, deliberately: each page commits only its own
fields, so the pages never fight over one another's unsaved edits. Greying the
footer back out *is* the confirmation that the write happened, which is why
there is no "Settings saved." message.
"""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtWidgets import (
    QComboBox, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QSpinBox,
    QVBoxLayout, QWidget,
)

from ...core.config import AppConfig, format_config_warning
from ...core.i18n import pgettext
from ...core.i18n import MessageKey, P_
from ..theme import css, theme
from .. import restyle, util
from ..widgets import icon, page_scroll, separator
from .base import Page

# Signals that mean "the user touched an input", most specific first — one
# connection per widget is enough to keep the footer's enabled state honest.
# Ordering matters for the one overlap in the list: a QSpinBox has
# ``textChanged`` as well as ``valueChanged``, so ``valueChanged`` must come
# first. (``currentTextChanged`` is deliberately not a member — it would
# create a second overlap, with ``currentIndexChanged``.)
_CHANGE_SIGNALS = ("currentChanged", "currentIndexChanged", "valueChanged",
                   "timeChanged", "toggled", "textChanged")


def _tr(text: MessageKey) -> str:
    """Translate one deferred settings-form key through the current catalog."""
    return pgettext(text.context, text)


class SettingsFormPage(Page):
    """A page that reads and writes ``config.toml``."""

    def __init__(self, ctx):
        super().__init__(ctx)
        # Set while the widgets are being filled from config, so the change
        # signals that fires don't read as the user editing the page.
        self._loading = False
        # What the widgets said at the last load or successful Apply. "Dirty"
        # is measured against this rather than against the config on disk —
        # see is_dirty for why the two are not the same question.
        self._baseline = None
        self._build()

    def on_shown(self) -> None:
        # Reload from disk when the page is opened, so external changes
        # (setup wizard, hand edits, the other settings page) are never
        # overwritten by Save.
        #
        # Never over staged edits, though: load() rebases, so it would throw
        # them away. Navigating here can't hit that — leaving a dirty page is
        # gated on settling it, so the page is clean on arrival — but being
        # *shown* is not the same as being navigated to. Hiding to the tray
        # deliberately keeps unapplied edits (MainWindow.confirm_unapplied_edits),
        # and reopening the window re-runs on_shown for whatever page you left
        # on, which without this guard would silently discard them.
        if not self.is_dirty():
            self.load()

    # ================= shape =================

    def _build(self) -> None:
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        scroll, outer = page_scroll()
        wrapper.addWidget(scroll)

        self._build_cards(outer)
        outer.addStretch()
        # Before the footer exists, so its own buttons aren't mistaken for
        # page inputs.
        self._watch_inputs()

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.RestoreDefaults
            | QDialogButtonBox.StandardButton.Reset
            | QDialogButtonBox.StandardButton.Apply)
        self._apply_btn = button_box.button(QDialogButtonBox.StandardButton.Apply)
        self._reset_btn = button_box.button(QDialogButtonBox.StandardButton.Reset)
        self._defaults_btn = button_box.button(
            QDialogButtonBox.StandardButton.RestoreDefaults)
        self._defaults_btn.setIcon(icon("view-refresh", "view-refresh-symbolic"))
        self._reset_btn.setIcon(icon("edit-undo", "edit-undo-symbolic"))
        # Apply is left bare: the semantically obvious candidate does not
        # exist in every icon theme, and the one that does exist everywhere
        # means "selection", not "confirm" -- a wrong glyph reads worse than
        # none.
        self._apply_btn.clicked.connect(self._apply_settings)
        self._reset_btn.clicked.connect(self.load)
        self._defaults_btn.clicked.connect(self._restore_defaults)
        # Plain, non-default buttons: Breeze tints the default button with the
        # accent colour, which read as an unwanted blue.
        self._apply_btn.setDefault(False)
        self._apply_btn.setAutoDefault(False)

        # Outside the scroll area, so the footer is stationary and the cards
        # scroll under it. Both pages are taller than the window's 600px
        # minimum, so a footer inside the scroll is one the user has to go
        # looking for — and Qt's own convention (QDialog, and the settings
        # dialogs of Okular and Konsole) is a button box the content can never
        # push off screen. The design mock draws it inline, but that is a
        # static prototype where everything fits, and the handoff asks for
        # toolkit conventions over pixel-matching.
        self._footer = QWidget()
        footer_col = QVBoxLayout(self._footer)
        footer_col.setContentsMargins(0, 6, 4, 0)
        footer_col.setSpacing(6)
        footer_col.addWidget(separator())
        footer_col.addWidget(button_box)
        wrapper.addWidget(self._footer)
        # Keep the footer's right edge over the cards' rather than over the
        # scrollbar's track. Driven by rangeChanged, and tested with maximum()
        # rather than isVisible() because the bar's visibility hasn't settled
        # when the range is what changed.
        self._scroll = scroll
        scroll.verticalScrollBar().rangeChanged.connect(self._sync_footer_inset)
        self._sync_footer_inset()
        self._refresh_buttons()

    def _sync_footer_inset(self, *_args) -> None:
        bar = self._scroll.verticalScrollBar()
        extent = bar.sizeHint().width() if bar.maximum() > 0 else 0
        # Set in the constructor; layout() is Optional only because a bare
        # QWidget need not have one.
        layout = self._footer.layout()
        if layout is not None:
            layout.setContentsMargins(0, 6, extent + 4, 0)

    def _build_cards(self, outer: QVBoxLayout) -> None:
        """Add this page's Cards to the scrolling column."""
        raise NotImplementedError

    def _watch_inputs(self) -> None:
        """Re-evaluate the footer whenever any input on the page changes.

        Walks the page rather than asking each card to wire itself up: the two
        pages between them hold spin boxes, combos, checkboxes, segmented
        controls, time edits, a line edit and the schedule's checkable day
        chips, and a list that has to be extended by hand is a list that gets
        forgotten when a card gains a row.

        Controls that aren't config — the autostart checkbox — need no
        exclusion: ``_apply`` doesn't write them, so a change simply recomputes
        the same answer.
        """
        for widget in self.findChildren(QWidget):
            for name in _CHANGE_SIGNALS:
                signal = getattr(widget, name, None)
                if signal is not None and hasattr(signal, "connect"):
                    signal.connect(self._on_input_changed)
                    break

    def _on_input_changed(self, *_args) -> None:
        if not self._loading:
            self._refresh_buttons()

    # ================= row / control helpers =================

    @staticmethod
    def _settings_row(label: str, control, help_text: str | None = None,
                      stretch_control: bool = False,
                      segment_help: list[str] | None = None) -> QWidget:
        """One card row: label (+ small help line) left, control right.

        ``segment_help`` gives one short line *per segment* of a
        ``SegmentedControl``, and the help line shows only the selected one,
        swapping as the selection changes. The alternative -- one static line
        glossing every segment -- is what these rows used to carry, and its
        length grows with the segment count: the three-way interruption policy
        reached 180 characters, the longest string in the app.

        Describing only the selection keeps that at one clause however many
        segments there are, and keeps the text *visible*, which is the part
        that matters. Tooltips were the obvious alternative and are ruled out:
        GNOME, KDE, Apple and Microsoft all restrict tooltips to supplemental
        content, and these lines are what you choose *from*. Qt's ``QToolTip``
        also fails WCAG 2.1 SC 1.4.13 -- it auto-hides on a timer and can't be
        hovered -- and never appears on a touch screen at all.

        The accepted cost is that the segments can't all be compared without
        clicking through them. That is a fair trade for a setting chosen once.
        """
        row_widget = QWidget()
        hbox = QHBoxLayout(row_widget)
        hbox.setContentsMargins(0, 4, 0, 4)
        hbox.setSpacing(12)
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        title = QLabel(label)
        title.setStyleSheet("border: none;")
        text_col.addWidget(title)
        if help_text or segment_help:
            help_label = QLabel(help_text or "")
            help_label.setWordWrap(True)

            def _restyle_help_label(target: QLabel = help_label) -> None:
                target.setStyleSheet(f"color: {css(theme().muted)}; border: none;")

            restyle.register(help_label, _restyle_help_label)
            font = help_label.font()
            font.setPointSizeF(font.pointSizeF() * 0.88)
            help_label.setFont(font)
            text_col.addWidget(help_label)
        if segment_help:
            def show_selected(*_args) -> None:
                index = control.currentIndex()
                text = (segment_help[index]
                        if 0 <= index < len(segment_help) else "")
                help_label.setText(text)
                # A help line that swaps is exactly the case a screen reader
                # misses, since nothing ties the label to the control. Mirror
                # it onto the control, where it is announced with it.
                control.setAccessibleDescription(text)

            control.currentChanged.connect(show_selected)
            show_selected()
        hbox.addLayout(text_col, 1)
        if isinstance(control, QWidget):
            hbox.addWidget(control, 1 if stretch_control else 0)
        else:
            hbox.addLayout(control)
        return row_widget

    @staticmethod
    def _minutes_spin(minimum: int, maximum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        # util.suffix_minutes() names its own translation context as a
        # literal, so it works from a @staticmethod on this base class —
        # neither an immediate lookup nor the base-class context trap
        # docstring's _tr) applies to it.
        spin.setSuffix(util.suffix_minutes())
        return spin

    @staticmethod
    def _seconds_spin(minimum: int, maximum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSuffix(util.suffix_seconds())
        return spin

    @staticmethod
    def _themed_combo() -> QComboBox:
        """A combo whose popup is themed like the card it sits in.

        A ``Card`` sets a stylesheet, which makes Qt render *all* its children
        through ``QStyleSheetStyle``; under that a ``QComboBox`` popup draws
        with no background at all. Give the popup view an explicit surface.
        The frame itself is deliberately not named here: the application's
        own installed style now draws it, and naming a border on a
        ``QComboBox`` in a per-widget stylesheet would hand this one widget's
        whole box model back to the stylesheet engine, taking it off Fusion's
        again -- the padding-too-tight regression this dropdown was the named
        example of.

        The highlighted row is the desktop's own selection pair at full
        strength rather than anything derived, for the reason ``theme.py``
        records above ``selection_text``: a list of options with one of
        them picked out is the case the user has a reference for in every
        other application they run.
        """
        combo = QComboBox()

        def _restyle_combo(target: QComboBox = combo) -> None:
            tokens = theme()
            target.setStyleSheet(
                f"QComboBox QAbstractItemView {{"
                f" background-color: {css(tokens.card_bg)};"
                f" color: {css(tokens.text)};"
                f" border: 1px solid {css(tokens.border)};"
                f" selection-background-color: {css(tokens.accent)};"
                f" selection-color: {css(tokens.selection_text)}; }}")

        restyle.register(combo, _restyle_combo)
        return combo

    @staticmethod
    def _select_data(combo: QComboBox, value) -> None:
        """Point ``combo`` at the item carrying ``value``.

        A value this build doesn't offer — hand-written, or left behind by a
        newer one — selects the first entry rather than leaving the combo on
        whatever it happened to be showing.
        """
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _muted_label(self, text: str = "") -> QLabel:
        """A wrapped, secondary-colour note line."""
        label = QLabel(text)
        label.setWordWrap(True)

        def _restyle_label(target: QLabel = label) -> None:
            target.setStyleSheet(f"color: {css(theme().muted)}; border: none;")

        restyle.register(label, _restyle_label)
        return label

    # ================= load / save =================

    def load(self) -> None:
        err = self.ctx.reload_config()
        if err is not None:  # ConfigError — show but keep the UI usable
            QMessageBox.warning(
                self, _tr(P_("settings-form", "Idasen Companion")),
                _tr(P_("settings-form", "Could not read config:\n%s")) % err)
            return
        config = self.ctx.cfg
        if config is None:
            # Unreachable: reload_config sets cfg whenever it returns None.
            # Narrowed rather than asserted so -O cannot remove the guard.
            return
        self._fill(config, rebase=True)
        if config.warnings:
            QMessageBox.warning(
                self, _tr(P_("config-warning", "Idasen Companion")),
                _tr(P_(
                    "config-warning",
                    "Some configuration settings are not recognized by this "
                    "version. They will be preserved:\n%s"))
                % "\n".join(format_config_warning(warning)
                             for warning in config.warnings))

    def _fill(self, config: AppConfig, rebase: bool) -> None:
        """Put ``config`` into the widgets without it counting as an edit.

        ``rebase`` says whether this becomes the new "unedited" state. A load
        does; staging the defaults does not, or Restore Defaults would leave
        the page looking as though it had nothing to apply.
        """
        self._loading = True
        try:
            self._load(config)
            self._update_dimming()
        finally:
            self._loading = False
        if rebase:
            self._baseline = self._staged_config()
        self._refresh_buttons()

    def _apply_settings(self) -> None:
        # config only exists once a load has succeeded; retry before writing
        # so a config that was unreadable at startup can't crash Apply.
        if self.ctx.cfg is None:
            self.load()
            if self.ctx.cfg is None:
                return
        title = _tr(P_("settings-form", "Idasen Companion"))
        invalid = self._validate()
        if invalid is not None:
            QMessageBox.warning(self, title, invalid)
            return
        err = self.ctx.write_config(self._apply)
        if err is not None:
            QMessageBox.warning(
                self, title,
                _tr(P_("settings-form", "Could not save config:\n%s")) % err)
            # Deliberately *not* rebased. write_config mutates config before it
            # tries to save, so after a failure the in-memory config already
            # holds the values that never reached the disk — measuring dirt
            # against it would grey the footer out and report a save that did
            # not happen, leaving no way to retry.
            self._refresh_buttons()
            return
        # Success: this is the new unedited state, and the footer greying out
        # is the confirmation.
        self._baseline = self._staged_config()
        self._refresh_buttons()

    # ================= footer state =================

    def _staged_config(self):
        """The config this page's widgets currently describe."""
        config = deepcopy(self.ctx.cfg)
        self._apply(config)
        return config

    def _defaults_config(self) -> AppConfig:
        """A pristine config, minus the fields Restore Defaults must not touch.

        Sourced from the *staged* config rather than the saved one so that
        restoring defaults leaves a field it doesn't govern — the Bluetooth
        address — exactly as the user currently has it, edited or not.
        """
        fresh = AppConfig()
        self._keep_on_defaults(fresh, self._staged_config())
        return fresh

    def is_dirty(self) -> bool:
        """Whether the page holds edits that Apply has not written yet.

        Measured against what the widgets said when they were last loaded,
        **not** against the config on disk. The two differ because the widgets
        can't always represent a config exactly, and comparing across that gap
        reports edits nobody made: a minute spin box shown a
        ``recent_input_threshold`` of ``"90s"`` can only offer 1 min and would
        apply 60; the day chips rebuild ``schedule.days`` in weekday order, so
        a hand-written ``["fri", "mon"]`` comes back reordered; ``QTimeEdit``
        normalises ``"9:00"`` to ``"09:00"``; and the address field's input
        mask upper-cases a lower-case MAC. Each of those is a *valid* config
        file, and each used to light Apply on a page the user had never
        touched — and then, once leaving a dirty page was gated, raise the
        unapplied-edits prompt on every single navigation.
        """
        if self.ctx.cfg is None or self._baseline is None:
            return False
        return self._staged_config() != self._baseline

    def apply_edits(self) -> bool:
        """Write the staged edits. False if validation or the write refused.

        For the shell, which offers to apply on the way out of a dirty page.
        """
        self._apply_settings()
        return not self.is_dirty()

    def discard_edits(self) -> None:
        """Throw the staged edits away — what Reset does."""
        self.load()

    def _at_defaults(self) -> bool:
        # Compare two configs that start from the same base and differ only in
        # the fields this page owns, since _apply writes exactly those. Anything
        # the page doesn't touch cancels out on both sides.
        fresh = self._defaults_config()
        probe = deepcopy(fresh)
        self._apply(probe)
        return probe == fresh

    def _refresh_buttons(self) -> None:
        if self.ctx.cfg is None:
            for button in (self._apply_btn, self._reset_btn,
                           self._defaults_btn):
                button.setEnabled(False)
            return
        dirty = self.is_dirty()
        self._apply_btn.setEnabled(dirty)
        self._reset_btn.setEnabled(dirty)
        self._defaults_btn.setEnabled(not self._at_defaults())

    def _restore_defaults(self) -> None:
        """Stage the shipped defaults. Nothing is written until Apply."""
        if self.ctx.cfg is None:
            return
        self._fill(self._defaults_config(), rebase=False)

    # ================= page hooks =================

    def _load(self, config: AppConfig) -> None:
        """Copy ``config`` into this page's widgets."""
        raise NotImplementedError

    def _apply(self, config: AppConfig) -> None:
        """Copy this page's widgets onto ``config``. Runs inside write_config."""
        raise NotImplementedError

    def _keep_on_defaults(self, target: AppConfig, source: AppConfig) -> None:
        """Copy the fields Restore Defaults must leave alone, target ← source.

        Defaults are a preference reset, not a factory wipe: a field that
        identifies *this* user's hardware isn't something anyone means to clear
        by asking for the shipped defaults back. Nothing by default.
        """

    def _validate(self) -> str | None:
        """Return a message to refuse the apply with, or None to go ahead."""
        return None

    def _update_dimming(self, *_args) -> None:
        """Re-evaluate which rows are live. Called after every load."""
