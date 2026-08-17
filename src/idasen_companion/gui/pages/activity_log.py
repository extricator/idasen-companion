"""Activity Log page: the daemon's log, filtered by audience and severity.

Two controls, because there are two questions (``docs/LOGGING.md``): *who is
this for* (channel) and *how bad is it* (level). The default shows the
activity channel only — the lines that answer "why did my desk do that?" —
and "All" folds the diagnostics back in for when something is wrong.

Lines are composed here, not by the daemon: each entry arrives as a message id
plus raw parameters, so the sentence is written in the user's language with
their units. The daemon's English comes along too and is what gets shown for
any id this build doesn't recognize.

The backlog is seeded from the journal rather than from the daemon alone, so
it survives a daemon restart and includes lines the GUI wrote itself while the
daemon was down.
"""

from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from ...core import journal
from .. import log_catalog, restyle
from ..theme import CONTROL_RADIUS, css, theme
from ..widgets import Card, SegmentedControl, icon
from .base import Page


class _BacklogSignals(QObject):
    done = Signal(list)


class _BacklogReader(QRunnable):
    """Reads the journal backlog off the GUI thread.

    ``journalctl`` is a subprocess round-trip — a few milliseconds warm, but
    its timeout is ten seconds, and that is how long the window would freeze
    for on a cold or very large journal, with no busy cursor, on a plain click
    in the sidebar.
    """

    def __init__(self, history: str):
        super().__init__()
        self._history = history
        self.signals = _BacklogSignals()

    def run(self) -> None:
        # read_recent never raises — it reports every failure as an empty
        # backlog, which is the right answer on a worker thread too.
        self.signals.done.emit(journal.read_recent(self._history))


