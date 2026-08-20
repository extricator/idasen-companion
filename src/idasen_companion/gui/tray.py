"""System tray icon (StatusNotifier via QSystemTrayIcon).

Optional by design: on GNOME without the AppIndicator extension the icon
never shows, so every action here is also reachable from the main
window. gui.main decides whether to construct this at all.
"""

from __future__ import annotations

import time
from datetime import date
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..core.machine import (
    COUNTDOWN_STATUSES, NO_CYCLE_STATUSES, RESUMABLE_STATUSES,
)
from .dbus_client import DaemonClient
from .sni import RichTooltip
from .util import (due_now_label, fmt_duration, fmt_height, fmt_hm,
                   position_or_custom, preset_label, snooze_line,
                   status_label)

SNOOZE_CHOICES = (5, 10, 15, 30, 60)

# The machine speaks ``Status``; the wire and this client speak its values.
_NO_CYCLE_STATUS_VALUES = frozenset(s.value for s in NO_CYCLE_STATUSES)
_RESUMABLE_VALUES = frozenset(s.value for s in RESUMABLE_STATUSES)
_COUNTDOWN_VALUES = frozenset(s.value for s in COUNTDOWN_STATUSES)

# The tooltip's bold title. Not a tr() string: it is the product name, and a
# brand name is the one piece of UI text that must read the same in every
# locale. It stands alone as the title now — the peers on a Plasma panel
# ("Bluetooth", "Updates") title themselves the same way, and the state it used
# to carry after an em dash reads better as the detail line it now is.
APP_TITLE = "Idasen Companion"

# How long "Connecting…" may stay up before we give up on ever seeing the move
# start. Only a backstop: the label normally clears the moment the desk moves.
# Generous because a failing connect retries with backoff behind a 30s scan
# timeout per attempt, and a label that vanishes early reads as "it gave up".
CONNECTING_TIMEOUT_MS = 90_000

# How often the countdown re-renders itself between the daemon's progress
# pushes. Those arrive one check_interval apart (60s by default), which is
# coarser than the second-by-second display the final minute needs, so the tray
# interpolates locally in between — exactly as Overview does.
TICK_MS = 1000


