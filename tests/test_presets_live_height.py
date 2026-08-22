"""The Presets page's "and the desk is here right now" layer.

The page draws a live marker on whichever preset the desk is currently at, a
tick on the RangeRail, and a capture button labelled with the current height.
All of that is only true while the app can actually see the desk — and with
on-demand Bluetooth the link drops a few seconds after every operation, so
"can't see it" is the ordinary state, not a fault.

What these pin is that the page stops asserting a height once it loses the
means to know one. The capture button matters most: pressing it makes the
daemon take a *fresh* reading, so a stale number in its label would be a claim
about a height it will not deliver.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import pytest

pytest.importorskip("PySide6")

import os

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Signal  # noqa: E402
from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.pages.presets import PresetsPage  # noqa: E402

PRESETS = {"sit": 0.62, "stand": 1.14}


class FakeClient(QObject):
    """The signals PresetsPage subscribes to, and nothing else."""

    presetsChanged = Signal(dict)
    heightChanged = Signal(float)
    connectedChanged = Signal(bool)
    availableChanged = Signal(bool)

    available = False

    def reload_config(self):  # pragma: no cover - unavailable, never nudged
        raise AssertionError("should not nudge an unavailable daemon")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(qapp, tmp_path, monkeypatch):
    config = AppConfig()
    # Pinned explicitly rather than left at "system": the labels below are
    # about the live-height marker, not about units, and "system" would
    # otherwise resolve against the *real* machine's locale (core/units.py's
    # resolver reads QLocale.system(), which tests/conftest.py's own locale
    # pin does not reach), making these assertions depend on whatever $LANG
    # the suite happens to run under.
    config.ui.units = "cm"
    path = tmp_path / "config.toml"
    save_config(config, path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    client = FakeClient()
    ctx = AppContext(client, tray_available=True)
    ctx.reload_config()
    page = PresetsPage(ctx)
    client.presetsChanged.emit(PRESETS)
    return page


def _lit_presets(page) -> int:
    """How many presets are showing their "the desk is here" marker.

    ``isHidden`` rather than ``isVisible``: the page is never shown in these
    tests, and a child of an unshown parent is never ``isVisible`` whatever
    its own flag says.
    """
    return sum(not chip.isHidden() for _, chip in page._preset_chips)


def test_a_reading_lights_up_the_page(page):
    page.client.heightChanged.emit(1.14)
    assert page._new_at_btn.text() == "+ New preset at 114.0 cm"
    assert page.range_rail._height == pytest.approx(1.14)
    assert _lit_presets(page) == 1


def test_losing_the_link_stops_the_page_claiming_a_height(page):
    page.client.heightChanged.emit(1.14)
    page.client.connectedChanged.emit(False)
    assert page._new_at_btn.text() == "+ New preset"
    assert page.range_rail._height == 0
    assert _lit_presets(page) == 0


def test_losing_the_daemon_stops_it_too(page):
    # A dead daemon is as blind as a dropped link, and it doesn't arrive as a
    # ConnectedChanged either.
    page.client.heightChanged.emit(1.14)
    page.client.availableChanged.emit(False)
    assert page._new_at_btn.text() == "+ New preset"
    assert page.range_rail._height == 0


def test_the_capture_button_never_keeps_a_height_it_cannot_deliver(page):
    # The sharp end of the bug: capture_preset re-reads the desk, so a label
    # quoting the old height promises a number it would not save.
    page.client.heightChanged.emit(1.14)
    page.client.connectedChanged.emit(False)
    assert "cm" not in page._new_at_btn.text()


def test_reconnecting_lights_the_page_back_up(page):
    page.client.heightChanged.emit(1.14)
    page.client.connectedChanged.emit(False)
    page.client.connectedChanged.emit(True)
    # Connecting alone proves nothing about position — the height comes back
    # only when the desk is actually read.
    assert page._new_at_btn.text() == "+ New preset"
    page.client.heightChanged.emit(0.62)
    assert page._new_at_btn.text() == "+ New preset at 62.0 cm"
    assert _lit_presets(page) == 1


def test_staying_connected_leaves_the_reading_alone(page):
    page.client.heightChanged.emit(1.14)
    page.client.connectedChanged.emit(True)
    page.client.availableChanged.emit(True)
    assert page._new_at_btn.text() == "+ New preset at 114.0 cm"


def test_the_presets_themselves_survive_the_disconnect(page):
    page.client.heightChanged.emit(1.14)
    page.client.connectedChanged.emit(False)
    assert page._presets == PRESETS
    assert len(page._preset_chips) == len(PRESETS)
    assert page._presets_empty.isHidden(), "the empty-state notice must stay away"
