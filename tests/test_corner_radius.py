"""Two corner radii and no third: a surface radius for cards, panels and
pills, a control radius for buttons, the segmented control, the Activity
Log's journal-copy chip and the standard control frames the proxy style
overlays.

This supersedes D-11's single shared value, which was rejected on the real
desktop: the app had two distinct radius classes before that decision, and
unifying them moved the controls up to the surface radius rather than the
surfaces down. D-11's intent -- no ad-hoc per-widget numbers -- is what
these assertions keep: every consumer must name one of the two tokens, and
neither may name the other's.

Most of these assertions read the *produced stylesheet strings* rather than
the source files -- a source grep is satisfiable by an explanatory comment
sitting next to the number it's describing, a runtime read is not. The proxy
style has no stylesheet to read: it paints, so its half is asserted against
rendered pixels, and against ``theme.corner_radius`` -- the one rule that
clamps either token to the box it is rounding.
``ConnectionChip`` is asserted the other way round (D-16): it is a
stadium/capsule at roughly half its own height, deliberately exempt from
both tokens until the maintainer judges it against the rest on a real
desktop.

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

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtGui import QIcon, QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QLineEdit, QPushButton,
    QStyleFactory,
)

from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import restyle  # noqa: E402
from idasen_companion.gui import widgets as widgets_mod  # noqa: E402
from idasen_companion.gui.pages import activity_log as activity_log_mod  # noqa: E402
from idasen_companion.gui.pages.activity_log import ActivityLogPage  # noqa: E402
from idasen_companion.gui.style import ControlStyle  # noqa: E402
from idasen_companion.gui.theme import (  # noqa: E402
    CONTROL_RADIUS, SURFACE_RADIUS, corner_radius, theme,
)
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


# Radii are checked as the "-radius: Npx" suffix shared by both
# `border-radius:` and the four corner-specific `border-<corner>-radius:`
# properties segment_css emits, so a padding value that happens to read
# "4px" (primary_button's "padding: 4px 14px") can't false-positive the
# check.
_SURFACE = f"-radius: {SURFACE_RADIUS}px"
_CONTROL = f"-radius: {CONTROL_RADIUS}px"

# The ad-hoc per-widget literals the two tokens fold away. The tokens' own
# values are deliberately absent from this tuple -- naming one of them is
# what every consumer below is required to do.
_RETIRED_RADII = ("-radius: 8px", "-radius: 3px", "-radius: 5px")


def _assert_names_only(stylesheet: str, who: str, kind: str) -> None:
    """``who``'s stylesheet names the ``kind`` token, not the other one and
    not an ad-hoc literal."""
    expected, other = ((_SURFACE, _CONTROL) if kind == "surface"
                       else (_CONTROL, _SURFACE))
    assert expected in stylesheet, (
        f"{who}'s stylesheet does not name theme's {kind} radius "
        f"({expected!r}) -- got: {stylesheet!r}")
    assert other not in stylesheet, (
        f"{who} is a {kind} but its stylesheet names the other token "
        f"({other!r}) -- the two are not interchangeable; "
        f"got: {stylesheet!r}")
    for retired in _RETIRED_RADII:
        assert retired not in stylesheet, (
            f"{who}'s stylesheet still carries the ad-hoc literal "
            f"{retired!r}, which the two tokens fold away -- "
            f"got: {stylesheet!r}")


def _assert_surface(stylesheet: str, who: str) -> None:
    _assert_names_only(stylesheet, who, "surface")


def _assert_control(stylesheet: str, who: str) -> None:
    _assert_names_only(stylesheet, who, "control")


# ================= The two tokens are distinct =================


def test_a_control_is_rounded_tighter_than_a_surface():
    """The whole point of the split. A single value was tried and moved the
    buttons to the cards' radius rather than the other way round, which is
    what the maintainer turned down: "the buttons themselves still don't
    have the look as the original look"."""
    assert CONTROL_RADIUS < SURFACE_RADIUS, (
        f"the control radius ({CONTROL_RADIUS}px) is not tighter than the "
        f"surface radius ({SURFACE_RADIUS}px) -- collapsing the two back "
        "into one value is the rejected design")


# ================= Surfaces =================


