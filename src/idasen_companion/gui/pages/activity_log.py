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
from datetime import date, datetime

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import (QFontDatabase, QFontMetricsF, QGuiApplication,
                           QTextCursor)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTextEdit, QVBoxLayout

from ...core import journal
from .. import log_catalog, restyle, util
from ..theme import CONTROL_RADIUS, css, theme
from ..widgets import Card, SegmentedControl, SpacedLabelButton, icon, tinted_icon
from .base import Page

# The confirmation glyph shown on the journal chip after a successful copy.
# Named once here so _copy_journal_cmd (which resolves it) and the restyle
# path (which re-derives the chip's icon on every palette change) cannot
# drift apart on which glyph they mean.
#
# These have to be outline glyphs, because the chip tints whatever it gets to
# a flat colour: tinting line art keeps the drawing, but tinting a solid shape
# gives back a featureless block. Do not put the obvious name first here —
# Breeze answers it with a *filled* badge (measured: ink covering the whole
# 16px box, against 55 subpixels for the copy glyph beside it), which tinted
# to a flat colour rendered as a grey square where the tick should be. The
# three names below all resolve to the same line-art tick on Breeze (16
# subpixels of ink) and the last of them also covers Adwaita.
_COPIED_ICON_NAMES = ("dialog-ok", "emblem-ok-symbolic",
                      "object-select-symbolic")


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
    # How far back to read on open. journal.read_recent caps the read at 2000
    # records and the document keeps 1000 blocks, so the old seven-day figure
    # was already nominal: on a busy journal (measured 2594 lines over seven
    # days, 1464 over one, on the developer's machine) the window was already
    # truncated to roughly two days regardless of what this said. Three days
    # keeps a Friday problem answerable on a Monday while stating what the
    # page actually shows.
    _HISTORY = "-3 days"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._entries: list[dict] = []
        self._seeded = False
        self._loading = False
        self._awaiting_scroll_range = False
        self._drawn = ""
        self._last_drawn_day: date | None = None
        self._chip_copied = False
        self._separator_width = 0
        self._build()
        self._refresh_separator_columns()

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
        self._journal_chip = SpacedLabelButton(self._JOURNAL_CMD)
        self._journal_chip.setFont(mono)
        self._journal_chip.setIconSize(QSize(16, 16))
        self._journal_chip.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # icon at right
        self._journal_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._journal_chip.setToolTip(self.tr("Copy command"))
        restyle.register(self._journal_chip, self._restyle_journal_chip)
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
        check = icon(*_COPIED_ICON_NAMES)
        if check.isNull():
            # Icon theme lacks a checkmark (e.g. Adwaita). The mark is part
            # of this one message, not glued onto a translated word, so a
            # translator can move it, replace it, or drop it.
            self._journal_chip.setText(self.tr("✓ copied"))
        else:
            self._chip_copied = True
            self._apply_journal_chip_icon()
        QTimer.singleShot(1500, self._restore_journal_chip)

    def _restore_journal_chip(self) -> None:
        self._journal_chip.setText(self._JOURNAL_CMD)
        self._chip_copied = False
        self._apply_journal_chip_icon()

    def _apply_journal_chip_icon(self) -> None:
        """Set the chip's icon for its current copied/resting state, tinted
        to sit at the same visual weight as the chip's text.

        The two glyphs are tinted to *different* tokens on purpose, because an
        equal colour does not buy an equal weight here. A tint fills the
        glyph's own coverage, so how heavy it looks is decided by how much of
        it is fully opaque rather than by the colour alone: the copy glyph is
        a dense outline (53 of its 55 subpixels of ink are solid), while the
        tick is a thin antialiased stroke (1 of 16), which the chip background
        blends most of the way back. Tinted alike, the copy glyph read as a
        dark blot beside its own label and the tick read correctly — so the
        dense glyph takes the lighter token to land where the thin one already
        was.

        The text-fallback branch in :meth:`_copy_journal_cmd` never sets
        ``_chip_copied`` true, so a theme with no tick glyph correctly leaves
        the resting icon in place here rather than needing a special case of
        its own.
        """
        tokens = theme()
        if self._chip_copied:
            self._journal_chip.setIcon(
                tinted_icon(icon(*_COPIED_ICON_NAMES), tokens.secondary))
        else:
            self._journal_chip.setIcon(
                tinted_icon(icon("edit-copy"), tokens.muted))

    def _restyle_journal_chip(self) -> None:
        tokens = theme()
        self._journal_chip.setStyleSheet(
            f"QPushButton {{ background: {css(tokens.hover)};"
            f" color: {css(tokens.secondary)};"
            f" border: 1px solid {css(tokens.border)};"
            f" border-radius: {CONTROL_RADIUS}px; padding: 3px 8px; }}"
            f"QPushButton:hover {{ background: {css(tokens.separator)}; }}")
        # A tinted icon is a baked pixmap and cannot follow a palette change
        # on its own -- re-deriving it from _chip_copied here, rather than
        # unconditionally resetting to the resting glyph, is what stops a
        # palette change mid-confirmation from reverting the checkmark.
        self._apply_journal_chip_icon()

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

    def _day_of(self, entry: dict) -> date:
        """The calendar day an entry falls on, in local time.

        Separator decisions compare these ``date`` objects directly, never a
        rendered heading string — so a locale or theme change can't
        accidentally join two different days by producing equal-looking text.
        """
        return datetime.fromtimestamp(entry["ts"]).date()

    def _trim_to_budget(self, shown: list[dict], limit: int) -> list[dict]:
        """Keep the newest entries whose rows-plus-separators fit ``limit``
        blocks.

        The budget for a kept set is (rows kept) + (distinct calendar days
        among them), because every day group is headed by exactly one
        separator — including the oldest kept day, which is what gives the
        first visible row a heading too. Walking backwards from the newest
        entry and charging both costs as they're incurred is the only way to
        know, before formatting anything, how far back the kept set can reach
        without exceeding the cap — so no row the document is about to drop
        is ever formatted.
        """
        kept = 0
        budget_day = None
        cut = len(shown)
        for index in range(len(shown) - 1, -1, -1):
            entry_day = self._day_of(shown[index])
            cost = 1 if entry_day == budget_day else 2
            if kept + cost > limit:
                break
            kept += cost
            budget_day = entry_day
            cut = index
        return shown[cut:]

    _SEPARATOR_RULE_CHAR = "─"

    def _separator_columns(self) -> int:
        """How many monospace cells a separator may fill without wrapping.

        Counting cells is exact here rather than approximate, because the view
        is monospace and the box-drawing character advances like everything
        else in it (measured identical to a digit, a capital and a space).

        The one spare cell held back below absorbs the rounding rather than
        letting it reach a wrap. A wrap costs appearance, not the block
        budget — Qt counts paragraphs, so an over-long separator would still
        be the single block :meth:`_trim_to_budget` allocated it (verified:
        a 400-character line in a 200px view stays one block) — but it would
        spill a stub of rule onto a second visual line and shove the heading
        off the centre it was placed on.

        The scrollbar's width comes off whether or not one is showing, and
        that is what keeps a redraw idempotent. Measuring the live viewport
        instead looked right and was not: the first draw of a long backlog
        measures before the scrollbar appears, the bar then claims its width,
        and the next redraw computes two cells narrower and rewrites a
        document that had not otherwise changed — the very write the
        ``_drawn`` comparison exists to avoid. Reserving it always costs a
        log too short to need a scrollbar a scrollbar's worth of rule.
        """
        advance = QFontMetricsF(self.log_view.font()).horizontalAdvance(
            self._SEPARATOR_RULE_CHAR)
        if advance <= 0:   # a font that reports nothing: draw no rule at all
            return 0
        usable = (self.log_view.width()
                  - 2 * self.log_view.document().documentMargin()
                  - 2 * self.log_view.frameWidth()
                  - self.log_view.verticalScrollBar().sizeHint().width())
        return max(0, int(usable / advance) - 1)

    def _refresh_separator_columns(self) -> bool:
        """Re-measure the separator width; True when it actually moved."""
        columns = self._separator_columns()
        if columns == self._separator_width:
            return False
        self._separator_width = columns
        return True

    def _separator_html(self, separator_day: date) -> str:
        """One document block: a muted day heading, ruled out to both edges.

        Centred, because the heading divides the log rather than belonging to
        any row in it — left-aligned it sat in the timestamp column and read
        as an odd entry instead of a break between days. The rules are then
        grown to fill whatever the heading leaves, so the separator spans the
        view's full width the way a divider should, instead of floating as a
        short fixed run in the middle of it.

        Any vertical breathing room around this block is its own CSS
        ``margin-top`` rather than a blank line above it; a blank line would
        spend a block from the document's own cap for nothing.
        """
        heading = util.fmt_day_heading(
            datetime(separator_day.year, separator_day.month, separator_day.day))
        # The two spaces flanking the heading are part of what has to fit.
        fill = max(0, (self._separator_width - len(heading) - 2) // 2)
        rule = self._SEPARATOR_RULE_CHAR * fill
        return (
            f'<div align="center" style="margin-top:6px;'
            f'color:{css(theme().muted)}">'
            f'{rule} {html.escape(heading)} {rule}</div>')

    def resizeEvent(self, event):   # pylint: disable=invalid-name
        # Qt dispatches this by exact name through its C++ meta-object
        # machinery, so it cannot be renamed to match the project's own
        # conventions.
        super().resizeEvent(event)
        if not self._refresh_separator_columns():
            return
        # Redrawing to re-rule the separators would otherwise drag a reader
        # who had scrolled up back down to the newest line, which is the very
        # thing _scroll_to_newest is written to avoid. Only follow the feed
        # here if the reader was already following it.
        scrollbar = self.log_view.verticalScrollBar()
        was_following = scrollbar.value() >= scrollbar.maximum()
        previous = scrollbar.value()
        self._redraw()
        if was_following:
            return
        # _redraw may have armed the pending-range handler, which parks the
        # bar at its maximum once the real range arrives — disarm it, or it
        # would undo the restore a frame later.
        if self._awaiting_scroll_range:
            scrollbar.rangeChanged.disconnect(self._on_scroll_range_settled)
            self._awaiting_scroll_range = False
        scrollbar.setValue(min(previous, scrollbar.maximum()))

    def _redraw(self) -> None:
        """Rebuild the whole view from ``_entries``, in one document write.

        Not a loop of :meth:`_append`, which is what this used to be. Each
        ``QTextEdit.append`` is its own document edit — parse the fragment,
        insert a block, re-lay-out, move the cursor, update the scrollbar — and
        past ``maximumBlockCount`` it also evicts the oldest block, which
        roughly quadruples the marginal cost. Measured on a 7-day backlog of
        ~1760 visible rows that came to 1.1 s of frozen GUI thread on every
        entry into the page (0.294 ms/row up to the cap, 1.15 ms/row after it),
        against 33 ms to render the very same rows to strings. So the cost was
        never the formatting or the painting: it was doing it 1760 times.

        Trimming to the cap first matters as much as batching. The document
        keeps the *last* ``maximumBlockCount`` blocks, so every row before that
        was being formatted, inserted and then immediately thrown away — around
        760 of them here, and they were the expensive ones. The trim is now
        day-aware too (:meth:`_trim_to_budget`): a day separator spends a block
        of its own, so the split between separators and rows has to be settled
        before anything is formatted, not after.
        """
        # Re-measure first, so a redraw reached by any other route than a
        # resize (a filter change, the first backlog merge) still rules its
        # separators to the width the view actually has.
        self._refresh_separator_columns()
        shown = [entry for entry in self._entries if self._visible(entry)]
        # Trim before formatting, not after: the point is not to render a row
        # the document is about to drop. Filtering first, because the cap
        # counts what is *displayed*.
        limit = self.log_view.document().maximumBlockCount()
        if limit > 0:
            shown = self._trim_to_budget(shown, limit)
        if not shown:
            # Leaves an empty document, so the placeholder text shows.
            self._drawn = ""
            self._last_drawn_day = None
            self.log_view.clear()
            return
        blocks: list[str] = []
        separator_day: date | None = None
        for entry in shown:
            entry_day = self._day_of(entry)
            if entry_day != separator_day:
                blocks.append(self._separator_html(entry_day))
                separator_day = entry_day
            blocks.append(f"<div>{self._row_html(entry)}</div>")
        self._last_drawn_day = separator_day
        rows = "".join(blocks)
        # Opening the page re-reads the journal and merges it in, and that
        # merge is idempotent — measured byte-identical on 46 of 48 entries,
        # the other two being visits a live line landed in. Rebuilding the
        # document to the same thing costs ~55 ms of blocked GUI thread and
        # loses the reader's selection for nothing. Comparing the rendered
        # rows rather than the entries behind them keeps this honest about
        # anything that changes how a row *looks* — a filter, the theme, the
        # language — since all of those change this string.
        if rows != self._drawn:
            self._drawn = rows
            self.log_view.setHtml(rows)
        self._scroll_to_newest()

    def _scroll_to_newest(self) -> None:
        """Put the view back on the last line, without scrolling past it.

        ``setHtml`` scrolls to the top, and undoing that has to restore both
        halves of what the old per-row ``append`` left behind: the cursor at
        the end, *and* the scrollbar at its maximum. The second is not implied
        by the first — ``ensureCursorVisible`` stops four pixels short, on the
        document's bottom margin, and ``QTextEdit.append`` follows a new line
        only while it judges the view already at the bottom, so a redraw that
        ends short stops the live feed for good.

        The catch is that the maximum cannot simply be read here. A document
        this size is laid out lazily, and until that finishes the scroll range
        is an estimate — measured 3712 px too large on a 7-day backlog, on
        every one of 48 entries into the page. Parking the bar on the estimate
        put the view past the last block, and the next frame painted the whole
        viewport as background: the white flash on opening the page. Asking the
        layout for its document size finishes the layout, so that height is
        real, and the bottom follows from it. The reported maximum is still
        used as a ceiling, so a wrong guess here can only ever be conservative.
        """
        view = self.log_view
        scrollbar = view.verticalScrollBar()
        bottom = (round(view.document().documentLayout().documentSize().height())
                  - view.viewport().height())
        view.moveCursor(QTextCursor.MoveOperation.End)
        scrollbar.setValue(max(0, min(scrollbar.maximum(), bottom)))
        # The bar keeps reporting the estimated range until Qt gets round to
        # correcting it, and in that window `value == maximum()` reads false —
        # which is the very test `append` uses. A line arriving in it would
        # leave the feed stuck, so take the bottom again when the real range
        # turns up. Measured: without this the feed freezes on a backlog
        # between the size at which layout goes lazy and the block cap.
        #
        # Only when the bar is actually still reporting an estimate, though.
        # Being at its maximum already means the range is settled and no
        # correction is coming, so an armed handler would sit there until some
        # unrelated change of range — a new line, a resized window — and then
        # yank a reader who had scrolled up back down to the bottom.
        if scrollbar.value() == scrollbar.maximum():
            return
        if not self._awaiting_scroll_range:
            self._awaiting_scroll_range = True
            scrollbar.rangeChanged.connect(self._on_scroll_range_settled)

    def _on_scroll_range_settled(self, _minimum: int, maximum: int) -> None:
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.rangeChanged.disconnect(self._on_scroll_range_settled)
        self._awaiting_scroll_range = False
        scrollbar.setValue(maximum)

    def _row_html(self, entry: dict) -> str:
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
        return (
            f'<span style="color:{css(tokens.muted)}">{stamp}</span>&nbsp;&nbsp;'
            f'<span style="color:{css(color)};font-weight:600">{label}</span>'
            f'{pad}{html.escape(message)}')

    def _append(self, entry: dict) -> None:
        """Add one line as it arrives, and a separator ahead of it when its
        day is new. Incremental insertion is the right shape for a single
        row — it is only doing this in a loop that was slow."""
        entry_day = self._day_of(entry)
        if entry_day != self._last_drawn_day:
            self.log_view.append(self._separator_html(entry_day))
            self._last_drawn_day = entry_day
        self.log_view.append(self._row_html(entry))
