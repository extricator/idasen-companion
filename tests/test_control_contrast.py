"""Fusion control borders (problem 2): proven to fail before Tasks 1-2 of
this plan and pass after.

Fusion draws a checkbox indicator, a combo frame and a spin frame from its
own palette, not from ``theme()`` -- on a card whose background is the same
white as Fusion's own fill, only a faint grey hairline survives. This module
asserts the fix has real contrast, in both schemes, without displacing the
checked-state glyph or the combo/spin sub-controls Fusion still draws
itself.

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

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QColor, QIcon, QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QSpinBox,
)

from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import restyle  # noqa: E402
from idasen_companion.gui.pages import settings_form as settings_form_mod  # noqa: E402
from idasen_companion.gui.pages.settings import SettingsPage  # noqa: E402
from idasen_companion.gui.theme import theme  # noqa: E402
from idasen_companion.gui.widgets import (  # noqa: E402
    Card, control_css, install_control_styling,
)

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
    """Empty the registry before each test and undo its palette/stylesheet
    side effects after, so one test's registrations or palette flip can't
    leak into the next -- same shape as test_theme_restyle.py's fixture of
    the same name."""
    original_palette = QPalette(qapp.palette())
    restyle.reset_registry_for_tests()
    yield
    restyle.reset_registry_for_tests()
    qapp.setStyleSheet("")
    qapp.setPalette(original_palette)
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


# ================= 2. The token-level floor =================


def test_control_border_clears_the_contrast_floor_against_card_bg(qapp):
    """The floor binds the token the controls use, and only that one.

    WCAG 2.1 SC 1.4.11 covers what is required to identify a control. A
    checkbox's empty box is its whole affordance, so it is held here. The
    decorative ``border`` token is deliberately not: it draws card edges
    and pills, which read as themselves without any border, and holding it
    to 3:1 darkened every surface in the app at once.
    """
    for dark in (False, True):
        flip_palette(qapp, dark=dark)
        ratio = contrast(theme().control_border, theme().card_bg)
        assert ratio >= 3.0, (
            f"theme().control_border only clears {ratio:.2f}:1 against "
            f"card_bg with dark={dark} -- this is a theme.py bug (the "
            "blend fraction the token is derived with), not something a "
            "per-control rule should paper over")


# ================= 3 & 4. The rendered indicator =================


def _build_checkbox_in_card(qapp) -> tuple[Card, QCheckBox]:
    """A checkbox the way the app builds one -- inside a Card, with the
    same application-level mechanism main.py wires up."""
    card = Card()
    checkbox = QCheckBox("test")
    card.body.addWidget(checkbox)
    install_control_styling(qapp)
    card.show()
    qapp.processEvents()
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


def _assert_indicator_border_has_contrast(qapp, dark: bool) -> None:
    flip_palette(qapp, dark=dark)
    card, checkbox = _build_checkbox_in_card(qapp)
    try:
        image = checkbox.grab().toImage()
        # Measured on this build: the indicator box sits at the checkbox's
        # vertical centre, so scanning that row finds its left edge first.
        y = checkbox.height() // 2
        pixel = _find_border_pixel(image, y, theme().card_bg.name())
        assert pixel.name() == theme().control_border.name(), (
            f"the unchecked checkbox indicator's border reads "
            f"{pixel.name()}, not the current theme().control_border "
            f"({theme().control_border.name()}) -- dark={dark}")
        ratio = contrast(pixel, theme().card_bg)
        assert ratio >= 3.0, (
            f"the indicator border only clears {ratio:.2f}:1 against "
            f"card_bg -- dark={dark}")
    finally:
        card.close()


def test_the_unchecked_indicator_border_has_contrast_in_light(qapp):
    _assert_indicator_border_has_contrast(qapp, dark=False)


def test_the_unchecked_indicator_border_has_contrast_in_dark(qapp):
    _assert_indicator_border_has_contrast(qapp, dark=True)


def _indicator_box(image, border_hex: str) -> tuple[int, int, int, int]:
    """The bounding box of every pixel matching ``border_hex`` -- measured
    from the unchecked state, where the rule's own border colour marks the
    indicator's extent directly, rather than a hardcoded box size."""
    xs, ys = [], []
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).name() == border_hex:
                xs.append(x)
                ys.append(y)
    if not xs:
        raise AssertionError(
            "no pixel in the image matches the border colour -- the "
            "indicator box could not be located")
    return min(xs), min(ys), max(xs), max(ys)


