"""Rendering tests for ``ControlStyle`` (`gui/style.py`): resting, hover,
focus, disabled, the checked glyph, the corner, the button's own metrics,
and whether any of it survives a control nested inside a `Card` -- a `Card`
sets a stylesheet, which routes its children through `QStyleSheetStyle`,
and every control this app builds sits inside one.

The style reaches a control in one of two ways and the tests below follow
that split. A push button's panel is *painted outright*, with no Fusion
underneath, so what is asserted about it is the whole rendering. The
checkbox indicator and the combo and spin frames are *drawn through Fusion
and then stroked*, with Fusion clipped to the app's own rounded frame, so
what is asserted about those is that the app's stroke is there, that
Fusion's sub-controls still are, and that nothing of Fusion's survives
outside the curve.

The checkbox indicator is measured with a colour-distance comparison rather
than an exact colour match. Its box is small -- Fusion draws it at 14px --
so the proportion of it the stroke's corners occupy is large, and how much
of each edge survives as a straight, unblended run depends on
``theme.corner_radius`` and on the indicator size Fusion picks, neither of
which this module should have to track. The distance comparison asks the
question antialiased blending can actually answer: is the observed pixel
closer to ``theme().border`` (or, when focused, ``theme().accent``)
than it is to ``theme().card_bg``. It stays exactly as sensitive to the
stroke's own colour changing, proven by the mutation runs recorded in this
plan's SUMMARY. The combo, spin and push button frames are far larger than
their radius and keep the exact-colour-match technique the border-pixel scan
already used in `tests/test_control_contrast.py`.

Every one of the four is measured against the app's own edge token. They
were once measured against two -- a frame that *is* its control's whole
affordance carried a heavier token than a frame around a labelled control,
because the first group was held to a contrast floor the second was not.
The floor was dropped, and re-deriving the weight by eye landed both in the
same place, so the distinction is no longer asserted anywhere.

Several assertions here come in pairs -- one saying what the app does, one
saying that plain Fusion does *not* already do it. That is deliberate:
"nothing protrudes past the corner" and "the icon is not full strength"
both pass just as happily on a build that draws nothing at all, and the
paired test is what stops them going quietly vacuous.
"""

import pytest

pytest.importorskip("PySide6")

import math
import os
from collections import Counter

# Forced, not defaulted -- a desktop session exports QT_QPA_PLATFORM (xcb
# here), which the RPM build inherits and then aborts on a display it can't
# reach. See tests/test_settings_form.py for the same rule.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPalette, QPixmap,
)
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QLineEdit, QPushButton, QSpinBox,
    QStyle, QStyleFactory, QStyleOption, QStyleOptionButton,
    QStyleOptionComboBox, QStyleOptionSpinBox, QVBoxLayout, QWidget,
)

from idasen_companion.gui import restyle  # noqa: E402
from idasen_companion.gui.style import ControlStyle  # noqa: E402
from idasen_companion.gui.theme import (  # noqa: E402
    BORDER_WIDTH, BUTTON_PADDING_V, button_icon_gap, theme,
)
from idasen_companion.gui.widgets import (  # noqa: E402
    Card, SegmentedControl, ToolIconButton, primary_button,
)

# Copied rather than imported from tests/test_control_contrast.py -- tests/
# carries no __init__.py, and no other test module in this suite imports
# across siblings; that module's own FakeClient docstring records the same
# reasoning.
_LIGHT = {
    QPalette.ColorRole.Window: QColor("#f0f0f0"),
    QPalette.ColorRole.Base: QColor("#ffffff"),
    QPalette.ColorRole.WindowText: QColor("#000000"),
    QPalette.ColorRole.Text: QColor("#000000"),
}
_DARK = {
    QPalette.ColorRole.Window: QColor("#202326"),
    QPalette.ColorRole.Base: QColor("#141618"),
    QPalette.ColorRole.WindowText: QColor("#fcfcfc"),
    QPalette.ColorRole.Text: QColor("#fcfcfc"),
}


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _installed_control_style(qapp):
    """Install ``ControlStyle`` as the ambient application style for every
    test in this module, and undo every side effect on teardown.

    The teardown installs a *fresh* ``QStyleFactory.create("fusion")``
    rather than saving and re-setting whatever style object was previously
    installed -- ``QApplication.setStyle`` takes ownership of the style
    object it replaces and may already have deleted it. Without this
    teardown ``ControlStyle`` leaks into every test module collected
    afterwards in the same process, and the suite starts meaning something
    different depending on collection order.
    """
    original_palette = QPalette(qapp.palette())
    restyle.reset_registry_for_tests()
    qapp.setStyle(ControlStyle())
    yield
    restyle.reset_registry_for_tests()
    qapp.setStyleSheet("")
    qapp.setPalette(original_palette)
    qapp.setStyle(QStyleFactory.create("fusion"))
    qapp.processEvents()


def _mix(start: QColor, end: QColor, fraction: float) -> QColor:
    return QColor(round(start.red() + (end.red() - start.red()) * fraction),
                  round(start.green() + (end.green() - start.green()) * fraction),
                  round(start.blue() + (end.blue() - start.blue()) * fraction))


def flip_palette(qapp, dark: bool) -> None:
    """Install a light or dark palette and pump the event loop.

    The Disabled colour group is filled in explicitly, with the
    three-argument ``setColor`` overload. The two-argument one writes every
    colour group at once, so a palette built only from it leaves Disabled
    identical to Active -- Fusion then has nothing to dim against, and a
    disabled control renders exactly like an enabled one no matter what the
    style under test does. A real desktop's palette does have a distinct
    Disabled group (Qt's own default: Text ``#000000`` active versus
    ``#bebebe`` disabled), so a fixture without one measures a world users
    never run in, and the disabled assertions below would pass on a build
    that ignored the disabled state entirely.
    """
    roles = _DARK if dark else _LIGHT
    pal = QPalette(qapp.palette())
    for role, color in roles.items():
        pal.setColor(role, color)
    window = roles[QPalette.ColorRole.Window]
    base = roles[QPalette.ColorRole.Base]
    text = roles[QPalette.ColorRole.WindowText]
    disabled = QPalette.ColorGroup.Disabled
    # Dimmed the way a desktop palette dims: foregrounds pulled most of the
    # way toward the window, surfaces pulled toward each other.
    pal.setColor(disabled, QPalette.ColorRole.WindowText, _mix(text, window, 0.7))
    pal.setColor(disabled, QPalette.ColorRole.Text, _mix(text, window, 0.7))
    pal.setColor(disabled, QPalette.ColorRole.Base, _mix(base, window, 0.5))
    pal.setColor(disabled, QPalette.ColorRole.Window, _mix(window, base, 0.3))
    pal.setColor(disabled, QPalette.ColorRole.Button, _mix(window, base, 0.3))
    qapp.setPalette(pal)
    qapp.processEvents()
    assert theme().is_dark is dark, (
        f"palette flip to dark={dark} did not take -- theme().is_dark is "
        f"{theme().is_dark}")


def _find_border_pixel(image, y: int, card_bg_hex: str):
    """The first non-background, non-transparent pixel scanning left to
    right at row ``y``."""
    for x in range(image.width()):
        pixel = image.pixelColor(x, y)
        if pixel.alpha() != 0 and pixel.name() != card_bg_hex:
            return pixel
    raise AssertionError(
        "no border-coloured pixel found scanning the indicator row -- "
        "the whole row reads as the card background")


def _channel_distance(a: QColor, b: QColor) -> int:
    return (abs(a.red() - b.red()) + abs(a.green() - b.green())
            + abs(a.blue() - b.blue()))


def _closer_to(pixel: QColor, target: QColor, other: QColor) -> bool:
    return _channel_distance(pixel, target) < _channel_distance(pixel, other)


def _contains_pixel(image, hex_color: str) -> bool:
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).name() == hex_color:
                return True
    return False


def _build_card_row(qapp, *, enabled: bool = True):
    """A checkbox, a combo and a spin box the way the app builds them --
    inside a `Card` -- plus a decoy field. Focuses the decoy and confirms
    none of the three controls has focus, since a widget alone in a shown,
    active window already has keyboard focus and a "resting" grab taken
    before focusing a decoy would silently measure the focused state."""
    window = QWidget()
    layout = QVBoxLayout(window)
    card = Card()
    decoy = QLineEdit()
    checkbox = QCheckBox("test")
    combo = QComboBox()
    spin = QSpinBox()
    for widget in (checkbox, combo, spin):
        widget.setEnabled(enabled)
    card.body.addWidget(decoy)
    card.body.addWidget(checkbox)
    card.body.addWidget(combo)
    card.body.addWidget(spin)
    layout.addWidget(card)
    window.show()
    qapp.processEvents()
    decoy.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    assert checkbox.hasFocus() is False
    assert combo.hasFocus() is False
    assert spin.hasFocus() is False
    return window, checkbox, combo, spin


# ================= 1. Resting, and nested in a Card =================


def test_the_overlay_reaches_every_control_nested_in_a_card(qapp):
    """The measurement `09-CONTEXT.md`'s stop-and-report condition asks
    for: does the installed proxy style's overlay survive a `Card`'s own
    stylesheet, which routes its children through `QStyleSheetStyle`?
    Proven by comparing the same three controls, built inside an
    otherwise-identical `Card`, once under the installed `ControlStyle`
    and once under plain, unmodified Fusion -- if the overlay were being
    intercepted, the two renders would be pixel-identical.
    """
    flip_palette(qapp, dark=False)
    styled_window, styled_checkbox, styled_combo, styled_spin = (
        _build_card_row(qapp))
    try:
        # Grabbed while ControlStyle is still the ambient application
        # style -- QApplication.setStyle() re-polishes every widget that
        # has no explicit per-widget style, so a widget built under one
        # style still reflects whatever style is *current* at grab time,
        # not the one installed when it was constructed. The images must
        # be captured before the style is swapped below, or this ends up
        # comparing two renders under the same (later-installed) style.
        styled_images = {
            "checkbox": styled_checkbox.grab().toImage(),
            "combo": styled_combo.grab().toImage(),
            "spin": styled_spin.grab().toImage(),
        }

        qapp.setStyle(QStyleFactory.create("fusion"))
        try:
            plain_window, plain_checkbox, plain_combo, plain_spin = (
                _build_card_row(qapp))
            try:
                for name, plain in (
                        ("checkbox", plain_checkbox),
                        ("combo", plain_combo),
                        ("spin", plain_spin)):
                    plain_image = plain.grab().toImage()
                    assert styled_images[name] != plain_image, (
                        f"{name}'s Card-nested render is pixel-identical "
                        "under the installed ControlStyle and under plain "
                        "Fusion -- the overlay is not reaching this "
                        "control")
            finally:
                plain_window.close()
        finally:
            qapp.setStyle(ControlStyle())
    finally:
        styled_window.close()


