"""Showing heights in inches: the ``[ui] units`` setting.

A display-layer setting only. What these pin down is that the *stored* height
never moves with it — the desk, the config and the wire stay in metres — and
that the conversion is precise enough that a value shown in inches and sent
straight back does not nudge the desk.

Skipped where PySide6 is missing, and forces the offscreen platform before
any ``QtWidgets`` import — see ``test_settings_form.py`` for why both matter.
"""

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QLocale, QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.config import (  # noqa: E402
    MAX_HEIGHT, MIN_HEIGHT, AppConfig, load_config, save_config,
)
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import util  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.pages.overview import OverviewPage  # noqa: E402
from idasen_companion.gui.pages.settings import SettingsPage  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def restore_unit():
    """Put the process-global unit back, whatever a test set it to.

    It is module state by design (see ``gui/util``), so without this a test
    that switches to inches silently re-renders every later test's heights.
    """
    previous = util.height_unit()
    try:
        yield
    finally:
        util.set_height_unit(previous)


@pytest.fixture
def locale(request):
    """Set the default QLocale for the test, restoring the previous one."""
    previous = QLocale()
    QLocale.setDefault(QLocale(request.param))
    try:
        yield
    finally:
        QLocale.setDefault(previous)


# ---- resolving the setting ------------------------------------------------


@pytest.mark.parametrize("setting", ["cm", "in"])
@pytest.mark.parametrize("locale", ["en_US", "es_ES"], indirect=True)
def test_an_explicit_unit_ignores_the_locale(setting, locale):
    assert util.resolve_height_unit(setting) == setting


@pytest.mark.parametrize("locale, expected", [
    ("en_US", "in"),
    # Qt calls the UK imperial, but a UK desk is sold in centimetres.
    ("en_GB", "cm"),
    ("es_ES", "cm"),
    ("de_DE", "cm"),
], indirect=["locale"])
def test_system_follows_the_locale_with_the_uk_on_the_metric_side(
        locale, expected):
    assert util.resolve_height_unit("system") == expected


# ---- the conversion itself ------------------------------------------------


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_centimetres_render_as_before(locale):
    util.set_height_unit("cm")
    assert util.fmt_height(1.105) == "110.5 cm"
    assert util.fmt_height_value(0.62, trim=True) == "62"
    assert util.suffix_height() == " cm"


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_inches_render_as_inches(locale):
    util.set_height_unit("in")
    assert util.fmt_height(1.105) == "43.50 in"
    assert util.suffix_height() == " in"


@pytest.mark.parametrize("locale", ["es_ES"], indirect=True)
def test_the_locale_still_owns_the_decimal_separator(locale):
    util.set_height_unit("in")
    assert util.fmt_height(1.105) == "43,50 in"


@pytest.mark.parametrize("unit", ["cm", "in"])
@pytest.mark.parametrize("meters", [MIN_HEIGHT, 0.75, 1.105, MAX_HEIGHT])
def test_a_displayed_height_survives_the_trip_back(unit, meters):
    """Show a height, then send exactly what was shown: the desk stays put.

    Overview's Move button does precisely this with a spin box the user never
    touched, so the rounding at display precision has to be smaller than the
    desk cares about — and must never land outside its travel.
    """
    util.set_height_unit(unit)
    shown = round(util.to_display_height(meters), util.height_decimals())
    back = util.from_display_height(shown)
    assert abs(back - meters) < 0.001          # under a millimetre
    assert MIN_HEIGHT <= back <= MAX_HEIGHT


def test_inches_carry_a_second_decimal():
    # One place is 2.54mm per step — coarser than the desk itself, and the
    # round trip above is what pays for it.
    util.set_height_unit("in")
    assert util.height_decimals() == 2
    util.set_height_unit("cm")
    assert util.height_decimals() == 1


# ---- config ---------------------------------------------------------------


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    return path


def test_the_setting_round_trips_through_the_file(config_path):
    cfg = load_config(config_path)
    cfg.ui.units = "in"
    save_config(cfg, config_path)
    assert load_config(config_path).ui.units == "in"


def test_a_units_change_leaves_the_stored_presets_alone(config_path):
    """The one way this task could corrupt data: rewriting a height in inches.

    Nothing converts on the way *in*, so switching units must leave every
    preset byte-identical.
    """
    before = load_config(config_path).presets
    cfg = load_config(config_path)
    cfg.ui.units = "in"
    save_config(cfg, config_path)
    assert load_config(config_path).presets == before


# ---- the GUI ---------------------------------------------------------------


class FakeClient(QObject):
    """The signals and call targets OverviewPage wires up, and nothing else."""

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


@pytest.fixture
def ctx(qapp, config_path):
    return AppContext(FakeClient(), tray_available=True)


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_the_settings_page_writes_the_chosen_unit(locale, ctx):
    page = SettingsPage(ctx)
    page.load()
    assert page.units_combo.currentData() == "system"

    page.units_combo.setCurrentIndex(page.units_combo.findData("in"))
    page._apply_settings()

    assert load_config(context_mod.DEFAULT_CONFIG_PATH).ui.units == "in"
    # Applied to the running app, not just the file: this is the setting that
    # takes effect without a restart.
    assert util.height_unit() == "in"


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_overview_reshapes_its_spin_box_when_the_unit_changes(locale, ctx):
    util.set_height_unit("cm")
    page = OverviewPage(ctx)
    page.client.heightChanged.emit(1.105)
    assert page.height_spin.value() == pytest.approx(110.5)
    assert page.height_label.text() == "110.5 cm"

    ctx.write_config(lambda cfg: setattr(cfg.ui, "units", "in"))

    # Same desk height, said differently — and the box now spans the desk's
    # travel in inches rather than clamping to the old centimetre range.
    assert page.height_spin.value() == pytest.approx(43.5, abs=0.01)
    assert page.height_spin.suffix() == " in"
    assert page.height_label.text() == "43.50 in"
    assert page.height_spin.maximum() == pytest.approx(50.0)


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_a_unit_change_keeps_the_target_the_user_dialled_in(locale, ctx):
    """Reshaping the box must not quietly re-aim it at a different height."""
    util.set_height_unit("cm")
    page = OverviewPage(ctx)
    page.height_spin.setValue(90.0)

    ctx.write_config(lambda cfg: setattr(cfg.ui, "units", "in"))

    assert util.from_display_height(page.height_spin.value()) == pytest.approx(
        0.90, abs=0.0005)
