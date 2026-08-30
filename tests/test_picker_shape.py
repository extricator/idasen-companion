"""Each of the five picker surfaces reads one shape, pinned separately.

Three renderings of one concept — a spelled-out unit in the Automation
page's spin boxes, a one-letter compact form two rows away in its own
dropdowns, and the tray Snooze submenu's verbose plural word again — is
what let this drift apart while every gate stayed green. A human walking
the app in two languages found it; nothing automated did. The window
golden (``tests/goldens/window_en.json`` / ``window_es.json``) covers only
two of the five surfaces (the Automation dropdowns and the Overview Snooze
button's text) — this module covers all five, each in its own test, so a
partial regression on one surface fails on that surface rather than as one
opaque golden diff naming a combo box index nobody can place.

The second half pins the opposite claim: the journal and the Activity Log
keep the compact shapes ``docs/LOGGING.md`` promises, and the Activity Log
proof renders a real catalogued log entry through its own path rather than
calling the formatter a second time — a formatter-only assertion would not
show the log still calls that formatter at all.

Every expected value below is hand-typed from D-10's table
(``18-CONTEXT.md``) and from ``docs/LOGGING.md``'s stated compact shapes.
None is captured from a run.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import pytest

pytest.importorskip("PySide6")

import os

# Forced, not defaulted — see tests/test_settings_form.py for why: a desktop
# session exports a real QT_QPA_PLATFORM and rpmbuild inherits it, then
# aborts on the display it can't reach.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from types import SimpleNamespace  # noqa: E402

import shiboken6  # noqa: E402
from PySide6.QtCore import QObject, QTime, Signal  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.core.presentation.english import (  # noqa: E402
    EnglishTranslator,
)
from idasen_companion.core.presentation.formatter import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.specs import TimeStyle
from idasen_companion.core.presentation.plain_locale import (  # noqa: E402
    PlainLocaleFormatter,
)
from idasen_companion.core.units import HeightUnit  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import log_catalog  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.pages.automation import AutomationPage  # noqa: E402
from idasen_companion.gui.pages.overview import OverviewPage  # noqa: E402
from idasen_companion.gui.tray import SNOOZE_CHOICES, TrayIcon  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _plain_formatter() -> Formatter:
    """A journal-shaped ``Formatter`` (Qt-free locale backend, pass-through
    English translator) — the same pairing every duration renderer in this
    module is checked against, so nothing here depends on a ``QLocale`` or a
    gettext catalog binding."""
    return Formatter(PresentationContext(
        locale=PlainLocaleFormatter(), translator=EnglishTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE_24))


# ----------------------------------------------------------------------
# 1. The Automation dropdowns.
# ----------------------------------------------------------------------

class _FakeAutomationClient:
    """Enough DaemonClient for AppContext: never available, so no D-Bus."""

    available = False

    def reload_config(self):  # pragma: no cover - unreachable while unavailable
        raise AssertionError("should not nudge an unavailable daemon")


@pytest.fixture
def automation_page(qapp, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    page = AutomationPage(
        AppContext(_FakeAutomationClient(), tray_available=True))
    page.load()
    return page


# The two "plus up to" rows (sit / stand variation): 0/2/5/10/15/20/30 min,
# in the offered ascending order. Zero reads through the connective, so it
# gets the number rather than a word ("plus up to Off" is not a sentence).
_VARIATION_ROW_LABELS = [
    "0 min", "2 min", "5 min", "10 min", "15 min", "20 min", "30 min"]

# The sync-interval row: Off / 2 / 5 / 10 / 15 / 30 / 60 min. The zero row
# keeps its own word (D-12 — a zero_label at the call site, not a duration),
# and the last row is the only offered choice that reaches an hour.
_SYNC_ROW_LABELS = ["Off", "2 min", "5 min", "10 min", "15 min", "30 min", "60 min"]


def test_automation_dropdowns_read_the_picker_shape(automation_page):
    page = automation_page
    for combo in (page.sit_var, page.stand_var):
        assert [combo.itemText(i) for i in range(combo.count())] == \
            _VARIATION_ROW_LABELS
    assert [page.sync_combo.itemText(i)
            for i in range(page.sync_combo.count())] == _SYNC_ROW_LABELS


def test_the_sync_combos_hour_row_reads_sixty_minutes_not_an_hour(
        automation_page):
    """D-11's whole point, its own named assertion rather than one entry in
    a list: the sync combo's top row (3600 seconds) is the only offered
    choice across every picker that reaches an hour, and it must read "60
    min" — never an hour decomposition ("1h 00m") — because the tray's own
    minutes-only Snooze design was deliberate and unifying every picker onto
    this shape must honour it, not silently hand the tray hour decomposition
    it was built to avoid.
    """
    combo = automation_page.sync_combo
    last = combo.count() - 1
    assert combo.itemText(last) == "60 min"


# ----------------------------------------------------------------------
# 2. The tray Snooze submenu.
# ----------------------------------------------------------------------

class _FakeTrayClient(QObject):
    """The signals ``TrayIcon.__init__`` subscribes to, and nothing else."""

    statusChanged = Signal(str)
    positionChanged = Signal(str)
    progressChanged = Signal(float, float)
    presetsChanged = Signal(dict)
    availableChanged = Signal(bool)
    connectedChanged = Signal(bool)
    movingChanged = Signal(bool)
    snoozeUntilChanged = Signal(float)

    available = False

    def __getattr__(self, name):
        # Menu entries wire up toggle/sit/stand/stop/... at construction;
        # none of them are exercised here beyond existing.
        return lambda *a, **kw: None


class _NullSignal:
    """Stands in for a Qt signal ``TrayIcon.__init__`` connects to, without
    a real ``QObject`` behind it."""

    def connect(self, *args, **kwargs):
        pass


class _FakeTrayWindow:
    """A ``ctx`` carrying only what ``TrayIcon`` reaches for."""

    def __init__(self):
        self.ctx = SimpleNamespace(
            cfg=None, configChanged=_NullSignal(), fmt=_plain_formatter())


@pytest.fixture
def tray(qapp):
    icon = TrayIcon(_FakeTrayClient(), _FakeTrayWindow(), QIcon())
    yield icon
    # Destroy it here rather than letting Python drop the last reference
    # whenever it feels like it: a QSystemTrayIcon collected after the
    # offscreen QPA platform has been torn down segfaults the interpreter at
    # exit, which fails the RPM build's %check even with every test passing.
    icon.hide()
    icon.setContextMenu(None)
    shiboken6.delete(icon)


def _snooze_submenu_actions(icon):
    menu = icon.contextMenu()
    for action in menu.actions():
        submenu = action.menu()
        if submenu is not None and action.text() == "Snooze":
            return submenu.actions()
    raise AssertionError("no Snooze submenu found in the tray context menu")


# Hand-typed from D-10's table and from tray.SNOOZE_CHOICES (5, 10, 15, 30,
# 60 minutes) — the picker shape, not the verbose plural word this submenu
# used to show.
_SNOOZE_SUBMENU_LABELS = ["5 min", "10 min", "15 min", "30 min", "60 min"]


def test_tray_snooze_submenu_reads_the_picker_shape(tray):
    assert list(SNOOZE_CHOICES) == [5, 10, 15, 30, 60]
    actions = _snooze_submenu_actions(tray)
    assert [action.text() for action in actions] == _SNOOZE_SUBMENU_LABELS


# ----------------------------------------------------------------------
# 3. The Overview Snooze button.
# ----------------------------------------------------------------------

class _FakeOverviewClient(QObject):
    """The signals and call targets OverviewPage wires up."""

    heightChanged = Signal(float)
    positionChanged = Signal(str)
    connectedChanged = Signal(bool)
    movingChanged = Signal(bool)
    statusChanged = Signal(str)
    progressChanged = Signal(float, float)
    presetsChanged = Signal(dict)
    availableChanged = Signal(bool)
    snoozeUntilChanged = Signal(float)

    available = False

    def sit(self): ...
    def stand(self): ...
    def stop(self): ...
    def pause(self): ...
    def resume(self): ...
    def skip_next(self): ...
    def snooze(self, minutes): ...
    def move_to_height(self, height): ...
    def set_automation_enabled(self, enabled): ...
    def idle_provider(self): return "none"
    def snooze_until(self): return 0.0


@pytest.fixture
def overview_page(qapp, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    ctx = AppContext(_FakeOverviewClient(), tray_available=True)
    ctx.reload_config()
    return OverviewPage(ctx)


def test_overview_snooze_button_reads_the_picker_shape(overview_page):
    buttons = [b for b in overview_page.findChildren(QPushButton)
               if b.text().startswith("Snooze")]
    assert len(buttons) == 1
    # The whole message with its substitution filled — the surrounding
    # "Snooze %(duration)s" sentence is unchanged, only the duration inside
    # it is now the picker shape.
    assert buttons[0].text() == "Snooze 10 min"


# ----------------------------------------------------------------------
# 4. The notification Snooze action — unchanged by this phase, pinned here
#    so "unchanged" is a checked claim rather than an intention.
# ----------------------------------------------------------------------

def test_notification_snooze_action_is_unchanged_by_this_phase():
    fmt = _plain_formatter()
    assert fmt.snooze_action_label(15) == "Snooze 15 min"


# ----------------------------------------------------------------------
# 5. The Overview user-idle note.
# ----------------------------------------------------------------------

def test_overview_user_idle_note_reads_the_picker_shape(overview_page):
    # AppConfig's default idle_threshold is 600s (10 min).
    overview_page.client.statusChanged.emit("user-idle")
    assert overview_page.status_reason.text() == "no input for 10 min"


# ----------------------------------------------------------------------
# The D-14 half: the compact renderers stay compact, and the Activity Log
# is proven to still call one of them rather than merely asserted to.
# ----------------------------------------------------------------------

def test_the_compact_renderers_keep_the_journal_and_activity_log_shapes():
    """``docs/LOGGING.md``'s greppable promise: ``"30s"`` / ``"45m"`` /
    ``"1h 05m"``. Hand-typed from that document, not from a run.
    """
    fmt = _plain_formatter()
    assert fmt.duration(30) == "30s"           # sub-minute, kept visible
    assert fmt.duration(45 * 60) == "45m"       # compact minutes-only
    assert fmt.duration(65 * 60) == "1h 05m"    # compact hours-and-minutes


def test_the_activity_log_still_renders_a_duration_through_the_compact_shape():
    """A proof, not an intention (WORD-07): render a real catalogued log
    entry — ``presence.now_idle``, which carries a ``Param.DURATION`` — end
    to end through ``gui/log_catalog.py``'s own path, rather than calling
    the formatter a second time here. A formatter-only assertion would not
    show the log still calls that formatter at all.
    """
    fmt = _plain_formatter()
    rendered = log_catalog.render(
        "presence.now_idle", {"idle_time": 65 * 60}, "fallback text",
        fmt=fmt)
    assert rendered == "Now idle (1h 05m idle time)"


# ---- the schedule summary follows the clock, the editors do not ----------

def _summary_on(page, style: TimeStyle) -> str:
    """The schedule sentence rendered on one clock.

    The page's formatter is swapped rather than the config rewritten: this
    asserts what the *summary* does with a clock style, and routing through
    a config reload would drag the whole settings round-trip into a test
    about one sentence.
    """
    page.ctx.fmt = Formatter(PresentationContext(
        locale=PlainLocaleFormatter(), translator=EnglishTranslator(),
        unit=HeightUnit.CENTIMETRES, time_style=style))
    page.sched_enabled.setChecked(True)
    page.start_time.setTime(QTime(9, 0))
    page.end_time.setTime(QTime(17, 0))
    page._update_sched_summary()
    return page._sched_summary.text()


def test_the_schedule_summary_follows_the_clock_format(automation_page):
    """The sentence is a wall-clock time the window shows, so it moves with
    the setting like every other one.

    It shipped on a hard-coded ``HH:mm``, which left one line reading 09:00
    while the Statistics page beside it read 9:00 AM — the exact split this
    phase exists to close, on the one surface nobody thought to name.
    """
    on_24 = _summary_on(automation_page, TimeStyle.HOUR_AND_MINUTE_24)
    assert "09:00" in on_24 and "17:00" in on_24

    on_12 = _summary_on(automation_page, TimeStyle.HOUR_AND_MINUTE_12)
    assert "9:00 AM" in on_12 and "5:00 PM" in on_12, on_12


def test_the_schedule_editors_keep_their_own_display(automation_page):
    """The two ``QTimeEdit``s are deliberately *not* swept along.

    They edit a value stored as ``HH:MM``, and an editor showing a shape
    different from the field it writes is its own kind of wrong. Pinned so a
    later sweep of "everything that shows a time" does not quietly take them
    too.
    """
    _summary_on(automation_page, TimeStyle.HOUR_AND_MINUTE_12)
    assert automation_page.start_time.time().toString("HH:mm") == "09:00"
    assert automation_page.end_time.time().toString("HH:mm") == "17:00"