def _assert_resting_border(qapp, dark: bool) -> None:
    flip_palette(qapp, dark=dark)
    window, checkbox, combo, spin = _build_card_row(qapp)
    try:
        card_bg_hex = theme().card_bg.name()
        edge = theme().border

        combo_pixel = _find_border_pixel(
            combo.grab().toImage(), combo.height() // 2, card_bg_hex)
        assert combo_pixel.name() == edge.name(), (
            f"the combo frame reads {combo_pixel.name()}, not the "
            f"current theme().border ({edge.name()}) -- dark={dark}")

        spin_pixel = _find_border_pixel(
            spin.grab().toImage(), spin.height() // 2, card_bg_hex)
        assert spin_pixel.name() == edge.name(), (
            f"the spin frame reads {spin_pixel.name()}, not the current "
            f"theme().border ({edge.name()}) -- dark={dark}")

        # See the module docstring: the checkbox indicator is small enough
        # that whether any given border pixel is the edge token itself or an
        # antialiased blend of it depends on the clamped radius and on
        # Fusion's indicator size. Assert the pixel is genuinely
        # border-derived (closer to it than to card_bg) instead.
        checkbox_pixel = _find_border_pixel(
            checkbox.grab().toImage(), checkbox.height() // 2, card_bg_hex)
        assert checkbox_pixel.name() != card_bg_hex
        assert _closer_to(checkbox_pixel, edge, theme().card_bg), (
            f"the checkbox indicator's border pixel {checkbox_pixel.name()} "
            f"is not closer to theme().border ({edge.name()}) than to "
            f"theme().card_bg ({card_bg_hex}) -- dark={dark}")
    finally:
        window.close()


def test_resting_controls_in_a_card_carry_the_overlay_in_light(qapp):
    _assert_resting_border(qapp, dark=False)


def test_resting_controls_in_a_card_carry_the_overlay_in_dark(qapp):
    _assert_resting_border(qapp, dark=True)


def _render_framed(qapp, style, control, option, *, frame: bool):
    """One complex control drawn straight through ``style`` onto a
    card-coloured image, with its frame flag set by hand.

    Synthetic, and at a rect this fixes itself, so the framed and frameless
    renders are the same size and comparable pixel for pixel -- a real
    ``setFrame(False)`` widget also lays out a couple of pixels smaller,
    which would make any comparison between the two a size difference
    rather than a frame one.
    """
    option.rect = QRect(0, 0, 120, 26)
    option.state = (QStyle.StateFlag.State_Enabled
                    | QStyle.StateFlag.State_Active)
    option.palette = qapp.palette()
    option.frame = frame
    option.subControls = QStyle.SubControl.SC_All
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    image.fill(theme().card_bg)
    painter = QPainter(image)
    try:
        style.drawComplexControl(control, option, painter, None)
    finally:
        painter.end()
    return image


@pytest.mark.parametrize("name, control, build_option", [
    ("combo box", QStyle.ComplexControl.CC_ComboBox, QStyleOptionComboBox),
    ("spin box", QStyle.ComplexControl.CC_SpinBox, QStyleOptionSpinBox),
])
def test_a_control_that_asked_for_no_frame_is_not_given_one(
        qapp, name, control, build_option):
    """``setFrame(False)`` is a widget saying it wants no frame at all.

    Fusion honours it and draws nothing. The overlay drew unconditionally,
    so a borderless control came back with a border it had explicitly
    switched off -- latent today (nothing in `src/` sets the flag) and one
    line to prevent, which a delegate-created editor would otherwise
    inherit.

    Measured as pixel equality with plain, unmodified Fusion rather than as
    the absence of any pixel matching the edge token. The absence form read
    correctly and was quietly fragile: it fails the moment Fusion happens
    to paint *anything* -- a drop-down arrow, a stepper face -- in the same
    colour the token currently derives to, which is a coincidence between
    two greys and says nothing about whether a frame was drawn. It shipped
    green only because the token it searched for was the one colour the
    overlay could not have left there anyway.

    The same control *with* its frame is put through the same comparison
    and must differ, so this cannot pass on a build whose overlay draws
    nothing at all.
    """
    flip_palette(qapp, dark=False)
    styled = ControlStyle()
    plain = QStyleFactory.create("fusion")
    assert (_render_framed(qapp, styled, control, build_option(), frame=False)
            == _render_framed(qapp, plain, control, build_option(),
                              frame=False)), (
        f"a frameless {name} renders differently under ControlStyle than "
        "under plain Fusion -- the overlay is ignoring the frame flag "
        "Fusion honours and handing back a border the widget switched off")
    assert (_render_framed(qapp, styled, control, build_option(), frame=True)
            != _render_framed(qapp, styled, control, build_option(),
                              frame=False)), (
        f"a framed {name} and a frameless one render identically under "
        "ControlStyle -- the overlay is reaching neither, so the equality "
        "above proves nothing")


# ================= 1b. Edge thickness =================


def _painted_bounds(image, background: QColor):
    """The first and last row and column of ``image`` carrying any pixel
    that isn't ``background`` -- i.e. the bounding box the style actually
    painted into."""
    width, height = image.width(), image.height()
    rows = [y for y in range(height)
            if any(image.pixelColor(x, y) != background for x in range(width))]
    columns = [x for x in range(width)
               if any(image.pixelColor(x, y) != background
                      for y in range(height))]
    assert rows and columns, "the style painted nothing at all"
    return QRect(columns[0], rows[0],
                 columns[-1] - columns[0] + 1, rows[-1] - rows[0] + 1)


def _render_onto_never_drawn(qapp, option, size, draw):
    """``draw`` run through plain, unmodified Fusion onto a colour Fusion
    never paints, so the painted bounds can be read straight off it."""
    never_drawn = QColor(0, 255, 0)
    option.rect = QRect(0, 0, size[0], size[1])
    option.state = (QStyle.StateFlag.State_Enabled
                    | QStyle.StateFlag.State_Active)
    option.palette = qapp.palette()
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    image.fill(never_drawn)
    painter = QPainter(image)
    try:
        draw(QStyleFactory.create("fusion"), option, painter)
    finally:
        painter.end()
    return _painted_bounds(image, never_drawn)


def _plain_fusion_frame_bounds(qapp, control, option, size):
    """Where plain, unmodified Fusion strokes ``control``'s frame."""
    option.frame = True
    option.subControls = QStyle.SubControl.SC_All
    return _render_onto_never_drawn(
        qapp, option, size,
        lambda style, opt, painter: style.drawComplexControl(
            control, opt, painter, None))


@pytest.mark.parametrize("size", [(48, 26), (80, 25), (120, 30), (144, 22),
                                  (60, 40)])
def test_the_overlay_lands_on_the_rect_fusion_actually_strokes(qapp, size):
    """The cause of the doubled edge, asserted at its source.

    ``subControlRect`` answers where a frame *is*; Fusion's paint code is
    free to stroke a smaller rect than that, and for a spin box it does --
    it insets the frame by a pixel at the top and bottom and leaves it
    flush at the left and right. The overlay followed the report, so it
    coincided with Fusion's own stroke down the sides and sat a pixel
    outside it along the top and bottom, which is the thicker top/bottom
    edge reported from the real desktop.

    Plain Fusion's painted bounds are re-derived here rather than
    hardcoded, so a Qt release that moves the inset turns this red instead
    of quietly restoring the doubled edge.
    """
    flip_palette(qapp, dark=False)
    for control, option, name in (
            (QStyle.ComplexControl.CC_ComboBox, QStyleOptionComboBox(),
             "combo box"),
            (QStyle.ComplexControl.CC_SpinBox, QStyleOptionSpinBox(),
             "spin box")):
        fusion_bounds = _plain_fusion_frame_bounds(qapp, control, option, size)
        overlay_rect = ControlStyle.stroked_frame_rect(
            control, QRect(0, 0, size[0], size[1]))
        assert overlay_rect == fusion_bounds, (
            f"at {size[0]}x{size[1]} the {name} overlay would be stroked at "
            f"{overlay_rect} while plain Fusion strokes its frame at "
            f"{fusion_bounds} -- the two land on different pixels, which the "
            "user sees as one edge twice as thick as the opposite one")


def _edge_thickness(pixels, surface: QColor, border: QColor) -> int:
    """How many pixels of drawn border a scan inward from one edge crosses.

    Leading pixels that still read as the surface behind the control are
    skipped (a frame Fusion insets does not start at the widget's own
    edge); the run of border-weight pixels after them is the thickness.
    "Border-weight" is at least half as far from the surface as the
    overlay's own colour, which separates a frame stroke from the near-white
    fill Fusion gradients a control with.
    """
    floor = _channel_distance(border, surface) / 2
    run = 0
    for pixel in pixels:
        if _channel_distance(pixel, surface) >= floor:
            run += 1
        elif run:
            break
    return run


def _frame_edge_thicknesses(card_image, widget) -> dict[str, int]:
    image = card_image.copy(widget.geometry())
    width, height = image.width(), image.height()
    surface, border = theme().card_bg, theme().border
    depth = range(6)
    middle_x, middle_y = width // 2, height // 2
    return {
        "top": _edge_thickness(
            [image.pixelColor(middle_x, d) for d in depth], surface, border),
        "bottom": _edge_thickness(
            [image.pixelColor(middle_x, height - 1 - d) for d in depth],
            surface, border),
        "left": _edge_thickness(
            [image.pixelColor(d, middle_y) for d in depth], surface, border),
        "right": _edge_thickness(
            [image.pixelColor(width - 1 - d, middle_y) for d in depth],
            surface, border),
    }


def test_a_control_frame_is_the_same_thickness_on_all_four_edges(qapp):
    """The symptom the maintainer reported, measured the way he measured it:
    "the height spinbox/stepper has a weird border.. top and bottom look
    thicker than sides".

    Light scheme only, deliberately. The measurement asks how many pixels
    inward from each edge read as a frame stroke rather than as the
    control's own fill, and it separates the two by distance from the card
    behind the control. That separation holds in a light scheme, where
    Fusion gradients a control in near-whites a shade off the card; under
    the dark palette this module installs, the same fill sits further from
    the card than the frame does and the scan can no longer tell them
    apart. The defect is geometry rather than colour, and the test above
    pins the geometry in both directions and at five sizes.
    """
    flip_palette(qapp, dark=False)
    window, _checkbox, combo, spin = _build_card_row(qapp)
    try:
        card = combo.parentWidget()
        card_image = card.grab().toImage()
        for widget, name in ((combo, "combo box"), (spin, "spin box")):
            thicknesses = _frame_edge_thicknesses(card_image, widget)
            assert len(set(thicknesses.values())) == 1, (
                f"the {name}'s drawn border is not the same thickness on "
                f"every edge: {thicknesses} (pixels of frame stroke crossed "
                "scanning inward from each edge's midpoint)")
            assert set(thicknesses.values()) == {1}, (
                f"the {name}'s drawn border is {thicknesses} pixels thick -- "
                "uniform, but no longer the single stroke the overlay paints")
    finally:
        window.close()


# ================= 1b'. The corner arc that protruded =================
#
# Two rounded rectangles of different radii on one box, and the squarer one
# wins the corner: Fusion rounds a frame far tighter than the app does, so
# its arc stands *outside* the app's own curve and shows as a grey nick at
# each corner -- reported from the real desktop as a grey thing protruding
# past the control. Measured here, light scheme, a QSpinBox in a Card: eight
# stray pixels, two per corner, at #d1d1d1 against a #ffffff card.
#
# The push button is cured by not drawing Fusion's panel at all. The spin
# and combo frames cannot be -- their arrows, stepper faces and drop-down
# are Fusion's and must stay -- so they are cured by clipping Fusion to the
# app's own rounded frame instead, which drops the pixels outside the curve
# and touches nothing inside it.


def _card_cropped_render(qapp, control):
    """``control`` rendered inside a `Card`, cropped out of the *card's*
    own render rather than grabbed on its own.

    Which one is grabbed decides what an unpainted pixel reads as. A
    correctly rounded control paints nothing in its corners, and grabbing
    the widget alone leaves those pixels at whatever the pixmap was
    initialised to. Cropping them out of the card shows what the user
    actually sees there: the surface behind the control.
    """
    card = Card()
    decoy = QLineEdit()
    card.body.addWidget(decoy)
    card.body.addWidget(control)
    card.show()
    qapp.processEvents()
    decoy.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    try:
        return card.grab().toImage().copy(control.geometry())
    finally:
        card.close()


def _app_curve(rect, radius):
    """The app's own rounded frame, as a path a pixel centre can be tested
    against.

    A path rather than a rendered mask, and centre-sampled rather than
    coverage-sampled, because the whole artefact lives inside one pixel of
    the boundary: an *antialiased* fill of this same shape puts a fringe
    roughly a pixel outside the true curve, which is exactly where the
    protruding arc sits, so a mask built that way calls the defect
    "inside" and reports nothing. Measured on a spin box, the app's own
    stroke pixels sit 3.81 and 3.54 from the corner's centre of curvature
    against a 4.0 radius, and the protruding ones 4.30 -- so a clean
    threshold at the radius separates them with room on both sides.
    """
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)
    return path


def _stray_corner_pixels(image, background, rect):
    """Pixels painted in ``rect``'s corners that lie outside the app's own
    rounded frame -- i.e. the protrusion, if there is one."""
    radius = ControlStyle.frame_radius(rect)
    curve = _app_curve(rect, radius)
    span = math.ceil(radius) + 1
    corners = ((rect.left(), rect.top()),
               (rect.right() - span + 1, rect.top()),
               (rect.left(), rect.bottom() - span + 1),
               (rect.right() - span + 1, rect.bottom() - span + 1))
    stray = []
    for left, top in corners:
        for x in range(left, left + span):
            for y in range(top, top + span):
                if not (0 <= x < image.width() and 0 <= y < image.height()):
                    continue
                if curve.contains(QPointF(x + 0.5, y + 0.5)):
                    continue
                pixel = image.pixelColor(x, y)
                # Well clear of an antialiased fringe: the measured
                # protrusion sits 138 channel levels off the card.
                if _channel_distance(pixel, background) > 24:
                    stray.append((x, y, pixel.name()))
    return stray


def _frame_rect(control, complex_control):
    """The rect the app strokes ``control``'s frame on. A push button's is
    its own; a complex control's is where Fusion actually strokes, which is
    not always where ``subControlRect`` reports it."""
    if complex_control is None:
        return control.rect()
    return ControlStyle.stroked_frame_rect(complex_control, control.rect())


# Every frame the app rounds, as (name, factory, complex control or None).
_ROUNDED_FRAMES = (
    ("spin box", QSpinBox, QStyle.ComplexControl.CC_SpinBox),
    ("combo box", QComboBox, QStyle.ComplexControl.CC_ComboBox),
    ("push button", lambda: QPushButton("Stop"), None),
)


@pytest.mark.parametrize("name, build, complex_control", _ROUNDED_FRAMES)
def test_no_frame_arc_protrudes_past_the_app_corner(
        qapp, name, build, complex_control):
    flip_palette(qapp, dark=False)
    control = build()
    image = _card_cropped_render(qapp, control)
    stray = _stray_corner_pixels(image, theme().card_bg,
                                 _frame_rect(control, complex_control))
    assert not stray, (
        f"the {name} paints {len(stray)} pixel(s) outside its own rounded "
        f"frame, in the corners: {stray[:8]} -- a second, squarer arc is "
        "showing past the app's curve, which is the grey nick reported from "
        "the real desktop")


@pytest.mark.parametrize("name, build, complex_control",
                         [frame for frame in _ROUNDED_FRAMES
                          if frame[0] != "combo box"])
def test_plain_fusion_is_what_protrudes_past_the_app_corner(
        qapp, name, build, complex_control):
    """The proof the assertion above is not vacuous.

    Rendered through plain, unmodified Fusion -- what sat underneath the
    app's stroke before this -- the same two controls do paint outside the
    app's curve, so a build that simply stopped drawing corners at all
    could not pass both tests. The combo box is deliberately absent:
    measured, Fusion's combo frame already falls inside the app's curve at
    every corner, so it never had the defect and asserting that it did
    would be asserting something untrue.
    """
    flip_palette(qapp, dark=False)
    qapp.setStyle(QStyleFactory.create("fusion"))
    try:
        control = build()
        image = _card_cropped_render(qapp, control)
        stray = _stray_corner_pixels(image, theme().card_bg,
                                     _frame_rect(control, complex_control))
    finally:
        qapp.setStyle(ControlStyle())
    assert stray, (
        f"plain Fusion paints nothing outside the app's own curve at the "
        f"{name}'s corners, so the assertion that ControlStyle paints "
        "nothing there is measuring an artefact that no longer exists")


# ================= 1c. The push button frame =================


def _card_render(qapp, control):
    """``control`` rendered inside a `Card`, resting.

    A decoy takes the keyboard focus first: a widget alone in a shown,
    active window already has it, and a "resting" grab taken before
    focusing a decoy would silently measure the focused state.
    """
    card = Card()
    decoy = QLineEdit()
    card.body.addWidget(decoy)
    card.body.addWidget(control)
    card.show()
    qapp.processEvents()
    decoy.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    try:
        assert control.hasFocus() is False
        return control.grab().toImage()
    finally:
        card.close()


def _plain_button():
    button = QPushButton("Stop")
    button.setFixedSize(80, 25)
    return button


# A colour no palette in this module produces and no antialiased edge of
# one can land on, so a scan can pick the icon's own pixels out of a
# rendered button with certainty.
_ICON_MARKER = QColor("#ff00ff")


def _marked_icon(extent: int = 16) -> QIcon:
    """An icon that fills its whole box in one unmistakable colour.

    Full-bleed on purpose: a glyph with transparent margins of its own
    would make the measured gap the sum of the app's spacing and whatever
    padding the icon designer left, and this suite has no business
    asserting the second.
    """
    pixmap = QPixmap(extent, extent)
    pixmap.fill(_ICON_MARKER)
    return QIcon(pixmap)


def _assert_plain_button_frame_is_the_apps_own(qapp, dark: bool) -> None:
    """A bare `QPushButton` is drawn entirely by Fusion unless this style
    takes an opinion about its frame, and Fusion's opinion is its own
    internal palette: measured offscreen at a device pixel ratio of 1 in a
    light scheme, an 80x25 button's top edge was 74 pixels of ``#ababab``
    against the app's own edge of ``#c7c7c7`` -- heavier than anything the
    app draws around it, which is the "borders still too coarse" of the
    maintainer's second real-desktop pass.

    Asserted against ``theme().border`` and against Fusion's own answer,
    which is the pair that says the app is drawing this edge rather than
    delegating it. It used to be asserted against the other edge token as
    well, back when a frame that *was* its control's affordance carried a
    heavier one than a frame around a labelled control; that split existed
    to hold the first group to a contrast floor that has since been
    dropped, and with the floor gone both wanted the same weight.
    """
    flip_palette(qapp, dark=dark)
    image = _card_render(qapp, _plain_button())
    edge = image.pixelColor(0, image.height() // 2)
    assert edge.name() == theme().border.name(), (
        f"a plain push button's left edge reads {edge.name()}, not the "
        f"app's own theme().border ({theme().border.name()}) -- dark={dark}")

    qapp.setStyle(QStyleFactory.create("fusion"))
    try:
        fusion_edge = _card_render(qapp, _plain_button()).pixelColor(
            0, image.height() // 2)
    finally:
        qapp.setStyle(ControlStyle())
    assert fusion_edge.name() != theme().border.name(), (
        f"plain Fusion already draws this button's edge in "
        f"theme().border ({theme().border.name()}), so the assertion above "
        f"is not measuring anything the app does -- dark={dark}")


def test_a_plain_push_button_frame_is_theme_derived_in_light(qapp):
    _assert_plain_button_frame_is_the_apps_own(qapp, dark=False)


def test_a_plain_push_button_frame_is_theme_derived_in_dark(qapp):
    _assert_plain_button_frame_is_the_apps_own(qapp, dark=True)


def _app_styled_buttons():
    """Every shape of button in this app that composes its own frame in a
    stylesheet, as (name, factory) pairs.

    A factory returns the button *and* whatever owns it, because a segment
    belongs to a `SegmentedControl` whose only reference is the factory's
    own local: let that go and Python collects the parent, which deletes
    the C++ button out from under the caller.
    """
    def segment():
        control = SegmentedControl(["One", "Two"])
        return control.findChildren(QPushButton)[0], control

    def accent():
        # Carrying an icon, so the icon-to-label spacing is inside the
        # comparison rather than beside it. `primary_button` places that
        # pair itself, which is what gives it the same gap as the bare
        # buttons beside it; the point of having it here is that placing
        # it *in the widget* keeps the rendering independent of which
        # style is installed, exactly as the border is.
        button = primary_button("Move")
        button.setIcon(_marked_icon())
        return button, None

    return (("primary_button", accent),
            ("SegmentedControl segment", segment),
            ("ToolIconButton",
             lambda: (ToolIconButton(QIcon(), "tip", "x"), None)))


def _render_app_styled(qapp, make):
    control, owner = make()
    try:
        return _card_render(qapp, control)
    finally:
        del owner


def test_a_button_that_styles_its_own_frame_is_left_alone(qapp):
    """The overlay must not double-draw on a button whose border is its own.

    Qt's dispatch already settles it -- a stylesheet declaring a border is
    rendered by ``QStyleSheetStyle``, which never delegates the bevel to
    its base style -- but "already settles it" is exactly the kind of claim
    that stops being true silently, so it is measured rather than trusted:
    each app-styled button must render pixel-identically with this style
    installed and with plain Fusion installed.

    A bare `QPushButton` is put through the same comparison as a control,
    and must differ. Without it this test would pass just as happily on a
    build whose overlay had stopped drawing anything at all.
    """
    flip_palette(qapp, dark=False)
    styled = {name: _render_app_styled(qapp, make)
              for name, make in _app_styled_buttons()}
    styled["a bare QPushButton"] = _card_render(qapp, _plain_button())

    qapp.setStyle(QStyleFactory.create("fusion"))
    try:
        fusion = {name: _render_app_styled(qapp, make)
                  for name, make in _app_styled_buttons()}
        fusion["a bare QPushButton"] = _card_render(qapp, _plain_button())
    finally:
        qapp.setStyle(ControlStyle())

    for name, _make in _app_styled_buttons():
        assert styled[name] == fusion[name], (
            f"{name} renders differently under ControlStyle than under "
            "plain Fusion -- the overlay is drawing over a border the "
            "widget composes itself, which puts a grey stroke on an "
            "accent-bordered button")
    assert styled["a bare QPushButton"] != fusion["a bare QPushButton"], (
        "a bare QPushButton renders identically under ControlStyle and "
        "under plain Fusion -- the overlay is not reaching it, so the "
        "equalities above prove nothing")


def _assert_disabled_button_frame_is_the_fainter_one(qapp, dark: bool) -> None:
    """The disabled treatment applies to a push button's frame too.

    The panel is painted outright, so the frame a disabled button ends up
    with is entirely the app's own choice -- there is no Fusion rendering
    underneath to dim. Drawing it at the resting weight would erase the one
    cue that says the button cannot be pressed, and would make a disabled
    button's outline exactly as strong as an enabled one's. Prominence is
    measured as distance from the card behind the button, which does not
    depend on which direction the palette dims in.
    """
    flip_palette(qapp, dark=dark)
    card_bg = theme().card_bg

    enabled = _plain_button()
    enabled_pixel = _find_border_pixel(
        _card_render(qapp, enabled), enabled.height() // 2, card_bg.name())

    disabled = _plain_button()
    disabled.setEnabled(False)
    disabled_pixel = _find_border_pixel(
        _card_render(qapp, disabled), disabled.height() // 2, card_bg.name())

    assert (_channel_distance(disabled_pixel, card_bg)
            < _channel_distance(enabled_pixel, card_bg)), (
        f"the disabled push button's frame ({disabled_pixel.name()}) is at "
        f"least as prominent against the card ({card_bg.name()}) as the "
        f"enabled one's ({enabled_pixel.name()}) -- a button that cannot be "
        f"pressed is drawn no fainter than one that can -- dark={dark}")


def test_a_disabled_push_button_has_the_fainter_frame_in_light(qapp):
    _assert_disabled_button_frame_is_the_fainter_one(qapp, dark=False)


def test_a_disabled_push_button_has_the_fainter_frame_in_dark(qapp):
    _assert_disabled_button_frame_is_the_fainter_one(qapp, dark=True)


# ================= 2. Focus =================


def _assert_combo_focus_changes_the_border(qapp, dark: bool) -> None:
    """Focusing a combo must make its outline *more* visible, not merely
    different.

    "Some pixel changed, and an accent-ish pixel appeared" would pass just
    as happily on a focused border that is invisible -- which is what
    shipped once, when the overlay used ``theme().accent_border`` (a
    half-way mix of the accent into the surface, meant for a border sitting
    on ``accent_fill``) and halved the outline's contrast against the card.
    So the rendered focused border pixel is compared against the rendered
    resting one, by distance from the card background: the focused stroke
    must be at least as far from the surface behind it as the resting
    stroke is. ``tests/test_control_contrast.py`` asserts the same
    direction on the tokens themselves, in WCAG terms.
    """
    flip_palette(qapp, dark=dark)
    window = QWidget()
    layout = QVBoxLayout(window)
    decoy = QLineEdit()
    target = QComboBox()
    layout.addWidget(decoy)
    layout.addWidget(target)
    window.show()
    qapp.processEvents()
    try:
        decoy.setFocus(Qt.FocusReason.OtherFocusReason)
        qapp.processEvents()
        assert target.hasFocus() is False, (
            "the combo already has focus before the decoy was focused -- "
            "the 'unfocused' baseline below would silently measure the "
            "focused state")
        unfocused = target.grab().toImage()

        target.setFocus(Qt.FocusReason.OtherFocusReason)
        qapp.processEvents()
        assert target.hasFocus() is True
        focused = target.grab().toImage()

        assert focused != unfocused, (
            f"focusing the combo changed no pixel at all -- dark={dark}")

        accent_hex = theme().accent.name()
        assert _contains_pixel(focused, accent_hex), (
            f"the focused combo carries no pixel matching theme().accent "
            f"({accent_hex}) -- dark={dark}")
        assert not _contains_pixel(unfocused, accent_hex), (
            f"the unfocused combo already carries theme().accent "
            f"({accent_hex}) -- the focus overlay leaked into the "
            f"resting state -- dark={dark}")

        card_bg = theme().card_bg
        row = target.height() // 2
        resting_pixel = _find_border_pixel(unfocused, row, card_bg.name())
        focused_pixel = _find_border_pixel(focused, row, card_bg.name())
        assert (_channel_distance(focused_pixel, card_bg)
                >= _channel_distance(resting_pixel, card_bg)), (
            f"focusing the combo made its outline fainter against the card: "
            f"{focused_pixel.name()} is closer to theme().card_bg "
            f"({card_bg.name()}) than the resting "
            f"{resting_pixel.name()} is -- that is a de-emphasis, not a "
            f"focus indicator -- dark={dark}")
    finally:
        window.close()


def test_a_focused_combo_carries_the_accent_in_light(qapp):
    _assert_combo_focus_changes_the_border(qapp, dark=False)


def test_a_focused_combo_carries_the_accent_in_dark(qapp):
    _assert_combo_focus_changes_the_border(qapp, dark=True)


# ================= 2b. Hover =================


def _render_combo(qapp, style, *, hovered: bool):
    """One combo frame drawn straight through ``style`` onto a card-coloured
    image, with hover forced by hand.

    A synthetic ``QStyleOptionComboBox`` rather than a real widget and a
    synthetic mouse move: the offscreen platform has no pointer to put over
    anything, and this is the mechanism 09-UI-SPEC names for the hover row
    of its state table.
    """
    option = QStyleOptionComboBox()
    option.rect = QRect(0, 0, 120, 26)
    option.state = (QStyle.StateFlag.State_Enabled
                    | QStyle.StateFlag.State_Active)
    if hovered:
        option.state |= QStyle.StateFlag.State_MouseOver
    option.palette = qapp.palette()
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    image.fill(theme().card_bg)
    painter = QPainter(image)
    try:
        style.drawComplexControl(
            QStyle.ComplexControl.CC_ComboBox, option, painter, None)
    finally:
        painter.end()
    return image


# Every control ``ControlStyle`` draws an edge for, as
# (name, option factory, size, draw). Named individually rather than
# exercised through one representative widget because the maintainer's
# report was about all of them -- "that highlight was present for all
# controls not just buttons" -- and because two of the four go through the
# push button's panel path and two through the framed controls' overlay.
def _drawn_controls():
    def draw_complex(control):
        def draw(style, option, painter):
            style.drawComplexControl(control, option, painter, None)
        return draw

    def draw_primitive(primitive):
        def draw(style, option, painter):
            style.drawPrimitive(primitive, option, painter, None)
        return draw

    return (
        ("a combo box", QStyleOptionComboBox, QSize(120, 26),
         draw_complex(QStyle.ComplexControl.CC_ComboBox)),
        ("a spin box", QStyleOptionSpinBox, QSize(120, 26),
         draw_complex(QStyle.ComplexControl.CC_SpinBox)),
        ("a checkbox indicator", QStyleOption, QSize(14, 14),
         draw_primitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox)),
        ("a push button", QStyleOptionButton, QSize(80, 25),
         draw_primitive(QStyle.PrimitiveElement.PE_PanelButtonCommand)),
    )


def _render_control(qapp, style, make_option, size, draw, *,
                    hovered: bool, enabled: bool = True):
    """One control drawn straight through ``style`` onto a card-coloured
    image, with hover and enablement forced by hand.

    Synthetic options rather than real widgets and a synthetic mouse move:
    the offscreen platform has no pointer to put over anything, and this is
    the mechanism 09-UI-SPEC names for the hover row of its state table.
    """
    option = make_option()
    # A default-constructed QStyleOptionSpinBox reports no frame, and the
    # style honours that -- QAbstractSpinBox.setFrame(False) is a real API
    # and a frame stroked over a control that asked for none would be a
    # bug. A real widget's initStyleOption sets it; a synthetic option has
    # to say so itself, or this renders a frameless control and asserts
    # nothing about the frame.
    if isinstance(option, (QStyleOptionComboBox, QStyleOptionSpinBox)):
        option.frame = True
    option.rect = QRect(0, 0, size.width(), size.height())
    option.state = QStyle.StateFlag.State_Active
    if enabled:
        option.state |= QStyle.StateFlag.State_Enabled
    if hovered:
        option.state |= QStyle.StateFlag.State_MouseOver
    option.palette = qapp.palette()
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    image.fill(theme().card_bg)
    painter = QPainter(image)
    try:
        draw(style, option, painter)
    finally:
        painter.end()
    return image


def _assert_hover_moves_every_control_edge(qapp, dark: bool) -> None:
    """The pointer moves a control's *border* to the desktop accent, on
    every control this style draws one for.

    The wave before this drew the highlight as a wash across the button's
    *face*, and that was turned down on the real desktop: the reference
    behaviour the maintainer is matching changes the border and leaves what
    is inside it alone. So the assertion is a pair -- the hovered edge
    reads as ``theme().hover_border`` and the resting one does not -- taken
    on the border pixel each render actually produces rather than on the
    tokens, which `tests/test_control_tokens.py` covers over five palettes.
    """
    flip_palette(qapp, dark=dark)
    style = ControlStyle()
    card_bg = theme().card_bg
    for name, make_option, size, draw in _drawn_controls():
        row = size.height() // 2
        resting = _find_border_pixel(
            _render_control(qapp, style, make_option, size, draw,
                            hovered=False), row, card_bg.name())
        hovered = _find_border_pixel(
            _render_control(qapp, style, make_option, size, draw,
                            hovered=True), row, card_bg.name())
        assert _closer_to(hovered, theme().hover_border, theme().border), (
            f"{name} under the pointer draws its border {hovered.name()}, "
            f"nearer the app's resting theme().border "
            f"({theme().border.name()}) than the hover edge it should take "
            f"({theme().hover_border.name()}) -- the pointer is not moving "
            f"this control's outline -- dark={dark}")
        assert _closer_to(resting, theme().border, theme().hover_border), (
            f"{name} at rest already draws its border {resting.name()}, "
            f"nearer the hover edge ({theme().hover_border.name()}) than "
            f"the resting theme().border ({theme().border.name()}) -- the "
            f"hover treatment has leaked into the resting state, so the "
            f"assertion above proves nothing -- dark={dark}")


def test_hover_moves_every_control_edge_in_light(qapp):
    _assert_hover_moves_every_control_edge(qapp, dark=False)


def test_hover_moves_every_control_edge_in_dark(qapp):
    _assert_hover_moves_every_control_edge(qapp, dark=True)


def test_hovering_a_disabled_control_leaves_its_edge_alone(qapp):
    """Qt reports ``State_MouseOver`` for a disabled widget under the
    pointer, so "a disabled control never takes the accent" is a rule the
    style holds rather than a state it never sees. Measured on the rendered
    border of each control rather than on the token, because the two draw
    routes settle the disabled case in the same method and a change that
    reintroduced a second answer would show up here first."""
    flip_palette(qapp, dark=False)
    style = ControlStyle()
    card_bg = theme().card_bg
    for name, make_option, size, draw in _drawn_controls():
        row = size.height() // 2
        pixel = _find_border_pixel(
            _render_control(qapp, style, make_option, size, draw,
                            hovered=True, enabled=False), row, card_bg.name())
        assert _closer_to(pixel, theme().disabled_border,
                          theme().hover_border), (
            f"a *disabled* {name} under the pointer draws its border "
            f"{pixel.name()}, nearer the hover edge "
            f"({theme().hover_border.name()}) than the disabled one "
            f"({theme().disabled_border.name()}) -- a control nobody can "
            "use is responding to the pointer")


def _changed_pixel_count(first, second) -> int:
    return sum(1
               for x in range(first.width())
               for y in range(first.height())
               if first.pixelColor(x, y) != second.pixelColor(x, y))


def test_the_overlay_leaves_fusions_hover_treatment_intact(qapp):
    """The overlay is drawn on top of Fusion's hover rendering, so it can
    erase part of it. Measured, it costs a couple of border pixels out of
    ~2720 and the hover fill survives untouched; the point of the test is
    that it stays that small, since a control whose hover response the
    overlay ate would look dead under the pointer everywhere except on its
    own outline.

    Counted against plain Fusion's own hover delta rather than against a
    number, so the app's *added* hover treatment -- the border moving to
    the accent -- can only push this further above the floor, never below
    it.
    """
    flip_palette(qapp, dark=False)
    styled_delta = _changed_pixel_count(
        _render_combo(qapp, ControlStyle(), hovered=False),
        _render_combo(qapp, ControlStyle(), hovered=True))
    fusion = QStyleFactory.create("fusion")
    plain_delta = _changed_pixel_count(
        _render_combo(qapp, fusion, hovered=False),
        _render_combo(qapp, fusion, hovered=True))

    assert plain_delta > 100, (
        f"plain Fusion changed only {plain_delta} pixels on hover -- the "
        "comparison below would be meaningless")
    assert styled_delta >= plain_delta * 0.9, (
        f"hovering the combo changes {styled_delta} pixels under "
        f"ControlStyle against plain Fusion's {plain_delta} -- the overlay "
        "is painting over Fusion's own hover treatment")


# ================= 3. Checked glyph =================


def _indicator_pixels(qapp, checked: bool) -> list[QColor]:
    """Every pixel inside the checkbox indicator's own bounding box.

    The box is read from Qt's own `subElementRect(SE_CheckBoxIndicator,
    ...)` rather than inferred from a colour scan -- the module docstring
    explains why an exact border-colour match is not available for this
    control.
    """
    window, checkbox, _combo, _spin = _build_card_row(qapp)
    try:
        checkbox.setChecked(checked)
        qapp.processEvents()
        option = QStyleOptionButton()
        checkbox.initStyleOption(option)
        indicator_rect = checkbox.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, checkbox)
        image = checkbox.grab().toImage()
        return [
            image.pixelColor(x, y)
            for x in range(indicator_rect.left(), indicator_rect.right() + 1)
            for y in range(indicator_rect.top(), indicator_rect.bottom() + 1)
        ]
    finally:
        window.close()


def _resting_edge(checked: bool) -> QColor:
    """The edge token a checkbox indicator is stroked with at rest.

    Two of them, and that is deliberate rather than drift: a ticked box is
    the one exemption from this style's single-edge-token rule, because
    the reference marks a ticked state in the accent on the edge as well
    as the fill. `gui/style.py`'s module docstring carries the reasoning.
    """
    return theme().accent_border if checked else theme().border


def _edge_pixels(pixels: list[QColor], edge: QColor) -> int:
    return sum(1 for pixel in pixels if pixel.name() == edge.name())


def test_a_checked_indicator_is_boxed_like_an_unchecked_one(qapp):
    """The app's own box is drawn in every checkbox state.

    This test replaces one that asserted the opposite -- that the checked
    and tristate glyphs were left entirely to Fusion, on the reasoning
    that a stroke over Fusion's own drawing would damage it. What that
    shipped, measured from the installed package on the maintainer's
    desktop, was a checked box with *no box*: zero frame pixels inside
    the indicator rect, a bare tick floating on the card, beside an
    unchecked box drawing a full 24. It never reproduced offscreen, where
    Fusion drew a frame of its own, so the previous test passed
    throughout -- and it would still pass today, because its tolerance is
    a distinct-colour count and the stroke this one asserts adds fewer
    colours than that tolerance absorbs.

    So the assertion is the frame itself, in the app's own token, on both
    states at once. Whether Fusion would have drawn something there is a
    question about whichever palette turned up; that the app draws it is
    a decision it makes on all of them.
    """
    flip_palette(qapp, dark=False)
    unchecked = _edge_pixels(_indicator_pixels(qapp, checked=False),
                             _resting_edge(checked=False))
    checked = _edge_pixels(_indicator_pixels(qapp, checked=True),
                           _resting_edge(checked=True))

    assert unchecked > 0, (
        "the unchecked indicator draws no pixel of its own edge token "
        f"({_resting_edge(checked=False).name()}) -- this test is measuring "
        "the wrong rect, not proving anything about the checked one")
    assert checked == unchecked, (
        f"the checked indicator draws {checked} pixels of its own edge "
        f"token against the unchecked one's {unchecked} -- ticking a "
        "checkbox changes how strongly it is boxed, and at zero it is the "
        "defect reported from the real desktop")


def test_a_checked_indicator_still_shows_its_glyph(qapp):
    """The box may not be bought by blanking the tick.

    The stroke follows the indicator's perimeter and the glyph is inset
    from it, so the two do not compete -- but that is a property of the
    radius and the indicator's size, both of which have moved during this
    phase, so it is asserted rather than reasoned about. Measured as ink:
    pixels far enough from the card to be the tick rather than the frame,
    which the unchecked box has none of.
    """
    flip_palette(qapp, dark=False)
    card = theme().card_bg

    def ink(pixels: list[QColor]) -> int:
        border_distance = _channel_distance(theme().border, card)
        return sum(1 for pixel in pixels
                   if _channel_distance(pixel, card) > 2 * border_distance)

    assert ink(_indicator_pixels(qapp, checked=False)) == 0, (
        "the unchecked indicator already carries pixels this test counts "
        "as a tick -- the threshold is not separating glyph from frame")
    assert ink(_indicator_pixels(qapp, checked=True)) > 0, (
        "the checked indicator carries no pixel darker than its own frame "
        "-- the overlay has painted the tick out")


def _mark_bounds_within(qapp, extent: int, state: QStyle.StateFlag) -> tuple:
    """Where the mark lands inside an ``extent``-square indicator, as
    fractions of the box, so two sizes can be compared directly.

    Read against the fill the style itself paints rather than against a
    colour nothing draws: the mark is the only thing inside a ticked box
    that is neither the fill nor the edge.
    """
    option = QStyleOptionButton()
    option.rect = QRect(0, 0, extent, extent)
    option.state = state
    option.palette = qapp.palette()
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    image.fill(theme().card_bg)
    painter = QPainter(image)
    try:
        ControlStyle().drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorCheckBox, option, painter)
    finally:
        painter.end()
    fill = ControlStyle.checkbox_fill(state)
    edge = ControlStyle.overlay_color(option, theme().accent_border)
    mark = (theme().text if state & QStyle.StateFlag.State_Enabled
            else theme().disabled_text)
    # A pixel belongs to the mark when the mark is the nearest of the
    # three things drawn in that box -- which needs no threshold to tune
    # and stays right when the fill or the edge moves, as both just did.
    ink = [(x, y)
           for x in range(extent) for y in range(extent)
           if min((_channel_distance(image.pixelColor(x, y), candidate),
                   index)
                  for index, candidate in enumerate((mark, fill, edge)))[1]
           == 0]
    assert ink, f"nothing was drawn inside a {extent}px ticked box"
    return (min(x for x, _ in ink) / extent, min(y for _, y in ink) / extent,
            max(x for x, _ in ink) / extent, max(y for _, y in ink) / extent)


def test_the_tick_follows_the_box_rather_than_a_pixel_count(qapp):
    """The mark is drawn from fractions of the indicator, so it is the
    same drawing at 14px and at twice that.

    This is the property Qt's own answer does not have and the reason the
    mark is the app's at all: a glyph laid out in whole pixels is right at
    one text scale and one device pixel ratio. Asserted as the mark's
    bounding box *as a fraction of its box*, which a pixel-count
    regression moves and a proportional one cannot.
    """
    flip_palette(qapp, dark=False)
    state = (QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_On)
    smaller = 14
    small = _mark_bounds_within(qapp, smaller, state)
    large = _mark_bounds_within(qapp, 2 * smaller, state)

    # Tolerated in pixels of the *smaller* box rather than as a flat
    # fraction, because that is the resolution at which a 14px box can
    # express anything at all: the outermost pixel of an antialiased
    # round cap is blended far enough into the fill at that size to stop
    # counting as the mark, and one pixel there is already 0.07 of the
    # box. A mark laid out in pixels rather than fractions misses by
    # several times this.
    tolerance = 1.5 / smaller
    for edge, (near, far) in enumerate(zip(small, large)):
        assert abs(near - far) <= tolerance, (
            f"edge {edge} of the tick sits at {near:.3f} of a {smaller}px "
            f"box and {far:.3f} of a {2 * smaller}px one, further apart "
            f"than the {tolerance:.3f} a pixel and a half of the smaller "
            "one comes to -- the mark is laid out in pixels, so it is "
            "drawn for one size and wrong at every other")


def test_a_ticked_box_and_a_tristate_one_carry_different_marks(qapp):
    """Nothing in the app sets a tristate checkbox today, which is exactly
    why this is asserted: the style draws that state's box outright, so a
    mark it forgot to draw would be a blank filled square nobody would
    meet until they built the widget that reaches it."""
    flip_palette(qapp, dark=False)
    ticked = _mark_bounds_within(
        qapp, 14, QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_On)
    middle = _mark_bounds_within(
        qapp, 14,
        QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_NoChange)
    assert ticked != middle, (
        "a tristate checkbox draws the same mark as a ticked one -- the "
        "two states are indistinguishable")


# ================= 4. Disabled =================


def _assert_disabled_reads_fainter_than_enabled(qapp, dark: bool) -> None:
    """A disabled control's frame must be *less* prominent than an enabled
    one's.

    The overlay draws ``theme().disabled_border`` when the control is
    disabled, rather than skipping (which left the frame to the palette's
    Disabled colour group, and this app cannot rely on that group -- on the
    maintainer's desktop it repeats the Active one) or stroking at resting
    strength. Asserting the disabled frame equals ``theme().border``
    exactly -- what this test used to do -- pinned the opposite in place: a
    disabled combo box came out *darker* than an enabled one had been
    before this style existed, and the assertion would have passed on a
    build that ignored the disabled state altogether.

    Prominence is measured as distance from the card behind the control,
    which is the question a user's eye asks and does not depend on which
    direction the palette dims in (light schemes dim toward white, dark
    ones toward black).
    """
    flip_palette(qapp, dark=dark)
    card_bg = theme().card_bg
    card_bg_hex = card_bg.name()

    enabled_window, enabled_checkbox, enabled_combo, enabled_spin = (
        _build_card_row(qapp))
    try:
        enabled_pixels = {
            "combo": _find_border_pixel(
                enabled_combo.grab().toImage(),
                enabled_combo.height() // 2, card_bg_hex),
            "spin": _find_border_pixel(
                enabled_spin.grab().toImage(),
                enabled_spin.height() // 2, card_bg_hex),
            "checkbox": _find_border_pixel(
                enabled_checkbox.grab().toImage(),
                enabled_checkbox.height() // 2, card_bg_hex),
        }
    finally:
        enabled_window.close()

    disabled_window, disabled_checkbox, disabled_combo, disabled_spin = (
        _build_card_row(qapp, enabled=False))
    try:
        disabled_widgets = {
            "combo": disabled_combo,
            "spin": disabled_spin,
            "checkbox": disabled_checkbox,
        }
        for name, widget in disabled_widgets.items():
            disabled_pixel = _find_border_pixel(
                widget.grab().toImage(), widget.height() // 2, card_bg_hex)
            enabled_pixel = enabled_pixels[name]
            assert (_channel_distance(disabled_pixel, card_bg)
                    < _channel_distance(enabled_pixel, card_bg)), (
                f"the disabled {name} frame ({disabled_pixel.name()}) is at "
                f"least as prominent against the card ({card_bg_hex}) as the "
                f"enabled one ({enabled_pixel.name()}) -- the overlay is "
                f"stroking a disabled control at resting weight -- "
                f"dark={dark}")
    finally:
        disabled_window.close()


def _flat_disabled_palette(qapp, dark: bool) -> None:
    """The palette that produced the defect: one whose Disabled colour group
    repeats its Active one.

    ``flip_palette`` above deliberately does the opposite -- it fills the
    Disabled group in by hand so Fusion has something to dim with -- which
    is right for the assertions that measure Fusion's own dimming, and
    wrong for these. Measured on the maintainer's Fedora KDE desktop, his
    palette gives Fusion nothing: an enabled and a disabled QPushButton
    came out with pixel-identical fills at identical counts, and only the
    frame moved. The two-argument ``setColor`` overload writes every colour
    group at once, which is exactly that condition.
    """
    roles = _DARK if dark else _LIGHT
    window = roles[QPalette.ColorRole.Window]
    text = roles[QPalette.ColorRole.WindowText]
    pal = QPalette(qapp.palette())
    for role, color in roles.items():
        pal.setColor(role, color)
    pal.setColor(QPalette.ColorRole.Button, window)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    qapp.setPalette(pal)
    qapp.processEvents()
    assert theme().is_dark is dark


def _button_render(qapp, *, enabled: bool):
    """One QPushButton, in a Card, at a fixed size so the two renders are
    directly comparable pixel for pixel."""
    card = Card()
    decoy = QLineEdit()
    button = QPushButton("Stop")
    button.setFixedSize(80, 25)
    button.setEnabled(enabled)
    card.body.addWidget(decoy)
    card.body.addWidget(button)
    card.show()
    qapp.processEvents()
    decoy.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    try:
        return button.grab().toImage()
    finally:
        card.close()


def _surface_and_label(image):
    """A button's own surface and the core of its label.

    The surface is the *mean* colour inside the frame rather than the
    commonest one: Fusion fills a button with a vertical gradient, so on a
    25px-tall button a dozen bands run within a pixel or two of each other
    for the same number of rows and which one wins the count is a tie-break,
    not a property of the rendering. The mean summarises the whole gradient
    and moves whenever any of it does. The frame is excluded by the margin,
    so a border change cannot masquerade as a fill change here.

    The label is the pixel furthest from that surface, which is a glyph's
    core rather than one of its antialiased edges.
    """
    margin = 3
    pixels = [image.pixelColor(x, y)
              for x in range(margin, image.width() - margin)
              for y in range(margin, image.height() - margin)]
    surface = QColor(round(sum(p.red() for p in pixels) / len(pixels)),
                     round(sum(p.green() for p in pixels) / len(pixels)),
                     round(sum(p.blue() for p in pixels) / len(pixels)))
    label = max(pixels, key=lambda pixel: _channel_distance(pixel, surface))
    return surface, label, Counter(pixel.name() for pixel in pixels)


def _assert_disabled_dims_fill_and_text(qapp, dark: bool) -> None:
    _flat_disabled_palette(qapp, dark)
    enabled_image = _button_render(qapp, enabled=True)
    disabled_image = _button_render(qapp, enabled=False)
    enabled_fill, enabled_label, enabled_counts = _surface_and_label(
        enabled_image)
    disabled_fill, disabled_label, disabled_counts = _surface_and_label(
        disabled_image)

    assert enabled_counts != disabled_counts, (
        f"an enabled and a disabled button render pixel-identical fills "
        f"({enabled_counts.most_common(4)}) -- only the frame is telling "
        f"the user this control cannot be used -- dark={dark}")
    assert enabled_fill.name() != disabled_fill.name(), (
        f"the disabled button's own surface is still {disabled_fill.name()}, "
        f"the same as the enabled one's -- dark={dark}")
    assert enabled_label.name() != disabled_label.name(), (
        f"the disabled button's label is still {disabled_label.name()}, the "
        f"same as the enabled one's -- dark={dark}")
    assert (_channel_distance(disabled_label, disabled_fill)
            < _channel_distance(enabled_label, enabled_fill)), (
        f"the disabled label ({disabled_label.name()} on "
        f"{disabled_fill.name()}) stands out from its own button at least as "
        f"strongly as the enabled one ({enabled_label.name()} on "
        f"{enabled_fill.name()}) -- it is different, not dimmed -- "
        f"dark={dark}")


def test_a_disabled_control_dims_its_fill_and_its_label_in_light(qapp):
    _assert_disabled_dims_fill_and_text(qapp, dark=False)


def test_a_disabled_control_dims_its_fill_and_its_label_in_dark(qapp):
    _assert_disabled_dims_fill_and_text(qapp, dark=True)


def _assert_disabled_frame_is_the_apps_own_token(qapp, install, dark: bool,
                                                 palette: str) -> None:
    """A disabled control's frame is the app's own ``disabled_border``,
    whatever the desktop's Disabled colour group happens to contain.

    Run against both palette shapes this module builds, and the second one
    is the point. ``flip_palette`` fills the Disabled group in by hand, so
    Fusion has something to dim with and *any* build looks plausible;
    ``_flat_disabled_palette`` repeats the Active group into it, which is
    what was measured on the maintainer's own desktop, and there Fusion
    dims nothing at all. Leaving the frame to Fusion -- what this style did
    before -- therefore drew a disabled control's outline at an enabled
    one's weight on exactly the palette the app actually ships to.
    """
    install(qapp, dark)
    window, checkbox, combo, spin = _build_card_row(qapp, enabled=False)
    try:
        card_bg_hex = theme().card_bg.name()
        expected = theme().disabled_border
        for widget, name in ((combo, "combo box"), (spin, "spin box")):
            pixel = _find_border_pixel(
                widget.grab().toImage(), widget.height() // 2, card_bg_hex)
            assert pixel.name() == expected.name(), (
                f"the disabled {name}'s frame reads {pixel.name()}, not the "
                f"app's own theme().disabled_border ({expected.name()}) -- "
                f"{palette} palette, dark={dark}")
        # The indicator is 14px, so its corners take a large share of the
        # box and a given border pixel may be an antialiased blend rather
        # than the stroke's own colour -- the module docstring covers this.
        pixel = _find_border_pixel(
            checkbox.grab().toImage(), checkbox.height() // 2, card_bg_hex)
        assert _closer_to(pixel, expected, theme().card_bg), (
            f"the disabled checkbox indicator's border pixel {pixel.name()} "
            f"is not closer to theme().disabled_border ({expected.name()}) "
            f"than to theme().card_bg ({card_bg_hex}) -- {palette} palette, "
            f"dark={dark}")
    finally:
        window.close()


@pytest.mark.parametrize("dark", [False, True])
def test_a_disabled_frame_is_the_apps_own_token_on_a_dimming_palette(
        qapp, dark):
    _assert_disabled_frame_is_the_apps_own_token(
        qapp, flip_palette, dark, "dimming")


@pytest.mark.parametrize("dark", [False, True])
def test_a_disabled_frame_is_the_apps_own_token_on_a_flat_palette(qapp, dark):
    _assert_disabled_frame_is_the_apps_own_token(
        qapp, _flat_disabled_palette, dark, "flat-disabled")


def test_a_disabled_control_reads_fainter_than_an_enabled_one_in_light(qapp):
    _assert_disabled_reads_fainter_than_enabled(qapp, dark=False)


def test_a_disabled_control_reads_fainter_than_an_enabled_one_in_dark(qapp):
    _assert_disabled_reads_fainter_than_enabled(qapp, dark=True)


# ----- ... including the one part of it a palette cannot reach -----


def _icon_button(*, enabled: bool):
    """A push button carrying a flat, saturated icon.

    Synthetic rather than from the icon theme: `QIcon.fromTheme` resolves
    nothing under the offscreen platform (Pitfall 3, 08-RESEARCH.md), and a
    single flat colour makes "was this recoloured, and to what" a question
    about one hex rather than about a glyph's internal shading.
    """
    glyph = QPixmap(16, 16)
    glyph.fill(QColor("#e01010"))
    button = QPushButton(QIcon(glyph), "")
    button.setIconSize(QSize(16, 16))
    button.setFixedSize(60, 26)
    button.setEnabled(enabled)
    return button


def _assert_a_disabled_icon_takes_the_apps_own_colour(qapp, dark: bool) -> None:
    """A `QIcon` is pixels, so no palette substitution reaches it.

    Qt does not leave it untouched either -- asked for a mode it holds no
    pixmap for, it synthesises one, grey-ramping the glyph toward the
    *application* palette's Disabled Window colour. Measured on a Breeze
    icon at 16px: mean opaque channel 35/38/41 normal against 116/116/116
    disabled, so it dims, but toward a colour group this app already knows
    it cannot rely on (the maintainer's repeats its Active one) and never
    toward the `disabled_text` the label right beside it is drawn in. The
    icon is recoloured through the app's own pixmap machinery instead, so
    the glyph and the label are one weight on every palette.
    """
    flip_palette(qapp, dark=dark)
    enabled_image = _card_cropped_render(qapp, _icon_button(enabled=True))
    disabled_image = _card_cropped_render(qapp, _icon_button(enabled=False))
    dimmed_hex = theme().disabled_text.name()

    assert _contains_pixel(enabled_image, "#e01010"), (
        "an enabled button's icon is not rendering in its own colour, so "
        f"nothing below distinguishes a recolour from a failure -- dark={dark}")
    assert not _contains_pixel(disabled_image, "#e01010"), (
        f"a disabled button's icon still carries its full-strength colour "
        f"#e01010 -- dark={dark}")
    assert _contains_pixel(disabled_image, dimmed_hex), (
        f"a disabled button's icon carries no pixel of the app's own "
        f"theme().disabled_text ({dimmed_hex}) -- it is being dimmed by "
        f"whatever Qt synthesises rather than by the app's rule, which is "
        f"the colour its label right beside it uses -- dark={dark}")


def test_a_disabled_buttons_icon_takes_the_apps_own_colour_in_light(qapp):
    _assert_a_disabled_icon_takes_the_apps_own_colour(qapp, dark=False)


def test_a_disabled_buttons_icon_takes_the_apps_own_colour_in_dark(qapp):
    _assert_a_disabled_icon_takes_the_apps_own_colour(qapp, dark=True)


def test_plain_fusion_does_not_dim_an_icon_to_the_apps_own_colour(qapp):
    """The proof the two tests above measure the app's rule and not Qt's.

    Under plain Fusion the same disabled icon still changes colour -- Qt
    synthesises a disabled pixmap for any icon that has none -- so
    "different from #e01010" on its own would pass with nothing of the
    app's involved. What does *not* happen without the app's rule is the
    icon landing on ``theme().disabled_text``.
    """
    flip_palette(qapp, dark=False)
    qapp.setStyle(QStyleFactory.create("fusion"))
    try:
        image = _card_cropped_render(qapp, _icon_button(enabled=False))
    finally:
        qapp.setStyle(ControlStyle())
    assert not _contains_pixel(image, theme().disabled_text.name()), (
        "plain Fusion already renders a disabled icon in "
        f"theme().disabled_text ({theme().disabled_text.name()}), so the "
        "assertions above are not measuring anything the app does")


# ================= 5. Geometry survives =================
#
# The regression wave 08-08 shipped and never had a test for: naming a
# border in a stylesheet hands the whole widget's box model to the
# stylesheet engine, whose padding defaults to zero, silently shrinking
# (or, for the spin box's width, growing) every affected control. This
# style overrides no PixelMetric or sizeFromContents -- ControlStyle draws
# through to Fusion first, unconditionally, for every primitive and
# complex control it touches -- so the expected result is exact equality
# with plain, unmodified Fusion. The `>=` form is asserted anyway (not
# `==`) so a deliberate future override that makes a control larger does
# not have to rewrite this test.
#
# Width and height are asserted independently, per control, never
# combined into one scalar or compared for only one control on behalf of
# the others: the 08-08 regression was not uniform (it shrank the combo by
# 10px wide and 4px tall, shrank the checkbox in both dimensions, and grew
# the spin box's width by 18px while shrinking its height), so an area
# comparison or a single representative control would have passed on the
# broken code by accident.


def _geometry_under_control_style_and_plain_fusion(qapp, widget_type):
    """``widget_a`` picks up whatever ``QApplication.setStyle()`` installed
    -- this module's fixture installs ``ControlStyle``. ``widget_b`` gets a
    second, separate ``QStyleFactory.create("fusion")`` instance via a
    per-widget ``setStyle()`` call, which does not disturb
    ``QApplication.style()``.

    ``widget_b`` is built with the application-level stylesheet cleared,
    then restored -- a per-widget ``QStyle`` does not exempt a widget from
    an application-level stylesheet (``QStyleSheetStyle`` wraps whichever
    base style is active, whichever one that is), so without this,
    ``widget_b`` would not be a genuine plain-Fusion reference: it would
    inherit the very stylesheet-forfeited box model this test exists to
    catch, the same as ``widget_a``, and the mutation proof this test's own
    SUMMARY records (wave 08-08's retired application-level control
    stylesheet mechanism applied) would silently pass instead of failing.
    """
    widget_a = widget_type()
    hint_a = widget_a.sizeHint()

    original_sheet = qapp.styleSheet()
    qapp.setStyleSheet("")
    try:
        widget_b = widget_type()
        widget_b.setStyle(QStyleFactory.create("fusion"))
        hint_b = widget_b.sizeHint()
    finally:
        qapp.setStyleSheet(original_sheet)
    return hint_a, hint_b


def _assert_geometry_survives(qapp, widget_type, name: str) -> None:
    control_style_hint, plain_fusion_hint = (
        _geometry_under_control_style_and_plain_fusion(qapp, widget_type))
    assert control_style_hint.width() >= plain_fusion_hint.width(), (
        f"{name}.sizeHint().width() shrank under ControlStyle: "
        f"{control_style_hint.width()} < plain Fusion's "
        f"{plain_fusion_hint.width()}")
    assert control_style_hint.height() >= plain_fusion_hint.height(), (
        f"{name}.sizeHint().height() shrank under ControlStyle: "
        f"{control_style_hint.height()} < plain Fusion's "
        f"{plain_fusion_hint.height()}")


def test_the_combo_box_geometry_survives_under_control_style(qapp):
    _assert_geometry_survives(qapp, QComboBox, "QComboBox")


def test_the_spin_box_geometry_survives_under_control_style(qapp):
    _assert_geometry_survives(qapp, QSpinBox, "QSpinBox")


def test_the_checkbox_geometry_survives_under_control_style(qapp):
    _assert_geometry_survives(qapp, QCheckBox, "QCheckBox")


def test_the_push_button_geometry_survives_under_control_style(qapp):
    """A push button is the one control this style *does* resize, and the
    direction it resizes in is the one this assertion already allows."""
    _assert_geometry_survives(qapp, lambda: QPushButton("Move"), "QPushButton")


def _line_edit_edge(qapp) -> str:
    """The colour a line edit's left edge is stroked in, under whichever
    style is currently installed on the application.

    The style is the caller's to set and reset, matching the idiom the
    checked-indicator tests above use: ``QApplication.setStyle`` takes
    ownership and destroys the outgoing style, so a saved reference to it
    cannot be put back.
    """
    card = Card()
    card._restyle()  # pylint: disable=protected-access
    edit = QLineEdit("FF:68:24:76:2E:80")
    # Somewhere else for focus to live. A lone focusable widget takes it on
    # show, and a focused control is stroked in the accent by design -- so
    # without this the test would measure the focus rule and never the
    # resting one.
    decoy = QPushButton("Find my desk…")
    card.body.addWidget(edit)
    card.body.addWidget(decoy)
    card.resize(card.sizeHint())
    card.show()
    decoy.setFocus()
    qapp.processEvents()
    image = card.grab().toImage()
    origin = edit.mapTo(card, edit.rect().topLeft())
    return image.pixelColor(origin.x(),
                            origin.y() + edit.height() // 2).name()


def test_a_line_edit_is_edged_in_the_apps_own_border(qapp):
    """The last control on a settings row that Fusion still framed itself.

    It was left alone deliberately while its hairline read *heavier* than
    the app's own edge rather than fainter -- measured in one card,
    `#ababab` against the `#c7c7c7` the combo and spin beside it carried.
    That is not a difference a user reads as a hairline weight; it is one
    control on the row looking outlined and the others looking drawn, and
    it was reported that way from the installed package as soon as the
    frame became visible at all.

    Asserted against plain Fusion as well as against the token, so the
    test says the app *changed* something rather than merely agreeing with
    whatever Qt happened to do.
    """
    flip_palette(qapp, dark=False)
    styled = _line_edit_edge(qapp)

    qapp.setStyle(QStyleFactory.create("fusion"))
    try:
        plain = _line_edit_edge(qapp)
    finally:
        qapp.setStyle(ControlStyle())

    assert styled == theme().border.name(), (
        f"a line edit's edge renders {styled}, not the app's own "
        f"theme().border ({theme().border.name()}) -- it is still Fusion's "
        "frame, and it does not match the controls beside it")
    assert plain != theme().border.name(), (
        f"plain Fusion already draws {plain} here, so this test would pass "
        "with the app's own overlay removed entirely")


def _framing_strokes(image, widget, host, edge: str) -> int:
    """How many separate vertical strokes in ``edge`` run down ``widget``.

    A control with one frame answers 2 -- its left side and its right. A
    box drawn inside a box answers more, which is the whole point: counted
    as *runs* of adjacent columns rather than as pixels, so antialiasing
    across two columns still reads as one stroke.

    A column counts only if the colour runs down at least half the
    control. Reading a single row through the middle instead made the
    answer depend on the host's font rendering, because that row passes
    through the control's text: a glyph's antialiased fringe lands on the
    frame colour exactly when text is rendered in greyscale, and does not
    when it is rendered in subpixel colour. The same commit was green on a
    developer machine and red in the RPM's build root for that reason
    alone.

    The two are not close once the whole column is read. Measured on the
    render that failed, a frame column carries the colour for 19 to 21
    pixels of a 31-pixel control, and every other column for 2 or 3 -- the
    top and bottom borders it passes through, plus at most one text pixel.
    """
    origin = widget.mapTo(host, widget.rect().topLeft())
    least = widget.height() // 2
    columns = []
    for x in range(widget.width()):
        run = longest = 0
        for y in range(widget.height()):
            if image.pixelColor(origin.x() + x,
                                origin.y() + y).name() == edge:
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        if longest >= least:
            columns.append(x)
    strokes, previous = 0, None
    for x in columns:
        if previous is None or x - previous > 1:
            strokes += 1
        previous = x
    return strokes


def test_no_framed_control_draws_a_box_inside_a_box(qapp):
    """Each framed control carries exactly one frame.

    The regression this exists for: a spin box draws its own frame through
    ``CC_SpinBox``, *and* its internal ``QLineEdit`` asks for
    ``PE_PanelLineEdit`` inside it. Stroking both put a second box around
    the text of every spinner in the app, which is what a real desktop
    showed within minutes of it shipping.

    It got in because the measurement that cleared the change keyed style
    dispatches by widget *type name*, and a spin box's own editor is a
    ``QLineEdit`` exactly like a free-standing one. Counting frames on the
    rendered control cannot be fooled that way, which is why this asserts
    pixels rather than dispatches.
    """
    flip_palette(qapp, dark=False)
    card = Card()
    card._restyle()  # pylint: disable=protected-access
    spin = QSpinBox()
    spin.setValue(60)
    combo = QComboBox()
    combo.addItem("Off")
    edit = QLineEdit("FF:68:24:76:2E:80")
    # Focus is stroked in the accent by design, so it has to live somewhere
    # that is not one of the controls being measured.
    decoy = QPushButton("Find my desk…")
    for widget in (spin, combo, edit, decoy):
        card.body.addWidget(widget)
    card.resize(card.sizeHint())
    card.show()
    decoy.setFocus()
    qapp.processEvents()

    image = card.grab().toImage()
    edge = theme().border.name()
    for name, widget in (("QSpinBox", spin), ("QComboBox", combo),
                         ("QLineEdit", edit)):
        strokes = _framing_strokes(image, widget, card, edge)
        assert strokes == 2, (
            f"a {name} is framed by {strokes} vertical strokes in the app's "
            f"own edge ({edge}), not the 2 one frame comes to -- something "
            "is drawing a box inside its box")


def _row_heights(qapp, point_size: int) -> dict:
    """Every kind of control a settings row puts side by side, at one font
    size, including the accent button -- which is sized by a different
    mechanism from the other four and so is exactly where they can drift
    apart."""
    font = QFont(qapp.font())
    font.setPointSize(point_size)
    built = {
        "QPushButton": QPushButton("Find my desk…"),
        "primary_button": primary_button("Move"),
        "QLineEdit": QLineEdit("FF:68:24:76:2E:80"),
        "QComboBox": QComboBox(),
        "QSpinBox": QSpinBox(),
    }
    built["QComboBox"].addItem("Toggle sit / stand")
    heights = {}
    for name, widget in built.items():
        widget.setFont(font)
        heights[name] = widget.sizeHint().height()
    return heights


@pytest.mark.parametrize("point_size", [7, 10, 11, 13, 15, 16, 22])
def test_every_control_in_a_row_stands_at_one_height(qapp, point_size):
    """A settings row mixes five kinds of control, and they have to line up.

    Fusion sizes each from its own contents and lands them apart -- 26, 26
    and 27 against a button's 32 at one text scale -- so a row stepped up
    and down for no reason a user could name. Reported that way from the
    installed package across every pane.

    The button is the reference rather than a fifth opinion, because it is
    the control this app already sized deliberately, against a measured
    comparison with the look being matched.

    Parameterised deliberately wide, because the drift this catches is a
    *rounding* difference and not a constant offset: a height taken from
    the label's own glyph bounding box rather than its line height agreed
    with the row at 10, 12, 14 and 18pt and stood a pixel above it at 11,
    13, 16 and 22. Any single-size check would have passed.
    """
    flip_palette(qapp, dark=False)
    heights = _row_heights(qapp, point_size)
    assert len(set(heights.values())) == 1, (
        f"at {point_size}pt the controls in a row hint different heights: "
        f"{heights} -- a row mixing them will not line up")


def test_the_row_height_grows_with_the_font(qapp):
    """It is a derivation from the line height, not a number. A constant
    would satisfy every equality above while leaving a user at 150% text
    with controls his own labels have outgrown."""
    flip_palette(qapp, dark=False)
    assert (_row_heights(qapp, 16)["QPushButton"]
            > _row_heights(qapp, 10)["QPushButton"]), (
        "the row height did not grow between 10pt and 16pt -- it has "
        "become a constant, which is right at one text scale and wrong at "
        "every other")


def test_a_spin_boxs_own_editor_is_not_floored_a_second_time(qapp):
    """The regression that fixing the row height introduced and this
    catches.

    ``QAbstractSpinBox`` sizes its internal ``QLineEdit`` first and feeds
    the answer into its own calculation, so a row-height floor applied to
    both compounds: the editor came out at the row height and the spin box
    at the row height *plus* its own frame, three pixels taller than
    everything beside it. The floor belongs to the control a layout
    places, not to an editor living inside one.
    """
    spin = QSpinBox()
    editor = spin.findChild(QLineEdit)
    assert editor is not None, (
        "this Qt build's QSpinBox has no internal QLineEdit, so the "
        "compounding this test guards cannot be measured here")
    assert not ControlStyle._stands_in_a_row(editor), (  # pylint: disable=protected-access
        "a spin box's own editor is being treated as a control standing in "
        "a row, so the row height is applied to it and to its host")
    assert ControlStyle._stands_in_a_row(QLineEdit()), (  # pylint: disable=protected-access
        "a free-standing line edit is being treated as an embedded editor, "
        "so it will not be held to the row height at all")


# ================= 5b. ... and a bare button matches the accent one =====


def test_a_bare_button_is_the_same_height_as_the_accent_one(qapp):
    """The "the buttons should be taller" fix, asserted as the relationship
    it actually is.

    Not a pixel count and not a pin. `widgets.primary_button` composes its
    stylesheet from ``theme``'s own button padding, and ``ControlStyle``
    hands the same padding to ``CT_PushButton``, so a bare `QPushButton`
    and an accent-filled one come out the same height *because they are
    sized from one pair of numbers* -- which is what makes the Overview
    page's Sit / Stand / Stop row level with the Move button beside it
    without either being measured against the other.

    Plain Fusion's own answer is asserted to be *shorter*, so this cannot
    pass on a build that dropped the override and happened to agree.
    """
    flip_palette(qapp, dark=False)
    card = Card()
    accent = primary_button("Move")
    bare = QPushButton("Move")
    card.body.addWidget(accent)
    card.body.addWidget(bare)
    card.show()
    qapp.processEvents()
    try:
        assert bare.sizeHint().height() == accent.sizeHint().height(), (
            f"a bare QPushButton hints {bare.sizeHint().height()}px tall "
            f"and primary_button {accent.sizeHint().height()}px for the "
            "same label -- the two kinds of button are no longer sized "
            "from one pair of padding numbers")
        assert bare.height() == accent.height(), (
            f"the two lay out at {bare.height()}px and "
            f"{accent.height()}px")
    finally:
        card.close()

    original_sheet = qapp.styleSheet()
    qapp.setStyleSheet("")
    try:
        fusion_button = QPushButton("Move")
        fusion_button.setStyle(QStyleFactory.create("fusion"))
        fusion_height = fusion_button.sizeHint().height()
    finally:
        qapp.setStyleSheet(original_sheet)
    assert fusion_height < bare.sizeHint().height(), (
        f"plain Fusion already hints {fusion_height}px for the same button, "
        f"the same as ControlStyle's {bare.sizeHint().height()}px -- the "
        "padding override is doing nothing and the equality above is a "
        "coincidence")


@pytest.mark.parametrize("point_size", [7, 10, 15, 22])
def test_the_button_padding_is_additive_to_the_label_metrics(qapp,
                                                             point_size):
    """A button's height is its own text plus the app's padding, at every
    text size -- and the two kinds of button stay level at every one of
    them.

    The vertical padding was raised because the buttons read as too short
    on a real desktop, and the risk of buying height that way is that it is
    bought once, at whatever font the author happened to be running. So
    this asserts the *relationship* rather than a pixel count: whatever the
    label's own metrics come to, the button stands taller than them by the
    app's own padding and its border, so a user at 150% text gets a
    proportionally taller button rather than a fixed box his text has
    outgrown. Parameterised across a range wide enough that a height
    smuggled in as a constant would show up as a failure at one end of it.
    """
    flip_palette(qapp, dark=False)
    font = QFont()
    font.setPointSize(point_size)
    card = Card()
    accent = primary_button("Move")
    bare = QPushButton("Move")
    for button in (accent, bare):
        button.setFont(font)
        card.body.addWidget(button)
    card.show()
    qapp.processEvents()
    try:
        expected = (bare.fontMetrics().height() + 2 * BUTTON_PADDING_V
                    + 2 * BORDER_WIDTH)
        assert bare.height() >= expected, (
            f"at {point_size}pt a bare button lays out {bare.height()}px "
            f"tall around {bare.fontMetrics().height()}px of label metrics "
            f"-- short of the {expected}px the app's own padding and border "
            "should add to it, so the padding has stopped being additive")
        assert bare.height() == accent.height(), (
            f"at {point_size}pt a bare QPushButton lays out "
            f"{bare.height()}px tall and primary_button {accent.height()}px "
            "-- the two kinds of button no longer track one pair of "
            "padding numbers across font sizes")
    finally:
        card.close()


# ================= 5c. ... and its icon stands clear of its label ========


def _label_gap(image: QImage) -> int:
    """The blank run between a push button's icon and the first ink of its
    label, in the rendered ``image``.

    Scanned rather than derived, because what was reported was a *visual*
    complaint -- "the glyph touches the S" -- and the toolkit's own answer
    to it is inconsistent with itself: Qt reserves four logical pixels for
    this in a push button's size hint and then draws the label at half of
    that, so a number read out of either half would have disagreed with
    what is on screen.

    The result includes the first glyph's own left side bearing, which is
    why every assertion below is a floor or a comparison rather than an
    equality.
    """
    columns = [x for x in range(image.width())
               if any(image.pixelColor(x, y) == _ICON_MARKER
                      for y in range(image.height()))]
    assert columns, "the button rendered no icon at all, so there is no gap"
    last_icon = columns[-1]
    fill = image.pixelColor(last_icon + 1, image.height() // 2)
    for x in range(last_icon + 1, image.width() - 2):
        for y in range(3, image.height() - 3):
            if _channel_distance(image.pixelColor(x, y), fill) > 40:
                return x - last_icon - 1
    raise AssertionError("the button rendered no label beside its icon")


# The text size the gap is measured at, and how far apart the app's answer
# and the toolkit's have to land there for the measurement to mean
# anything. Qt's spacing is a fixed pixel count and the app's is a
# fraction of the line height, so the two necessarily converge as the font
# shrinks; pinning the size and asserting the separation is what keeps a
# build that dropped the override from passing by coincidence.
_GAP_TEST_POINT_SIZE = 16
_SEPARABLE_GAP = 2


def _labelled_icon_button(point_size: int | None = None) -> QPushButton:
    button = QPushButton(_marked_icon(), "Skip next")
    if point_size is not None:
        font = QFont()
        font.setPointSize(point_size)
        button.setFont(font)
    return button


def test_a_push_button_icon_stands_clear_of_its_label(qapp):
    """The gap the maintainer asked for, measured where he saw it missing.

    Plain Fusion's own answer is asserted to be narrower, so this cannot
    pass on a build that dropped the spacing and happened to agree -- and
    that pairing is also the evidence for where the collapse came from:
    the two styles measured the same before this, which is what said the
    toolkit lays a button's label out that way rather than anything this
    phase's own paint code doing it.

    The font is pinned rather than left to whichever default the session
    hands over. The app's gap is a fraction of the label's line height and
    Qt's is a fixed pixel count, so on a small enough default font the two
    converge and the comparison would quietly stop distinguishing
    anything; ``_SEPARABLE_GAP`` below is asserted directly so that going
    vacuous is a failure rather than a pass.
    """
    flip_palette(qapp, dark=False)
    button = _labelled_icon_button(point_size=_GAP_TEST_POINT_SIZE)
    gap = _label_gap(_card_render(qapp, button))
    wanted = button_icon_gap(button.fontMetrics().height())
    assert gap >= wanted, (
        f"a push button's icon stands {gap}px clear of its label, short of "
        f"the {wanted}px the app asks for at this text size -- the gap has "
        "collapsed back onto the toolkit's own")

    qapp.setStyle(QStyleFactory.create("fusion"))
    try:
        fusion_gap = _label_gap(_card_render(
            qapp, _labelled_icon_button(point_size=_GAP_TEST_POINT_SIZE)))
    finally:
        qapp.setStyle(ControlStyle())
    assert wanted - fusion_gap >= _SEPARABLE_GAP, (
        f"plain Fusion already leaves {fusion_gap}px between the same "
        f"button's icon and label against the app's own {wanted}px, inside "
        f"the {_SEPARABLE_GAP}px that makes the two tellable apart -- the "
        "assertion above would pass on a build whose spacing override did "
        "nothing at all")


def test_every_kind_of_button_leaves_the_same_icon_gap(qapp):
    """Move and the buttons beside it have to space their icons alike.

    ``primary_button`` declares a border in a stylesheet, so Qt renders it
    through ``QStyleSheetStyle``, which lays a push button's label out
    through ``QCommonStyle`` directly and never reaches the application
    style. That left Move on the Overview page at the toolkit's ~2px while
    Sit, Stand and Stop took the app's, in the same row. It now places its
    own pair, from the same helper the style uses.

    Asserted as agreement between the two rather than as a floor under
    each, because "at least the app's gap" would pass just as happily on a
    Move that had drifted wider. One pixel of tolerance, because the scan
    finds the label's *first ink* and the two buttons do not present it
    identically: an accent-filled button carries its label at font-weight
    600 on a tinted fill, so the leading glyph's antialiased edge can clear
    the scan's threshold a column later than the same glyph in a plain
    weight on a neutral one. That is a property of the measurement, and it
    is four pixels smaller than the difference this test exists to catch.
    """
    flip_palette(qapp, dark=False)
    accent = primary_button("Skip next")
    accent.setIcon(_marked_icon())
    accent.setFont(_labelled_icon_button(
        point_size=_GAP_TEST_POINT_SIZE).font())
    accent_gap = _label_gap(_card_render(qapp, accent))
    bare_gap = _label_gap(_card_render(
        qapp, _labelled_icon_button(point_size=_GAP_TEST_POINT_SIZE)))
    assert abs(accent_gap - bare_gap) <= 1, (
        f"primary_button leaves {accent_gap}px between its icon and its "
        f"label where a bare QPushButton beside it leaves {bare_gap}px -- "
        "the two kinds of button in the same row are spaced differently")
    wanted = button_icon_gap(accent.fontMetrics().height())
    assert accent_gap >= wanted, (
        f"primary_button's icon stands {accent_gap}px clear of its label, "
        f"short of the {wanted}px the app asks for at this text size -- "
        "so the agreement above is two buttons sharing the toolkit's gap "
        "rather than the app's")


def test_the_icon_gap_follows_the_text_size(qapp):
    """It scales with the label rather than being a pixel count chosen at
    one font. Qt's own spacing is the counter-example: it measured two
    pixels at 10pt and two at 15pt, so a user at 150% text got the same
    gap beside text half again as large."""
    flip_palette(qapp, dark=False)
    small = _label_gap(_card_render(qapp, _labelled_icon_button(point_size=8)))
    large = _label_gap(_card_render(qapp, _labelled_icon_button(point_size=16)))
    assert large > small, (
        f"a push button leaves {small}px beside an 8pt label and {large}px "
        "beside a 16pt one -- the gap is a fixed pixel count, so it reads "
        "wrong at every text size but the one it was picked at")


def test_the_icon_gap_survives_a_right_to_left_layout(qapp):
    """Mirroring the pair must mirror the gap with it, not close it.

    The two halves of the label are placed by the app rather than by
    Fusion, so nothing about right-to-left comes for free here; both rects
    go through ``QStyle.visualRect``. Measured from the other side: with
    the icon on the right, the blank run is between the label's *last* ink
    and the icon's first column.
    """
    flip_palette(qapp, dark=False)
    button = _labelled_icon_button(point_size=_GAP_TEST_POINT_SIZE)
    button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    image = _card_render(qapp, button)
    columns = [x for x in range(image.width())
               if any(image.pixelColor(x, y) == _ICON_MARKER
                      for y in range(image.height()))]
    assert columns, "the right-to-left button rendered no icon at all"
    first_icon = columns[0]
    fill = image.pixelColor(first_icon - 1, image.height() // 2)
    last_ink = None
    for x in range(first_icon - 1, 1, -1):
        if any(_channel_distance(image.pixelColor(x, y), fill) > 40
               for y in range(3, image.height() - 3)):
            last_ink = x
            break
    assert last_ink is not None, (
        "the right-to-left button rendered no label beside its icon")
    wanted = button_icon_gap(button.fontMetrics().height())
    gap = first_icon - last_ink - 1
    assert gap >= wanted, (
        f"a right-to-left push button leaves {gap}px between its label and "
        f"its icon, short of the {wanted}px the app asks for -- mirroring "
        "the pair has closed the gap between them")
