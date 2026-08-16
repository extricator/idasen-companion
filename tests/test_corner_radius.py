"""D-11: one corner radius, shared by every rounded frame the app draws for
a card, a pill, a segmented button, a primary button, a ghost icon button and
the Activity Log's journal-copy chip.

These assertions read the *produced stylesheet strings* rather than the
source files -- a source grep is satisfiable by an explanatory comment sitting
next to the number it's describing, a runtime read is not. ``ConnectionChip``
is asserted the other way round (D-16): it is a stadium/capsule at roughly
half its own height, deliberately exempt from the shared radius until the
maintainer judges it against the rest on a real desktop.

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
from PySide6.QtGui import QIcon, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import restyle  # noqa: E402
from idasen_companion.gui import widgets as widgets_mod  # noqa: E402
from idasen_companion.gui.pages import activity_log as activity_log_mod  # noqa: E402
from idasen_companion.gui.pages.activity_log import ActivityLogPage  # noqa: E402
from idasen_companion.gui.theme import CORNER_RADIUS, theme  # noqa: E402
from idasen_companion.gui.widgets import (  # noqa: E402
    Card, ConnectionChip, ToolIconButton, pill_css, primary_button,
    segment_css,
)

# Copied rather than imported from a sibling GUI test module -- tests/
# carries no __init__.py, and no other test module in this suite imports
# across siblings; that module's own FakeClient docstring records the same
# reasoning.


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_registry(qapp):
    """Empty the registry before each test and undo its palette side effects
    after, so one test's registrations can't leak into the next -- same
    shape as the sibling Fusion-control-border test module's fixture of the
    same name."""
    original_palette = QPalette(qapp.palette())
    restyle.reset_registry_for_tests()
    yield
    restyle.reset_registry_for_tests()
    qapp.setPalette(original_palette)
    qapp.processEvents()


class FakeClient(QObject):
    """Every signal a page's __init__ subscribes to, and nothing live.
    Copied from the sibling Fusion-control-border test module's class of the
    same name."""

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


def _build_ctx() -> context_mod.AppContext:
    return context_mod.AppContext(FakeClient(), tray_available=True)


# The retired per-consumer literals D-11 folds away. Checked as the
# "-radius: Npx" suffix shared by both `border-radius:` and the four
# corner-specific `border-<corner>-radius:` properties segment_css emits,
# so a padding value that happens to read "4px" (primary_button's
# "padding: 4px 14px") can't false-positive the check.
_RETIRED_RADII = ("-radius: 4px", "-radius: 8px", "-radius: 3px")
_SHARED_RADIUS = f"-radius: {CORNER_RADIUS}px"


def _assert_names_shared_radius(stylesheet: str, who: str) -> None:
    assert _SHARED_RADIUS in stylesheet, (
        f"{who}'s stylesheet does not name theme.CORNER_RADIUS "
        f"({CORNER_RADIUS}px) -- got: {stylesheet!r}")
    for retired in _RETIRED_RADII:
        assert retired not in stylesheet, (
            f"{who}'s stylesheet still carries the retired literal "
            f"{retired!r}, which D-11 folds into the shared constant -- "
            f"got: {stylesheet!r}")


# ================= Folded-in consumers (D-11) =================


def test_card_names_the_shared_radius(qapp):
    card = Card()
    try:
        _assert_names_shared_radius(card.styleSheet(), "Card")
    finally:
        card.deleteLater()


def test_pill_css_names_the_shared_radius(qapp):
    css = pill_css(theme().secondary)
    _assert_names_shared_radius(css, "pill_css()")


def test_segment_css_names_the_shared_radius(qapp):
    css = segment_css(first=True, last=True)
    _assert_names_shared_radius(css, "segment_css()")


def test_primary_button_names_the_shared_radius(qapp):
    button = primary_button("x")
    try:
        _assert_names_shared_radius(button.styleSheet(), "primary_button()")
    finally:
        button.deleteLater()


def test_tool_icon_button_names_the_shared_radius(qapp):
    button = ToolIconButton(QIcon(), "tooltip")
    try:
        _assert_names_shared_radius(button.styleSheet(), "ToolIconButton")
    finally:
        button.deleteLater()


def test_the_activity_log_journal_chip_names_the_shared_radius(qapp):
    page = ActivityLogPage(_build_ctx())
    try:
        _assert_names_shared_radius(
            page._journal_chip.styleSheet(),  # pylint: disable=protected-access
            "ActivityLogPage's journal chip")
    finally:
        page.deleteLater()


# ================= The deliberate exemption (D-16) =================


def test_the_connection_chip_stays_exempt_from_the_shared_radius(qapp):
    """D-16: the connection chip is a stadium/capsule, not a rounded
    rectangle, and folding it into the shared radius is the maintainer's
    call to make on a real desktop -- not something to resolve here in
    either direction. A red test here means someone folded it in without
    asking."""
    chip = ConnectionChip()
    try:
        stylesheet = chip.styleSheet()
        assert _SHARED_RADIUS not in stylesheet, (
            "ConnectionChip's stylesheet now names theme.CORNER_RADIUS -- "
            "D-16 reserves that decision for the maintainer's real-desktop "
            "pass; this must not be folded in here")
        assert "border-radius: 11px" in stylesheet, (
            "ConnectionChip no longer draws its capsule at the expected "
            f"literal radius -- got: {stylesheet!r}")
    finally:
        chip.deleteLater()


# ================= The radius is read fresh, not baked in (behavioural) =================


def test_a_consumer_rereads_the_radius_when_it_changes(qapp, monkeypatch):
    """Card's restyler names ``CORNER_RADIUS`` as a bare global, bound into
    ``widgets``'s own namespace by its ``from .theme import CORNER_RADIUS``
    statement -- a copy taken once, when ``widgets`` was first imported, not
    a live alias back to ``theme``'s attribute. So the value that actually
    moves a restyle is ``widgets.CORNER_RADIUS``, and that is what this test
    changes; patching ``theme.CORNER_RADIUS`` after ``widgets`` has already
    imported it would prove nothing, since nothing in ``widgets`` looks at
    ``theme``'s copy of the name again.
    """
    distinctive = CORNER_RADIUS + 11
    monkeypatch.setattr(widgets_mod, "CORNER_RADIUS", distinctive)
    card = Card()
    try:
        assert f"-radius: {distinctive}px" in card.styleSheet(), (
            "Card's restyler did not pick up the changed CORNER_RADIUS -- "
            "the constant is being baked in rather than read fresh")
    finally:
        card.deleteLater()
