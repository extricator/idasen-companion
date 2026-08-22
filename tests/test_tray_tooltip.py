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
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.presentation.english import EnglishTranslator  # noqa: E402
from idasen_companion.core.presentation.formatter import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.plain_locale import (  # noqa: E402
    PlainLocaleFormatter,
)
from idasen_companion.core.units import HeightUnit  # noqa: E402
from idasen_companion.gui.tray import TrayIcon  # noqa: E402
from idasen_companion.gui.util import fmt_clock  # noqa: E402


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

    def __init__(self, available=False, daily_rows=()):
        super().__init__()
        self._snooze_until = 0.0
        self.stats_calls = 0
        # An instance attribute, not the class-level ``available = False`` the
        # other tray tests get away with: _today_summary returns "" outright
        # when the daemon is unavailable, so the summary line is unreachable
        # without this.
        self.available = available
        self.daily_rows = list(daily_rows)

    def get_daily_stats(self, start, end):
        # A real method rather than the __getattr__ fallback below, which
        # returns None — and _today_summary iterates the result. Counted
        # because the real one is a blocking D-Bus round trip, and the tray
        # now re-renders once a second.
        self.stats_calls += 1
        return self.daily_rows

    def snooze_until(self):
        # Also real: the fallback returns None, and the tray formats this.
        return self._snooze_until

    def set_snooze_until(self, value):
        """Announce a deadline the way the real client does — after the status.

        Test-only helper; ``DaemonClient`` does this from its async property
        fetch (``dbus_client.py`` ``_set_snooze_until``).
        """
        self._snooze_until = value
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
                locale=PlainLocaleFormatter(), translator=EnglishTranslator(),
                unit=HeightUnit.CENTIMETRES)))


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


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
    icon._on_status("active")
    icon._on_progress(2580.0, 3240.0)


def test_title_is_the_app_name_on_its_own(tray):
    # It used to be "Idasen Companion — Standing". The compound headline read
    # as a sentence fragment and put the state in the one field that is styled
    # as an identity, not a status.
    icon, _ = tray
    standing_and_active(icon)

    assert icon.toolTip().split("\n")[0] == "Idasen Companion"


def test_held_position_and_next_change_are_separate_lines(tray):
    icon, _ = tray
    standing_and_active(icon)

    lines = icon.toolTip().split("\n")

    assert lines[1] == "Standing for 43m"
    assert lines[2] == "Sitting down in 11m"


def test_next_change_names_the_direction_it_is_heading(tray):
    # Sitting means the next event is standing up — the same wording the
    # daemon's pre-move notification uses, so one event is named one way.
    icon, _ = tray
    icon._on_position("sitting")
    icon._on_status("active")
    icon._on_progress(2580.0, 3240.0)

    assert icon.toolTip().split("\n")[2] == "Standing up in 11m"


def test_countdown_replaces_the_status_word(tray):
    # Deliberate: a visible countdown already proves automation is running, so
    # "Automation active" beside it was filler.
    icon, _ = tray
    standing_and_active(icon)

    assert "Automation active" not in icon.toolTip()


def test_status_word_returns_when_there_is_no_countdown(tray):
    # ...and it earns its place here, where nothing else explains the state.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_status("paused")

    assert icon.toolTip().split("\n")[2] == "Paused"


def test_a_stopped_cycle_drops_the_held_duration(tray):
    # The duration is active time, not time in the position: once the cycle
    # stops running down the machine stops crediting it, so it would stand at
    # the same number for the whole pause while reading like a running clock.
    icon, _ = tray
    standing_and_active(icon)
    assert icon.toolTip().split("\n")[1] == "Standing for 43m"

    icon._on_status("paused")
    assert icon.toolTip().split("\n")[1] == "Standing"


@pytest.mark.parametrize("status", ["paused", "snoozed", "disabled",
                                    "out-of-schedule", "unconfigured"])
def test_every_stopped_cycle_state_drops_it_not_just_pause(tray, status):
    # One rule, taken from the machine's own NO_CYCLE_STATUSES. Hiding it for
    # a pause but not a snooze would leave the same stopped clock on screen.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_status(status)

    assert icon.toolTip().split("\n")[1] == "Standing"


@pytest.mark.parametrize("status", ["user-idle", "locked", "away"])
def test_a_merely_paused_accumulator_keeps_the_duration(tray, status):
    # Idle, lock and away stop the accumulator too, but the cycle is still
    # this one and the freeze ends when the user comes back — stale, not
    # meaningless. Dropping it here would flicker the line on every absence.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_status(status)

    assert icon.toolTip().split("\n")[1] == "Standing for 43m"


