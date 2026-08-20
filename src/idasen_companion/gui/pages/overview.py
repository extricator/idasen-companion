"""Overview page: live desk state, manual control, and automation status."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDoubleSpinBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from ...core.config import MAX_HEIGHT, MIN_HEIGHT
from ...core.machine import COUNTDOWN_STATUSES, RESUMABLE_STATUSES
from .. import restyle
from ..theme import css, theme
from ..util import (
    PROTECTED_PRESETS, connection_state, due_now_label, fmt_countdown,
    fmt_days, fmt_height, from_display_height, height_decimals, height_step,
    position_or_custom, preset_label, snooze_line, status_head, status_label,
    suffix_height, to_display_height,
)
from ..widgets import (
    Card, ConnectionChip, HeightRail, StatusDot, emphasize, equal_height_row,
    icon, primary_button, section_label,
)
from .base import Page


# The machine speaks ``Status``; the wire and this client speak its values.
_RESUMABLE_VALUES = frozenset(s.value for s in RESUMABLE_STATUSES)
_COUNTDOWN_VALUES = frozenset(s.value for s in COUNTDOWN_STATUSES)


class OverviewPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self._remaining = 0.0
        self._status = ""
        self._connected = False
        self._position = ""
        self._moving = False
        self._progress_stamp = time.monotonic()
        # The desk's last reported height in metres, kept so the labels that
        # show it can be redrawn without waiting for the next push.
        self._height = 0.0
        # The height the Move button would send, in metres — the spin box's
        # value in the unit-independent form. Held here rather than read back
        # off the box because changing units reshapes the box, and the target
        # has to survive that. Starts where an untouched box does.
        self._target = MIN_HEIGHT

        self._build()

        # These three already read theme() fresh and recompute their whole
        # output from live instance state -- they are correct restylers that
        # were simply never wired to a palette change.
        restyle.register(self, self._update_connection_chip)
        restyle.register(self, self._render_status)

        # stop_btn's rule is conditional on desk motion, not just a colour,
        # so a restyle must re-run the whole condition rather than reapply
        # whichever branch last happened to be true.
        def _restyle_stop_btn() -> None:
            self._on_moving(self._moving)

        restyle.register(self, _restyle_stop_btn)

        client = self.client
        client.heightChanged.connect(self._on_height)
        client.positionChanged.connect(self._on_position)
        client.connectedChanged.connect(self._on_connected)
        client.movingChanged.connect(self._on_moving)
        client.statusChanged.connect(self._on_status)
        # The deadline arrives a round-trip after the status that implies it,
        # so the first snoozed render says "later" and this redraws it with
        # the time. See DaemonClient.snooze_until.
        client.snoozeUntilChanged.connect(lambda *_: self._render_status())
        client.progressChanged.connect(self._on_progress)
        client.presetsChanged.connect(self._on_presets)
        client.availableChanged.connect(self._on_available)
        self.ctx.configChanged.connect(self._on_config_changed)

        # 1s ticker interpolates the countdown between daemon updates.
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._tick_countdown)
        self._ticker.start(1000)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ----- DESK card (primary) -----
        desk = Card()
        desk.body.addWidget(section_label(self.tr("Desk")))

        header = QHBoxLayout()
        header.setSpacing(10)
        self.position_label = QLabel("—")
        font = self.position_label.font()
        font.setPointSizeF(font.pointSizeF() * 2.0)
        self.position_label.setFont(emphasize(font))
        self.position_label.setStyleSheet("border: none;")
        self.height_label = QLabel("")
        font = self.height_label.font()
        font.setPointSizeF(font.pointSizeF() * 1.45)
        self.height_label.setFont(font)

        def _restyle_height_label(target: QLabel = self.height_label) -> None:
            target.setStyleSheet(f"color: {css(theme().secondary)}; border: none;")

        restyle.register(self.height_label, _restyle_height_label)
        header.addWidget(self.position_label, 0, Qt.AlignmentFlag.AlignBaseline)
        header.addWidget(self.height_label, 0, Qt.AlignmentFlag.AlignBaseline)
        header.addStretch()
        self.connection_chip = ConnectionChip()
        header.addWidget(self.connection_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        desk.body.addLayout(header)

        rail_row = QHBoxLayout()
        rail_row.setSpacing(10)
        self.height_rail = HeightRail(MIN_HEIGHT, MAX_HEIGHT)
        self.height_rail.targetChanged.connect(self._on_rail_target)
        self.height_spin = QDoubleSpinBox()
        self._shape_height_spin()
        self.height_spin.valueChanged.connect(self._on_spin_changed)
        move_btn = primary_button(self.tr("Move"))
        move_btn.setIcon(icon("media-playback-start", "go-next", "arrow-right"))
        move_btn.clicked.connect(
            lambda: self.client.move_to_height(
                from_display_height(self.height_spin.value())))
        # The spin box and Move read as one control pair, so they have to be
        # the same height — and neither height is knowable here. Move is a
        # button and takes the app's own button padding; the spin box is
        # sized entirely by QStyleSheetStyle the moment it is parented into
        # the Card below, which never consults the application style, so no
        # metric the app overrides reaches it. Pinning either to a hint read
        # at construction is exactly what came apart; equal_height_row
        # resolves both at layout time. The Sit / Stand / Stop row below
        # needs none of this: those are buttons beside a button.
        rail_row.addWidget(self.height_rail, 1)
        rail_row.addWidget(
            equal_height_row(self.height_spin, move_btn,
                             spacing=rail_row.spacing()),
            0, Qt.AlignmentFlag.AlignTop)
        desk.body.addLayout(rail_row)

        btn_row = QHBoxLayout()
        sit_btn = QPushButton(
            icon("go-down", "arrow-down", "go-bottom"), preset_label("sit"))
        sit_btn.clicked.connect(self.client.sit)
        stand_btn = QPushButton(
            icon("go-up", "arrow-up", "go-top"), preset_label("stand"))
        stand_btn.clicked.connect(self.client.stand)
        self.stop_btn = QPushButton(
            icon("media-playback-stop", "process-stop"), self.tr("Stop"))
        self.stop_btn.clicked.connect(self.client.stop)
        self.stop_btn.setEnabled(False)
        # Buttons share the row in equal thirds; each keeps its icon+text
        # centred as the window widens (stretch factor grows the cell, the
        # button's default centre alignment keeps the label off the edge).
        for desk_btn in (sit_btn, stand_btn, self.stop_btn):
            btn_row.addWidget(desk_btn, 1)
        desk.body.addLayout(btn_row)
        layout.addWidget(desk)

        # ----- AUTOMATION card (secondary) -----
        auto = Card()
        auto.body.addWidget(section_label(self.tr("Automation")))

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_dot = StatusDot()
        # Emphasised head + plain-coloured reason as two labels (not RichText),
        # so emphasis is a QFont weight like everywhere else.
        self.status_head_lbl = QLabel("—")
        self.status_head_lbl.setFont(emphasize(self.status_head_lbl.font()))
        self.status_head_lbl.setStyleSheet("border: none;")
        self.status_reason = QLabel("")
        self.status_reason.setWordWrap(True)

        def _restyle_status_reason(target: QLabel = self.status_reason) -> None:
            target.setStyleSheet(f"color: {css(theme().secondary)}; border: none;")

        restyle.register(self.status_reason, _restyle_status_reason)
        status_row.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.status_head_lbl, 0)
        status_row.addWidget(self.status_reason, 1)
        auto.body.addLayout(status_row)

        # Countdown block, only visible while automation is active.
        self._countdown_widget = QWidget()
        countdown_col = QVBoxLayout(self._countdown_widget)
        countdown_col.setContentsMargins(0, 0, 0, 0)
        countdown_col.setSpacing(5)
        # Header: "Next: <word>" left, "in <time> of active time" right. The
        # emphasised word/time are DemiBold sub-labels, not RichText <b>, so
        # the whole UI emphasises text the same way.
        self.countdown_next_lbl = QLabel(self.tr("Next:"))
        self.countdown_next_lbl.setStyleSheet("border: none;")
        self.countdown_next_word = QLabel("")
        self.countdown_next_word.setFont(
            emphasize(self.countdown_next_word.font()))
        self.countdown_next_word.setStyleSheet("border: none;")
        self.countdown_in_lbl = QLabel(self.tr("in"))

        def _restyle_countdown_in_lbl(
                target: QLabel = self.countdown_in_lbl) -> None:
            target.setStyleSheet(f"color: {css(theme().secondary)}; border: none;")

        restyle.register(self.countdown_in_lbl, _restyle_countdown_in_lbl)
        self.countdown_time_word = QLabel("")
        self.countdown_time_word.setFont(
            emphasize(self.countdown_time_word.font()))

        def _restyle_countdown_time_word(
                target: QLabel = self.countdown_time_word) -> None:
            target.setStyleSheet(f"color: {css(theme().secondary)}; border: none;")

        restyle.register(self.countdown_time_word, _restyle_countdown_time_word)
        self.countdown_of_lbl = QLabel(self.tr("of active time"))

        def _restyle_countdown_of_lbl(
                target: QLabel = self.countdown_of_lbl) -> None:
            target.setStyleSheet(f"color: {css(theme().secondary)}; border: none;")

        restyle.register(self.countdown_of_lbl, _restyle_countdown_of_lbl)
        cd_header = QHBoxLayout()
        cd_header.setContentsMargins(0, 0, 0, 0)
        cd_header.setSpacing(4)
        cd_header.addWidget(self.countdown_next_lbl)
        cd_header.addWidget(self.countdown_next_word)
        cd_header.addStretch()
        cd_header.addWidget(self.countdown_in_lbl)
        cd_header.addWidget(self.countdown_time_word)
        cd_header.addWidget(self.countdown_of_lbl)
        self.countdown_bar = QProgressBar()
        self.countdown_bar.setTextVisible(False)
        self.countdown_bar.setFixedHeight(4)

        def _restyle_countdown_bar(
                target: QProgressBar = self.countdown_bar) -> None:
            # Both rules live in one string -- a second setStyleSheet call
            # would replace rather than add to the first.
            target.setStyleSheet(
                f"QProgressBar {{ background: {css(theme().separator)};"
                f" border: none; border-radius: 2px; }}"
                f"QProgressBar::chunk {{ background: {css(theme().accent)};"
                f" border-radius: 2px; }}")

        restyle.register(self.countdown_bar, _restyle_countdown_bar)
        self.progress_caption = QLabel("")
        self.progress_caption.setAlignment(Qt.AlignmentFlag.AlignRight)

        def _restyle_progress_caption(
                target: QLabel = self.progress_caption) -> None:
            target.setStyleSheet(f"color: {css(theme().muted)}; border: none;")

        restyle.register(self.progress_caption, _restyle_progress_caption)
        countdown_col.addLayout(cd_header)
        countdown_col.addWidget(self.countdown_bar)
        countdown_col.addWidget(self.progress_caption)
        self._countdown_widget.hide()
        auto.body.addWidget(self._countdown_widget)

        # Pause / Skip / Snooze act on a running timer, so the whole row is
        # swapped out (not just disabled) when automation is off, replaced by
        # the one control that state needs: a way out of it. "Turn off" rides
        # along in the row so the switch works both ways from here — offering
        # only the way back on made this a one-way door.
        self._cycle_controls = QWidget()
        cycle_row = QHBoxLayout(self._cycle_controls)
        cycle_row.setContentsMargins(0, 0, 0, 0)
        self.pause_btn = QPushButton(
            icon("media-playback-pause"), self.tr("Pause"))
        self.pause_btn.clicked.connect(self._toggle_pause)
        skip_btn = QPushButton(
            icon("media-skip-forward", "media-seek-forward", "go-next-skip"),
            self.tr("Skip next"))
        skip_btn.clicked.connect(self.client.skip_next)
        snooze_btn = QPushButton(
            icon("alarm", "chronometer", "clock", "appointment-soon"),
            self.tr("Snooze 10 min"))
        snooze_btn.clicked.connect(lambda: self.client.snooze(10))
        # Deliberately not a stop/pause icon: this isn't a stronger Pause, it's
        # a different kind of thing — a durable preference rather than a
        # "not right now". No confirmation, since the state announces itself
        # and the button to undo it appears in the same spot.
        disable_btn = QPushButton(
            icon("process-stop", "media-playback-stop"), self.tr("Turn off"))
        disable_btn.clicked.connect(
            lambda: self.client.set_automation_enabled(False))
        for cycle_btn in (self.pause_btn, skip_btn, snooze_btn, disable_btn):
            cycle_row.addWidget(cycle_btn, 1)
        auto.body.addWidget(self._cycle_controls)

        self.enable_btn = QPushButton(
            icon("media-playback-start"), self.tr("Turn on automation"))
        self.enable_btn.clicked.connect(
            lambda: self.client.set_automation_enabled(True))
        self.enable_btn.hide()
        auto.body.addWidget(self.enable_btn)

        self.idle_provider_label = QLabel()

        def _restyle_idle_provider_label(
                target: QLabel = self.idle_provider_label) -> None:
            target.setStyleSheet(f"color: {css(theme().muted)}; border: none;")

        restyle.register(self.idle_provider_label, _restyle_idle_provider_label)
        auto.body.addWidget(self.idle_provider_label)
        layout.addWidget(auto)
        layout.addStretch()

    def _shape_height_spin(self) -> None:
        """Range, step, precision and suffix for the current height unit.

        Decimals first: Qt rounds the range to whatever precision is set at
        the time, and the inch minimum (24.409") needs two places to land
        inside the desk's travel rather than below it.

        Called again when the unit changes, so the box is reshaped in place
        and re-seeded with the target it already held — the number changes,
        the height it means does not.
        """
        spin = self.height_spin
        spin.blockSignals(True)
        try:
            spin.setDecimals(height_decimals())
            spin.setRange(to_display_height(MIN_HEIGHT),
                          to_display_height(MAX_HEIGHT))
            spin.setSingleStep(height_step())
            spin.setSuffix(suffix_height())
            spin.setValue(to_display_height(self._target))
        finally:
            spin.blockSignals(False)

    def _set_spin_height(self, meters: float) -> None:
        """Show ``meters`` in the spin box without it reading as a user edit —
        the box's own valueChanged is what moves the rail the other way."""
        self.height_spin.blockSignals(True)
        try:
            self.height_spin.setValue(to_display_height(meters))
        finally:
            self.height_spin.blockSignals(False)

    def _on_rail_target(self, meters: float) -> None:
        self._target = meters
        self._set_spin_height(meters)

    def _on_spin_changed(self, value: float) -> None:
        self._target = from_display_height(value)
        self.height_rail.set_target(self._target)

    def _toggle_pause(self) -> None:
        if self._status in _RESUMABLE_VALUES:
            self.client.resume()
        else:
            self.client.pause()

    # ----- live updates -----

    def _on_available(self, available: bool) -> None:
        if available:
            self.idle_provider_label.setText(
                self.tr("Idle detection: %s") % self.client.idle_provider())
        self._update_connection_chip()

    def _on_height(self, height: float) -> None:
        if height <= 0:
            return
        self._height = height
        self.height_label.setText(fmt_height(height))
        self.height_rail.set_height(height)
        # While idle the proposed target follows the desk; while moving,
        # or while the user is adjusting it, it stays put.
        if (not self._moving and not self.height_rail.dragging()
                and not self.height_spin.hasFocus()):
            self._target = height
            self.height_rail.set_target(height)
            self._set_spin_height(height)

    def _on_position(self, position: str) -> None:
        self._position = position
        self._update_position_word()

    def _on_connected(self, connected: bool) -> None:
        self._connected = connected
        self._update_connection_chip()

    def _on_config_changed(self) -> None:
        self._update_connection_chip()
        self._render_status()
        # The height unit may have changed with it. Everything else on this
        # page repaints on its own next update; the spin box is configured
        # once at construction, so it needs telling.
        self._shape_height_spin()
        if self._height > 0:
            self.height_label.setText(fmt_height(self._height))
        self.height_rail.update()

    def _update_connection_chip(self) -> None:
        color, _footer, chip = connection_state(
            theme(), self._connected, self.client.available, self.ctx.persistent)
        self.connection_chip.set_state(color, chip)

    def _on_moving(self, moving: bool) -> None:
        self._moving = moving
        tokens = theme()
        self.stop_btn.setEnabled(moving)
        self.stop_btn.setStyleSheet(
            f"color: {css(tokens.error)}; font-weight: 600;" if moving else "")
        self._update_position_word()

    def _update_position_word(self) -> None:
        self.position_label.setText(
            self.tr("Moving…") if self._moving
            # Empty position = held off sit/stand; the real height still shows
            # beside this, so name it "Custom" rather than a bare dash.
            else position_or_custom(self._position))

    def _on_presets(self, presets: dict) -> None:
        self.height_rail.set_marks(
            [(preset_label(name), presets[name])
             for name in PROTECTED_PRESETS if name in presets])

    def _on_status(self, status: str) -> None:
        self._status = status
        self._render_status()

    def _render_status(self) -> None:
        tokens = theme()
        status = self._status
        config = self.ctx.cfg
        if status == "active":
            color, head = tokens.success, status_head(status)
            reason = self.tr("alternating sit / stand while you're at the desk")
        elif status == "paused":
            color, head = tokens.warning, status_head(status)
            reason = self.tr("the desk won't move until you resume")
        elif status == "snoozed":
            color, head = tokens.warning, snooze_line(self.client.snooze_until())
            reason = self.tr("automation resumes on its own")
        elif status == "user-idle":
            mins = config.automation.idle_threshold // 60 if config else 10
            color, head = tokens.muted, status_head(status)
            reason = self.tr(
                "no input for %s min — the timer is paused") % mins
        elif status == "away":
            color, head = tokens.muted, status_head(status)
            reason = self.tr(
                "switched to another user or console — the timer is paused "
                "until you're back")
        elif status == "locked":
            color, head = tokens.muted, status_head(status)
            reason = self.tr("the timer is paused until you're back")
        elif status == "out-of-schedule":
            if config:
                sched = self.tr("runs %s %s–%s") % (
                    fmt_days(config.schedule.days), config.schedule.start,
                    config.schedule.end)
            else:
                sched = self.tr("runs on a schedule")
            color, head = tokens.muted, status_head(status)
            reason = self.tr("%s — the desk stays put") % sched
        elif status == "disabled":
            color, head = tokens.muted, status_head(status)
            reason = self.tr(
                "presets and manual moves still work")
        elif status == "held":
            color, head = tokens.warning, status_head(status)
            reason = self.tr(
                "the desk was moved off sit / stand — automation resumes "
                "when it's back at a preset")
        elif status == "move-failed":
            color, head = tokens.error, status_head(status)
            reason = self.tr(
                "the desk couldn't be reached — the cycle keeps running "
                "and will try again")
        else:
            color, head, reason = tokens.muted, status_label(status), ""
        self.status_dot.set_color(color)
        self.status_head_lbl.setText(head)
        self.status_reason.setText(f"— {reason}" if reason else "")
        # A failed move doesn't stop the cycle (a fresh one starts right
        # after), so hiding the countdown here would remove information
        # exactly when the user needs it most.
        self._countdown_widget.setVisible(status in _COUNTDOWN_VALUES)
        disabled = status == "disabled"
        self._cycle_controls.setVisible(not disabled)
        self.enable_btn.setVisible(disabled)
        paused = status in _RESUMABLE_VALUES
        self.pause_btn.setText(self.tr("Resume") if paused else self.tr("Pause"))
        self.pause_btn.setIcon(icon("media-playback-start") if paused
                               else icon("media-playback-pause"))

    def _on_progress(self, active_time: float, target: float) -> None:
        self._remaining = max(0.0, target - active_time)
        self._progress_stamp = time.monotonic()
        self.countdown_bar.setMaximum(max(1, int(target)))
        self._update_countdown_text()

    def _tick_countdown(self) -> None:
        if self._status in _COUNTDOWN_VALUES and self._remaining > 0:
            elapsed = time.monotonic() - self._progress_stamp
            shown = max(0.0, self._remaining - elapsed)
            self._update_countdown_text(shown)

    def _update_countdown_text(self, remaining: float | None = None) -> None:
        remaining = self._remaining if remaining is None else remaining
        next_pos = {"sitting": preset_label("stand"),
                    "standing": preset_label("sit")}.get(self._position)
        self.countdown_next_lbl.setText(self.tr("Next:") if next_pos else "")
        self.countdown_next_word.setText(next_pos or self.tr("Next change"))
        # A cycle with nothing left on the clock is *due*, not stalled: the
        # move is waiting on the next tick (and on the recent-input gate), and
        # a countdown parked at "in 0:00 of active time" reads as frozen. Most
        # visible after saving a shorter interval than the time already
        # accumulated, which lands the cycle at zero the moment it reloads.
        # Rounded the same way fmt_countdown rounds, so "0:00" is never shown.
        due = int(remaining) <= 0
        self.countdown_in_lbl.setVisible(not due)
        self.countdown_of_lbl.setVisible(not due)
        self.countdown_time_word.setText(
            due_now_label() if due else fmt_countdown(remaining))
        total = self.countdown_bar.maximum()
        elapsed = max(0, min(total, int(total - remaining)))
        self.countdown_bar.setValue(elapsed)
        self.progress_caption.setText(
            self.tr("%s%% of this interval elapsed")
            % (elapsed * 100 // total))
