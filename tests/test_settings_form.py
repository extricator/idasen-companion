"""The settings-class pages' staged-edit footer.

Covers what ``SettingsFormPage`` promises: edits stay in the widgets until
Apply, Apply/Reset light up only when something actually differs from disk,
and Restore Defaults stages the shipped defaults while leaving the Bluetooth
address — which identifies the user's hardware, not a preference — alone.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import pytest

pytest.importorskip("PySide6")

import os

# Forced, not defaulted. A desktop session exports QT_QPA_PLATFORM (xcb here),
# which the RPM build inherits — and then aborts, because the build sandbox
# can't reach that display. Tests must not depend on an ambient one.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from language_context import installed_language as _language  # noqa: E402
from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import context as context_mod, service_ctl  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.main_window import MainWindow  # noqa: E402
from idasen_companion.gui.pages.automation import AutomationPage  # noqa: E402
from idasen_companion.gui.pages.settings import SettingsPage  # noqa: E402

MAC = "E1:B2:C3:D4:E5:F6"


class FakeClient:
    """Enough DaemonClient for AppContext: never available, so no D-Bus."""

    available = False

    def reload_config(self):  # pragma: no cover - unreachable while unavailable
        raise AssertionError("should not nudge an unavailable daemon")


class WindowClient(QObject):
    """Every signal the real main window and its preloaded pages consume."""

    availableChanged = Signal(bool)
    heightChanged = Signal(float)
    positionChanged = Signal(str)
    connectedChanged = Signal(bool)
    movingChanged = Signal(bool)
    statusChanged = Signal(str)
    progressChanged = Signal(float, float)
    transitionCompleted = Signal(str, str, bool)
    snoozeUntilChanged = Signal(float)
    presetsChanged = Signal(dict)
    logEntry = Signal(float, str, str, str, dict, str)
    commandFailed = Signal(str, str)

    available = False

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    cfg = AppConfig()
    cfg.desk.mac = MAC
    save_config(cfg, path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    return AppContext(FakeClient(), tray_available=True)


def _edit(page):
    """Make one arbitrary change to a page, whichever page it is."""
    spin = page.linger_spin if isinstance(page, SettingsPage) else page.sit_dur
    spin.setValue(spin.value() + 7)


@pytest.fixture(params=[SettingsPage, AutomationPage],
                ids=["settings", "automation"])
def page(request, ctx):
    page = request.param(ctx)
    page.load()
    return page


def test_a_freshly_loaded_page_is_clean(page):
    assert not page.is_dirty()
    assert not page._apply_btn.isEnabled()
    assert not page._reset_btn.isEnabled()


def test_settings_page_never_owns_unknown_config_dialogs(
        ctx, monkeypatch):
    path = context_mod.DEFAULT_CONFIG_PATH
    with path.open("a") as stream:
        stream.write('\n[ui.future_palette]\naccent = "violet"\n')
    shown = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *args: shown.append(args)))

    page = SettingsPage(ctx)
    page.load()

    assert shown == []


@pytest.mark.parametrize("language", ["en", "es"])
def test_main_window_aggregates_and_remembers_unknown_config_warnings(
        qapp, tmp_path, monkeypatch, language):
    path = tmp_path / "config.toml"
    initial = (
        'future_root = "kept"\n'
        '[ui]\n'
        f'language = "{language}"\n'
        'future_theme = "violet"\n'
    )
    path.write_text(initial)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    monkeypatch.setattr(
        service_ctl, "autostart_state",
        lambda: service_ctl.AutostartState("enabled", True, ""))

    shown = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *args: shown.append(args)))

    with _language(language):
        window = MainWindow(WindowClient(), tray_available=True)
        try:
            assert len(shown) == 1
            body = shown[0][2]
            assert body.count("future_root") == 1
            assert body.count("future_theme") == 1
            assert body.index("future_root") < body.index("future_theme")

            # Both pages were preloaded by MainWindow. Navigating to each
            # reloads the same file and must not create another modal.
            window._nav.setCurrentRow(1)  # pylint: disable=protected-access
            window._nav.setCurrentRow(5)  # pylint: disable=protected-access
            assert len(shown) == 1

            path.write_text(initial + '\n[future]\nvalue = 7\n')
            window.settings.load()
            assert len(shown) == 2
            assert "[future]" in shown[1][2]
            assert "future_root" not in shown[1][2]
            assert "future_theme" not in shown[1][2]

            window.settings.load()
            assert len(shown) == 2

            # Seen fingerprints remain remembered even if one disappears and
            # is later reintroduced during this GUI process.
            path.write_text(initial)
            window.settings.load()
            path.write_text(initial + '\n[future]\nvalue = 7\n')
            window.settings.load()
            assert len(shown) == 2
        finally:
            window.close()


def test_editing_a_field_enables_apply_and_reset(page):
    _edit(page)
    assert page.is_dirty()
    assert page._apply_btn.isEnabled()
    assert page._reset_btn.isEnabled()


def test_an_edit_is_not_written_until_apply(page, ctx):
    from idasen_companion.core.config import load_config

    # Compare the file's *bytes*, not load_config(...) == ctx.cfg: staging
    # edits widgets without mutating ctx.cfg, so that comparison held equally
    # well if staging had written to disk.
    before = context_mod.DEFAULT_CONFIG_PATH.read_text()
    _edit(page)
    assert context_mod.DEFAULT_CONFIG_PATH.read_text() == before, (
        "staging must not touch the file")
    page._apply_settings()
    assert context_mod.DEFAULT_CONFIG_PATH.read_text() != before, (
        "apply did not reach the file")
    assert load_config(context_mod.DEFAULT_CONFIG_PATH) == ctx.cfg


def test_apply_greys_the_footer_back_out(page):
    _edit(page)
    page._apply_settings()
    assert not page.is_dirty()
    assert not page._apply_btn.isEnabled()
    assert not page._reset_btn.isEnabled()


def test_reset_throws_the_staged_edit_away(page):
    _edit(page)
    page.load()
    assert not page.is_dirty()


def test_restore_defaults_stages_without_writing(page, ctx):
    _edit(page)
    page._apply_settings()
    before = ctx.cfg.automation.sit_duration, ctx.cfg.desk.linger
    page._restore_defaults()
    assert page.is_dirty(), "defaults are staged, so Apply must light up"
    assert (ctx.cfg.automation.sit_duration, ctx.cfg.desk.linger) == before


def test_restore_defaults_is_undone_by_reset(page, ctx):
    _edit(page)
    page._apply_settings()
    changed = ctx.cfg.automation.sit_duration, ctx.cfg.desk.linger
    page._restore_defaults()
    page.load()
    assert not page.is_dirty()
    assert (ctx.cfg.automation.sit_duration, ctx.cfg.desk.linger) == changed


def test_restore_defaults_dims_once_the_page_is_at_defaults(page):
    assert not page._defaults_btn.isEnabled(), "shipped config is the defaults"
    _edit(page)
    assert page._defaults_btn.isEnabled()
    page._restore_defaults()
    assert not page._defaults_btn.isEnabled()


def test_restore_defaults_keeps_the_bluetooth_address(ctx):
    page = SettingsPage(ctx)
    page.load()
    page.linger_spin.setValue(99)
    page._restore_defaults()
    page._apply_settings()
    assert ctx.cfg.desk.mac == MAC
    assert ctx.cfg.desk.linger == AppConfig().desk.linger


def test_restore_defaults_keeps_an_unapplied_address_edit(ctx):
    """The address is not this button's business, edited or not."""
    page = SettingsPage(ctx)
    page.load()
    page.mac_edit.setText("AA:BB:CC:DD:EE:FF")
    page._restore_defaults()
    assert page.mac_edit.text() == "AA:BB:CC:DD:EE:FF"