def test_the_checked_indicator_still_shows_its_glyph(qapp):
    flip_palette(qapp, dark=False)
    card, checkbox = _build_checkbox_in_card(qapp)
    try:
        unchecked_image = checkbox.grab().toImage()
        min_x, min_y, max_x, max_y = _indicator_box(
            unchecked_image, theme().control_border.name())

        checkbox.setChecked(True)
        qapp.processEvents()
        checked_image = checkbox.grab().toImage()
        distinct = {checked_image.pixelColor(x, y).name()
                    for x in range(min_x, max_x + 1)
                    for y in range(min_y, max_y + 1)}
        # Well above the two-colour figure an unscoped rule produces (a
        # bare Fusion checked box measures 30 on this build) -- a threshold
        # with margin on both sides, so a font or DPI difference doesn't
        # flap the test.
        assert len(distinct) > 10, (
            f"the checked indicator shows only {len(distinct)} distinct "
            "colours across its box -- the border rule is taking over "
            "checked-state rendering too, which means it lost its "
            "unchecked-only scope")
    finally:
        card.close()


# ================= 5. Combo and spin frames =================

_COMBO_BASE_RULE_RE = re.compile(
    r"QComboBox \{ border: 1px solid (#[0-9a-fA-F]{6});"
    r" border-radius: (\d+)px; \}")


def test_the_themed_combo_composes_a_base_selector_border(qapp):
    flip_palette(qapp, dark=False)
    combo = settings_form_mod.SettingsFormPage._themed_combo()  # pylint: disable=protected-access

    match = _COMBO_BASE_RULE_RE.search(combo.styleSheet())
    assert match is not None, (
        "the themed combo's stylesheet carries no QComboBox base-selector "
        "border rule")
    assert match.group(1) == theme().control_border.name(), (
        "the themed combo's base-selector border does not name the "
        "current theme().control_border")
    assert int(match.group(2)) > 0, (
        "the themed combo's base-selector rule states a zero corner "
        "radius -- naming border at all takes the frame from Fusion, and "
        "the stylesheet engine's default corner is square")


def test_every_control_rule_states_a_nonzero_corner_radius(qapp):
    """A colour-only rule squares off a control Fusion drew rounded.

    That shipped once and was rejected on sight: the three controls were
    the only hard corners in an app whose every other frame is rounded.
    Each selector in control_css() must carry its own radius, since Qt
    applies none of its own once the border is named.
    """
    flip_palette(qapp, dark=False)
    rules = [rule for rule in control_css().split("}") if "border:" in rule]
    assert len(rules) == 3, (
        f"expected a rule each for the checkbox indicator, the combo and "
        f"the spin box -- found {len(rules)} in control_css()")
    for rule in rules:
        selector = rule.split("{")[0].strip()
        match = re.search(r"border-radius: (\d+)px", rule)
        assert match is not None and int(match.group(1)) > 0, (
            f"control_css()'s rule for {selector} names a border without "
            f"a non-zero radius, so Qt draws it square")


def test_the_spin_box_frame_is_theme_derived_not_fusions_grey(qapp):
    flip_palette(qapp, dark=False)
    card = Card()
    spin = QSpinBox()
    card.body.addWidget(spin)
    install_control_styling(qapp)
    card.show()
    qapp.processEvents()
    try:
        image = spin.grab().toImage()
        y = spin.height() // 2
        pixel = _find_border_pixel(image, y, theme().card_bg.name())
        assert pixel.name() == theme().control_border.name(), (
            f"the spin box frame reads {pixel.name()}, not the current "
            f"theme().control_border ({theme().control_border.name()})")
    finally:
        card.close()


# ================= 6. The icon candidate lists, not the icons =================
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
