"""Reopening the window counts as showing the page you left on.

The lazily-reloading pages (Statistics, Activity Log, the settings-class pages,
About) reload in ``on_shown``, and for a long time the only caller was
``_on_nav_changed``. A hide/show cycle is not a navigation, so closing the app
to the tray and reopening it redisplayed whatever the current page had read
when it was last navigated to — however long ago that was. Reported from the
field as the Statistics page showing yesterday's "today" the following morning,
correct only after changing panes.

The second half is the trap in fixing it: ``SettingsFormPage.on_shown``
*reloads from disk and rebases*, and hiding to the tray deliberately keeps
staged edits rather than making you settle them (``confirm_unapplied_edits``
says so in as many words). Re-running ``on_shown`` on the way back in would
therefore have thrown away unapplied settings — silently, and only for people
who park the window mid-edit.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import pytest

pytest.importorskip("PySide6")

import os

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import main_window as mw  # noqa: E402
from idasen_companion.gui import service_ctl  # noqa: E402
from idasen_companion.gui.pages.base import Page  # noqa: E402
from idasen_companion.gui.pages.settings_form import (  # noqa: E402
    SettingsFormPage,
)

MAC = "E1:B2:C3:D4:E5:F6"

# Sidebar order, from MainWindow._pages.
OVERVIEW, AUTOMATION, PRESETS, STATISTICS = 0, 1, 2, 3


class FakeClient(QObject):
    """Every signal MainWindow and its pages subscribe to, and nothing live.

    ``available`` stays False so no page attempts a D-Bus read during
    construction — except the ones we drive deliberately below, which count
    their calls instead.
    """

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

    def reload_config(self):  # pragma: no cover - unavailable, never nudged
        raise AssertionError("should not nudge an unavailable daemon")

    def __getattr__(self, name):
        # Building the whole window wires up every page's buttons, and those
        # connect to daemon calls (sit, stand, move_to_height, …) this fake has
        # no business answering. Nothing here is ever *invoked* — no test
        # presses a button — so a no-op stands in for all of them rather than
        # this file carrying a second copy of the client's surface.
        return lambda *args, **kwargs: None


def _stub_autostart():
    """The unit is installed and enabled — the banner's uninteresting case."""
    return service_ctl.AutostartState("enabled", True, "")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    cfg = AppConfig()
    cfg.desk.mac = MAC
    save_config(cfg, path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    return path


@pytest.fixture
def window(qapp, config_path, monkeypatch):
    # The "daemon not running" banner asks systemd whether the unit is enabled,
    # to decide which remedy to offer. Not this file's subject, and it would
    # otherwise shell out to systemctl from a unit test.
    monkeypatch.setattr(service_ctl, "autostart_state", _stub_autostart)
    window = mw.MainWindow(FakeClient(), tray_available=True)
    yield window
    # Settle any staged edits before closing. closeEvent asks about them
    # through a modal QMessageBox, and offscreen there is nobody to answer —
    # the teardown hangs rather than failing. That prompt is the app behaving
    # correctly; it just cannot be left to fire in a test.
    for page in window._pages:
        if isinstance(page, SettingsFormPage):
            page.discard_edits()
    window.close()


def _record_shows(window, index, monkeypatch):
    """Count on_shown calls on one page without changing what it does."""
    page = window._pages[index]
    calls = []
    original = page.on_shown
    monkeypatch.setattr(page, "on_shown",
                        lambda: (calls.append(None), original())[1])
    return calls


def test_reopening_shows_the_page_you_left_on(window, monkeypatch):
    # The reported bug: park on a lazily-reloading page, close to the tray,
    # come back the next day to what it read yesterday.
    window.show()
    window._nav.setCurrentRow(STATISTICS)
    calls = _record_shows(window, STATISTICS, monkeypatch)

    window.hide()
    window.present()

    assert len(calls) == 1


def test_it_is_the_current_page_that_is_shown_again(window, monkeypatch):
    # Not a broadcast: reopening shows one page, so the others must not be
    # told they were shown — Activity Log's on_shown starts a journal read.
    window.show()
    window._nav.setCurrentRow(STATISTICS)
    others = [_record_shows(window, i, monkeypatch)
              for i in (OVERVIEW, AUTOMATION, PRESETS)]

    window.hide()
    window.present()

    assert [len(c) for c in others] == [0, 0, 0]


def test_reopening_repeatedly_keeps_re_reading(window, monkeypatch):
    window.show()
    window._nav.setCurrentRow(STATISTICS)
    calls = _record_shows(window, STATISTICS, monkeypatch)

    for _ in range(3):
        window.hide()
        window.present()

    assert len(calls) == 3


def test_reopening_does_not_discard_staged_settings(window):
    # Hiding to the tray keeps unapplied edits on purpose — the window is put
    # away, not dismissed. Reopening must not quietly settle that for you.
    settings = window.settings
    window.show()
    window._nav.setCurrentRow(window._pages.index(settings))
    settings.linger_spin.setValue(settings.linger_spin.value() + 7)
    staged = settings.linger_spin.value()
    assert settings.is_dirty(), "precondition: the page is holding an edit"

    window.hide()
    window.present()

    assert settings.is_dirty()
    assert settings.linger_spin.value() == staged


def test_a_clean_settings_page_still_reloads_on_reopen(window, config_path):
    # The guard is narrow: it protects staged edits, it does not stop the page
    # picking up a config someone else changed while the window was away.
    settings = window.settings
    window.show()
    window._nav.setCurrentRow(window._pages.index(settings))
    assert not settings.is_dirty()

    cfg = AppConfig()
    cfg.desk.mac = MAC
    cfg.desk.linger = settings.linger_spin.value() + 11
    save_config(cfg, config_path)

    window.hide()
    window.present()

    assert settings.linger_spin.value() == cfg.desk.linger


def test_the_first_show_is_harmless(qapp, config_path, monkeypatch):
    # showEvent also fires on the very first show, when __init__ has just
    # primed everything. Page 0 is Overview, which has no on_shown of its own,
    # so this is the base-class no-op — pinned so a future reordering of the
    # sidebar doesn't quietly start doing D-Bus reads during startup.
    monkeypatch.setattr(service_ctl, "autostart_state", _stub_autostart)
    window = mw.MainWindow(FakeClient(), tray_available=True)
    try:
        assert window._page_index == OVERVIEW
        assert type(window._pages[OVERVIEW]).on_shown is Page.on_shown
        window.show()  # must not raise
    finally:
        window.close()