def test_a_half_typed_address_refuses_the_apply(ctx, silent_dialogs):
    page = SettingsPage(ctx)
    page.load()
    page.mac_edit.setText("AA:BB")
    assert page._validate() is not None
    # The load-bearing half: apply_edits reports failure, which is what makes
    # the shell abandon the navigation instead of the edit.
    assert page.apply_edits() is False
    assert page.is_dirty()
    assert ctx.cfg.desk.mac == MAC


@pytest.fixture
def silent_dialogs(monkeypatch):
    """Swallow the modal warnings, which would otherwise block the run."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **kw: None))


# A config the widgets cannot represent exactly is still a *valid* config, and
# must not read as an edit the user made. Each of these round-trips lossily
# through the page: minute spin boxes, weekday-ordered day chips, QTimeEdit's
# zero-padding, and the address field's upper-casing input mask.
@pytest.mark.parametrize("field, value, page_cls", [
    ("automation.recent_input_threshold", 90, AutomationPage),
    ("automation.sit_duration", 45 * 60 + 30, AutomationPage),
    ("schedule.days", ["fri", "mon"], AutomationPage),
    ("schedule.start", "9:00", AutomationPage),
    ("desk.mac", "e1:b2:c3:d4:e5:f6", SettingsPage),
])
def test_a_lossy_config_does_not_read_as_an_edit(
        qapp, tmp_path, monkeypatch, field, value, page_cls):
    from idasen_companion.core.config import save_config as _save

    cfg = AppConfig()
    cfg.desk.mac = MAC
    section, name = field.split(".")
    setattr(getattr(cfg, section), name, value)
    path = tmp_path / "config.toml"
    _save(cfg, path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)

    page = page_cls(AppContext(FakeClient(), tray_available=True))
    page.load()
    assert not page.is_dirty()
    assert not page._apply_btn.isEnabled()


def test_a_failed_save_keeps_the_page_dirty(page, ctx, monkeypatch,
                                            silent_dialogs):
    """A write that never reached the disk must not look like a save.

    write_config mutates cfg before saving, so the in-memory config already
    holds the failed values — measuring against it would grey the footer out
    and strand the edit with no way to retry.
    """
    _edit(page)

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(context_mod, "save_config", boom)
    assert page.apply_edits() is False
    assert page.is_dirty()
    assert page._apply_btn.isEnabled()
    assert page._reset_btn.isEnabled()


# ---- the Clock format row ---------------------------------------------------
#
# Asserted on the combo's *data* values throughout, never its visible labels:
# the labels are catalog entries, already covered by the catalog tests, and
# pinning them here would go red on a translation change that broke nothing.


def test_the_clock_format_row_offers_the_three_config_values_in_order(ctx):
    page = SettingsPage(ctx)
    page.load()
    combo = page.clock_format_combo
    assert [combo.itemData(i) for i in range(combo.count())] == [
        "system", "12", "24"]


def _store_clock_format(value: str) -> None:
    """Put a value in the config *file*: `load()` re-reads from disk, so a
    field set on the in-memory config would be discarded before the page
    ever saw it."""
    from idasen_companion.core.config import load_config

    path = context_mod.DEFAULT_CONFIG_PATH
    config = load_config(path)
    config.ui.clock_format = value
    save_config(config, path)


@pytest.mark.parametrize(("stored", "index"), [
    ("system", 0), ("12", 1), ("24", 2),
])
def test_loading_selects_the_clock_entry_the_config_names(ctx, stored, index):
    _store_clock_format(stored)
    page = SettingsPage(ctx)
    page.load()
    assert page.clock_format_combo.currentIndex() == index


def test_an_unknown_clock_format_selects_the_first_entry(ctx):
    """Not "whatever the combo happened to show": a config written by a
    later version has to land somewhere defined. The loader rejects such a
    value, so this exercises the widget's own fallback directly."""
    page = SettingsPage(ctx)
    page.load()
    page._select_data(page.clock_format_combo, "swatch-beats")
    assert page.clock_format_combo.currentIndex() == 0


