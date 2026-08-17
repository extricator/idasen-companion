"""Fusion control borders: the checkbox indicator, combo frame and spin
frame, drawn by ``ControlStyle`` (`gui/style.py`) rather than by
``theme()``'s own colours -- on a card whose background is the same white
as Fusion's own fill, only a faint grey hairline would otherwise survive.
This module asserts the drawn border is theme()-derived and distinct from
the card background behind it, in both schemes, without displacing the
checked-state glyph or the combo/spin sub-controls Fusion still draws
itself. It asserts no absolute WCAG contrast ratio: the 3:1 non-text floor
was dropped as a gate, deliberately, because the app's control-border weight
is a look decision and is expected to sit below it. The one ratio comparison
below is *relative* -- focus and hover against rest -- and re-introduces
no threshold.
Where the floor might live instead is an open question recorded in the
repository's own `TODO.md`, under the item about it living nowhere.

Skipped where PySide6 is missing, matching every other GUI test in this
suite.
"""

import pytest

pytest.importorskip("PySide6")

import os
import re

# Forced, not defaulted -- a desktop session exports QT_QPA_PLATFORM (xcb
# here), which the RPM build inherits and then aborts on a display it can't
# reach. See tests/test_settings_form.py for the same rule.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor, QIcon, QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QLineEdit, QSpinBox, QStyle, QStyleFactory,
    QStyleOption,
)

from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import restyle  # noqa: E402
from idasen_companion.gui.pages import settings_form as settings_form_mod  # noqa: E402
from idasen_companion.gui.pages.settings import SettingsPage  # noqa: E402
from idasen_companion.gui.style import ControlStyle  # noqa: E402
from idasen_companion.gui.theme import css, theme  # noqa: E402
from idasen_companion.gui.widgets import Card  # noqa: E402

# Copied rather than imported from tests/test_theme_restyle.py -- tests/
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
def _isolated_registry(qapp):
    """Empty the registry before each test, install ``ControlStyle`` as the
    ambient application style, and undo every side effect after, so one
    test's registrations, palette flip or installed style can't leak into
    the next -- mirrors tests/test_control_style.py's fixture of the same
    purpose.

    The teardown installs a *fresh* ``QStyleFactory.create("fusion")``
    rather than saving and re-setting whatever style object was previously
    installed -- ``QApplication.setStyle`` takes ownership of the style
    object it replaces and may already have deleted it. Without this
    teardown ``ControlStyle`` leaks into every test module collected
    afterwards in the same process.
    """
    original_palette = QPalette(qapp.palette())
    restyle.reset_registry_for_tests()
    qapp.setStyle(ControlStyle())
    yield
    restyle.reset_registry_for_tests()
    qapp.setPalette(original_palette)
    qapp.setStyle(QStyleFactory.create("fusion"))
    qapp.processEvents()


def flip_palette(qapp, dark: bool) -> None:
    """Install a light or dark palette and pump the event loop."""
    roles = _DARK if dark else _LIGHT
    pal = QPalette(qapp.palette())
    for role, color in roles.items():
        pal.setColor(role, color)
    qapp.setPalette(pal)
    qapp.processEvents()
    assert theme().is_dark is dark, (
        f"palette flip to dark={dark} did not take -- theme().is_dark is "
        f"{theme().is_dark}")


class FakeClient(QObject):
    """Every signal a settings-class page's __init__ subscribes to, and
    nothing live. Copied from tests/test_theme_restyle.py's class of the
    same name -- see that module's docstring for why this isn't imported."""

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


# ================= 1. The contrast formula =================


def _linearize(channel: int) -> float:
    fraction = channel / 255
    if fraction <= 0.03928:
        return fraction / 12.92
    return ((fraction + 0.055) / 1.055) ** 2.4


def _relative_luminance(color: QColor) -> float:
    return (0.2126 * _linearize(color.red())
            + 0.7152 * _linearize(color.green())
            + 0.0722 * _linearize(color.blue()))


