"""The Overview page's spin box and Move button are one control pair, so
they must lay out at one height.

They stopped doing so when the application-level control stylesheet was
deleted. That stylesheet named ``QSpinBox``, which put the box on
``QStyleSheetStyle``'s metrics from the moment it was constructed, so its
size hint did not move when it was later parented into a `Card` — and a
Move button pinned to the hint read at construction happened to match.
Without it the hint moves (26px unparented, 22px inside a `Card`, measured
offscreen at a device pixel ratio of 1) and the pin froze the button at a
height the spin box no longer had.

So these assert the laid-out heights, not a hint and not a pixel count:
what the user sees is the geometry the layout settled on, and the pairing
has to survive the things that move it — a live palette switch rewrites
``primary_button``'s stylesheet padding, and a font change moves both.

Skipped where PySide6 is missing, matching every other GUI test in this
suite.
"""

import pytest

pytest.importorskip("PySide6")

import os

# Forced, not defaulted -- a desktop session exports QT_QPA_PLATFORM (xcb
# here), which the RPM build inherits and then aborts on a display it can't
# reach. See tests/test_settings_form.py for the same rule.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QPushButton, QVBoxLayout, QWidget,
)

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import restyle  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.pages.overview import OverviewPage  # noqa: E402


class FakeClient(QObject):
    """The signals and call targets OverviewPage wires up, and nothing else.
    Copied rather than imported from the sibling Overview test module --
    tests/ carries no __init__.py, and no other test module in this suite
    imports across siblings."""

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

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_registry(qapp):
    original_palette = QPalette(qapp.palette())
    original_font = QFont(qapp.font())
    restyle.reset_registry_for_tests()
    yield
    restyle.reset_registry_for_tests()
    qapp.setPalette(original_palette)
    qapp.setFont(original_font)
    qapp.processEvents()


@pytest.fixture
def shown_page(qapp, tmp_path, monkeypatch):
    """A real `OverviewPage`, inside a real window, laid out.

    Shown rather than merely constructed: an unshown page's children keep
    whatever geometry they were created with, and this module is about the
    geometry the layout settles on.
    """
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    page = OverviewPage(AppContext(FakeClient(), tray_available=True))
    window = QWidget()
    layout = QVBoxLayout(window)
    layout.addWidget(page)
    window.resize(760, 620)
    window.show()
    qapp.processEvents()
    qapp.processEvents()
    yield page
    window.close()


def _move_button(page) -> QPushButton:
    """The Move button, found by its own label.

    No translator is installed under the test platform, so ``tr()`` returns
    the source string -- the same assumption the sibling Overview countdown
    module's header assertions make.
    """
    buttons = [button for button in page.findChildren(QPushButton)
               if button.text() == "Move"]
    assert len(buttons) == 1, (
        f"expected exactly one button labelled 'Move' on the Overview page, "
        f"found {[button.text() for button in page.findChildren(QPushButton)]}")
    return buttons[0]


def _assert_level(page, when: str) -> None:
    spin, move = page.height_spin, _move_button(page)
    assert spin.height() > 1 and move.height() > 1, (
        f"the height spin box ({spin.height()}px) or the Move button "
        f"({move.height()}px) has no laid-out height at all {when} -- "
        "nothing below would mean anything")
    assert spin.height() == move.height(), (
        f"the height spin box lays out {spin.height()}px tall and the Move "
        f"button beside it {move.height()}px {when} -- the two read as one "
        "control pair and must be the same height")


def test_the_move_button_is_the_same_height_as_the_height_spin(shown_page):
    _assert_level(shown_page, "as first laid out")


def test_the_pair_stays_level_across_a_live_palette_switch(qapp, shown_page):
    """A palette switch runs every restyler, and a restyler calls
    ``setStyleSheet``, which unpolishes and re-polishes the widget -- the
    same machinery whose metrics moved the spin box's hint on parenting in
    the first place. Measured, neither hint moves across a sweep today; the
    assertion is here because a padding or radius edit inside
    ``primary_button`` could make one move tomorrow.
    """
    _assert_level(shown_page, "as first laid out")
    palette = QPalette(qapp.palette())
    for role, color in ((QPalette.ColorRole.Window, "#202326"),
                        (QPalette.ColorRole.Base, "#141618"),
                        (QPalette.ColorRole.WindowText, "#fcfcfc"),
                        (QPalette.ColorRole.Text, "#fcfcfc")):
        palette.setColor(role, QColor(color))
    qapp.setPalette(palette)
    restyle.sweep()
    qapp.processEvents()
    qapp.processEvents()
    _assert_level(shown_page, "after a live palette switch")


def test_the_pair_stays_level_when_the_controls_font_grows(qapp, shown_page):
    """The stand-in for a font or DPI change, which is what a height
    captured once at construction cannot follow.

    The larger font is set on the two controls rather than on the
    application, and that is deliberate rather than a shortcut: measured,
    ``QApplication.setFont`` does not reach these two through the shown
    page at all -- the spin box stays at 9pt and both hints stay where they
    were -- so a test written that way asserts that two unchanged numbers
    are still equal. Setting it where it demonstrably lands is what a font
    or DPI change ultimately does to each widget anyway, and the two hints
    are asserted to have actually pulled apart first, so this cannot go
    quietly vacuous the same way.

    What they do at 1.6x is worth recording, because it is the defect
    again from a different direction: the button's hint goes 27 -> 36 and
    the spin box's does not move at all, because inside a `Card` its
    metrics come from ``QStyleSheetStyle`` and no longer follow its own
    font. Two controls whose hints answer to different things is exactly
    what pinning one to the other's cannot survive.
    """
    spin, move = shown_page.height_spin, _move_button(shown_page)
    _assert_level(shown_page, "as first laid out")
    before = (spin.sizeHint().height(), move.sizeHint().height())

    for control in (spin, move):
        bigger = QFont(control.font())
        bigger.setPointSizeF(bigger.pointSizeF() * 1.6)
        control.setFont(bigger)
    qapp.processEvents()
    qapp.processEvents()

    after = (spin.sizeHint().height(), move.sizeHint().height())
    assert after[1] - after[0] != before[1] - before[0], (
        f"the two size hints are still the same distance apart after the "
        f"font grew ({before} -> {after}) -- nothing pulled them apart, so "
        "the assertion below would hold on a build that captured a height "
        "once and never looked again")
    _assert_level(shown_page, "after the controls' font grew")