def test_the_clock_format_round_trips_through_apply(ctx):
    page = SettingsPage(ctx)
    page.load()
    assert page.clock_format_combo.currentData() == "system", "shipped default"
    before = context_mod.DEFAULT_CONFIG_PATH.read_text()

    page.clock_format_combo.setCurrentIndex(1)
    assert page.is_dirty()
    assert context_mod.DEFAULT_CONFIG_PATH.read_text() == before, (
        "staging must not touch the file")

    page._apply_settings()
    assert ctx.cfg.ui.clock_format == "12"
    page.load()
    assert page.clock_format_combo.currentData() == "12"


def test_reset_throws_a_staged_clock_format_away(ctx):
    page = SettingsPage(ctx)
    page.load()
    page.clock_format_combo.setCurrentIndex(2)
    assert page.is_dirty()

    page._reset_btn.click()

    assert page.clock_format_combo.currentData() == "system"
    assert ctx.cfg.ui.clock_format == "system"


# ---- the Notifications card's two peer checkboxes ---------------------------


def test_the_problem_notification_toggle_round_trips(ctx):
    page = AutomationPage(ctx)
    page.load()
    assert page.problems_check.isChecked(), "shipped default is on"
    page.problems_check.setChecked(False)
    assert page.is_dirty()
    assert page._apply_btn.isEnabled()
    page._apply_settings()
    assert ctx.cfg.notifications.problems is False
    page.load()
    assert not page.problems_check.isChecked()