def test_snoozed_tooltip_says_when_automation_resumes(tray):
    # The one question a snooze raises. Overview's exact wording, so the two
    # surfaces name one state one way.
    icon, client = tray
    standing_and_active(icon)
    icon._on_status("snoozed")
    client.set_snooze_until(datetime(2026, 8, 3, 14, 32).timestamp())

    assert icon.toolTip().split("\n")[2] == (
        "Snoozed until %s" % fmt_clock(datetime(2026, 8, 3, 14, 32)))


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
        "Snoozed until %s" % fmt_clock(datetime(2026, 8, 3, 9, 5)))


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


def test_menu_entry_keeps_the_position_when_not_active(tray):
    # A status word must not take the whole line: knowing where the desk is
    # matters most when you are about to press Sit or Stand.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_status("paused")

    assert icon._status_action.text() == "Standing · Paused"


def test_menu_entry_names_the_failure_over_the_countdown(tray):
    # A failed move still has a countdown running, but the failure is the thing
    # worth the one line the menu gets.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_status("move-failed")

    assert icon._status_action.text() == "Standing · Last move failed"


def test_no_line_ends_with_a_stranded_separator(tray):
    # The original bug: Plasma wrapped after the "·", so a line ended on it.
    icon, _ = tray
    standing_and_active(icon)

    for line in icon.toolTip().split("\n"):
        assert not line.rstrip().endswith("·"), line


def test_empty_position_falls_back_to_custom(tray):
    # Held off sit/stand. "Custom" mirrors the Overview title, and with no
    # sit/stand to head towards the countdown loses its direction word.
    icon, _ = tray
    icon._on_position("")
    icon._on_status("active")
    icon._on_progress(2580.0, 3240.0)

    lines = icon.toolTip().split("\n")

    assert lines[1] == "Custom for 43m"
    assert lines[2] == "11m left"


def test_today_summary_is_still_the_last_line(tray_with_stats):
    icon, _ = tray_with_stats
    standing_and_active(icon)

    assert icon.toolTip().split("\n") == ["Idasen Companion",
                                          "Standing for 43m",
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
    icon._on_position("standing")
    icon._on_status("active")
    icon._on_progress(12.0, 3240.0)

    assert icon.toolTip().split("\n")[1] == "Standing for 12s"


def test_countdown_ticks_between_daemon_pushes(tray):
    # The daemon speaks once a check_interval (60s by default), which is far
    # too coarse for a seconds display — so the tray ages the last number it
    # was given, the way Overview already does.
    icon, _ = tray
    standing_and_active(icon)
    icon._progress_stamp -= 630.0

    icon._tick()

    lines = icon.toolTip().split("\n")
    assert lines[1] == "Standing for 53m"
    assert lines[2] == "Sitting down in 30s"


def test_ticking_does_not_re_ask_the_daemon_for_the_day_totals(tray_with_stats):
    # _today_summary is a blocking D-Bus call. Once per push is fine; once per
    # second is not, so the ticker reuses the cached line — which must still
    # be there.
    icon, client = tray_with_stats
    standing_and_active(icon)
    icon._progress_stamp -= 630.0
    before = client.stats_calls

    icon._tick()

    assert client.stats_calls == before
    assert icon.toolTip().split("\n")[3] == (
        "Today: 1h 58m sitting / 50m standing")


def test_ticker_does_no_work_when_there_is_no_countdown(tray):
    # It runs for the life of the tray, so the two states that have nothing to
    # age — no countdown showing, and a cycle already spent — must cost a
    # comparison rather than a re-render.
    icon, _ = tray
    standing_and_active(icon)
    icon._on_status("paused")
    renders = []
    icon._refresh_texts = lambda *a, **kw: renders.append(1)

    icon._tick()
    assert renders == []

    # Set directly: _on_status would re-render through the spy itself.
    icon._status = "active"
    icon._progress_stamp -= 660.0
    icon._tick()
    assert renders == []


def test_connecting_is_a_single_status_line(tray):
    # One clause, and nothing else is known yet — no position, no countdown.
    icon, _ = tray
    icon._on_connected(False)
    icon._on_moving(False)

    icon._run_action("toggle")

    assert icon._status_action.text() == "Connecting…"
    assert icon.toolTip() == "Idasen Companion\nConnecting…"
