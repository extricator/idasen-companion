"""The colour *relationships* a drawn control depends on, over five
palettes.

Every assertion here is relative, and that is the whole design of the
module. The app has no target colours: `gui/theme.py` derives every token
from `QPalette`, so a hex is a property of whichever desktop happened to be
running, never of the app. What the app does own is the ordering between
its own tokens -- a resting face is a step out of the card and not a panel
lying on it, a disabled face is stepped away from an enabled one and
stepped in the right direction, the pointer moves an edge and not a face,
focus is not fainter than rest -- and that ordering has to hold on any
palette a user turns up with. So the tokens are measured against each other, on a spread
of palettes chosen to break a rule that only works on one kind of desktop:

* a light one and a dark one, because a rule expressed as "lighten" or
  "darken" is direction-correct on exactly one of them;
* one whose Window and Base are the *same colour*, because a token derived
  from the distance between those two collapses to nothing there -- which
  is not hypothetical, it is the defect this module was written for:
  ``disabled_fill`` was ``mix(window, base, 0.9)`` and landed on the
  enabled face on every real desktop measured;
* one with an unusual hue and low internal contrast (Solarized-like),
  because a rule tuned on near-greys can quietly depend on the channels
  moving together;
* and Qt's own default palette, which is what the app renders against when
  no desktop tells it anything.

Distances are measured as a proportion of each palette's own ink axis --
the distance from the card to the text -- rather than in absolute channel
counts, because a low-contrast palette *should* produce low-contrast
tokens, and holding it to a fixed number would only mean the rule was
written for high-contrast palettes.

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

from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QPushButton, QStyle, QStyleOptionButton,
)

from idasen_companion.gui.style import ControlStyle  # noqa: E402
from idasen_companion.gui.theme import theme  # noqa: E402

# The five palettes, as (name, role -> colour). A palette naming no
# Highlight keeps Qt's own, which is all the accent assertions below need.
#
# "flat" is the one that matters most: its Window and Base are the same
# colour, which is what Adwaita's light scheme is very nearly and what any
# token derived from the gap between those two cannot survive.
_PALETTES = {
    "light": {
        QPalette.ColorRole.Window: "#f0f0f0",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.WindowText: "#000000",
        QPalette.ColorRole.Text: "#000000",
    },
    "dark": {
        QPalette.ColorRole.Window: "#202326",
        QPalette.ColorRole.Base: "#141618",
        QPalette.ColorRole.WindowText: "#fcfcfc",
        QPalette.ColorRole.Text: "#fcfcfc",
    },
    "flat": {
        QPalette.ColorRole.Window: "#fafafa",
        QPalette.ColorRole.Base: "#fafafa",
        QPalette.ColorRole.WindowText: "#2e3436",
        QPalette.ColorRole.Text: "#2e3436",
    },
    "solarized": {
        QPalette.ColorRole.Window: "#eee8d5",
        QPalette.ColorRole.Base: "#fdf6e3",
        QPalette.ColorRole.WindowText: "#657b83",
        QPalette.ColorRole.Text: "#657b83",
        QPalette.ColorRole.Highlight: "#268bd2",
    },
    # Qt's own, untouched -- what the app renders against on a session that
    # tells it nothing.
    "default": {},
}

# How far apart two steps of the same ramp must be, as a fraction of the
# palette's own card-to-ink distance. The tightest gap the ramp in theme.py
# has to hold open is the one between two neighbouring enabled faces; this
# floor sits well below it, with room for a deliberate future adjustment
# and far above the zero a collapse would produce.
_MIN_STEP = 0.025

# How far the *nearest* step of the ramp -- a resting button's face -- must
# still sit from the card, on the same scale. Smaller than a step between
# two ramp entries, because being close to the card is the whole point of
# the resting face; it just may not land *on* it, which is what the retired
# ``mix(window, base, 0.9)`` did to the disabled face on every palette
# measured. The same floor keeps a disabled control's own edge off its own
# fill: those two are deliberately close, and "close" still has to be a
# gap.
_MIN_SURFACE_STEP = 0.015

# How far the resting face may sit from the card, on the same scale, and
# the reason it is capped at all: a control is identified by the edge
# drawn around it, so its face only has to say a surface is there. Past
# that it stops being a step out of the card and becomes a grey panel
# lying on it -- reported from the installed package twice, most recently
# as a dropdown that "looks disabled" at a face 0.05 of the axis out while
# the disabled face sat at 0.13. The cap is what makes that report a test
# failure rather than a matter of taste, and it is set high enough above
# the shipped fraction to leave room for an adjustment that is not a
# return to a slab.
_MAX_SURFACE_STEP = 0.035

# The most of an enabled control's own internal contrast -- edge against
# fill, label against fill -- that a disabled one may keep. Half is a
# generous cap rather than a target: the tokens land near a quarter, and
# the assertion is there to catch a disabled treatment that changes a
# control's colour without flattening it, which is the state that reads as
# a second kind of button rather than as an unusable one.
_MAX_DISABLED_SHARE = 0.5

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restored_palette(qapp):
    original = QPalette(qapp.palette())
    yield
    qapp.setPalette(original)
    qapp.processEvents()


def install(qapp, name: str) -> None:
    """Install the named palette and confirm ``theme()`` recomputed."""
    palette = QPalette()
    for role, value in _PALETTES[name].items():
        palette.setColor(role, QColor(value))
    qapp.setPalette(palette)
    qapp.processEvents()


def channel_distance(a: QColor, b: QColor) -> int:
    return (abs(a.red() - b.red()) + abs(a.green() - b.green())
            + abs(a.blue() - b.blue()))


def ink_axis() -> int:
    """How far this palette's text sits from its card -- the span every
    surface token is a fraction of, and the only meaningful unit for
    "measurably stepped" on a palette nobody chose."""
    axis = channel_distance(theme().card_bg, theme().text)
    assert axis > 0, "a palette whose text is its card colour is unusable"
    return axis


def from_card(color: QColor) -> int:
    return channel_distance(color, theme().card_bg)


def _button_option(*flags: QStyle.StateFlag) -> QStyleOptionButton:
    option = QStyleOptionButton()
    option.state = QStyle.StateFlag.State_None
    for flag in flags:
        option.state |= flag
    return option


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_resting_face_is_a_surface_and_not_a_panel(qapp, name):
    """Bounded on both sides, because the resting face has been wrong in
    both directions on a real desktop and only one of them was ever
    asserted.

    The floor is the older half: a face that lands *on* the card leaves
    the control with no surface of its own, which is what the retired
    ``mix(window, base, 0.9)`` derivation did on every palette measured.

    The cap is the half this test was missing. Nothing stopped the face
    walking away from the card, and at 0.05 of the ink axis it had walked
    far enough that a combo box -- which has no fill but this one, and
    which sits in the same column as a spin box that keeps Fusion's own
    Base fill -- was reported from the installed package as looking
    disabled. Being "a visible step from the card" was satisfied
    throughout, which is exactly why the floor alone could not catch it.

    Both bounds are fractions of each palette's own ink axis rather than
    channel counts: a low-contrast palette should produce a low-contrast
    face, and either bound written as a number would only hold on the
    kind of desktop it was measured on.
    """
    install(qapp, name)
    step = from_card(theme().button_fill)
    assert step >= _MIN_SURFACE_STEP * ink_axis(), (
        f"on the {name} palette a resting button's face "
        f"({theme().button_fill.name()}) is {step} from the card behind it "
        f"({theme().card_bg.name()}), under the {_MIN_SURFACE_STEP:.3f} of "
        f"this palette's own ink axis ({ink_axis()}) that keeps it a surface "
        "at all -- the control has dissolved into the card")
    assert step <= _MAX_SURFACE_STEP * ink_axis(), (
        f"on the {name} palette a resting button's face "
        f"({theme().button_fill.name()}) is {step} from the card behind it "
        f"({theme().card_bg.name()}), over the {_MAX_SURFACE_STEP:.3f} of "
        f"this palette's own ink axis ({ink_axis()}) that keeps it a step "
        "out of the card -- an available control reads as a grey panel, "
        "and a combo box reads as disabled")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_dropdown_is_filled_like_a_field_and_a_button_is_not(qapp, name):
    """A combo box arrives at this style as a push button's panel, and it
    is not one.

    Fusion routes a combo's whole body through ``PE_PanelButtonCommand``,
    so it takes the button ramp unless something says otherwise -- while
    the spin box beside it in the same column keeps ``QPalette::Base``
    from Fusion and never touches the ramp at all. The two therefore
    agreed only while the ramp happened to sit near the card, and stopped
    agreeing the moment it moved, which is what was reported twice from
    the installed package. A dropdown now fills from the card like the
    field it is.

    Only at rest: disabled and popup-open still answer from the ramp,
    because those describe the control's state rather than its kind, and
    the disabled assertion here is the one that matters -- a field with no
    disabled treatment reads as usable.
    """
    install(qapp, name)
    combo = QComboBox()
    button = QPushButton()
    enabled = QStyle.StateFlag.State_Enabled

    assert ControlStyle.panel_face(enabled, combo).name() == \
        theme().card_bg.name(), (
        f"on the {name} palette a resting dropdown fills "
        f"{ControlStyle.panel_face(enabled, combo).name()} rather than the "
        f"card's own {theme().card_bg.name()} -- it is being drawn as a "
        "button, and the spin box beside it is not")
    assert ControlStyle.panel_face(enabled, button).name() == \
        theme().button_fill.name(), (
        f"on the {name} palette a resting push button fills "
        f"{ControlStyle.panel_face(enabled, button).name()} rather than the "
        "button ramp -- the field rule has escaped the control it is for")
    assert ControlStyle.panel_face(QStyle.StateFlag.State_None, combo).name() \
        == theme().disabled_fill.name(), (
        f"on the {name} palette a dropdown nobody can use fills like a "
        "field, so it reads as usable")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_resting_button_edge_is_the_apps_own_border_token(qapp, name):
    """The edge a resting button is drawn with is ``theme().border``, and
    it is measurably an edge -- further from the card than any face the
    button can take, which the ramp test below asserts state by state.

    This used to assert an ordering between two edge tokens as well: a
    frame that *is* its control's whole affordance carried a heavier one
    than a frame around a labelled control. That split existed only to hold
    the first group to a 3:1 contrast floor the second was never held to;
    the floor was dropped, and re-deriving the weight as an appearance
    decision put both at the same fraction, so there is no longer an
    ordering to assert.
    """
    install(qapp, name)
    edge = ControlStyle.button_edge(
        _button_option(QStyle.StateFlag.State_Enabled))
    assert edge.name() == theme().border.name(), (
        f"on the {name} palette the style draws a resting button's edge in "
        f"{edge.name()}, not the app's own theme().border "
        f"({theme().border.name()})")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_ticked_box_is_filled_from_the_desktops_own_accent(qapp, name):
    """A ticked checkbox is the one control in this style with a fill that
    is not neutral, and it may not be a colour this app chose.

    Asserted by moving ``QPalette::Highlight`` and watching the fill
    follow, the same way the hovered edge is asserted below -- a hardcoded
    blue passes any check that only looks at the shipped value, and this
    is the app that renders on whatever desktop it is installed on.

    The step off the card is asserted too, because a tint of the accent
    laid thinly enough is a white box with an argument behind it.
    """
    install(qapp, name)
    ticked = ControlStyle.checkbox_fill(QStyle.StateFlag.State_Enabled)
    assert from_card(ticked) >= _MIN_SURFACE_STEP * ink_axis(), (
        f"on the {name} palette a ticked box's fill ({ticked.name()}) is "
        f"{from_card(ticked)} from the card behind it, under the "
        f"{_MIN_SURFACE_STEP:.3f} of this palette's ink axis ({ink_axis()}) "
        "that makes it a fill at all -- ticking the box shows nothing")

    palette = QPalette(qapp.palette())
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#b8336a"))
    qapp.setPalette(palette)
    qapp.processEvents()
    moved = ControlStyle.checkbox_fill(QStyle.StateFlag.State_Enabled)
    assert moved.name() != ticked.name(), (
        f"on the {name} palette a ticked box still fills {ticked.name()} "
        "after the desktop's Highlight moved -- the fill is a colour this "
        "app picked, not the one the user did")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_selection_is_the_desktops_own_pair_and_never_a_tint(qapp, name):
    """Where the app marks something *selected* it takes the palette's
    Highlight and HighlightedText at full strength, unmixed.

    This is the one place the app deliberately does not derive a colour.
    Everywhere else a token is a fraction of the distance between two
    palette roles, because the app owns the relationship and the desktop
    owns the colour. A selection is different in kind: the user already
    has selected rows in every other Qt application on the machine, and
    they are that pair at full strength, so anything this app blends
    instead is a selection that does not look like the ones beside it.

    Both halves are asserted, because taking one without the other is
    worse than taking neither -- Highlight without HighlightedText leaves
    the label at whatever the surrounding text colour was, which on a
    saturated selection is the unreadable case.

    The last assertion is the one that answers the report this came from:
    a selection has to outweigh ``accent_fill``, the thin tint the app
    uses for emphasis. That tint *was* the sidebar's selected row, and on
    a dark desktop 0.16 of the accent laid on a near-black card is a step
    of a few channel levels -- reported from the installed package as
    muted. Pinning the ordering is what stops a future adjustment quietly
    walking a selection back onto the tint.
    """
    install(qapp, name)
    palette = qapp.palette()
    tokens = theme()

    assert tokens.accent.name() == palette.color(
        QPalette.ColorRole.Highlight).name(), (
        f"on the {name} palette a selection fills {tokens.accent.name()} "
        f"rather than the desktop's own Highlight "
        f"({palette.color(QPalette.ColorRole.Highlight).name()})")
    assert tokens.selection_text.name() == palette.color(
        QPalette.ColorRole.HighlightedText).name(), (
        f"on the {name} palette a selected label is "
        f"{tokens.selection_text.name()} rather than the desktop's own "
        f"HighlightedText "
        f"({palette.color(QPalette.ColorRole.HighlightedText).name()}) -- "
        "a selection that takes the fill without the label leaves the text "
        "at whatever colour the card behind it wanted")
    assert from_card(tokens.accent) > from_card(tokens.accent_fill), (
        f"on the {name} palette a selection ({tokens.accent.name()}, "
        f"{from_card(tokens.accent)} from the card) is no further from the "
        f"card than the emphasis tint ({tokens.accent_fill.name()}, "
        f"{from_card(tokens.accent_fill)}) -- being selected has stopped "
        "outweighing being merely emphasised")

    moved = QPalette(palette)
    moved.setColor(QPalette.ColorRole.Highlight, QColor("#b8336a"))
    moved.setColor(QPalette.ColorRole.HighlightedText, QColor("#f5e6c8"))
    qapp.setPalette(moved)
    qapp.processEvents()
    assert theme().accent.name() != tokens.accent.name(), (
        f"on the {name} palette a selection still fills "
        f"{tokens.accent.name()} after the desktop's Highlight moved")
    assert theme().selection_text.name() != tokens.selection_text.name(), (
        f"on the {name} palette a selected label is still "
        f"{tokens.selection_text.name()} after the desktop's "
        "HighlightedText moved -- it is a colour this app picked, not the "
        "one the user did")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_ticked_boxs_accent_edge_stays_ordered_against_hover_and_focus(
        qapp, name):
    """The one exemption from this style's single-edge-token rule, held to
    the ordering the rule was protecting.

    A ticked box strokes ``accent_border`` at rest, where every other
    control strokes ``border``. The risk that bought is real: hover
    carries the neutral edge 0.65 of the way to the accent and focus takes
    the accent outright, so a resting edge that starts part-way there
    could leave the three indistinguishable. It does not, because
    ``accent_border`` is a half-way mix of the accent *into the card*
    while the other two are carried from the edge toward the accent
    itself -- but that is a property of two derivations that could each
    move independently, which is exactly the kind of thing that has to be
    asserted rather than reasoned about once.
    """
    install(qapp, name)
    resting = ControlStyle.overlay_color(
        _button_option(QStyle.StateFlag.State_Enabled),
        theme().accent_border)
    hovered = ControlStyle.overlay_color(
        _button_option(QStyle.StateFlag.State_Enabled,
                       QStyle.StateFlag.State_MouseOver),
        theme().accent_border)
    focused = ControlStyle.overlay_color(
        _button_option(QStyle.StateFlag.State_Enabled,
                       QStyle.StateFlag.State_HasFocus),
        theme().accent_border)
    assert from_card(resting) < from_card(hovered) <= from_card(focused), (
        f"on the {name} palette a ticked box's three edge states are not "
        f"ordered away from the card: resting {resting.name()} "
        f"{from_card(resting)}, hover {hovered.name()} {from_card(hovered)}, "
        f"focus {focused.name()} {from_card(focused)}")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_ticked_box_nobody_can_use_takes_no_accent(qapp, name):
    """One disabled treatment, not one per control. A ticked box is the
    only thing this style fills with the accent, so it is also the only
    place a disabled control could come out as the brightest thing on a
    card full of grey."""
    install(qapp, name)
    ticked = ControlStyle.checkbox_fill(QStyle.StateFlag.State_None)
    assert ticked.name() == theme().disabled_fill.name(), (
        f"on the {name} palette a disabled ticked box fills {ticked.name()} "
        f"rather than the app's own disabled face "
        f"({theme().disabled_fill.name()})")
    assert ticked.name() == ControlStyle.button_face(
        QStyle.StateFlag.State_None).name(), (
        f"on the {name} palette a disabled ticked box and a disabled button "
        "carry different faces -- there are two disabled treatments")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_disabled_face_is_stepped_away_from_an_enabled_one(qapp, name):
    """The defect this module exists for, in both directions of scheme.

    ``disabled_fill`` used to be ``mix(window, base, 0.9)``. On the light
    and dark palettes here that lands within a couple of levels of the
    card, and on ``flat`` -- Window and Base the same colour -- it lands on
    it exactly, so a disabled control rendered the same as an enabled one.
    Both faces are now fractions of the same card-to-ink axis, which cannot
    collapse onto each other while the palette has any contrast at all.
    """
    install(qapp, name)
    enabled = ControlStyle.button_face(QStyle.StateFlag.State_Enabled)
    disabled = ControlStyle.button_face(QStyle.StateFlag.State_None)
    step = channel_distance(enabled, disabled)
    assert step >= _MIN_STEP * ink_axis(), (
        f"on the {name} palette a disabled button's face ({disabled.name()}) "
        f"is {step} from an enabled one's ({enabled.name()}), under the "
        f"{_MIN_STEP:.3f} of this palette's ink axis ({ink_axis()}) that "
        "counts as a visible step -- a switched-off control reads as usable")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_disabled_face_sits_further_from_the_card_than_a_resting_one(
        qapp, name):
    """Which way round the two faces go, pinned as an ordering.

    The pair shipped inverted: measured on the maintainer's light palette
    from the installed 1.0.2 package, a disabled button was ``#f7f7f7`` on
    a white card and a resting enabled one ``#e8e8e8``, so the control that
    could not be pressed was the crisper of the two. Being "a visible step
    apart" is satisfied by that rendering, which is why the step assertion
    above did not catch it and this one exists beside it.

    Bounded at the far end as well: a disabled face may not push past the
    strongest face a button can take while it is still usable, or the
    switched-off control becomes the heaviest thing on the card -- the same
    complaint, arrived at from the other side.
    """
    install(qapp, name)
    resting = ControlStyle.button_face(QStyle.StateFlag.State_Enabled)
    pressed = ControlStyle.button_face(QStyle.StateFlag.State_Enabled
                                       | QStyle.StateFlag.State_Sunken)
    disabled = ControlStyle.button_face(QStyle.StateFlag.State_None)
    assert from_card(disabled) > from_card(resting), (
        f"on the {name} palette a disabled button's face ({disabled.name()}, "
        f"{from_card(disabled)} from the card) sits nearer the card than a "
        f"resting enabled one ({resting.name()}, {from_card(resting)}) -- "
        "the switched-off control is the crisper of the two")
    assert from_card(disabled) <= from_card(pressed), (
        f"on the {name} palette a disabled button's face ({disabled.name()}, "
        f"{from_card(disabled)} from the card) asserts itself harder than a "
        f"button held down ({pressed.name()}, {from_card(pressed)}) -- "
        "nothing switched off may outweigh the heaviest usable state")
    # ... and the resting face stops short of dissolving into the card.
    # This is the assertion the retired derivation fails on all five
    # palettes: it put the nearest step between 0 and 6 channel levels from
    # the card, and exactly 0 on the one whose Window is its Base.
    assert from_card(resting) >= _MIN_SURFACE_STEP * ink_axis(), (
        f"on the {name} palette a resting button's face ({resting.name()}) "
        f"is {from_card(resting)} from the card behind it "
        f"({theme().card_bg.name()}), under the {_MIN_SURFACE_STEP:.3f} of "
        f"this palette's ink axis ({ink_axis()}) that keeps it a surface at "
        "all -- the control has dissolved into the card")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_disabled_control_is_flatter_inside_than_an_enabled_one(qapp, name):
    """Being a different shade is not being unavailable.

    A disabled face stepped away from an enabled one satisfies the two
    assertions above and still leaves a control that reads as a second kind
    of button -- crisp edge, full-strength label, simply painted another
    colour. What says "you cannot use this" is the *internal* contrast
    going flat: the edge closes onto the fill and the label closes onto it
    too, so the control loses its own structure rather than its own colour.

    Measured as a share of the enabled control's own equivalents, on each
    palette's own scale, since a low-contrast palette should produce a
    low-contrast control and holding either side to a fixed number would
    only mean the rule was written for high-contrast desktops. Both are
    floored as well as capped: flat is not blank, and an edge that has
    landed exactly on its fill has stopped being an edge.
    """
    install(qapp, name)
    resting = ControlStyle.button_face(QStyle.StateFlag.State_Enabled)
    disabled = ControlStyle.button_face(QStyle.StateFlag.State_None)
    enabled_edge = channel_distance(
        ControlStyle.button_edge(
            _button_option(QStyle.StateFlag.State_Enabled)), resting)
    disabled_edge = channel_distance(
        ControlStyle.button_edge(_button_option()), disabled)
    enabled_label = channel_distance(theme().text, resting)
    disabled_label = channel_distance(theme().disabled_text, disabled)

    assert disabled_edge <= _MAX_DISABLED_SHARE * enabled_edge, (
        f"on the {name} palette a disabled control's edge stands "
        f"{disabled_edge} off its own fill against an enabled one's "
        f"{enabled_edge} -- more than the {_MAX_DISABLED_SHARE:.2f} share "
        "that makes the control read as closed rather than as repainted")
    assert disabled_label <= _MAX_DISABLED_SHARE * enabled_label, (
        f"on the {name} palette a disabled control's label stands "
        f"{disabled_label} off its own fill against an enabled one's "
        f"{enabled_label} -- more than the {_MAX_DISABLED_SHARE:.2f} share")
    assert disabled_edge >= _MIN_SURFACE_STEP * ink_axis(), (
        f"on the {name} palette a disabled control's edge has landed on its "
        f"own fill ({disabled_edge} apart) -- flat is not the same as gone")
    assert disabled_label >= _MIN_STEP * ink_axis(), (
        f"on the {name} palette a disabled control's label has dissolved "
        f"into its own fill ({disabled_label} apart) -- the control is "
        "unavailable, not unlabelled")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_the_pointer_leaves_a_face_alone_and_pressing_does_not(qapp, name):
    """The pointer changes an edge; the mouse button changes a face.

    This asserted the opposite until 2026-08-17 -- that hovering moved the
    face a visible step -- and shipped that way twice. The first version
    washed the face in the desktop accent and was rejected as tuning to
    one desktop; the second kept the accent on the edge alone and stepped
    the face along the neutral ramp instead, and was rejected too, which
    is what settled that the objection was to the face moving at all
    rather than to the colour it moved to. So equality here is the
    assertion, not the absence of one: a hovered face that differs from a
    resting one by a single channel level is the regression.

    Nothing about hover feedback is lost by asserting it, because hover is
    an *edge* rule and the two tests below own it -- one holds the hovered
    edge to the desktop's own Highlight, the other holds it apart from
    keyboard focus.
    """
    install(qapp, name)
    resting = ControlStyle.button_face(QStyle.StateFlag.State_Enabled)
    hovered = ControlStyle.button_face(QStyle.StateFlag.State_Enabled
                                       | QStyle.StateFlag.State_MouseOver)
    pressed = ControlStyle.button_face(QStyle.StateFlag.State_Enabled
                                       | QStyle.StateFlag.State_Sunken)
    checked = ControlStyle.button_face(QStyle.StateFlag.State_Enabled
                                       | QStyle.StateFlag.State_On)
    assert hovered.name() == resting.name(), (
        f"on the {name} palette a hovered button's face ({hovered.name()}) "
        f"differs from a resting one's ({resting.name()}) -- the pointer is "
        "moving the fill, and it may move only the edge")
    assert channel_distance(pressed, resting) >= _MIN_STEP * ink_axis(), (
        f"on the {name} palette a pressed button ({pressed.name()}) is not "
        f"a visible step from a resting one ({resting.name()}) -- holding "
        "the control down does nothing to it")
    assert checked.name() == pressed.name(), (
        "a checked button and a held-down one are the same face, by design")
    assert from_card(resting) < from_card(pressed), (
        f"on the {name} palette the resting/pressed ramp is not ordered "
        f"away from the card: {resting.name()} {from_card(resting)}, "
        f"{pressed.name()} {from_card(pressed)}")

    focused = ControlStyle.button_edge(
        _button_option(QStyle.StateFlag.State_Enabled,
                       QStyle.StateFlag.State_HasFocus))
    edge = ControlStyle.button_edge(
        _button_option(QStyle.StateFlag.State_Enabled))
    assert focused.name() != edge.name(), (
        f"on the {name} palette a focused button's edge is the same colour "
        "as a resting one's -- keyboard focus is invisible")
    assert from_card(focused) >= from_card(edge), (
        f"on the {name} palette focusing a button makes its edge fainter "
        f"against the card ({focused.name()} at {from_card(focused)} "
        f"against {edge.name()} at {from_card(edge)}) -- that is a "
        "de-emphasis, not a focus indicator")


def _edges(*flags: QStyle.StateFlag) -> tuple[QColor, QColor]:
    """The edge the style draws in ``flags``, by both routes that draw one:
    a push button's panel and the overlay stroked on the framed controls.

    Both are asserted throughout this module rather than one standing in
    for the other, because the maintainer's report was that the pointer
    changes the border of *every* control -- and the two routes are
    separate code paths that have already carried different tokens once.
    """
    option = _button_option(*flags)
    return (ControlStyle.button_edge(option),
            ControlStyle.overlay_color(option, theme().border))


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_hovered_control_takes_the_desktops_own_accent_border(qapp, name):
    """The pointer moves a control's *edge* to ``QPalette::Highlight``.

    Asserted by moving only the Highlight role and watching the hovered
    edge move with it: an edge that had quietly gone back to a neutral grey
    would sit still, and a test naming a colour would pass on one desktop
    and mean nothing on the next. The resting edge is asserted *not* to
    move in the same breath, and neither is the face behind either of them
    -- the whole point of this treatment, as against the accent fill it
    replaced, is that hovering changes the outline and leaves the control's
    surface alone.
    """
    install(qapp, name)
    hovered = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_MouseOver
    before_hover = [color.name() for color in _edges(hovered)]
    before_rest = [color.name()
                   for color in _edges(QStyle.StateFlag.State_Enabled)]
    before_face = ControlStyle.button_face(hovered).name()

    palette = QPalette(qapp.palette())
    # Any colour the palette does not already use for Highlight; the point
    # is only that it changed.
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#b4009c"))
    qapp.setPalette(palette)
    qapp.processEvents()

    after_hover = [color.name() for color in _edges(hovered)]
    assert all(one != two for one, two in zip(before_hover, after_hover)), (
        f"on the {name} palette, changing only the desktop's accent left a "
        f"hovered control's edges at {before_hover} -- the hover border is "
        "not derived from QPalette::Highlight, so it cannot follow the "
        "desktop the user actually chose")
    assert [color.name()
            for color in _edges(QStyle.StateFlag.State_Enabled)] == (
                before_rest), (
        f"on the {name} palette, changing the desktop's accent moved a "
        f"*resting* control's edge from {before_rest} -- a control nobody "
        "is pointing at has started announcing itself")
    assert ControlStyle.button_face(hovered).name() == before_face, (
        f"on the {name} palette, changing the desktop's accent moved a "
        f"hovered control's *face* from {before_face} -- the accent belongs "
        "on the border, and washing the face with it is the treatment this "
        "one replaced")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_hover_and_keyboard_focus_are_told_apart(qapp, name):
    """The collision this treatment has to avoid.

    A control's frame already turns ``theme().accent`` on keyboard focus,
    and it has to: a non-editable QComboBox -- what this app builds -- gets
    no focus indication from Fusion at all, so the overlay is its only one.
    Painting the accent on hover as well would make a pointer crossing the
    pane indistinguishable from Tab landing on it.

    They are separated by *weight*, not by thickness -- every edge in this
    app is one pixel and stays one -- with focus keeping the stronger of
    the two, because it is the persistent state and the one that says where
    the keys go. So the three states order by prominence against the card:
    resting, then hover, then focus.
    """
    install(qapp, name)
    floor = _MIN_STEP * ink_axis()
    states = {
        "resting": _edges(QStyle.StateFlag.State_Enabled),
        "hovered": _edges(QStyle.StateFlag.State_Enabled,
                          QStyle.StateFlag.State_MouseOver),
        "focused": _edges(QStyle.StateFlag.State_Enabled,
                          QStyle.StateFlag.State_HasFocus),
    }
    for route, index in (("a push button's panel", 0),
                         ("the framed controls' overlay", 1)):
        resting, hovered, focused = (states[label][index]
                                     for label in ("resting", "hovered",
                                                   "focused"))
        for first, second in (("resting", "hovered"), ("hovered", "focused"),
                              ("resting", "focused")):
            gap = channel_distance(states[first][index], states[second][index])
            assert gap >= floor, (
                f"on the {name} palette {route} draws {first} "
                f"({states[first][index].name()}) and {second} "
                f"({states[second][index].name()}) only {gap} apart, under "
                f"the {_MIN_STEP:.3f} of this palette's ink axis "
                f"({ink_axis()}) that counts as a visible step -- the two "
                "states are the same control to look at")
        assert (from_card(resting) < from_card(hovered)
                < from_card(focused)), (
            f"on the {name} palette {route} does not order its edges "
            f"resting, hover, focus away from the card: "
            f"{resting.name()} {from_card(resting)}, {hovered.name()} "
            f"{from_card(hovered)}, {focused.name()} {from_card(focused)}")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_disabled_control_never_takes_the_accent_border(qapp, name):
    """A pointer resting on a control that cannot be used must leave its
    outline alone too. Qt reports ``State_MouseOver`` for a disabled widget
    under the pointer, so this is a rule both edge routes have to hold
    rather than a state they never see, and the desktop accent is exactly
    the wrong thing to hand something unactionable."""
    install(qapp, name)
    for label, flags in (("hovered", (QStyle.StateFlag.State_MouseOver,)),
                         ("pressed", (QStyle.StateFlag.State_Sunken,)),
                         ("focused", (QStyle.StateFlag.State_HasFocus,)),
                         ("hovered and focused",
                          (QStyle.StateFlag.State_MouseOver,
                           QStyle.StateFlag.State_HasFocus))):
        for route, edge in zip(("a push button's panel",
                                "the framed controls' overlay"),
                               _edges(*flags)):
            assert edge.name() == theme().disabled_border.name(), (
                f"on the {name} palette {route} draws a {label} *disabled* "
                f"control's edge in {edge.name()} rather than "
                f"theme().disabled_border "
                f"({theme().disabled_border.name()}) -- an unusable control "
                "is responding to the pointer")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_a_disabled_button_never_responds_to_the_pointer(qapp, name):
    """A pointer resting on a control that cannot be used must change
    nothing about it. Qt still reports ``State_MouseOver`` for a disabled
    widget under the pointer, so this is a rule the style has to hold
    rather than a state it never sees."""
    install(qapp, name)
    disabled = ControlStyle.button_face(QStyle.StateFlag.State_None)
    for label, state in (
            ("hovered", QStyle.StateFlag.State_MouseOver),
            ("pressed", QStyle.StateFlag.State_Sunken),
            ("checked", QStyle.StateFlag.State_On)):
        face = ControlStyle.button_face(state)
        assert face.name() == disabled.name(), (
            f"on the {name} palette a {label} *disabled* button renders "
            f"{face.name()} rather than the disabled face "
            f"({disabled.name()}) -- an unusable control is responding to "
            "the pointer")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_the_whole_button_ramp_stays_inside_its_own_edge(qapp, name):
    """The edge drawn around a button never disappears into the face drawn
    inside it, in any state the button can be in -- including at the far
    end of the ramp, and including the disabled state, whose edge is
    deliberately the closest of all to its own fill.

    Measured as the distance between the edge and the fill, which is what
    "the outline is still there" means. It used to be measured as the fill
    staying nearer the card than the edge, which is a legitimate proxy only
    while every face and every edge sits on the one card-to-ink axis. An
    edge need not: an accent-derived one can be further from the card than
    the face inside it and still stand out against it perfectly well, so
    the proxy would fail on a palette where the outline it exists to
    protect was never at risk.
    """
    install(qapp, name)
    for state, label in (
            (QStyle.StateFlag.State_None, "disabled"),
            (QStyle.StateFlag.State_Enabled, "resting"),
            (QStyle.StateFlag.State_Enabled
             | QStyle.StateFlag.State_MouseOver, "hovered"),
            (QStyle.StateFlag.State_Enabled
             | QStyle.StateFlag.State_Sunken, "pressed")):
        face = ControlStyle.button_face(state)
        edge = ControlStyle.button_edge(_button_option(state))
        separation = channel_distance(edge, face)
        assert separation >= _MIN_SURFACE_STEP * ink_axis(), (
            f"on the {name} palette a {label} button's edge ({edge.name()}) "
            f"stands only {separation} off its own face ({face.name()}), "
            f"under the {_MIN_SURFACE_STEP:.3f} of this palette's ink axis "
            f"({ink_axis()}) that keeps it visible -- the button loses its "
            "outline in that state")


@pytest.mark.parametrize("name", list(_PALETTES))
def test_no_button_token_moves_when_only_the_window_colour_does(qapp, name):
    """The structural reason the collapse cannot come back.

    ``mix(window, base, …)`` failed because it measured the gap between two
    roles a desktop is free to make identical. Every face below is a
    fraction of card-to-ink instead, so moving Window -- to Base's own
    colour, which is the worst case -- must move none of them. A rule that
    quietly reintroduced a Window term would show up here as a changed
    colour rather than as a subtly wrong rendering nobody notices.
    """
    install(qapp, name)
    states = (QStyle.StateFlag.State_None,
              QStyle.StateFlag.State_Enabled,
              QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_MouseOver,
              QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Sunken)
    before = [ControlStyle.button_face(state).name() for state in states]

    palette = QPalette(qapp.palette())
    palette.setColor(QPalette.ColorRole.Window,
                     palette.color(QPalette.ColorRole.Base))
    qapp.setPalette(palette)
    qapp.processEvents()
    assert theme().window.name() == theme().card_bg.name(), (
        "the Window == Base palette did not take, so nothing below is "
        "being measured")

    after = [ControlStyle.button_face(state).name() for state in states]
    assert before == after, (
        f"on the {name} palette, collapsing Window onto Base moved a "
        f"button's own faces {before} -> {after} -- something in the ramp "
        "is derived from the distance between two roles a desktop is free "
        "to make identical, which is exactly the defect it replaced")
