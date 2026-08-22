"""The "plus up to" dropdowns on the Automation page.

Each sit / stand row offers a short list of variations instead of the free
0-120 minute spin it used to be, so the same back-compat promise the sync
interval made applies here — and applies harder: the old spin accepted *any*
count in that range, which makes a config holding 7 min ordinary rather than
exotic. A value outside the offered list is a value someone chose, so it must
survive being looked at rather than being snapped to the nearest offered one.

Also pinned here: 0 reads "0m", not "Off". These labels are read through
the row's connective, and "plus up to Off" is not a sentence.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import pytest

pytest.importorskip("PySide6")

import os

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.pages.automation import (  # noqa: E402
    _VARIATION_CHOICES, AutomationPage,
)


class FakeClient:
    """Enough DaemonClient for AppContext: never available, so no D-Bus."""

    available = False

    def reload_config(self):  # pragma: no cover - unreachable while unavailable
        raise AssertionError("should not nudge an unavailable daemon")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(qapp, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    page = AutomationPage(AppContext(FakeClient(), tray_available=True))
    page.load()
    return page


def _round_trip(page, seconds: int) -> int:
    """Load ``seconds`` as the sit variation, then read back what it writes."""
    cfg = AppConfig()
    cfg.automation.sit_variation = seconds
    page._fill(cfg, rebase=True)
    return page._staged_config().automation.sit_variation


def _values(combo) -> list[int]:
    return [combo.itemData(i) for i in range(combo.count())]


def test_the_offered_variations_are_the_agreed_list(page):
    # 0 / 2 / 5 / 10 / 15 / 20 / 30 min. 30 is the ceiling: past that it stops
    # reading as jitter and starts being a second duration knob.
    assert _values(page.sit_var) == [0, 120, 300, 600, 900, 1200, 1800]
    assert _values(page.stand_var) == [0, 120, 300, 600, 900, 1200, 1800]


def test_both_shipped_defaults_are_offered(page):
    # A default that isn't in its own list would show as a spliced one-off on
    # a fresh install, which is the mechanism working but reads as a bug.
    defaults = AppConfig().automation
    assert defaults.sit_variation in _VARIATION_CHOICES
    assert defaults.stand_variation in _VARIATION_CHOICES


@pytest.mark.parametrize("seconds", _VARIATION_CHOICES)
def test_each_offered_variation_round_trips(page, seconds):
    assert _round_trip(page, seconds) == seconds


def test_no_variation_reads_as_a_number_not_off(page):
    # The label is read through the row's connective: "plus up to 0m".
    # "plus up to Off" is not a sentence, which is why this row does not
    # borrow the sync combo's word for zero.
    assert _round_trip(page, 0) == 0
    assert page.sit_var.currentText() == "0m"


def test_an_out_of_list_value_is_kept_rather_than_snapped(page):
    # Any minute count from 0 to 120 was reachable from the old spin, so this
    # is a setting someone chose — not a corruption to be cleaned up.
    assert _round_trip(page, 7 * 60) == 7 * 60
    assert page.sit_var.currentData() == 7 * 60
    assert page.sit_var.currentText() == "7m"


def test_an_out_of_list_value_is_offered_in_sorted_position(page):
    _round_trip(page, 7 * 60)
    assert _values(page.sit_var) == [0, 120, 300, 420, 600, 900, 1200, 1800]


def test_a_value_above_the_ceiling_survives(page):
    # The old spin went to 120 min; the list stops at 30. Narrowing the offer
    # must not rewrite a config that used the old range.
    assert _round_trip(page, 90 * 60) == 90 * 60
    assert _values(page.sit_var)[-1] == 90 * 60


def test_a_one_off_entry_does_not_outlive_the_value_that_caused_it(page):
    _round_trip(page, 7 * 60)
    assert _round_trip(page, 5 * 60) == 5 * 60
    assert _values(page.sit_var) == list(_VARIATION_CHOICES), "stale one-off"


def test_the_two_rows_do_not_share_a_one_off(page):
    # Separate config keys, so a hand-edited sit variation must not appear in
    # the stand row's list.
    _round_trip(page, 7 * 60)
    assert _values(page.stand_var) == list(_VARIATION_CHOICES)


def test_restore_defaults_selects_the_shipped_variation(page):
    _round_trip(page, 7 * 60)
    page._restore_defaults()
    assert page.sit_var.currentData() == AppConfig().automation.sit_variation
    assert page.stand_var.currentData() == (
        AppConfig().automation.stand_variation)


def test_picking_a_different_variation_dirties_the_page(page):
    page.sit_var.setCurrentIndex(_values(page.sit_var).index(1200))
    assert page.is_dirty()
    assert page._staged_config().automation.sit_variation == 1200