def test_the_pre_move_warning_does_not_govern_the_problem_notices(ctx):
    """They are peers: one announces what automation is about to do, the other
    reports a fault. Turning the announcements off is not a request to stop
    hearing that the desk didn't move — asserted rather than assumed, since
    the two sit in the same card."""
    page = AutomationPage(ctx)
    page.load()
    page.notif_enabled.setChecked(False)
    assert not page._lead_row.isEnabled(), "the lead time is subordinate"
    assert page.problems_check.isEnabled()


# ---- per-segment help lines -------------------------------------------------
#
# A segmented row shows one short line describing the *selected* segment rather
# than a static gloss of every segment (see _settings_row). Two things have to
# hold for that to work: the line must follow a click, and it must follow a
# programmatic load — which is why SegmentedControl.setCurrentIndex emits
# currentChanged rather than leaving that to idClicked.


def _help_line(row):
    """The muted help QLabel of a row built by _settings_row."""
    from PySide6.QtWidgets import QLabel
    return row.findChildren(QLabel)[1]


def test_a_segmented_row_describes_only_the_selected_segment(ctx):
    page = AutomationPage(ctx)
    page.load()
    row = page.interruption_policy.parentWidget()
    page.interruption_policy.setCurrentIndex(0)
    assert _help_line(row).text() == "Returns the desk to where it started"
    page.interruption_policy.setCurrentIndex(2)
    assert _help_line(row).text() == "Moves toward the target once more"


def test_the_segment_help_survives_a_reload_from_disk(ctx):
    """load() sets the index programmatically, which must still update it."""
    page = AutomationPage(ctx)
    page.load()
    row = page.ext_policy.parentWidget()
    page.ext_policy.setCurrentIndex(1)
    assert _help_line(row).text() == "Counts it as the nearer one and keeps going"
    page.load()  # config says "hold", so the line must go back to Hold's
    assert page.ext_policy.currentIndex() == 0
    assert _help_line(row).text() == "Pauses until the desk is back at sit or stand"


def test_the_selected_segment_help_is_exposed_to_screen_readers(ctx):
    """A label that swaps is one nothing ties to the control — mirror it."""
    page = SettingsPage(ctx)
    page.load()
    page.repeat_move.setCurrentIndex(2)
    assert (page.repeat_move.accessibleDescription()
            == "Sends the desk back to where the move began")


def test_a_programmatic_segment_change_does_not_dirty_the_page(ctx):
    """setCurrentIndex now emits, so _loading has to keep load() clean."""
    page = AutomationPage(ctx)
    page.load()
    assert not page.is_dirty()
    page.load()
    assert not page.is_dirty()
