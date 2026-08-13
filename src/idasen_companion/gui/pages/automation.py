"""Automation page: the sit/stand cycle, its schedule, and its warnings.

How the automation *behaves*, as opposed to how the app is set up (Settings).
Schedule and Notifications live here because both exist only to serve the
cycle — one gates when it runs, the other announces its moves.

The division of labour with Overview: Overview acts on *this* cycle (pause,
skip, snooze, turn on), this page configures *every* cycle.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTimeEdit, QVBoxLayout, QWidget,
)

from ...core.config import AppConfig, VALID_DAYS
from ..util import day_label, fmt_days, fmt_duration
from ..widgets import (
    Card, SegmentedControl, section_label, segment_css, separator,
)
from .settings_form import SettingsFormPage

# Config values behind the interruption-policy segments, in segment order
# (see VALID_INTERRUPTION_POLICIES).
_INTERRUPTION_POLICIES = ("undo", "leave", "retry")

# Offered position-check intervals, in **seconds**, ascending; 0 is "Off".
#
# A short list rather than the free 0-120 minute spin this used to be: it is a
# coarse polling cadence, not a precision knob — the pre-decide read reconciles
# right before every move regardless — so an arbitrary minute count only looked
# more exact than it was.
#
# Nothing faster than 2 min on purpose. Every check is a real on-demand BLE
# connect to a controller that accepts exactly one client, and the case that
# most needs prompt detection already has its own floor: a desk held off sit /
# stand polls at HELD_POLL_INTERVAL (5 min) whatever this says.
_SYNC_CHOICES = (0, 2 * 60, 5 * 60, 10 * 60, 15 * 60, 30 * 60, 60 * 60)

# Offered interval variations, in **seconds**, ascending; 0 is no variation.
#
# A short list rather than the free 0-120 minute spin this used to be, for a
# sharper version of the reason the sync interval got one: the whole point of
# this number is that the interval is *not* exact, so offering it to the minute
# invites care over a value chosen to be careless. machine.py rounds it up to
# whole minutes before use in any case.
#
# 30 min is the ceiling. Past that it stops reading as jitter on a 20-45 minute
# interval and starts being a second duration knob.
_VARIATION_CHOICES = (0, 2 * 60, 5 * 60, 10 * 60, 15 * 60, 20 * 60, 30 * 60)


class AutomationPage(SettingsFormPage):
    def _build_cards(self, outer) -> None:
        # ----- THE CYCLE -----
        auto = Card()
        head = QHBoxLayout()
        head.addWidget(section_label(self.tr("Sit / stand cycle")))
        head.addStretch()
        # The master switch. Off keeps presets, manual moves and statistics
        # working — only the sit/stand timer stops — so the rest of this card
        # dims rather than disappearing.
        self.auto_enabled = QCheckBox(self.tr("Automate sit / stand"))
        self.auto_enabled.toggled.connect(self._update_dimming)
        head.addWidget(self.auto_enabled)
        auto.body.addLayout(head)
        self._auto_details = QWidget()
        auto_details = QVBoxLayout(self._auto_details)
        auto_details.setContentsMargins(0, 0, 0, 0)
        auto_details.setSpacing(0)
        self.sit_dur = self._minutes_spin(1, 480)
        self.stand_dur = self._minutes_spin(1, 480)
        self.sit_var = self._themed_combo()
        self.stand_var = self._themed_combo()

        def interval_row(word: str, dur: QSpinBox, var: QComboBox):
            hbox = QHBoxLayout()
            hbox.setSpacing(6)
            hbox.addWidget(dur)
            # "plus up to", not the "± " this used to read: machine.py adds
            # 0..variation to the baseline and never subtracts, so a ± was
            # promising a shorter interval than the desk will ever wait.
            plus = QLabel(self.tr("plus up to"))
            plus.setStyleSheet("border: none;")
            hbox.addWidget(plus)
            hbox.addWidget(var)
            return self._settings_row(self.tr("%s for") % word, hbox)

        auto_details.addWidget(
            interval_row(self.tr("Sit"), self.sit_dur, self.sit_var))
        auto_details.addWidget(
            interval_row(self.tr("Stand"), self.stand_dur, self.stand_var))
        auto_details.addWidget(separator())
        self.idle_thresh = self._minutes_spin(1, 120)
        auto_details.addWidget(self._settings_row(
            self.tr("Count as away after"), self.idle_thresh,
            self.tr("No keyboard or mouse input — the timer pauses")))
        self.recent_input = self._minutes_spin(0, 60)
        auto_details.addWidget(self._settings_row(
            self.tr("Only move if input within"), self.recent_input,
            self.tr("Skips the change if you just stepped away")))
        auto_details.addWidget(separator())
        # These two rows are the reactions to you taking the desk over yourself:
        # a scheduled move you cut short, and the desk being left off a preset
        # (hold vs keep cycling). Grouped by the surrounding separators rather
        # than a sub-heading (a "Manual control" heading under "Automation"
        # read as a contradiction).
        self.interruption_policy = SegmentedControl(
            [self.tr("Undo"), self.tr("Leave it"), self.tr("Try again")])
        # The label carries the "when" that the old glossary opened with ("when
        # you stop it with the panel, or it hits something"), so dropping to a
        # per-segment line loses nothing.
        auto_details.addWidget(self._settings_row(
            self.tr("If a move is stopped or blocked"), self.interruption_policy,
            segment_help=[
                self.tr("Returns the desk to where it started"),
                self.tr("Keeps the height it stopped at"),
                self.tr("Moves toward the target once more"),
            ]))
        self.ext_policy = SegmentedControl(
            [self.tr("Hold"), self.tr("Keep cycling")])
        auto_details.addWidget(self._settings_row(
            self.tr("If left off sit / stand"), self.ext_policy,
            segment_help=[
                self.tr("Pauses until the desk is back at sit or stand"),
                self.tr("Counts it as the nearer one and keeps going"),
            ]))
        auto.body.addWidget(self._auto_details)
        auto.body.addWidget(separator())
        # Below the dimmed block on purpose: these two keep working with
        # automation off. Position checks are what statistics are attributed
        # to, and the tick they ride on still runs — "off" stops the desk
        # moving, not the app watching.
        self.sync_combo = self._themed_combo()
        auto.body.addWidget(self._settings_row(
            self.tr("Check position every"), self.sync_combo,
            self.tr("Catches moves made with the panel or another app. Off "
                    "still checks right before each scheduled move")))
        self.check_spin = self._seconds_spin(5, 600)
        auto.body.addWidget(self._settings_row(
            self.tr("Update countdown every"), self.check_spin,
            self.tr("How finely automation tracks time, uses no Bluetooth")))
        outer.addWidget(auto)

        # ----- NOTIFICATIONS -----
        # No header switch here, unlike the Cycle and Schedule cards. The two
        # checkboxes are peers — one announces what automation is about to do,
        # the other reports something that went wrong — and a checkbox in the
        # header would read as the card-level master switch it is on those two,
        # putting the fault notices under the announcements. The lead time is
        # the only thing that really is subordinate, so it alone is indented
        # under the checkbox that governs it.
        notif = Card()
        notif.body.addWidget(section_label(self.tr("Notifications")))
        self.notif_enabled = QCheckBox(self.tr("Warn before the desk moves"))
        self.notif_enabled.toggled.connect(self._update_dimming)
        notif.body.addWidget(self.notif_enabled)
        self.lead_spin = self._seconds_spin(5, 300)
        self._lead_row = QWidget()
        lead_col = QVBoxLayout(self._lead_row)
        lead_col.setContentsMargins(20, 0, 0, 0)
        lead_col.setSpacing(0)
        lead_col.addWidget(self._settings_row(
            self.tr("Warning lead time"), self.lead_spin))
        notif.body.addWidget(self._lead_row)
        self.problems_check = QCheckBox(
            self.tr("Tell me when something goes wrong"))
        notif.body.addWidget(self.problems_check)
        outer.addWidget(notif)

        # ----- SCHEDULE -----
        sched = Card()
        head = QHBoxLayout()
        head.addWidget(section_label(self.tr("Schedule")))
        head.addStretch()
        self.sched_enabled = QCheckBox(self.tr("Use schedule"))
        self.sched_enabled.toggled.connect(self._update_dimming)
        head.addWidget(self.sched_enabled)
        sched.body.addLayout(head)

        self._sched_details = QWidget()
        details = QVBoxLayout(self._sched_details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(4)
        days_row = QHBoxLayout()
        days_row.setSpacing(6)
        self.day_checks = {}
        for day in VALID_DAYS:
            chip = QPushButton(day_label(day))
            chip.setCheckable(True)
            chip.setFixedHeight(28)
            chip.setMinimumWidth(40)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(segment_css(first=True, last=True,
                                           padding="3px 9px"))
            chip.toggled.connect(self._update_sched_summary)
            self.day_checks[day] = chip
            days_row.addWidget(chip)
        days_row.addStretch()
        details.addWidget(self._settings_row(self.tr("Active days"), days_row))
        times_row = QHBoxLayout()
        times_row.setSpacing(6)
        self.start_time = QTimeEdit()
        self.end_time = QTimeEdit()
        for edit in (self.start_time, self.end_time):
            edit.setDisplayFormat("HH:mm")
            edit.timeChanged.connect(self._update_sched_summary)
        times_row.addWidget(self.start_time)
        to_label = QLabel(self.tr("to"))
        to_label.setStyleSheet("border: none;")
        times_row.addWidget(to_label)
        times_row.addWidget(self.end_time)
        details.addWidget(self._settings_row(self.tr("Active hours"), times_row))
        sched.body.addWidget(self._sched_details)
        self._sched_summary = self._muted_label()
        sched.body.addWidget(self._sched_summary)
        outer.addWidget(sched)

    def _update_dimming(self, *_args) -> None:
        # Native dimming for dependent controls (the mock's .45-opacity
        # pattern): lead time only with warnings on, days/hours only with the
        # schedule on, the cycle rows only with automation on.
        # The problem-notification checkbox is deliberately absent: it is a
        # peer of the pre-move warning, not something the warning governs.
        self._auto_details.setEnabled(self.auto_enabled.isChecked())
        self._lead_row.setEnabled(self.notif_enabled.isChecked())
        self._sched_details.setEnabled(self.sched_enabled.isChecked())
        self._update_sched_summary()

    def _update_sched_summary(self, *_args) -> None:
        if self.sched_enabled.isChecked():
            days = [d for d, c in self.day_checks.items() if c.isChecked()]
            start = self.start_time.time().toString("HH:mm")
            end = self.end_time.time().toString("HH:mm")
            self._sched_summary.setText(self.tr(
                "Automation runs %s, %s–%s. Outside these hours the desk "
                "stays put.") % (fmt_days(days), start, end))
        else:
            self._sched_summary.setText(self.tr(
                "Schedule off — automation runs whenever you're active."))

    def _interval_label(self, seconds: int, zero_label: str = "") -> str:
        """Item text for one offered interval.

        ``zero_label`` names the 0 entry for rows where a word reads better
        than a number ("Check position every **Off**"). Rows whose label is
        read *through* a connective leave it unset and get "0 min", because
        "plus up to Off" is not a sentence.
        """
        if seconds == 0 and zero_label:
            return zero_label
        if seconds % 60 == 0:
            return self.tr("%d min") % (seconds // 60)
        # Sub-minute: only reachable from a hand-edited config or a test one,
        # and shown as it really is ("30s") rather than rounded into a minute
        # count the user never chose.
        return fmt_duration(seconds)

    def _fill_intervals(self, combo, choices, seconds: int,
                        zero_label: str = "") -> None:
        """Point ``combo`` at ``seconds``, keeping a value that isn't one of
        ``choices`` instead of snapping it to the nearest one.

        A config written by hand — or by an older build, whose spins accepted
        any minute count in a wide range — must survive being looked at. So an
        unknown value is spliced into the list in its sorted place and
        selected; only choosing something else discards it. The list is rebuilt
        from scratch each time so yesterday's one-off doesn't outlive the value
        that caused it.
        """
        values = list(choices)
        if seconds not in values:
            values.append(seconds)
            values.sort()
        combo.clear()
        for value in values:
            combo.addItem(self._interval_label(value, zero_label), value)
        combo.setCurrentIndex(values.index(seconds))

    def _load(self, cfg: AppConfig) -> None:
        self.auto_enabled.setChecked(cfg.automation.enabled)
        self.sit_dur.setValue(cfg.automation.sit_duration // 60)
        self.stand_dur.setValue(cfg.automation.stand_duration // 60)
        self._fill_intervals(self.sit_var, _VARIATION_CHOICES,
                             cfg.automation.sit_variation)
        self._fill_intervals(self.stand_var, _VARIATION_CHOICES,
                             cfg.automation.stand_variation)
        self.idle_thresh.setValue(cfg.automation.idle_threshold // 60)
        self.recent_input.setValue(cfg.automation.recent_input_threshold // 60)
        self.interruption_policy.setCurrentIndex(
            _INTERRUPTION_POLICIES.index(cfg.automation.interruption_policy)
            if cfg.automation.interruption_policy in _INTERRUPTION_POLICIES else 0)
        self.ext_policy.setCurrentIndex(
            1 if cfg.automation.external_move_policy == "adopt" else 0)
        self._fill_intervals(self.sync_combo, _SYNC_CHOICES,
                             cfg.automation.sync_interval, self.tr("Off"))
        self.check_spin.setValue(cfg.automation.check_interval)
        self.sched_enabled.setChecked(cfg.schedule.enabled)
        for day, check in self.day_checks.items():
            check.setChecked(day in cfg.schedule.days)
        start_h, start_m = cfg.schedule.start.split(":")
        end_h, end_m = cfg.schedule.end.split(":")
        self.start_time.setTime(QTime(int(start_h), int(start_m)))
        self.end_time.setTime(QTime(int(end_h), int(end_m)))
        self.notif_enabled.setChecked(cfg.notifications.enabled)
        self.lead_spin.setValue(cfg.notifications.lead_time)
        self.problems_check.setChecked(cfg.notifications.problems)

    def _apply(self, cfg: AppConfig) -> None:
        cfg.automation.enabled = self.auto_enabled.isChecked()
        cfg.automation.sit_duration = self.sit_dur.value() * 60
        cfg.automation.stand_duration = self.stand_dur.value() * 60
        cfg.automation.sit_variation = self.sit_var.currentData()
        cfg.automation.stand_variation = self.stand_var.currentData()
        cfg.automation.idle_threshold = self.idle_thresh.value() * 60
        cfg.automation.recent_input_threshold = self.recent_input.value() * 60
        cfg.automation.interruption_policy = _INTERRUPTION_POLICIES[
            max(0, self.interruption_policy.currentIndex())]
        cfg.automation.external_move_policy = (
            "adopt" if self.ext_policy.currentIndex() == 1 else "yield")
        cfg.automation.sync_interval = self.sync_combo.currentData()
        cfg.automation.check_interval = self.check_spin.value()
        cfg.schedule.enabled = self.sched_enabled.isChecked()
        cfg.schedule.days = [d for d, c in self.day_checks.items()
                             if c.isChecked()]
        cfg.schedule.start = self.start_time.time().toString("HH:mm")
        cfg.schedule.end = self.end_time.time().toString("HH:mm")
        cfg.notifications.enabled = self.notif_enabled.isChecked()
        cfg.notifications.lead_time = self.lead_spin.value()
        cfg.notifications.problems = self.problems_check.isChecked()
