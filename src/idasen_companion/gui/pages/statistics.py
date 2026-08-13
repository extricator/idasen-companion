"""Statistics page: daily sit/stand totals and recent transitions."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..theme import css, theme
from ..util import (
    fmt_day_and_clock, fmt_day_label, position_label, trigger_label,
)
from ..widgets import (
    Card, DailyBarsChart, StatusDot, card_scroll, clear_layout, pill,
    section_label, separator,
)
from .base import Page


class StatisticsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self._build()

        # Initial data is driven by MainWindow (availableChanged + refresh_all)
        # once every page is constructed; here we only subscribe.
        self.client.transitionCompleted.connect(self._on_transition_completed)
        self.client.availableChanged.connect(self._on_available)

    def on_shown(self) -> None:
        # Unconditionally: the daemon accrues active time every tick, so the
        # daily totals grow the whole time you sit — waiting for a transition
        # to mark the page stale would leave it showing this morning's numbers.
        self._refresh()

    def _build(self) -> None:
        tokens = theme()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        daily = Card()
        head = QHBoxLayout()
        head.addWidget(section_label(self.tr("Daily totals — last 14 days")))
        head.addStretch()
        sit_color, stand_color = DailyBarsChart.series_colors()
        for color, name in ((sit_color, self.tr("Sitting")),
                            (stand_color, self.tr("Standing"))):
            dot = StatusDot(color)
            label = QLabel(name)
            label.setStyleSheet(f"color: {css(tokens.secondary)}; border: none;")
            head.addWidget(dot)
            head.addWidget(label)
            head.addSpacing(6)
        daily.body.addLayout(head)
        self.daily_chart = DailyBarsChart()
        daily.body.addWidget(self.daily_chart)
        self.stats_footer = QLabel("")
        self.stats_footer.setStyleSheet(
            f"color: {css(tokens.muted)}; border: none;")
        daily.body.addWidget(self.stats_footer)
        layout.addWidget(daily)

        trans = Card()
        head = QHBoxLayout()
        head.addWidget(section_label(self.tr("Recent transitions")))
        head.addStretch()
        refresh_btn = QPushButton(self.tr("Refresh"))
        refresh_btn.clicked.connect(self._refresh)
        head.addWidget(refresh_btn)
        trans.body.addLayout(head)
        scroll, scroll_body = card_scroll()
        self._trans_rows = QVBoxLayout()
        self._trans_rows.setSpacing(0)
        scroll_body.addLayout(self._trans_rows)
        scroll_body.addStretch()
        trans.body.addWidget(scroll)
        layout.addWidget(trans, 1)

    def _on_available(self, available: bool) -> None:
        if available:
            self._refresh()

    def _on_transition_completed(self, *_args) -> None:
        # Refreshing means two blocking D-Bus reads and a row rebuild;
        # only do it live when the Statistics page is actually visible.
        # While hidden there is nothing to do — on_shown re-reads on the way in.
        if self.isVisible():
            self._refresh()

    def _refresh(self) -> None:
        if not self.client.available:
            return
        end_date = date.today()
        start = end_date - timedelta(days=13)
        by_day: dict[str, dict[str, float]] = {}
        for day_str, state, seconds in self.client.get_daily_stats(
                start.isoformat(), end_date.isoformat()):
            by_day.setdefault(day_str, {})[state] = seconds

        # One bar per calendar day, oldest first / today last.
        rows = []
        total_sit = total_stand = 0.0
        for offset in range(14):
            window_day = start + timedelta(days=offset)
            data = by_day.get(window_day.isoformat(), {})
            sit = data.get("sitting", 0.0)
            stand = data.get("standing", 0.0)
            total_sit += sit
            total_stand += stand
            rows.append((fmt_day_label(datetime(window_day.year, window_day.month, window_day.day)),
                         sit, stand, window_day == end_date))
        self.daily_chart.set_rows(rows)
        overall = total_sit + total_stand
        if overall:
            avg = (self.tr(" 14-day average: %s%%.")
                   % f"{total_stand / overall * 100:.0f}")
        else:
            avg = ""
        self.stats_footer.setText(
            self.tr("Standing share = standing time / tracked time per day.")
            + avg)

        clear_layout(self._trans_rows)
        for i, (occurred_at, from_state, to_state, trigger, interrupted) in enumerate(
                self.client.get_transitions(50)):
            if i:
                self._trans_rows.addWidget(separator())
            self._trans_rows.addWidget(
                self._make_transition_row(occurred_at, from_state, to_state,
                                          trigger, interrupted))

    def _make_transition_row(self, occurred_at: float, from_state: str, to_state: str,
                             trigger: str, interrupted: bool) -> QWidget:
        tokens = theme()
        row_widget = QWidget()
        hbox = QHBoxLayout(row_widget)
        hbox.setContentsMargins(2, 6, 2, 6)
        hbox.setSpacing(10)
        when = QLabel(fmt_day_and_clock(datetime.fromtimestamp(occurred_at)))
        when.setStyleSheet(f"color: {css(tokens.secondary)}; border: none;")
        # Size the timestamp column from the font so it never clips the
        # "Wed 30 23:59"-style label at the user's font size / DPI / locale.
        # Measured from a rendered sample rather than a literal: the label is
        # locale-formatted now, so "Wed 30 23:59" is no longer what it says.
        when.setFixedWidth(
            when.fontMetrics().horizontalAdvance(
                fmt_day_and_clock(datetime(2026, 12, 30, 23, 59))) + 8)
        change = QLabel(f"{position_label(from_state)} → "
                        f"{position_label(to_state)}")
        change.setStyleSheet("border: none;")
        hbox.addWidget(when)
        hbox.addWidget(change)
        if interrupted:
            hbox.addWidget(pill(self.tr("interrupted"), tokens.warning_text,
                                tokens.warning))
        hbox.addStretch()
        tag_color = {"automation": tokens.success_text,
                     "manual": tokens.muted}.get(trigger, tokens.warning_text)
        hbox.addWidget(pill(trigger_label(trigger), tag_color))
        return row_widget