def contrast(a: QColor, b: QColor) -> float:
    """WCAG relative-luminance contrast ratio between two colours."""
    lum_a, lum_b = _relative_luminance(a), _relative_luminance(b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def test_the_contrast_formula_measures_black_on_white_at_21_to_1():
    ratio = contrast(QColor("black"), QColor("white"))
    assert abs(ratio - 21.0) < 0.01, (
        f"black-on-white should measure 21:1, a formula nobody validated "
        f"is not evidence -- got {ratio}")


def _control_option(*flags: QStyle.StateFlag) -> QStyleOption:
    """An enabled control's style option carrying ``flags`` and nothing
    else -- the input ``ControlStyle.overlay_color`` reads its answer
    from."""
    option = QStyleOption()
    option.state = QStyle.StateFlag.State_Enabled
    for flag in flags:
        option.state |= flag
    return option


def _assert_overlays_are_not_fainter_than_rest(qapp, dark: bool) -> None:
    """Whatever colour the focus or hover overlay uses, it must not be
    *fainter* against the card than the resting border it replaces.

    This is a relative assertion between two of the app's own tokens, not
    the fixed 3:1 floor D-05/D-06 deleted -- it re-introduces no threshold.
    It exists because a focus indicator that halves the outline's contrast
    is a de-emphasis, and because for a non-editable QComboBox (what this
    app builds) plain Fusion draws no focus indication at all, so this
    overlay is the only keyboard-focus affordance those controls have.
    Shipped once as ``theme().accent_border``: 1.82:1 light and 2.72:1
    dark against ``card_bg``, versus the resting border's 3.36:1 and
    4.45:1 as it was weighted then.

    One token rather than the two this once ran over: the edge a control's
    frame carries and the edge a push button's panel carries were separate
    tokens while the first was held to a contrast floor, and are one now
    that it is not.

    Hover is held to the same direction for the same reason. It is a
    weaker accent than focus by design -- the two would otherwise be
    indistinguishable -- and "weaker than focus" must not slide into
    "weaker than doing nothing at all".

    Read through ``ControlStyle.overlay_color`` rather than by reproducing
    the rule here, so this measures the colour the style will actually
    paint and not one a later edit could quietly stop using.
    """
    flip_palette(qapp, dark=dark)
    card_bg = theme().card_bg
    edge = theme().border
    focused_color = ControlStyle.overlay_color(
        _control_option(QStyle.StateFlag.State_HasFocus), edge)
    hovered_color = ControlStyle.overlay_color(
        _control_option(QStyle.StateFlag.State_MouseOver), edge)
    resting_color = ControlStyle.overlay_color(_control_option(), edge)
    focused = contrast(focused_color, card_bg)
    hovered = contrast(hovered_color, card_bg)
    resting = contrast(resting_color, card_bg)
    assert focused >= resting, (
        f"the focus overlay's colour ({focused_color.name()}, "
        f"{focused:.2f}:1 against the card) is fainter than the resting "
        f"theme().border it replaces ({resting_color.name()}, "
        f"{resting:.2f}:1) -- focusing a control must not make it harder "
        f"to see -- dark={dark}")
    assert hovered >= resting, (
        f"the hover overlay's colour ({hovered_color.name()}, "
        f"{hovered:.2f}:1 against the card) is fainter than the resting "
        f"theme().border it replaces ({resting_color.name()}, "
        f"{resting:.2f}:1) -- putting the pointer on a control must not "
        f"make it harder to see -- dark={dark}")


def test_the_pointer_overlays_are_not_fainter_than_the_resting_border_light(
        qapp):
    _assert_overlays_are_not_fainter_than_rest(qapp, dark=False)


def test_the_pointer_overlays_are_not_fainter_than_the_resting_border_dark(
        qapp):
    _assert_overlays_are_not_fainter_than_rest(qapp, dark=True)


# ================= 2. The rendered indicator =================


def _build_checkbox_in_card(qapp) -> tuple[Card, QCheckBox]:
    """A checkbox the way the app builds one -- inside a Card, under the
    installed ``ControlStyle`` the module fixture applies. A decoy field is
    focused first: a widget alone in a shown window already has keyboard
    focus, and the checkbox's own focus-ring colour would otherwise leak
    into what looks like its resting state."""
    card = Card()
    decoy = QLineEdit()
    checkbox = QCheckBox("test")
    card.body.addWidget(decoy)
    card.body.addWidget(checkbox)
    card.show()
    qapp.processEvents()
    decoy.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    assert checkbox.hasFocus() is False, (
        "the checkbox already has focus before the decoy was focused -- "
        "the 'resting' grab below would silently measure the focused state")
    return card, checkbox


def _find_border_pixel(image, y: int, card_bg_hex: str):
    """The first non-background, non-transparent pixel scanning left to
    right at row ``y`` -- not a hardcoded column, since a font-size change
    would move the indicator box."""
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


def _assert_indicator_border_has_contrast(qapp, dark: bool) -> None:
    """The checkbox indicator is the smallest box the overlay draws on --
    Fusion sizes it at 14px -- so how much of each edge survives as a
    straight, unblended run depends on ``theme.corner_radius`` and on
    Fusion's own indicator size, neither of which this assertion is about.
    It asks the question antialiased blending can always answer instead: is
    the observed pixel closer to ``theme().border`` than to
    ``theme().card_bg``."""
    flip_palette(qapp, dark=dark)
    card, checkbox = _build_checkbox_in_card(qapp)
    try:
        image = checkbox.grab().toImage()
        # Measured on this build: the indicator box sits at the checkbox's
        # vertical centre, so scanning that row finds its left edge first.
        y = checkbox.height() // 2
        pixel = _find_border_pixel(image, y, theme().card_bg.name())
        assert pixel.name() != theme().card_bg.name()
        assert _closer_to(pixel, theme().border, theme().card_bg), (
            f"the unchecked checkbox indicator's border pixel "
            f"{pixel.name()} is not closer to theme().border "
            f"({theme().border.name()}) than to theme().card_bg "
            f"({theme().card_bg.name()}) -- dark={dark}")
    finally:
        card.close()


def test_the_unchecked_indicator_border_has_contrast_in_light(qapp):
    _assert_indicator_border_has_contrast(qapp, dark=False)


def test_the_unchecked_indicator_border_has_contrast_in_dark(qapp):
    _assert_indicator_border_has_contrast(qapp, dark=True)


# The checked glyph is covered by
# `tests/test_control_style.py::test_the_checked_indicator_still_shows_its_glyph`.
# A test of that name lived here too, asserting an absolute floor of ten
# distinct colours over the indicator box. That floor was written against
# the stylesheet mechanism this phase replaced, whose failure mode was an
# unscoped rule *blanking* the glyph to two colours. The draw-through
# overlay inverts it: losing the unchecked-only scope draws a thin stroke on
# top of the glyph and *raises* the colour count, so the floor passes on the
# very mutation its own message names -- proven, the guard deleted from
# `gui/style.py` left all seven tests in this module green. The successor
# asserts a delta against plain Fusion's own count, which catches both
# directions.


# ================= 3. Combo and spin frames =================

# Repurposed as the negative matcher below: _themed_combo() used to compose
# this exact rule itself, independently of the app-wide control stylesheet
# rule wave 08-08 shipped, and this phase removes it -- the frame now comes
# from the application's own installed style.
_COMBO_FRAME_BORDER_RE = re.compile(
    r"QComboBox \{ border: 1px solid (#[0-9a-fA-F]{6});"
    r" border-radius: (\d+)px; \}")


def test_the_themed_combo_names_no_frame_border_of_its_own(qapp):
    """_themed_combo() must not take its own frame off Fusion's box model.

    Reads ``combo.styleSheet()`` at runtime rather than the source file --
    deliberate, since a source grep can be satisfied (or tripped) by an
    explanatory comment nearby, and a runtime read cannot be.
    """
    flip_palette(qapp, dark=False)
    combo = settings_form_mod.SettingsFormPage._themed_combo()  # pylint: disable=protected-access
    stylesheet = combo.styleSheet()

    assert _COMBO_FRAME_BORDER_RE.search(stylesheet) is None, (
        "the themed combo's stylesheet still names a QComboBox frame-border "
        "selector of its own -- that hands this widget's whole box model "
        "back to the stylesheet engine, off Fusion's again")

    popup_border = css(theme().border)
    assert popup_border in stylesheet, (
        "the themed combo's popup-view rule does not name the current "
        "theme().border")
    assert "QAbstractItemView" in stylesheet, (
        "the themed combo's stylesheet carries no popup-view rule at all")


def test_the_themed_combos_highlighted_row_is_the_desktops_selection(qapp):
    """The popup's highlighted option takes the desktop's own selection
    pair, the same as a selected sidebar row.

    A dropdown list with one option picked out is a selection in the
    strictest sense, and it used to be the app's thin ``accent_fill``
    tint with ordinary ``text`` written over it -- so on a dark desktop
    the row you were about to choose was a few channel levels off the
    popup behind it. The label moves with the fill and not separately:
    leaving it on ``text`` over a saturated background is the case where
    the option you are pointing at becomes the hardest one to read.

    Read from the built widget rather than from the source, for the
    reason the frame test above records -- a source grep can be satisfied
    by a comment.
    """
    flip_palette(qapp, dark=True)
    combo = settings_form_mod.SettingsFormPage._themed_combo()  # pylint: disable=protected-access
    stylesheet = combo.styleSheet()
    tokens = theme()

    assert f"selection-background-color: {css(tokens.accent)}" in stylesheet, (
        "the themed combo's highlighted row does not fill with the "
        f"desktop's own selection colour ({css(tokens.accent)}); the sheet "
        f"is {stylesheet}")
    assert f"selection-color: {css(tokens.selection_text)}" in stylesheet, (
        "the themed combo's highlighted row does not label itself in the "
        f"desktop's own selected-text colour ({css(tokens.selection_text)}); "
        f"the sheet is {stylesheet}")
    assert css(tokens.accent_fill) not in stylesheet, (
        f"the themed combo still names the emphasis tint "
        f"({css(tokens.accent_fill)}) -- its highlighted row has gone back "
        "to being a tint, or half of it has")


def test_the_spin_box_frame_is_theme_derived_not_fusions_grey(qapp):
    flip_palette(qapp, dark=False)
    card = Card()
    decoy = QLineEdit()
    spin = QSpinBox()
    card.body.addWidget(decoy)
    card.body.addWidget(spin)
    card.show()
    qapp.processEvents()
    decoy.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    assert spin.hasFocus() is False, (
        "the spin box already has focus before the decoy was focused -- "
        "the 'resting' grab below would silently measure the focused state")
    try:
        image = spin.grab().toImage()
        y = spin.height() // 2
        pixel = _find_border_pixel(image, y, theme().card_bg.name())
        assert pixel.name() == theme().border.name(), (
            f"the spin box frame reads {pixel.name()}, not the current "
            f"theme().border ({theme().border.name()})")
    finally:
        card.close()


# ================= 4. The icon candidate lists, not the icons =================
#
# Icon-theme resolution is unreachable under the offscreen platform used
# here (Pitfall 3, 08-RESEARCH.md) -- assert what icon() was called with,
# never the resolution itself.


def test_the_button_box_icon_candidates_match_what_this_plan_settled_on(
        qapp, monkeypatch):
    recorded: list[tuple[str, ...]] = []

    def _recording_icon(*names: str) -> QIcon:
        recorded.append(names)
        return QIcon()

    monkeypatch.setattr(settings_form_mod, "icon", _recording_icon)
    page = SettingsPage(_build_ctx())
    try:
        assert ("view-refresh", "view-refresh-symbolic") in recorded, (
            "RestoreDefaults was not given the expected icon candidates")
        assert ("edit-undo", "edit-undo-symbolic") in recorded, (
            "Reset was not given the expected icon candidates")
        assert len(recorded) == 2, (
            f"icon() was called {len(recorded)} times, not 2 -- Apply "
            "should receive no icon at all")
    finally:
        page.close()
