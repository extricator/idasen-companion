"""The "Check desk position every" dropdown on the Automation page.

The control offers a short list of polling cadences instead of the free
0-120 minute spin it used to be. What needs pinning is the back-compat
promise that came with that narrowing: a config value outside the list is a
value someone chose, so it must survive being looked at rather than being
snapped to the nearest offered one.

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
    _SYNC_CHOICES, AutomationPage,
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
    """Load ``seconds`` into the page, then read back what it would write."""
    cfg = AppConfig()
    cfg.automation.sync_interval = seconds
    page._fill(cfg, rebase=True)
    return page._staged_config().automation.sync_interval


def _values(page) -> list[int]:
    combo = page.sync_combo
    return [combo.itemData(i) for i in range(combo.count())]


def test_the_offered_intervals_are_the_agreed_list(page):
    # Off / 2 / 5 / 10 / 15 / 30 / 60 min. Nothing faster than 2 min: every
    # check is a real BLE connect, and a held desk already polls at 5 min.
    assert _values(page) == [0, 120, 300, 600, 900, 1800, 3600]


@pytest.mark.parametrize("seconds", _SYNC_CHOICES)
def test_each_offered_interval_round_trips(page, seconds):
    assert _round_trip(page, seconds) == seconds


def test_off_stays_off(page):
    # 0 is a real choice, not a missing one — it must not come back as the
    # default the way an unset field would.
    assert _round_trip(page, 0) == 0
    assert page.sync_combo.currentText() == "Off"


def test_an_out_of_list_value_is_kept_rather_than_snapped(page):
    # 7 min was reachable from the old free spin. Loading it must not quietly
    # rewrite the user's setting to 5 or 10 on the next Apply.
    assert _round_trip(page, 7 * 60) == 7 * 60
    assert page.sync_combo.currentData() == 7 * 60
    assert page.sync_combo.currentText() == "7m"


def test_an_out_of_list_value_is_offered_in_sorted_position(page):
    _round_trip(page, 7 * 60)
    assert _values(page) == [0, 120, 300, 420, 600, 900, 1800, 3600]


def test_a_sub_minute_value_survives_and_shows_its_real_size(page):
    # The old page rounded these up to 1 min for display, so a 30 s config
    # silently became 60 s on the next Apply.
    assert _round_trip(page, 30) == 30
    assert page.sync_combo.currentText() == "30s"


def test_a_one_off_entry_does_not_outlive_the_value_that_caused_it(page):
    _round_trip(page, 7 * 60)
    assert _round_trip(page, 5 * 60) == 5 * 60
    assert _values(page) == list(_SYNC_CHOICES), "stale one-off left behind"


def test_restore_defaults_selects_the_shipped_interval(page):
    _round_trip(page, 7 * 60)
    page._restore_defaults()
    assert page.sync_combo.currentData() == AppConfig().automation.sync_interval


def test_picking_a_different_interval_dirties_the_page(page):
    page.sync_combo.setCurrentIndex(_values(page).index(1800))
    assert page.is_dirty()
    assert page._staged_config().automation.sync_interval == 1800
