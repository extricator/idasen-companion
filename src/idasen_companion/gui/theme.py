"""Palette-derived design tokens.

Colors are mapped onto platform theme roles (window/base/text/highlight)
rather than hardcoded, so the UI follows Breeze/Adwaita in both light and
dark variants while keeping the same relative hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def _mix(start: QColor, end: QColor, fraction: float) -> QColor:
    """Linear blend of two colors, fraction=0 -> start, fraction=1 -> end."""
    return QColor(round(start.red() + (end.red() - start.red()) * fraction),
                  round(start.green() + (end.green() - start.green()) * fraction),
                  round(start.blue() + (end.blue() - start.blue()) * fraction))


# The app's two corner radii. Every bordered or filled rectangle the app
# draws reads one of them, so there are exactly two numbers to move and no
# per-widget exceptions list -- except the two rails and the chart bars,
# whose radii are their own geometry rather than a style choice, and
# ConnectionChip, whose capsule shape is a deliberate exemption pending the
# maintainer's real-desktop pass (D-16). Deliberately not Theme fields below
# -- that dataclass holds QColors keyed off the palette cache, and these are
# geometry, which does not vary with the palette.
#
# Two, not one. A single value was tried and rejected on the real desktop:
# the app had two distinct radius classes before this phase -- surfaces at
# 6 (cards) and controls at 4 (buttons, combo and spin frames, the segmented
# control) -- and unifying them moved the *controls* to 6 rather than the
# surfaces to 4, so "the buttons themselves still don't have the look as the
# original look". A surface is large and its rounding is a soft edge on a
# panel; a control is small and its rounding has to stay tight enough to
# still read as a rectangle.
SURFACE_RADIUS: int = 6   # cards, panels, pills -- anything the app draws on
CONTROL_RADIUS: int = 4   # buttons, combo and spin frames, checkbox, segments

# Every edge the app strokes, in logical pixels. One number, so a card, a
# pill, a control frame and a button all read as the same drawing.
BORDER_WIDTH: int = 1

# The inner padding of a push button, vertical then horizontal. They live
# here so the proxy style can hand the same metrics to a button that has no
# stylesheet at all (``gui/style.py``, ``CT_PushButton``) as
# ``widgets.primary_button`` composes its own from. Two consumers of one
# pair, so the accent-filled button and the neutral one beside it are the
# same size by construction rather than by anyone measuring one against the
# other -- which is what keeps the Overview page's Sit / Stand / Stop row
# level with Move.
#
# Padding rather than a height, and that is the point of expressing it this
# way: it is *added to* whatever the label's own font metrics come to, so a
# user at 150% text gets a proportionally taller button instead of a fixed
# box his text has outgrown.
#
# The vertical number was raised from 4 after a real-desktop pass on the
# installed package: measured there with a vertical pixel slice through the
# Sit button, the look the maintainer is matching stands 35px tall against
# this app's 32px, and the two have the *same* 30-row fill -- the reference
# simply spends more rows on edge and shadow treatment than a 1px stroke
# can. Height is what he asked for, so it is bought where this app has it
# to spend, and 6 is the value that clears 35 rather than stopping a pixel
# short of it (his label metrics come to 22px, so a whole padding step is
# 2px and no integer lands exactly on 35).
BUTTON_PADDING_V: int = 6
BUTTON_PADDING_H: int = 14


def control_height(text_height: float) -> int:
    """The height every control in a row stands at, for a label whose line
    height is ``text_height``.

    This is the push button's own height, and the button is deliberately
    the reference rather than one of four opinions: it is the control this
    app already sized on purpose, against a measured comparison with the
    look being matched, and the one whose padding was raised by eye from
    the installed package.

    Everything else is *floored* at it rather than set to it. Fusion sizes
    a line edit, a combo and a spin box from their own contents and lands
    six logical pixels short of a button beside them -- 26, 26 and 27
    against 32 at one text scale, 34, 34 and 35 against 40 at another --
    so a row mixing them steps up and down for no reason a user could
    name. Taking Fusion's answer as the floor keeps any minimum it holds
    that this has no opinion about, and only ever grows a control.

    Derived from the line height rather than fixed, for the same reason
    the padding above and the checkbox indicator are: a user at 150% text
    gets a proportionally taller row instead of four controls that
    disagree by more the larger the font gets.
    """
    return round(text_height) + 2 * BUTTON_PADDING_V + 2 * BORDER_WIDTH

# The clear space between a push button's icon and its label, as a
# fraction of the label's own line height -- the same quantity the vertical
# padding above is added to, so a button's inside is described in one unit.
#
# A fraction and a function rather than a constant, matching the shape
# ``corner_radius`` below already uses, because this is the one button
# metric that has to follow the text. Qt's own answer is a hardcoded pixel
# count: ``QPushButton``'s size hint reserves 4 logical pixels for it and
# the label is then drawn at half of that, so the measured clear space is
# 2px at every font size. That is what "the glyph touches the S" is, and it
# gets worse rather than better at 150% text, where the label grows and the
# space beside it does not.
#
# The fraction is half what it first shipped as. 0.45 was set without a
# reference to compare against and read as too loose on the real desktop
# -- "the icon gap is too big now. should be half that" -- where the
# label's metrics come to 22px, so it bought 10 logical pixels of clear
# space where 5 was wanted.
_ICON_GAP_FRACTION = 0.225


# The clear space Qt's own push button already reserves between its icon
# and its label. ``QPushButton``'s size hint adds this to the width it asks
# for, so a button only has to grow by whatever the app's gap comes to
# beyond it -- adding the whole gap would pad every icon button by this
# much again.
_RESERVED_ICON_GAP = 4


def button_icon_gap(text_height: float) -> int:
    """The clear space to leave between a push button's icon and its label,
    for a label whose line height is ``text_height``.

    Rounded to whole logical pixels, because it positions a pixmap; Qt
    scales the result for the display's device pixel ratio the same way it
    scales every other metric.
    """
    return round(text_height * _ICON_GAP_FRACTION)


def extra_icon_gap(text_height: float) -> int:
    """How much wider than Qt's own answer a button carrying both an icon
    and a label has to be, for ``button_icon_gap`` to fit between them.

    Never negative: a gap narrower than the reserved one is left to sit
    inside it rather than clawing width back off the button.

    Here rather than in one of the two callers because both kinds of
    button in this app have to grow by it, and they arrive at their size
    by different routes -- ``gui/style.py`` answers ``CT_PushButton`` for a
    bare ``QPushButton``, while a button carrying its own stylesheet is
    sized by ``QStyleSheetStyle`` and has to add it to its own size hint.
    """
    return max(0, button_icon_gap(text_height) - _RESERVED_ICON_GAP)


# How large a checkbox indicator is drawn, as a fraction of the label's own
# line height -- the same unit the button padding and the icon gap above are
# expressed in, so a control's insides are all described the same way.
#
# A fraction rather than a pixel count because Qt's own answer is a
# hardcoded 14 that does not move with the font: at 150% text a 14px box
# beside 33px text is a tick-sized afterthought. The style floors it at
# whatever the base style asks for, so this can only make the indicator
# bigger, never smaller than the toolkit expects.
#
# Set from a real-desktop comparison: the reference draws 15px against the
# app's 14 at his 22px label metrics -- "a tad bigger" -- and 0.70 is what
# clears 15 there while scaling from the one number.
_CHECKBOX_EXTENT_FRACTION = 0.70


def checkbox_extent(text_height: float) -> int:
    """The side of a checkbox indicator drawn beside a label whose line
    height is ``text_height``, in logical pixels."""
    return round(text_height * _CHECKBOX_EXTENT_FRACTION)


# The most of a box's own shorter side that a corner radius may take. A
# radius large in proportion to the box it rounds stops reading as a rounded
# rectangle at all: at half the shorter side the shape is a capsule, and
# Fusion's 14px checkbox indicator at the full control radius is 29% of its
# own box -- so near-circular that it reads as a radio button, and its stroke
# has no straight run and therefore not one pure, unblended pixel anywhere.
# 0.22 puts that indicator at ~3px while leaving every control from ~19px up,
# and every surface from ~28px up, on its own full radius.
_RADIUS_FRACTION = 0.22


def corner_radius(radius: int, shorter_side: float) -> float:
    """``radius``, clamped to the box whose shorter side is ``shorter_side``.

    One rule for both tokens and no per-widget exceptions: the token, or a
    fraction of the box's own shorter side, whichever is smaller. So a
    normally-sized control takes its token unchanged and a checkbox
    indicator takes a proportionate one, from the same constant, and moving
    a token still moves every consumer of it at once.

    Callers who write a stylesheet name the token directly instead: a
    stylesheet rule is composed before its widget has a geometry, so at that
    point there is no shorter side to clamp against, and Qt's stylesheet
    syntax has no proportional radius to defer it to. This function is the
    rule wherever the box being rounded is known -- today, the proxy style's
    paint code in ``gui/style.py``.
    """
    return min(float(radius), shorter_side * _RADIUS_FRACTION)


@dataclass(frozen=True)
class Theme:
    is_dark: bool
    window: QColor        # app background
    card_bg: QColor       # card surfaces
    sidebar_bg: QColor    # slightly darker than content
    text: QColor
    secondary: QColor
    muted: QColor
    border: QColor        # every edge the app strokes
    hover_border: QColor  # ... on a control under the pointer
    separator: QColor     # row separators inside cards
    hover: QColor         # row hover highlight
    button_fill: QColor         # a push button's face, at rest or hovered
    button_pressed_fill: QColor  # ... held down, or checked
    disabled_fill: QColor    # the surface of a control that cannot be used
    disabled_border: QColor  # its edge
    disabled_text: QColor    # its label
    accent: QColor
    accent_text: QColor   # readable accent for text on surfaces
    accent_fill: QColor   # light accent fill (selection, primary buttons)
    accent_border: QColor
    success: QColor
    success_text: QColor
    warning: QColor
    warning_text: QColor
    error: QColor
    error_text: QColor    # readable on top of the error fill itself


_cache: tuple[int, Theme] | None = None  # pylint: disable=invalid-name  # mutable singleton, reassigned via `global`, not a true constant


def theme() -> Theme:
    # Cached per palette: paintEvents call this at BLE-notification rate
    # while the desk moves. cacheKey changes when the palette does.
    global _cache
    pal = QApplication.palette()
    cache_key = pal.cacheKey()
    if _cache is not None and _cache[0] == cache_key:
        return _cache[1]
    window = pal.color(QPalette.ColorRole.Window)
    base = pal.color(QPalette.ColorRole.Base)
    text = pal.color(QPalette.ColorRole.WindowText)
    accent = pal.color(QPalette.ColorRole.Highlight)
    is_dark = text.lightness() > window.lightness()
    # Named here rather than written twice below, because `hover_border` is
    # a blend *of the resting edge* toward the accent and the two must move
    # together: the pointer changes an edge's colour, not which edge it is.
    edge = _mix(base, text, 0.22)

    result = Theme(
        is_dark=is_dark,
        window=window,
        card_bg=base,
        sidebar_bg=_mix(window, text, 0.04),
        text=text,
        secondary=_mix(window, text, 0.72),
        muted=_mix(window, text, 0.52),
        # The weight of every edge the app strokes: a card, a pill, a
        # segmented button, a push button's panel, and the three frames that
        # *are* their control's affordance -- a checkbox's box in every one
        # of its states, a combo frame, a spin frame.
        #
        # One token, and it used to be two. The second sat at 0.45 for
        # exactly one reason: the WCAG 2.1 SC 1.4.11 3:1 non-text floor was
        # held to bind those three affordance frames but not a card edge or
        # a labelled button, and 0.45 was the fraction that cleared it for
        # them (measured against card_bg by the relative-luminance
        # formula: 3.36:1 light, 4.45:1 dark) where 0.22 does not (1.69:1
        # and 2.00:1). That floor has since been dropped as a standing
        # requirement, deliberately and with the cost written down, so the
        # heavier number was carrying a rule that no longer exists -- and
        # it was carrying it visibly: from the installed 1.0.2 package on
        # the maintainer's light palette a spin box frame rendered #9C9D9F
        # against the #C8CACB of the look he approves of, "coarser/darker
        # than reference/old look".
        #
        # Re-derived as what a frame is actually for -- saying where the
        # control is without competing with what is inside it or with the
        # card behind it -- both landed on the same weight, which is the
        # same job a card's own edge already did. So the split was folded
        # away rather than left as two names for one colour.
        border=edge,
        # The same edge under the pointer, carried most of the way to
        # `QPalette::Highlight` -- the colour the user chose for his own
        # desktop, which the bundled portal platform theme feeds from the
        # host, so this follows whatever desktop and theme he is on with no
        # branching. This is the hover treatment the reference look has and
        # the one that was asked for: the border changes and the face
        # behind it does not.
        #
        # *Most* of the way, not all of it, because keyboard focus already
        # takes the accent outright and hover would otherwise be
        # indistinguishable from it. Focus keeps the stronger of the two on
        # purpose -- it is the persistent state, it says where the keys go,
        # and for a non-editable QComboBox this app's overlay is its only
        # focus affordance at all -- so hover is the one that gives ground.
        # 0.65 leaves them 74-93 channel levels apart on the five palettes
        # the token tests cover, against the 9-19 those same palettes count
        # as a visible step, and orders the three states by prominence
        # against the card: resting, then hover, then focus.
        #
        # Blended from the resting edge rather than from the card, so what
        # the pointer produces is that edge changing colour rather than a
        # second stroke derived from somewhere else; on all five palettes
        # it lands further from the card than the resting edge, which is
        # the direction a hover has to move in to not be a de-emphasis.
        hover_border=_mix(edge, accent, 0.65),
        separator=_mix(base, text, 0.09),
        hover=_mix(base, text, 0.05),
        # A control's faces, as steps away from `base` -- the card it sits
        # on. Every step is therefore *relative to the surface behind the
        # control*, which is what makes it distinguishable from its card on
        # any palette and in either scheme: a light palette's ink is darker
        # than its card and a dark palette's is lighter, so "toward the ink"
        # darkens one and lightens the other from a single statement. A
        # fixed lighten or darken cannot do that, and neither can anything
        # derived from `window`, which on a real desktop is frequently the
        # same colour as `base`.
        #
        # All three sit on that one axis, and there is one set of them for
        # every control this app draws. There were four: the pointer used
        # to move a control's face as well as its edge. Both of the tried
        # versions of that were turned down on the real desktop -- first
        # washing the face in the desktop accent, then merely stepping it
        # further along this axis -- and the second rejection is the one
        # that settled it, because it says the objection was never to the
        # *colour* the face moved to. The pointer changes an edge and
        # nothing else, which is what the reference look does: measured
        # there, a resting button's face and a hovered one's are the same
        # colour to the channel, and only the border moves.
        #
        # The order is the whole design. A *resting* button sits nearest
        # the card, and deliberately barely off it: what identifies a
        # button is the edge drawn around it, not the shade inside it, so
        # the face has one job -- saying there is a surface there at all --
        # and doing more of that job is how it becomes a grey slab lying on
        # the card instead of a step out of it. *Pressed* moves out as the
        # pointer engages it. A *disabled* face sits further out than
        # resting, because a control nobody can use reads as a filled-in
        # gap in the layout rather than as a lighter version of a button --
        # and no further out than the heaviest usable face, so nothing
        # switched off outweighs anything still usable. `border` at 0.22
        # stays outside the neutral faces, so a button's own edge never
        # disappears into its fill.
        #
        # Two earlier orderings were rejected from the installed package,
        # and both are why this ramp is asserted as an ordering rather than
        # as values. Disabled nearest the card with resting a long way out
        # at 0.09 drew "i think that the button colors are inverted with
        # disabled?" (2026-08-16), measured there as a #f7f7f7 disabled
        # face against a #e8e8e8 enabled one on a white card. Righting that
        # left resting at 0.05, which measured #f4f4f4 against the same
        # white card while a disabled control sat at #e2e3e3 -- so an
        # unusable control was nearer an available one than an available
        # one was to the card it sat on, and the available one was reported
        # (2026-08-17) as looking disabled.
        #
        # `disabled_fill` remains a *different fraction of the same axis*
        # as `button_fill`, so the two cannot collapse onto each other
        # unless the palette's ink equals its card -- which was exactly the
        # bug in the mix(window, base, 0.9) two derivations ago. That
        # expression put a disabled control nine tenths of the way from
        # `window` to `base`, and on any palette whose window and base are
        # close (Breeze's are, Adwaita light's are nearly identical) it
        # landed on `base`, rendering a disabled button the same colour as
        # an enabled one. Measured on the maintainer's desktop, they were
        # identical.
        button_fill=_mix(base, text, 0.02),
        button_pressed_fill=_mix(base, text, 0.15),
        disabled_fill=_mix(base, text, 0.13),
        # A disabled control's own edge and label, and the two fractions
        # here are chosen for their *distance from its fill* rather than for
        # any weight of their own. That distance is what says "unavailable":
        # an enabled button's edge stands 0.20 of the ink axis off its face
        # and its label very nearly all of it, where these stand 0.04 and
        # 0.25 -- a fifth and a quarter. So a disabled control goes flat and
        # closed rather than merely repainted, which is the difference
        # between reading as switched off and reading as a second colour of
        # button. Both sit on the card-to-ink axis, like the fill they are
        # measured against, so the ratio is a property of the app and not of
        # whichever palette turned up. `disabled_text` in particular is no
        # longer measured off `window`, which a desktop is free to set
        # anywhere relative to `base` and which therefore left the label's
        # contrast against its own button drifting from palette to palette.
        disabled_border=_mix(base, text, 0.17),
        disabled_text=_mix(base, text, 0.38),
        accent=accent,
        accent_text=(_mix(accent, QColor("white"), 0.35) if is_dark
                     else _mix(accent, QColor("black"), 0.30)),
        accent_fill=_mix(base, accent, 0.16),
        accent_border=_mix(base, accent, 0.50),
        success=QColor("#2fbe74") if is_dark else QColor("#1f9e58"),
        success_text=QColor("#4ec98a") if is_dark else QColor("#1f7a48"),
        warning=QColor("#e0a52e") if is_dark else QColor("#c07f00"),
        warning_text=QColor("#e0a52e") if is_dark else QColor("#a05a00"),
        error=QColor("#e06c5c") if is_dark else QColor("#c0392b"),
        # Measured against the fill above, not against card_bg like
        # success_text/warning_text: dark's lighter #e06c5c only clears the
        # 4.5:1 text-contrast floor against a near-black foreground, while
        # light's darker #c0392b only clears it against white.
        error_text=QColor("black") if is_dark else QColor("white"),
    )
    _cache = (cache_key, result)
    return result


def css(color: QColor) -> str:
    return color.name()
