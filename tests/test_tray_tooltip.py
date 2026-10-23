# SPDX-License-Identifier: GPL-3.0-or-later
"""What the tray tooltip says, and the one-line constraint on the menu entry.

The tooltip answers the two questions a glance at a sit/stand desk is asking —
how long have I been like this, and when does it change — as two detail lines
under the app name. See ``tests/test_tray_sni.py`` for how those lines are split
into the bold title and lighter detail Plasma renders; this file is about the
*words*, which are shared with the tray menu and must stay correct either way.

Three things here are guards rather than descriptions:

* ``test_menu_entry_stays_on_one_line`` — the same text labels
  ``_status_action``, a ``QAction`` in the context menu, and a QAction cannot
  render a second line. The newline must reach the tooltip and only the tooltip.
* ``test_no_line_ends_with_a_stranded_separator`` — the original bug. Plasma
  word-wrapped the old single-line headline right after its "·", stranding the
  dot at the end of a visual line. We pick the breaks now, so no line may end
  on one.
* ``test_countdown_replaces_the_status_word`` — "Automation active" next to a
  countdown is redundant, and dropping it is deliberate, not an omission.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import pytest

pytest.importorskip("PySide6")

import os
from datetime import date, datetime

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from types import SimpleNamespace  # noqa: E402

import shiboken6  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402

import dataclasses  # noqa: E402

from idasen_companion.core.clocks import MonotonicInstant, WallInstant  # noqa: E402
from idasen_companion.core.presentation import EnglishTranslator  # noqa: E402
from idasen_companion.core.durations import Duration  # noqa: E402
from idasen_companion.core.presentation import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.locale_profile import TimeStyle  # noqa: E402
from idasen_companion.core.locale_profile import (  # noqa: E402
    LocaleProfile,
)
from idasen_companion.core.display_prefs import HeightUnit  # noqa: E402
from idasen_companion.core.machine import Status  # noqa: E402
from idasen_companion.core.decoded_data import DailyStatRow  # noqa: E402
from idasen_companion.gui import tray as tray_mod  # noqa: E402
from idasen_companion.gui.tray import TrayIcon  # noqa: E402


class FakeClient(QObject):
    """The signals TrayIcon subscribes to, plus the calls it makes."""

    statusChanged = Signal(str)
    positionChanged = Signal(str)
    progressChanged = Signal(float, float)
    presetsChanged = Signal(dict)
    availableChanged = Signal(bool)
    connectedChanged = Signal(bool)
    movingChanged = Signal(bool)
    snoozeUntilChanged = Signal(float)
    positionObservationChanged = Signal()

    def __init__(self, available=False, daily_rows=()):
        super().__init__()
        self._snooze_until = WallInstant(0.0)
        self.stats_calls = 0
        self.observation = None
        # An instance attribute, not the class-level ``available = False`` the
        # other tray tests get away with: _today_summary returns "" outright
        # when the daemon is unavailable, so the summary line is unreachable
        # without this.
        self.available = available
        self.daily_rows = [DailyStatRow(*row) for row in daily_rows]

    def get_daily_stats(self, start, end):
        # A real method rather than the __getattr__ fallback below, which
        # returns None — and _today_summary iterates the result. Counted
        # because the real one is a blocking D-Bus round trip, and the tray
        # now re-renders once a second.
        self.stats_calls += 1
        return self.daily_rows

    def position_observation_elapsed(self, position):
        return self.observation if position in ("sitting", "standing") else None

    def snooze_until(self):
        # Also real: the fallback returns None, and the tray formats this.
        return self._snooze_until

    def set_snooze_until(self, value):
        """Announce a deadline the way the real client does — after the status.

        Test-only helper; ``DaemonClient`` does this from its async property
        fetch (``dbus_client.py`` ``_set_snooze_until``).
        """
        self._snooze_until = WallInstant(value)
        self.snoozeUntilChanged.emit(value)

    def __getattr__(self, name):
        # Menu entries wire up toggle/sit/stand/stop/... at construction; none
        # of them are exercised here beyond existing.
        return lambda *a, **kw: None


class _NullSignal:
    """Stands in for a Qt signal ``TrayIcon.__init__`` connects to, without
    a real ``QObject`` behind it."""

    def connect(self, *args, **kwargs):
        pass


class FakeWindow:
    """A ``ctx`` carrying only what ``TrayIcon`` reaches for -- ``cfg``
    stays ``None`` so ``TrayIcon._action`` still falls back to its
    defaults, exactly as it did before ``_fmt()`` had a caller."""

    def __init__(self):
        self.ctx = SimpleNamespace(
            cfg=None,
            configChanged=_NullSignal(),
            fmt=Formatter(PresentationContext(
                locale=LocaleProfile("en_US"), translator=EnglishTranslator(),
                unit=HeightUnit.CENTIMETRES,
                time_style=TimeStyle.HOUR_AND_MINUTE_24)))


def _make_tray(client):
    icon = TrayIcon(client, FakeWindow(), QIcon())
    yield icon, client
    # Destroy it here rather than letting Python drop the last reference
    # whenever it feels like it: a QSystemTrayIcon collected after the offscreen
    # QPA platform has been torn down segfaults the interpreter at exit, which
    # fails the RPM build's %check even with every test passing.
    icon.hide()
    icon.setContextMenu(None)
    shiboken6.delete(icon)


@pytest.fixture
def tray(qapp):
    yield from _make_tray(FakeClient())


@pytest.fixture
def tray_with_stats(qapp):
    today = date.today().isoformat()
    yield from _make_tray(FakeClient(
        available=True,
        daily_rows=[(today, "sitting", 7080.0), (today, "standing", 3000.0)]))


def standing_and_active(icon):
    """Standing 43m into a 54m cycle, so 11m remain."""
    icon._on_position("standing")
    icon.client.observation = Duration(2580)
    icon._on_status("active")
    icon._on_progress(2580.0, 3240.0)


def test_progress_receipt_ages_as_a_duration_before_formatting(tray, monkeypatch):
    icon, _ = tray
    clock = 10.0
    monkeypatch.setattr(tray_mod, "time", SimpleNamespace(monotonic=lambda: clock))
    icon._on_status("active")
    icon._on_progress(2580.0, 3240.0)

    assert isinstance(icon._remaining, Duration)
    assert icon._progress_stamp == MonotonicInstant(10.0)

    clock += 0.25
    assert icon._since_progress() == Duration(0.25)
    assert icon._shown_remaining() == 660.0
    assert icon._shown_elapsed() is None

    # Active credit only ages the countdown; absent observations stay absent.
    readings = iter((10.75,))
    monkeypatch.setattr(tray_mod, "time", SimpleNamespace(monotonic=lambda: next(readings)))
    assert icon._shown_remaining() == 659.0
    assert icon._shown_elapsed() is None


def test_position_signal_preserves_tray_labels_and_direction(tray):
    icon, client = tray
    client.observation = Duration(2580)
    for raw, label, direction in (
            ("sitting", "Sitting", "Standing up in 11m"),
            ("standing", "Standing", "Sitting down in 11m"),
            ("", "Custom", "11m left"),
            ("custom", "Custom", "11m left"),
            (" Future-POSITION \t", " future-position \t", "11m left"),
            ("SITTING", "Sitting", "11m left")):
        client.positionChanged.emit(raw)
        client.statusChanged.emit("active")
        client.progressChanged.emit(2580.0, 3240.0)
        held = label + " for about 43m" if raw in ("sitting", "standing") else label
        assert icon.toolTip().split("\n")[1:] == [held, direction]
        assert icon._status_action.text() == label + " · 11m left"


def test_status_signal_preserves_tray_actions_and_fallbacks(tray, monkeypatch):
    icon, client = tray
    dispatched = []
    monkeypatch.setattr(client, "pause", lambda: dispatched.append("pause"))
    monkeypatch.setattr(client, "resume", lambda: dispatched.append("resume"))
    standing_and_active(icon)

    for raw, label, _stopped, resume, visible in (
            ("move-failed", "Last move failed", False, False, True),
            ("paused", "Paused", True, True, True),
            ("snoozed", "Snoozed", True, True, True),
            ("held", "Paused — desk moved off sit/stand", True, False, True),
            ("disabled", "Automation off", True, False, False),
            (" Future Status ", " Future Status ", False, False, True),
            ("", "", False, False, True)):
        client.statusChanged.emit(raw)
        assert icon._status_action.text() == "Standing · " + label
        assert all(action.isVisible() is visible for action in icon._cycle_actions)
        assert icon._cycle_separator.isVisible() is visible
        assert icon._pause_action.text() == (
            "Resume automation" if resume else "Pause automation")
        icon._pause_action.trigger()
        assert dispatched[-1] == ("resume" if resume else "pause")
        lines = icon.toolTip().split("\n")
        assert lines[1] == "Standing for about 43m"
        if raw == "move-failed":
            assert lines[2] == "Last move failed · 11m left"
        elif raw == "snoozed":
            assert lines[2] == "Snoozed until later"
        else:
            assert lines[2] == label


def test_title_is_the_app_name_on_its_own(tray):
    # It used to be "Idasen Companion — Standing". The compound headline read
    # as a sentence fragment and put the state in the one field that is styled
    # as an identity, not a status.
    icon, _ = tray
    standing_and_active(icon)

    assert icon.toolTip().split("\n")[0] == "Idasen Companion"


def test_countdown_replaces_the_status_word(tray):
    # Deliberate: a visible countdown already proves automation is running, so
    # "Automation active" beside it was filler.
    icon, _ = tray
    standing_and_active(icon)

    assert "Automation active" not in icon.toolTip()


@pytest.mark.parametrize("status", ["paused", "snoozed", "disabled",
                                    "out-of-schedule", "unconfigured"])
def test_every_stopped_cycle_state_drops_it_not_just_pause(tray, status):
    # Existing state coverage now protects an independently fresh observation.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_status(status)

    assert icon.toolTip().split("\n")[1] == "Standing for about 43m"


@pytest.mark.parametrize("status", ["user-idle", "locked", "away"])
def test_a_merely_paused_accumulator_keeps_the_duration(tray, status):
    # Automation status never supplies or invalidates an observation itself;
    # the shared cache owns continuity and hard-boundary invalidation.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_status(status)

    assert icon.toolTip().split("\n")[1] == "Standing for about 43m"


def test_snoozed_tooltip_says_when_automation_resumes(tray):
    # The one question a snooze raises. Overview's exact wording, so the two
    # surfaces name one state one way.
    icon, client = tray
    standing_and_active(icon)
    icon._on_status("snoozed")
    client.set_snooze_until(datetime(2026, 8, 3, 14, 32).timestamp())

    assert icon.toolTip().split("\n")[2] == (
        "Snoozed until %s" % icon.window.ctx.fmt.clock(
            datetime(2026, 8, 3, 14, 32)))


def test_a_rebuilt_formatter_reaches_the_next_tooltip_redraw(tray):
    """The clock format applies on Apply, and this is the whole mechanism:
    `AppContext.write_config` rebuilds `ctx.fmt`, and the tray reads that
    formatter fresh at every redraw instead of caching it. No new signal and
    no restart — so what is pinned here is that the surface re-reads, not
    that the helper formats correctly, which its own tests already own.
    """
    icon, client = tray
    standing_and_active(icon)
    icon._on_status("snoozed")
    deadline = datetime(2026, 8, 3, 14, 32)
    client.set_snooze_until(deadline.timestamp())
    assert "PM" not in icon.toolTip()

    context = icon.window.ctx.fmt.context
    icon.window.ctx.fmt = Formatter(dataclasses.replace(
        context, time_style=TimeStyle.HOUR_AND_MINUTE_12))
    client.set_snooze_until(deadline.timestamp())

    assert icon.toolTip().split("\n")[2] == "Snoozed until 2:32 PM"


def test_snoozed_tooltip_says_later_until_the_deadline_arrives(tray):
    # The client fetches SnoozeUntil asynchronously, so the status lands first
    # and the deadline follows. "Snoozed until 01:00" (the epoch) would be a
    # lie; "later" is merely vague.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_status("snoozed")

    assert icon.toolTip().split("\n")[2] == "Snoozed until later"


def test_deadline_arriving_redraws_the_tooltip(tray):
    # The subscription earns its place: without it the tooltip would sit on
    # "later" for the whole snooze.
    icon, client = tray
    standing_and_active(icon)
    icon._on_status("snoozed")
    assert "later" in icon.toolTip()

    client.set_snooze_until(datetime(2026, 8, 3, 9, 5).timestamp())

    assert icon.toolTip().split("\n")[2] == (
        "Snoozed until %s" % icon.window.ctx.fmt.clock(
            datetime(2026, 8, 3, 9, 5)))


def test_menu_entry_keeps_the_bare_word_while_snoozed(tray):
    # Deliberate asymmetry, not an oversight. "Standing · Snoozed until 14:32"
    # is 30 characters against the 20 the menu budgets, so it would widen every
    # row beneath it for as long as the snooze lasts. The deadline is one hover
    # away.
    icon, client = tray
    standing_and_active(icon)
    icon._on_status("snoozed")
    client.set_snooze_until(datetime(2026, 8, 3, 14, 32).timestamp())

    text = icon._status_action.text()

    assert text == "Standing · Snoozed"
    assert len(text) <= len("Skip next transition")


def test_position_stands_alone_before_any_progress_is_known(tray):
    # No progress push yet, so there is no duration to report and
    # "Standing for 0m" would be a claim we cannot back.
    icon, _ = tray
    icon._on_position("standing")
    icon._on_status("active")

    assert icon.toolTip().split("\n")[1] == "Standing"


def test_menu_entry_is_short_and_on_one_line(tray):
    # Two guards at once. The text labels a QAction, which cannot render a
    # second line — and a menu's width is set by its longest item, so the
    # heading must not outgrow the actions beneath it (the longest of which,
    # "Skip next transition", is 20 characters).
    icon, _ = tray
    standing_and_active(icon)

    text = icon._status_action.text()

    assert text == "Standing · 11m left"
    assert "\n" not in text
    assert len(text) <= len("Skip next transition")


def test_menu_entry_stays_short_in_a_bad_state(tray):
    # The regression that motivated splitting the menu line from the tooltip:
    # appending a status word to an elapsed clause was longest precisely when
    # something was wrong, so the menu jumped wider exactly when you opened it
    # to fix that.
    icon, _ = tray
    standing_and_active(icon)

    for status in ("paused", "snoozed", "disabled", "move-failed"):
        icon._on_status(status)
        text = icon._status_action.text()
        assert "\n" not in text
        assert text.startswith("Standing · ")


def test_no_line_ends_with_a_stranded_separator(tray):
    # The original bug: Plasma wrapped after the "·", so a line ended on it.
    icon, _ = tray
    standing_and_active(icon)

    for line in icon.toolTip().split("\n"):
        assert not line.rstrip().endswith("·"), line


def test_today_summary_is_still_the_last_line(tray_with_stats):
    icon, _ = tray_with_stats
    standing_and_active(icon)

    assert icon.toolTip().split("\n") == ["Idasen Companion",
                                          "Standing for about 43m",
                                          "Sitting down in 11m",
                                          "Today: 1h 58m sitting / 50m standing"]


def test_final_minute_is_counted_in_seconds(tray):
    # fmt_hm floors, so the whole last minute used to read "0m" — and the tray
    # is the surface you check *because* the move is close.
    icon, _ = tray
    icon._on_position("standing")
    icon._on_status("active")
    icon._on_progress(3195.0, 3240.0)

    assert icon.toolTip().split("\n")[2] == "Sitting down in 45s"
    assert icon._status_action.text() == "Standing · 45s left"


def test_a_minute_exactly_is_still_a_minute(tray):
    # The handover between the two bands. "60s" would be a third spelling of
    # the same instant, so the seconds band stops one second short of it.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_progress(3180.0, 3240.0)

    assert icon.toolTip().split("\n")[2] == "Sitting down in 1m"


def test_a_spent_countdown_says_due_now_rather_than_disappearing(tray):
    # Both halves of the original bug. The clause used to be guarded by a
    # falsy check on a float, so at exactly 0.0 the countdown didn't reach
    # "0m" — it vanished, and the tooltip fell back to the bare status word.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_progress(3240.0, 3240.0)

    assert icon.toolTip().split("\n")[2] == "Due now"
    assert icon._status_action.text() == "Standing · Due now"


def test_due_now_is_reserved_for_zero(tray):
    # Not widened to cover the last minute: "Due now" promises immediacy and
    # is already optimistic (the move still waits on the next tick and the
    # recent-input gate), so a second of it is as much as it can back.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_progress(3239.0, 3240.0)

    assert icon.toolTip().split("\n")[2] == "Sitting down in 1s"


def test_a_failed_move_keeps_its_countdown_at_zero_too(tray):
    # The cycle keeps running through a failure, so the same guard applied to
    # the same clause on this line.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_status("move-failed")
    icon._on_progress(3240.0, 3240.0)

    assert icon.toolTip().split("\n")[2] == "Last move failed · Due now"


def test_first_minute_in_a_position_is_counted_in_seconds(tray):
    # The same flooring on the other side of the cycle: "Standing for 0m" for
    # the first minute after every transition.
    icon, _ = tray
    icon.client.observation = Duration(12)
    icon._on_position("standing")
    icon._on_status("active")
    icon._on_progress(12.0, 3240.0)

    assert icon.toolTip().split("\n")[1] == "Standing for about 12s"


def test_countdown_ticks_between_daemon_pushes(tray):
    # The daemon speaks once a check_interval (60s by default), which is far
    # too coarse for a seconds display — so the tray ages the last number it
    # was given, the way Overview already does.
    icon, _ = tray
    standing_and_active(icon)
    icon._progress_stamp -= Duration(630.0)

    icon._tick()

    lines = icon.toolTip().split("\n")
    assert lines[1] == "Standing for about 43m"
    assert lines[2] == "Sitting down in 30s"


def test_ticking_does_not_re_ask_the_daemon_for_the_day_totals(tray_with_stats):
    # _today_summary is a blocking D-Bus call. Once per push is fine; once per
    # second is not, so the ticker reuses the cached line — which must still
    # be there.
    icon, client = tray_with_stats
    standing_and_active(icon)
    icon._progress_stamp -= Duration(630.0)
    before = client.stats_calls

    icon._tick()

    assert client.stats_calls == before
    assert icon.toolTip().split("\n")[3] == (
        "Today: 1h 58m sitting / 50m standing")


@pytest.mark.parametrize("status", ["paused", " Future Status ", ""])
def test_ticker_does_no_work_when_there_is_no_countdown(tray, status):
    # No countdown does not mean no observation. Repaint without statistics
    # I/O so valid observations age and expired observations disappear.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_status(status)
    renders = []
    icon._refresh_texts = lambda *a, **kw: renders.append(kw)

    icon._tick()
    assert renders == [{"stats": False}]

    # Set directly: _on_status would re-render through the spy itself.
    icon._status = Status.ACTIVE
    icon._progress_stamp -= Duration(660.0)
    icon._tick()
    assert renders == [{"stats": False}, {"stats": False}]


def test_connecting_is_a_single_status_line(tray):
    # One clause, and nothing else is known yet — no position, no countdown.
    icon, _ = tray
    icon._on_connected(False)
    icon._on_moving(False)

    icon._run_action("toggle")

    assert icon._status_action.text() == "Connecting…"
    assert icon.toolTip() == "Idasen Companion\nConnecting…"