def test_card_names_the_surface_radius(qapp):
    card = Card()
    try:
        _assert_surface(card.styleSheet(), "Card")
    finally:
        card.deleteLater()


def test_pill_css_names_the_surface_radius(qapp):
    css = pill_css(theme().secondary)
    _assert_surface(css, "pill_css()")


# ================= Controls =================


def test_segment_css_names_the_control_radius(qapp):
    css = segment_css(first=True, last=True)
    _assert_control(css, "segment_css()")


def test_primary_button_names_the_control_radius(qapp):
    button = primary_button("x")
    try:
        _assert_control(button.styleSheet(), "primary_button()")
    finally:
        button.deleteLater()


def test_tool_icon_button_names_the_control_radius(qapp):
    button = ToolIconButton(QIcon(), "tooltip")
    try:
        _assert_control(button.styleSheet(), "ToolIconButton")
    finally:
        button.deleteLater()


def test_the_activity_log_journal_chip_names_the_control_radius(qapp):
    page = ActivityLogPage(_build_ctx())
    try:
        _assert_control(
            page._journal_chip.styleSheet(),  # pylint: disable=protected-access
            "ActivityLogPage's journal chip")
    finally:
        page.deleteLater()


# ================= The deliberate exemption (D-16) =================


def test_the_connection_chip_stays_exempt_from_both_radii(qapp):
    """D-16: the connection chip is a stadium/capsule, not a rounded
    rectangle, and folding it into either token is the maintainer's call to
    make on a real desktop -- not something to resolve here in either
    direction. A red test here means someone folded it in without asking."""
    chip = ConnectionChip()
    try:
        stylesheet = chip.styleSheet()
        for token, name in ((_SURFACE, "SURFACE_RADIUS"),
                            (_CONTROL, "CONTROL_RADIUS")):
            assert token not in stylesheet, (
                f"ConnectionChip's stylesheet now names theme.{name} -- "
                "D-16 reserves that decision for the maintainer's "
                "real-desktop pass; this must not be folded in here")
        assert "border-radius: 11px" in stylesheet, (
            "ConnectionChip no longer draws its capsule at the expected "
            f"literal radius -- got: {stylesheet!r}")
    finally:
        chip.deleteLater()


# ================= The painted consumer (the proxy style) =================


@pytest.mark.parametrize("token", [SURFACE_RADIUS, CONTROL_RADIUS])
def test_either_radius_is_clamped_to_the_box_it_rounds(token):
    """One clamp rule for both tokens, no per-widget exceptions: the token,
    or a fraction of the box's own shorter side, whichever is smaller.

    A radius large in proportion to its own box stops reading as a rounded
    rectangle -- the full control radius on Fusion's 14px checkbox
    indicator is 29% of the box, which reads as a radio button and leaves
    the stroke no straight run at all. A card is far above the crossover
    and keeps its token unchanged.
    """
    assert corner_radius(token, 200) == token, (
        "a box far larger than the token must take it unchanged")
    indicator = corner_radius(token, 14)
    assert 0 < indicator < token, (
        f"a 14px checkbox indicator takes {indicator}px, which is not a "
        f"clamped fraction of the {token}px token")
    assert (corner_radius(token, 14) < corner_radius(token, 17)
            < corner_radius(token, 200)), (
        "the clamp must grow with the box, not step between fixed values")


# The frames the proxy style rounds, as (name, factory). One is a frame the
# app strokes over Fusion's own rendering and the other a panel the app
# paints outright, and the radius is the same for both, which is the point
# of asserting them together.
_OVERLAID_FRAMES = (
    ("combo box", QComboBox),
    ("push button", lambda: QPushButton("Stop")),
)