class ActivityLogPage(Page):
    # Filters on the identifier, not the unit, so it returns what this page
    # shows. `-u idasen-companion` is a strictly smaller set: it misses every
    # line the GUI wrote itself, which isn't in the daemon's cgroup — and a
    # user copies this chip precisely when they want the whole log.
    _JOURNAL_CMD = f"journalctl --user -t {journal.SYSLOG_IDENTIFIER}"
    _LEVELS = ["debug", "info", "warning", "error"]
    # How far back to read on open. The ring buffer holds 500 lines; a week of
    # journal is a different order of thing, and it is what makes "why did my
    # desk do that on Tuesday?" answerable at all.
    _HISTORY = "-7 days"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._entries: list[dict] = []
        self._seeded = False
        self._loading = False
        self._build()

        self.client.logEntry.connect(self._on_log_entry)
        self.client.availableChanged.connect(self._on_available)

    def on_shown(self) -> None:
        # Re-read on every open, not just the first: the GUI writes to the
        # journal itself (autostart toggled while the daemon is down) and those
        # lines have no D-Bus path to arrive by, so seeding once left them
        # invisible until the next launch. Not done at startup because most
        # launches never open this page; not expensive now that the read is off
        # the GUI thread, and the merge is idempotent.
        self._load_backlog()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel(self.tr("Show")))
        self.channel = SegmentedControl([self.tr("Activity"), self.tr("All")])
        self.channel.setCurrentIndex(0)
        self.channel.setToolTip(self.tr(
            "Activity explains what the desk did. All adds the diagnostic "
            "detail you'd attach to a bug report."))
        self.channel.currentChanged.connect(lambda _: self._redraw())
        filter_row.addWidget(self.channel)
        self.log_level = SegmentedControl(
            [self.tr("Debug"), self.tr("Info"), self.tr("Warn"),
             self.tr("Error")])
        self.log_level.setCurrentIndex(1)
        self.log_level.currentChanged.connect(lambda _: self._redraw())
        filter_row.addWidget(self.log_level)
        filter_row.addWidget(QLabel(self.tr("and above")))
        filter_row.addStretch()
        layout.addLayout(filter_row)

        log_card = Card()
        log_card.body.setContentsMargins(6, 6, 6, 6)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFrameShape(QTextEdit.Shape.NoFrame)
        self.log_view.setPlaceholderText(self.tr("Nothing at this level yet."))
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSizeF(mono.pointSizeF() * 0.9)
        self.log_view.setFont(mono)
        self.log_view.document().setMaximumBlockCount(1000)
        log_card.body.addWidget(self.log_view)
        layout.addWidget(log_card, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        full_log = QLabel(self.tr("Full log:"))

        def _restyle_full_log(target: QLabel = full_log) -> None:
            target.setStyleSheet(f"color: {css(theme().muted)};")

        restyle.register(full_log, _restyle_full_log)
        self._journal_chip = QPushButton(f" {self._JOURNAL_CMD}")
        self._journal_chip.setFont(mono)
        self._journal_chip.setIcon(icon("edit-copy"))
        self._journal_chip.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # icon at right
        self._journal_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._journal_chip.setToolTip(self.tr("Copy command"))

        def _restyle_journal_chip(target: QPushButton = self._journal_chip) -> None:
            tokens = theme()
            target.setStyleSheet(
                f"QPushButton {{ background: {css(tokens.hover)};"
                f" color: {css(tokens.secondary)};"
                f" border: 1px solid {css(tokens.border)};"
                f" border-radius: {CONTROL_RADIUS}px; padding: 3px 8px; }}"
                f"QPushButton:hover {{ background: {css(tokens.separator)}; }}")

        restyle.register(self._journal_chip, _restyle_journal_chip)
        self._journal_chip.clicked.connect(self._copy_journal_cmd)
        footer.addWidget(full_log)
        footer.addWidget(self._journal_chip)
        footer.addStretch()
        layout.addLayout(footer)

    def _on_available(self, available: bool) -> None:
        # A daemon appearing (or reappearing after a restart) brings a ring
        # buffer this page hasn't seen. Only worth merging in if the page has
        # already been opened; otherwise on_shown will do it.
        if available and self._seeded:
            self._load_backlog()

    def _copy_journal_cmd(self) -> None:
        QGuiApplication.clipboard().setText(self._JOURNAL_CMD)
        check = icon("checkmark", "dialog-ok", "emblem-ok-symbolic",
                     "object-select-symbolic")
        if check.isNull():   # icon theme lacks a checkmark (e.g. Adwaita)
            self._journal_chip.setText(" ✓ " + self.tr("copied"))
        else:
            self._journal_chip.setIcon(check)
        QTimer.singleShot(1500, self._restore_journal_chip)

    def _restore_journal_chip(self) -> None:
        self._journal_chip.setText(f" {self._JOURNAL_CMD}")
        self._journal_chip.setIcon(icon("edit-copy"))

    # ----- data -----

    def _visible(self, entry: dict) -> bool:
        if self.channel.currentIndex() == 0 and entry["channel"] != "activity":
            return False
        try:
            rank = self._LEVELS.index(entry["level"])
        except ValueError:
            rank = 3   # unknown levels (e.g. "critical") are never hidden
        return rank >= self.log_level.currentIndex()

    # How far apart two records of the *same* line can be and still be the
    # same line. The ring stamps a line when the daemon emits it; the journal
    # stamps it when journald receives it, which is under a millisecond later
    # but never identical — so an exact-timestamp key matched nothing and
    # every daemon line appeared twice. Seconds of slack is safe: a genuine
    # repeat of the same message this close together is not something the
    # reader can act on differently anyway.
    _SAME_LINE_WINDOW = 2.0

    def _load_backlog(self) -> None:
        """Start a journal read; :meth:`_merge_backlog` finishes the job."""
        if self._loading:
            return
        self._loading = True
        reader = _BacklogReader(self._HISTORY)
        # Bound method, so Qt drops the connection if this page is destroyed
        # while the read is in flight.
        reader.signals.done.connect(self._on_backlog_read)
        QThreadPool.globalInstance().start(reader)

    def _on_backlog_read(self, entries: list) -> None:
        self._loading = False
        self._merge_backlog(entries)

    def _merge_backlog(self, entries: list) -> None:
        """Rebuild from the journal, the running daemon's ring, and what is
        already on screen.

        The journal is the persistent record and covers restarts and
        GUI-written lines; the ring covers anything journald hasn't flushed or
        that predates a working socket. They overlap almost entirely, and what
        is already on screen overlaps both — but it is the only place a line
        that arrived over D-Bus *during* this read can be.
        """
        merged: list[dict] = []
        positions: dict[str, list[int]] = {}

        def add(entry: dict) -> None:
            same = positions.setdefault(entry["text"], [])
            for merged_index in same:
                if abs(entry["ts"] - merged[merged_index]["ts"]) >= self._SAME_LINE_WINDOW:
                    continue
                # Two records of one line. Keep whichever carries a message id:
                # if the native journal send failed, the line reached journald
                # as plain stdout, arriving back unlabelled and therefore
                # classed as a diagnostic — dropping the labelled copy would
                # have hidden a real activity line and lost its translation.
                if not merged[merged_index]["msg_id"] and entry["msg_id"]:
                    merged[merged_index] = entry
                return
            same.append(len(merged))
            merged.append(entry)

        for entry in entries:
            add(entry)
        if self.client.available:
            for raw in self.client.get_recent_log():
                add(self._normalize(raw))
        for entry in self._entries:
            add(entry)
        self._entries = sorted(merged, key=lambda e: e["ts"])
        self._seeded = True
        self._redraw()

    @staticmethod
    def _normalize(entry: dict) -> dict:
        """Fill in anything an older daemon's JSON left out."""
        return {
            "ts": float(entry.get("ts", 0.0)),
            "level": str(entry.get("level", "info")),
            "channel": str(entry.get("channel", "activity")),
            "msg_id": str(entry.get("msg_id", "")),
            "params": entry.get("params") or {},
            "text": str(entry.get("text", "")),
        }

    def _on_log_entry(self, ring_ts: float, level: str, channel: str, msg_id: str,
                      params: dict, text: str) -> None:
        entry = {"ts": ring_ts, "level": level, "channel": channel,
                 "msg_id": msg_id, "params": params, "text": text}
        self._entries.append(entry)
        if self._visible(entry):
            self._append(entry)

    def _redraw(self) -> None:
        self.log_view.clear()
        for entry in self._entries:
            if self._visible(entry):
                self._append(entry)

    def _append(self, entry: dict) -> None:
        tokens = theme()
        level = entry["level"]
        color = {"debug": tokens.muted, "info": tokens.accent_text,
                 "warning": tokens.warning_text, "error": tokens.error}.get(
                     level, tokens.secondary)
        stamp = datetime.fromtimestamp(entry["ts"]).strftime("%H:%M:%S")
        label = "WARN" if level == "warning" else level.upper()
        pad = "&nbsp;" * (6 - len(label))
        message = log_catalog.render(entry["msg_id"], entry["params"],
                                     entry["text"])
        self.log_view.append(
            f'<span style="color:{css(tokens.muted)}">{stamp}</span>&nbsp;&nbsp;'
            f'<span style="color:{css(color)};font-weight:600">{label}</span>'
            f'{pad}{html.escape(message)}')