class TrayIcon(QSystemTrayIcon):
    def __init__(self, client: DaemonClient, window, icon: QIcon, parent=None):
        super().__init__(icon, parent)
        self.client = client
        self.window = window
        self._status = ""
        self._position = ""
        # None until the first progress push, and deliberately not 0.0: a zero
        # countdown is a real state ("Due now"), not the absence of one. A
        # falsy 0.0 conflated the two, so the countdown clause vanished
        # outright once the clock ran out — for as long as the move waited.
        self._remaining: float | None = None
        self._elapsed: float | None = None
        # When those two were last true, so the ticker below can age them.
        self._progress_stamp = time.monotonic()
        # The day's totals, cached: see _refresh_texts for why the ticker
        # must not re-fetch them.
        self._today = ""
        self._connected = False
        self._moving = False
        self._connecting = False
        # The presets submenu's contents, cached so a units change can redraw
        # the labels without waiting for the daemon to announce them again.
        self._presets: dict[str, float] = {}
        # Set once we own the StatusNotifierItem object and can give the
        # tooltip a real title/detail split; None means we never got it and
        # everything below stays on plain QSystemTrayIcon behaviour.
        self._rich: RichTooltip | None = None
        self._connecting_timer = QTimer(self)
        self._connecting_timer.setSingleShot(True)
        self._connecting_timer.setInterval(CONNECTING_TIMEOUT_MS)
        self._connecting_timer.timeout.connect(self._end_connecting)
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start(TICK_MS)

        menu = QMenu()
        self._status_action = menu.addAction(self.tr("Starting…"))
        self._status_action.setEnabled(False)
        menu.addSeparator()

        menu.addAction(self.tr("Toggle sit / stand"),
                       lambda: self._move(client.toggle))
        menu.addAction(preset_label("sit"), lambda: self._move(client.sit))
        menu.addAction(preset_label("stand"), lambda: self._move(client.stand))
        self._presets_menu = menu.addMenu(self.tr("Presets"))
        menu.addAction(self.tr("Stop movement"), client.stop)
        menu.addSeparator()

        self._pause_action = QAction(self.tr("Pause automation"), menu)
        self._pause_action.triggered.connect(self._toggle_pause)
        menu.addAction(self._pause_action)
        self._skip_action = menu.addAction(
            self.tr("Skip next transition"), client.skip_next)
        snooze_menu = menu.addMenu(self.tr("Snooze"))
        for minutes in SNOOZE_CHOICES:
            # partial, not a lambda with a default argument: both freeze the
            # loop variable, but only this one states that it is what it is
            # doing, and PySide6's addAction overloads stopped inferring the
            # lambda form in 6.11.2.
            snooze_menu.addAction(self.tr("%n minute(s)", "", minutes),
                                  partial(client.snooze, minutes))
        # Hidden together when automation is off: all three act on a timer
        # that isn't running. The move actions above stay — they are the whole
        # point of using the app without automation.
        self._cycle_actions = (self._pause_action, self._skip_action,
                               snooze_menu.menuAction())
        self._cycle_separator = menu.addSeparator()
        menu.addAction(self.tr("Open window"), self._show_window)
        menu.addAction(self.tr("Quit"), self._quit)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        client.statusChanged.connect(self._on_status)
        client.positionChanged.connect(self._on_position)
        client.progressChanged.connect(self._on_progress)
        client.presetsChanged.connect(self._rebuild_presets)
        client.availableChanged.connect(self._on_available)
        client.connectedChanged.connect(self._on_connected)
        client.movingChanged.connect(self._on_moving)
        # The deadline arrives *after* the status that implies it — the client
        # fetches SnoozeUntil asynchronously on the snoozed announcement — so
        # the first snoozed tooltip says "later" and this redraws it with the
        # time. Same reason OverviewPage subscribes to snoozeUntilChanged.
        client.snoozeUntilChanged.connect(lambda *_: self._refresh_texts())
        # The window owns the config; the only part of it this menu renders is
        # the unit its preset heights are in. Duck-typed because the tray is
        # also built in tests around a stand-in window.
        ctx = getattr(window, "ctx", None)
        if ctx is not None:
            ctx.configChanged.connect(
                lambda: self._rebuild_presets(self._presets))

        # Drive the initial state now that we've subscribed, for the same
        # reason MainWindow re-emits availableChanged after subscribing — but
        # the tray was missed. Both earlier bursts (the client's own ping in
        # its constructor, and the window's refresh_all in *its* constructor)
        # happen before gui.main builds this tray, so they were emitted into
        # the void. Nothing else here ever calls _refresh_texts, so without
        # this the tooltip is never set at all — and an unset tooltip shows
        # *nothing* on hover, not a stale value — until the daemon's next
        # periodic push, up to a whole check_interval later.
        client.availableChanged.emit(client.available)
        if client.available:
            client.refresh_all()   # also repopulates the presets submenu
        else:
            self._rebuild_presets({})

    # ----- StatusNotifierItem takeover -----

    def show(self) -> None:
        super().show()
        # Deliberately after show(): Qt builds its D-Bus tray objects — and
        # registers the pixmap metatype the ToolTip struct needs — as a side
        # effect of the icon becoming visible. A zero-delay hop lets that
        # settle before we take the object path over.
        QTimer.singleShot(0, self._install_rich_tooltip)

    def _install_rich_tooltip(self) -> None:
        if self._rich is not None:
            return
        self._rich = RichTooltip.install(self)
        if self._rich is not None:
            self._refresh_texts()

    def run_tray_action(self, name: str, default: str) -> None:
        """Run a configured tray gesture.

        Public because the SNI object calls it: once we own the item, clicks
        arrive as Activate/SecondaryActivate on D-Bus and ``activated`` no
        longer fires for them.
        """
        self._run_action(self._action(name, default))

    # ----- updates -----

    def _on_available(self, available: bool) -> None:
        if not available:
            self._end_connecting()
            text = self.tr("Daemon not running")
            self._status_action.setText(text)
            self._set_tooltip(text)

    def _on_connected(self, connected: bool) -> None:
        self._connected = connected

    def _on_moving(self, moving: bool) -> None:
        # The desk moving is the first thing the user can actually see, so
        # that — not the link coming up — is what "Connecting…" waits for:
        # a connected desk is still ~1.5s of service discovery and a height
        # read away from moving.
        self._moving = moving
        if moving:
            self._end_connecting()

    def _on_status(self, status: str) -> None:
        self._status = status
        if status == "move-failed":
            self._end_connecting()
        self._pause_action.setText(
            self.tr("Resume automation") if status in _RESUMABLE_VALUES
            else self.tr("Pause automation"))
        for action in self._cycle_actions:
            action.setVisible(status != "disabled")
        self._cycle_separator.setVisible(status != "disabled")
        self._refresh_texts()

    def _on_position(self, position: str) -> None:
        self._position = position
        self._refresh_texts()

    def _on_progress(self, active_time: float, target: float) -> None:
        self._remaining = max(0.0, target - active_time)
        # The other half of the same number: how long this position has been
        # held. Both sides of the cycle are worth a line in the tooltip.
        self._elapsed = max(0.0, active_time)
        self._progress_stamp = time.monotonic()
        self._refresh_texts()

    def _tick(self) -> None:
        """Age the countdown by a second.

        Only the two states that show one, mirroring Overview's own ticker
        (``pages/overview.py`` ``_tick_countdown``). Everywhere else this is a
        bare comparison, and even inside a cycle it usually re-renders the same
        string — which ``RichTooltip.update`` drops without a D-Bus signal.
        """
        if self._status not in _COUNTDOWN_VALUES:
            return
        remaining = self._shown_remaining()
        if remaining is None or remaining <= 0:
            return
        self._refresh_texts(stats=False)

    def _shown_remaining(self) -> float | None:
        """Seconds left, aged forward from the last progress push.

        The daemon speaks once a check_interval, so its number is stale for
        most of the time it is on screen — and a countdown that stands still
        for a minute and then jumps is exactly what a countdown must not do.
        Overview solved this the same way; the tray gets the identical signal
        and now draws the identical number from it.

        Rounded to the whole second the display works in, so that the instant a
        push lands we show exactly what the daemon said. Truncating instead
        would turn a fresh "660 seconds" into 659.999 and floor the minutes
        band a whole minute low.
        """
        if self._remaining is None:
            return None
        return max(0.0, round(self._remaining - self._since_progress()))

    def _cycle_stopped(self) -> bool:
        """Whether the active-time clock is frozen with no scheduled thaw.

        The machine's own list, not a copy of it — see ``NO_CYCLE_STATUSES``.
        Deliberately excludes idle, lock and away: those stop the accumulator
        too, but the cycle is still this one and the freeze ends the moment the
        user comes back, so the duration is stale rather than meaningless.
        """
        return self._status in _NO_CYCLE_STATUS_VALUES

    def _shown_elapsed(self) -> float | None:
        """How long this position has been held, aged the same way."""
        if self._elapsed is None:
            return None
        return float(round(self._elapsed + self._since_progress()))

    def _since_progress(self) -> float:
        return time.monotonic() - self._progress_stamp

    def _time_left(self, remaining: float) -> str:
        """The remaining time as a word: '11m', '45s'.

        ``fmt_duration`` rather than ``fmt_hm`` because ``fmt_hm`` floors to
        whole minutes, so it renders the entire final minute — 59 seconds of
        it — as "0m". (``fmt_duration`` exists because that same flooring was
        already found wrong once, for the Activity Log.) Truncated to whole
        seconds first so the handover between the two bands reads "1m" rather
        than a rounded-up "60s".
        """
        return fmt_duration(int(remaining))

    def _countdown_clause(self, remaining: float) -> str:
        """'11m left', or 'Due now' once the clock has actually run out.

        "Due now" is deliberately reserved for zero rather than spread over
        the last minute: it promises immediacy, and it is already optimistic —
        the move still waits on the next tick and on the recent-input gate —
        so widening it would compound an over-promise instead of fixing one.
        """
        return (due_now_label() if int(remaining) <= 0
                else self.tr("%s left") % self._time_left(remaining))

    def _position_word(self) -> str:
        # Empty position = held off sit/stand; mirror the Overview title's
        # "Custom" so the tray and the window agree on the same state.
        return position_or_custom(self._position)

    def _menu_line(self) -> str:
        """The one-line status heading the context menu shows.

        Deliberately shorter than the tooltip, and not merely the tooltip
        joined up. Two reasons it diverges:

        * a menu's width is set by its longest item, and ours is "Skip next
          transition" at 20 characters. A heading longer than that widens every
          row beneath it — and the *worst* case is a bad state, where a status
          word appended to an elapsed clause is longest, so the menu would jump
          wider exactly when you opened it because something was wrong.
        * you reach the menu to act, so the useful facts are where the desk is
          and how long you have — not how long it has already been there. The
          elapsed duration stays in the tooltip, one hover away.

        So: the position, then a countdown when one is running and the reason
        when one isn't.
        """
        if self._connecting:
            return self.tr("Connecting…")
        # Only "active" gets the countdown. A failed move has a countdown too,
        # but the failure is the thing worth the line.
        tail = ""
        remaining = self._shown_remaining()
        if self._status == "active" and remaining is not None:
            tail = self._countdown_clause(remaining)
        return self.tr("%s · %s") % (self._position_word(),
                                     tail or status_label(self._status))

    def _tooltip_lines(self) -> list[str]:
        """The status as tooltip detail lines.

        Two lines, answering the two questions a glance at a sit/stand desk is
        actually asking — how long have I been like this, and when does that
        change. Neither is the app's name, which is why the name is the title
        on its own rather than a compound headline.
        """
        if self._connecting:
            return [self.tr("Connecting…")]

        position = self._position_word()
        # Before the first progress push there is no duration to report, and
        # "Sitting for 0m" would be a claim we can't back. A duration we *do*
        # know is reported in seconds while it is under a minute, so the first
        # minute after a transition no longer reads "Sitting for 0m" either.
        #
        # Nor is one reported once the cycle stops running down (paused,
        # snoozed, off, out of hours, held). The number is active time, not
        # time in the position: the machine stops crediting it the moment the
        # cycle freezes, so it would sit there unchanged for the whole pause
        # while reading like a running clock. Showing nothing is the honest
        # version — the position word alone is still true.
        elapsed = None if self._cycle_stopped() else self._shown_elapsed()
        held = (self.tr("%s for %s") % (position, fmt_duration(int(elapsed)))
                if elapsed is not None else position)

        # "Automation active" is dropped when a countdown is showing: a visible
        # "Standing up in 17m" already proves automation is running, and the
        # phrase only earns its place in the states where there is no countdown
        # (paused, snoozed, off), which is where it stops being filler.
        change = status_label(self._status)
        remaining = self._shown_remaining()
        if self._status == "snoozed":
            change = self._snooze_line()
        elif remaining is not None and self._status == "active":
            if int(remaining) <= 0:
                # No direction word here: "Standing up Due now" is not a
                # sentence, and the held line above already says which way the
                # desk is about to go.
                change = due_now_label()
            elif self._position == "sitting":
                # Deliberately the daemon's pre-move notification wording, so
                # the notification and the tooltip name one event one way.
                change = (self.tr("Standing up in %s")
                          % self._time_left(remaining))
            elif self._position == "standing":
                change = (self.tr("Sitting down in %s")
                          % self._time_left(remaining))
            else:
                # Off sit/stand: we know when, not what to call it.
                change = self.tr("%s left") % self._time_left(remaining)
        elif remaining is not None and self._status == "move-failed":
            change = self.tr("%s · %s") % (
                change, self._countdown_clause(remaining))
        return [held, change]

    def _snooze_line(self) -> str:
        """When automation comes back — the one question a snooze raises.

        Overview's exact wording (``pages/overview.py`` ``_render_status``),
        fallback included, so one state is named one way. The fallback covers
        the window where the status has been announced but the deadline hasn't
        arrived: the client fetches ``SnoozeUntil`` asynchronously and
        ``snoozeUntilChanged`` brings us back here with the real time.

        Tooltip only, deliberately. ``_menu_line`` keeps the bare status word
        because "Standing · Snoozed until 14:32" is 30 characters against the
        20 its docstring budgets, and a heading that long widens every row of
        the menu for as long as the snooze lasts.
        """
        return snooze_line(self.client.snooze_until())

    def _refresh_texts(self, stats: bool = True) -> None:
        # `stats=False` on the ticker path, and not an optimization to taste:
        # `_today_summary` makes a blocking D-Bus call for the day's totals,
        # which is fine once per daemon push but not once per second. The
        # totals move by a second per second, so the cached line stays honest
        # in between.
        if stats:
            self._today = self._today_summary()
        self._status_action.setText(self._menu_line())
        # `_today` is an optional final member of the list, present only
        # when the daemon has totals to report.
        lines = self._tooltip_lines()
        if self._today:
            lines = lines + [self._today]
        # Stacking whole lines this way is layout, not sentence-building:
        # each line above is already a complete message its own translator
        # owns end to end, and only the order is fixed here. A break that
        # instead sits inside one of those messages is a different thing
        # and does not get this treatment -- see `_today_summary`.
        detail = "\n".join(lines)
        self._set_tooltip(detail)

    def _set_tooltip(self, detail: str) -> None:
        """Publish the tooltip both ways: split when we own the item, joined
        when we don't.

        The fallback keeps the title as its first line, so the plain
        ``QSystemTrayIcon`` string stays exactly what the split renders — the
        two differ in styling, never in words.

        The title placed ahead of ``detail`` here is the app's brand name,
        never translated -- so this is not a translated fragment stuck onto
        anything else, the one thing about this line a reader might
        otherwise flag.
        """
        self.setToolTip(f"{APP_TITLE}\n{detail}")
        if self._rich is not None:
            self._rich.update(APP_TITLE, detail)

    def _today_summary(self) -> str:
        if not self.client.available:
            return ""
        today = date.today().isoformat()
        totals = {"sitting": 0.0, "standing": 0.0}
        for _, state, seconds in self.client.get_daily_stats(today, today):
            totals[state] = seconds
        if totals["sitting"] or totals["standing"]:
            return (self.tr("Today: %s sitting / %s standing")
                    % (fmt_hm(totals["sitting"]),
                       fmt_hm(totals["standing"])))
        return ""

    def _rebuild_presets(self, presets: dict) -> None:
        self._presets = dict(presets)
        self._presets_menu.clear()
        for name in sorted(presets):
            self._presets_menu.addAction(
                self.tr("%s (%s)") % (preset_label(name),
                                      fmt_height(presets[name])),
                partial(self._move, self.client.move_to_preset, name))
        self._presets_menu.setEnabled(bool(presets))

    # ----- actions -----

    def _toggle_pause(self) -> None:
        if self._status in _RESUMABLE_VALUES:
            self.client.resume()
        else:
            self.client.pause()

    def _move(self, request, *args) -> None:
        """Issue a desk move from the tray, showing "Connecting…" if it has to
        wait on the BLE link first.

        The connection is on-demand and dropped after a short linger, so most
        tray clicks pay a cold connect before anything happens — measured
        between 2 and 12 seconds, all of it inside BlueZ's link establishment
        and none of it visible. The click looked ignored. This does not make
        the wait shorter; it makes it legible.
        """
        if not (self._connected or self._moving or self._connecting):
            self._connecting = True
            self._connecting_timer.start()
            self._refresh_texts()
        request(*args)

    def _end_connecting(self) -> None:
        if not self._connecting:
            return
        self._connecting = False
        self._connecting_timer.stop()
        self._refresh_texts()

    def _action(self, name: str, default: str) -> str:
        # The configured action for a tray gesture, tolerating an unreadable
        # config at startup.
        config = getattr(self.window, "ctx", None) and self.window.ctx.cfg
        return getattr(config.ui, name) if config is not None else default

    def _run_action(self, action: str) -> None:
        if action == "window":
            self._show_window()
        elif action in ("toggle", "sit", "stand"):
            # The daemon owns the repeat-to-cancel decision (stop/reverse per
            # [ui] tray_repeat_move) from its authoritative movement state, so
            # the second press of a gesture reliably interrupts the move rather
            # than racing lagged client-side state.
            self._move(self.client.gesture_move, action)
        # "none": do nothing.

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._run_action(self._action("tray_left_click", "window"))
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self._run_action(self._action("tray_middle_click", "toggle"))
        # DoubleClick is intentionally unhandled: StatusNotifierItem trays
        # (KDE, GNOME, most modern Linux) never deliver it, so it isn't a
        # configurable action. On a legacy XEmbed tray that does emit it, the
        # first click already fired Trigger, so ignoring it is harmless.

    def _show_window(self) -> None:
        self.window.present()

    def _quit(self) -> None:
        # Through the window, not straight to QApplication.quit(): a settings
        # page with edits that were never applied gets to ask first, the same
        # as it would when the window is closed.
        self.window.request_quit()