@pytest.mark.parametrize("name, build", _OVERLAID_FRAMES)
def test_the_proxy_style_paints_its_overlay_with_rounded_corners(
        qapp, name, build):
    """The one consumer that has no stylesheet to read.

    Square corners on these frames are the exact rendering the maintainer
    rejected on sight in wave 08-08, and nothing asserted against them:
    with the radius set to zero in the paint call, every other control test
    in this suite still passed. What separates the two renders is the three
    pixels in the very corner of the frame. A rounded stroke curves inside
    them and leaves them showing whatever is behind the control; a square
    one runs straight through them in the overlay's own colour, the same
    colour as the middle of the edge -- which is asserted first, so a
    failure here can only mean the corner.

    The push button was Fusion's alone until the maintainer's second
    real-desktop pass -- "the buttons borders are still too coarse, and the
    corner too narrow" -- which is Fusion's 2px corner showing through where
    every control the app had an opinion about already curved at the
    control radius.
    """
    qapp.setStyle(ControlStyle())
    try:
        card = Card()
        decoy = QLineEdit()
        control = build()
        card.body.addWidget(decoy)
        card.body.addWidget(control)
        card.show()
        qapp.processEvents()
        decoy.setFocus(Qt.FocusReason.OtherFocusReason)
        qapp.processEvents()
        try:
            image = control.grab().toImage()
            border_hex = theme().border.name()

            edge = image.pixelColor(0, control.height() // 2)
            assert edge.name() == border_hex, (
                f"the {name}'s left edge reads {edge.name()}, not the "
                f"overlay's own theme().border ({border_hex}) -- this test "
                "cannot say anything about its corners")

            corner = {(x, y): image.pixelColor(x, y).name()
                      for x, y in ((0, 0), (1, 0), (0, 1))}
            assert border_hex not in corner.values(), (
                f"the {name}'s top-left corner reads {corner} -- the "
                f"overlay's own {border_hex} runs straight through it, so "
                "it is painting a square frame rather than one rounded at "
                "theme.corner_radius")
        finally:
            card.close()
    finally:
        qapp.setStyle(QStyleFactory.create("fusion"))
        qapp.processEvents()


def test_the_clamp_reaches_the_smallest_control_the_style_paints(qapp):
    """The clamp has to be applied where the box is known, not just exist.

    Its observable effect on Fusion's 14px checkbox indicator is that the
    stroke gets straight runs: at the full control radius the corners meet
    and every single pixel of that stroke is an antialiased blend, so not
    one of them is the overlay's own colour (measured: zero exact matches
    in the whole rendered image, against 24 once clamped). Counting exact
    matches therefore fails if the paint code stops clamping, while staying
    indifferent to the exact radius D-07 settles on.
    """
    qapp.setStyle(ControlStyle())
    try:
        card = Card()
        decoy = QLineEdit()
        checkbox = QCheckBox("test")
        card.body.addWidget(decoy)
        card.body.addWidget(checkbox)
        card.show()
        qapp.processEvents()
        decoy.setFocus(Qt.FocusReason.OtherFocusReason)
        qapp.processEvents()
        try:
            image = checkbox.grab().toImage()
            border_hex = theme().border.name()
            exact = sum(
                1
                for x in range(image.width())
                for y in range(image.height())
                if image.pixelColor(x, y).name() == border_hex)
            assert exact >= 4, (
                f"the checkbox indicator's stroke carries {exact} pixels of "
                f"the overlay's own {border_hex} -- with no straight run "
                "left, its corners have met and the indicator is being "
                "drawn at a radius its own box is too small for")
        finally:
            card.close()
    finally:
        qapp.setStyle(QStyleFactory.create("fusion"))
        qapp.processEvents()


# ================= The radius is read fresh, not baked in (behavioural) =================


def test_a_consumer_rereads_the_radius_when_it_changes(qapp, monkeypatch):
    """Card's restyler names ``SURFACE_RADIUS`` as a bare global, bound into
    ``widgets``'s own namespace by its ``from .theme import`` statement -- a
    copy taken once, when ``widgets`` was first imported, not a live alias
    back to ``theme``'s attribute. So the value that actually moves a
    restyle is ``widgets.SURFACE_RADIUS``, and that is what this test
    changes; patching ``theme``'s copy after ``widgets`` has already
    imported it would prove nothing, since nothing in ``widgets`` looks at
    it again.
    """
    distinctive = SURFACE_RADIUS + 11
    monkeypatch.setattr(widgets_mod, "SURFACE_RADIUS", distinctive)
    card = Card()
    try:
        assert f"-radius: {distinctive}px" in card.styleSheet(), (
            "Card's restyler did not pick up the changed SURFACE_RADIUS -- "
            "the constant is being baked in rather than read fresh")
    finally:
        card.deleteLater()
