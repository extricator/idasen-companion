"""The app's own opinion about how its standard controls are drawn.

A `QProxyStyle` over Fusion. Fusion stays the renderer for everything the
app has no opinion about -- every label, every icon, every focus rect,
every metric not named below, and every primitive not named below -- so a
state nobody thought of still renders, which is the property a stylesheet
cannot offer. Naming a border in a stylesheet (the approach this module
replaced) hands the whole widget's box model to the stylesheet engine,
whose padding and corner radius both default to zero, and forces every
state -- hover, pressed, focus, disabled, checked, right-to-left,
non-unity device pixel ratio -- to be enumerated by hand or render bare.

**Two ways in, and the difference matters.**

*Drawn outright.* ``PE_PanelButtonCommand`` -- a push button's panel -- is
painted here in one pass: fill, edge and corner together, with no call to
Fusion underneath. Drawing through Fusion first and overlaying afterwards
put two rounded rectangles of different radii on the same box, and Fusion's
is the squarer one, so its corner arc stood *outside* the app's own curve
and showed as a grey nick at each corner -- reported from the real desktop
as a grey thing protruding past the button. Nothing underneath is nothing
to protrude. A push button's panel is safe to own outright because it has
no sub-controls: it is a filled, stroked box and nothing else.

*Drawn through, then overlaid.* The combo frame, the spin frame and the
checkbox indicator keep Fusion's own rendering with one theme-derived
stroke on top, because those three do have sub-controls -- a spin box's
stepper arrows and their two button faces, a combo's drop-down arrow -- and
reimplementing them would be exactly the enumeration this module exists to
avoid. They get the same corner artefact for the same reason, and it is
cured by *clipping*: Fusion draws inside a clip path shaped like the app's
own rounded frame, so whatever it would have painted outside that curve is
simply never rasterised, while every pixel inside it -- arrows, button
faces, text -- is untouched. See ``_clip_to_frame``.

**Every resting edge here is one token, and one control is exempt.** An
empty checkbox, a combo or spin frame, a push button's panel: all four
are stroked in ``theme().border``, so a card, a control and a button read
as one drawing. There were two general edge tokens once -- a frame that
*is* its control's whole affordance was held to a 3:1 non-text contrast
floor that a frame around a labelled control was not -- and that floor
has been dropped, which left the heavier of the two carrying a rule that
no longer exists and reading, on a real desktop, as coarser than the look
it was meant to match. ``theme.py`` documents the re-derivation above
``border``.

The exemption is a *ticked* checkbox, which strokes
``theme().accent_border``. It is the one control whose whole purpose is
to show a state rather than to offer an action, the reference marks that
state in the accent on both the fill and the edge, and once the fill
moved a neutral ring around an accent centre was the thing left looking
unfinished. The three edge states stay ordered through it -- measured
against the card on a light palette, resting 148, hover 252, focus 297 --
because ``accent_border`` is a half-way mix *into the surface* while
hover and focus are carried from the neutral edge toward the accent
itself.

**The neutral push button is the accent one without the accent.** The app
already had a button whose look was approved: ``widgets.primary_button``.
So the button drawn here is that button with neutral ``theme()`` tokens in
place of its accent ones -- the same corner radius, the same border weight,
and, through the ``CT_PushButton`` size override below, the same padding.
The consequence is the point: an accent-filled button and a bare
``QPushButton`` beside it come out the same size by construction, so a row
mixing the two is level without anything measuring one against the other.

**The pointer moves an edge, not a face.** Every control this style
draws -- a push button's panel, a combo frame, a spin frame, a checkbox
indicator -- strokes ``theme().hover_border`` while it is under the
pointer, and the fill behind that stroke does not move *at all*. That is
the highlight the reference look has and the one that was asked for. Two
weaker versions of it were built and turned down from the installed
package in turn: one washed the face in the accent, and the one after it
kept the accent on the edge alone but still stepped the face further
along its own neutral axis, which was reported as a foreground colour
change that should go. The colour is ``QPalette::Highlight``, carried
across the bundle boundary by the portal platform theme, so it is
whatever the user chose for his own desktop with no branching here.

Hover and keyboard focus would collide, since focus already takes the
accent outright -- and has to, because a non-editable ``QComboBox`` gets
no focus indication from Fusion at all, which makes this overlay its only
one. They are separated by weight rather than by thickness: focus keeps
the accent itself, hover takes an edge carried most of the way to it, and
a focused control under the pointer still reads as focused.
``overlay_color`` is where that is decided, and it answers *disabled*
before it reads either flag -- Qt reports ``State_MouseOver`` on a
disabled widget, so a control nobody can use would otherwise light up
like one they can.

**A checkbox gets its box in every state, checked included.** It did not
once: the checked and tristate glyphs were left entirely to Fusion, on
the reasoning that they are Fusion's drawing and stroking them would
damage it. What that actually left on the maintainer's desktop was a
checked box with no box -- a bare tick floating on the card, measured
from the installed package as *zero* frame pixels inside the indicator
rect against the 24 the unchecked one beside it drew. Whether Fusion
would have drawn a frame there is a question about his palette; that the
app draws one is a decision it can make on every palette, and it is the
same decision the unchecked box already had. So the state test is gone
and one rule covers all four states. The tick survives it because the
stroke follows the indicator's perimeter and the glyph is inset from it.

**What it deliberately does not draw.** ``QLineEdit``
(``PE_FrameLineEdit``/``PE_PanelLineEdit``) and ``QRadioButton``
(``PE_IndicatorRadioButton``) are untouched, so those two keep Fusion's own
hairline and sit visibly *heavier* than the controls that are drawn
here -- measured in one card, light scheme: a line edit's first border
pixel is ``#ababab`` where the combo, spin and time edit beside it read
``#c7c7c7``. That is a known gap, not an oversight: extending the treatment
is a change to how the app looks, and the whole look is waiting on a
maintainer's pass against the installed package. ``TODO.md`` carries it.
(The direction of that gap reversed when the control edge was re-weighted;
Fusion's hairline did not move.)

``QScrollBar`` is the third, and it was declined on a real-desktop pass
rather than never raised: drawing it is possible and was prototyped, but
it makes the scrollbar a fourth control family this style owns, and
widening one visual complaint at a time is the failure this phase is
under instruction to avoid. Note there is no partial version available --
a scrollbar arrives as one ``drawComplexControl(CC_ScrollBar)`` call with
Fusion painting the groove, the slider and both stepper arrows
internally, so nothing here can tint a slider without owning the whole
control. ``TODO.md`` and the planning todo beside it carry the prototype
and what it still owes.

**A widget that draws its own frame is never reached.** Several buttons in
this app compose their own border in a stylesheet -- ``primary_button``,
every segment of ``SegmentedControl``, ``ToolIconButton`` -- and painting
over those would put a grey stroke on an accent-bordered button. Nothing
here has to test for that, because Qt's own dispatch already settles it: a
widget carrying a stylesheet is rendered through ``QStyleSheetStyle``,
which draws the box itself and does *not* delegate to its base style
whenever the rule declares a border. Measured, by counting the calls that
reach this class for one ``grab()`` of each: a bare ``QPushButton`` arrives
as ``CE_PushButton`` -> ``CE_PushButtonBevel`` -> ``PE_PanelButtonCommand``
-> ``CE_PushButtonLabel``, and ``primary_button``, a ``SegmentedControl``
segment and a ``ToolIconButton`` arrive as *nothing at all*. A stylesheet
that names no border -- the Overview page's Stop button sets only a colour
and a weight -- does delegate, and does get the treatment, which is the
wanted behaviour rather than an exception to it.

The one thing those buttons do *not* get for free is the icon-to-label
gap, because ``QStyleSheetStyle`` lays a push button's label out too, and
a gap is not something a stylesheet rule can declare. ``primary_button``
therefore places its own pair, from the same
``widgets.spaced_label_parts`` this style uses, so Move and the bare
buttons beside it space their icons alike without either being measured
against the other.

**What it draws for a disabled control.** Four things, each from
``theme()`` rather than from the desktop's Disabled colour group, because
measured on the maintainer's desktop that group repeats its Active one and
so dims nothing: the fill (``_dimmed`` for anything Fusion renders, the
button panel directly), the edge (``_overlay`` for the framed controls,
``button_edge`` for the panel), the label (``_dimmed`` again) and the
*icon* (``_dimmed_icon``). What makes those read as unavailable is not
their weight but how little of it separates them: the edge and the label
each sit about a quarter as far from the fill as their enabled
counterparts do, so the control goes flat rather than merely changing
colour. ``theme.py`` documents the fractions. The icon needs its own
handling because a ``QIcon`` is
not a colour a palette can rewrite -- Qt will synthesise a greyed pixmap
for a mode it has none for, but it builds that ramp from the application
palette's own Disabled group, which is the group that repeats Active here,
and never from the app's ``disabled_text``. Recolouring it through
``widgets.tinted_icon`` puts the glyph and the label beside it at the same
weight on every palette.

``drawPrimitive``, ``drawControl``, ``drawComplexControl`` and
``sizeFromContents`` below are Qt virtual overrides, dispatched by exact
name from Qt's C++ meta-object machinery, so their names cannot follow this
project's own naming convention. Each carries its own inline naming-check
suppression rather than a file-level one, matching the convention
``gui/widgets.py`` and ``gui/main_window.py`` already use.
"""

from __future__ import annotations

from typing import TypeVar

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (QBrush, QColor, QIcon, QPainter, QPainterPath,
                           QPalette, QPen)
from PySide6.QtWidgets import (QAbstractSpinBox, QComboBox, QProxyStyle,
                               QStyle, QStyleFactory, QStyleOption,
                               QStyleOptionButton, QStyleOptionComboBox,
                               QStyleOptionComplex, QStyleOptionSpinBox,
                               QWidget)

from .theme import (BORDER_WIDTH, BUTTON_PADDING_H, BUTTON_PADDING_V,
                    CONTROL_RADIUS, checkbox_extent, control_height,
                    corner_radius, extra_icon_gap, theme)
from .widgets import spaced_label_parts, tinted_icon

# How far inside its own widget rect Fusion strokes a complex control's
# frame, as (vertical, horizontal) logical pixels.
#
# Fusion's spin box is the odd one out, and it is the whole of the doubled
# edge reported on the real desktop: it builds its frame from the widget
# rect inset by one pixel at the top and bottom and flush at the left and
# right, while ``subControlRect(CC_SpinBox, SC_SpinBoxFrame)`` still reports
# the *full* widget rect. Overlaying on the reported rect therefore landed
# on top of Fusion's own stroke down the left and right edges -- one visible
# line -- but one pixel outside it along the top and bottom, leaving two
# stacked lines there and an edge that reads twice as thick.
#
# Measured under plain Fusion, light scheme, at 48x26, 80x25, 120x30,
# 144x22 and 60x40: a spin box paints rows 1..H-2 and columns 0..W-1 at
# every one of them, a combo box rows 0..H-1 and columns 0..W-1 at every one
# of them. ``tests/test_control_style.py`` re-derives both from a plain
# Fusion render rather than trusting these numbers, so a Qt release that
# moves them turns a test red instead of quietly restoring the doubled edge.
#
# A push button is absent because it is no longer drawn through Fusion at
# all -- see the module docstring -- so there is no second stroke to line up
# with, and its panel is painted on its own option rect.
_FRAME_INSETS: dict[QStyle.ComplexControl, tuple[int, int]] = {
    QStyle.ComplexControl.CC_ComboBox: (0, 0),
    QStyle.ComplexControl.CC_SpinBox: (1, 0),
}

# The sub-control carrying each complex control's frame. A complex control
# absent from this mapping is drawn straight through, untouched.
_FRAME_SUBCONTROLS: dict[QStyle.ComplexControl, QStyle.SubControl] = {
    QStyle.ComplexControl.CC_ComboBox: QStyle.SubControl.SC_ComboBoxFrame,
    QStyle.ComplexControl.CC_SpinBox: QStyle.SubControl.SC_SpinBoxFrame,
}

# The palette roles Fusion reads for a control's own surface and for its
# label. Everything else in the Disabled group -- Window above all, which is
# where Fusion derives a disabled frame's colour from -- is left to the
# desktop, so the frame keeps whatever dimming the user's own palette and
# Fusion between them produce.
_DISABLED_FILL_ROLES = (QPalette.ColorRole.Button, QPalette.ColorRole.Base)
_DISABLED_TEXT_ROLES = (QPalette.ColorRole.ButtonText, QPalette.ColorRole.Text,
                        QPalette.ColorRole.WindowText)

# The two metrics that size a checkbox indicator. Qt asks for each
# separately and the answer is one square, so both are answered together
# rather than by two rules that could drift into a rectangle.
_INDICATOR_METRICS = (QStyle.PixelMetric.PM_IndicatorWidth,
                      QStyle.PixelMetric.PM_IndicatorHeight)

# The controls held to the app's one row height. A push button is absent
# because it *is* that height -- see ``theme.control_height`` -- and
# adding it would only floor it against itself.
_ROW_HEIGHT_CONTENTS = (QStyle.ContentsType.CT_LineEdit,
                        QStyle.ContentsType.CT_ComboBox,
                        QStyle.ContentsType.CT_SpinBox)

# Controls that contain an editor of their own. The row height must not be
# applied to that editor, only to its host -- measured, a spin box asks for
# its internal line edit's size first and feeds the answer into its own,
# so flooring both compounds: the line edit came out at the row height and
# the spin box at the row height *plus* its own frame, three pixels taller
# than everything it sits beside.
_EMBEDDING_CONTROLS = (QAbstractSpinBox, QComboBox)

# The frames drawn through Fusion and then stroked in the app's own edge.
# Each has sub-controls the app has no wish to reimplement -- a spin box's
# steppers, a combo's arrow, a line edit's text cursor and selection -- so
# Fusion keeps the inside and the app takes the outline.
_OVERLAID_PRIMITIVES = (QStyle.PrimitiveElement.PE_IndicatorCheckBox,
                        QStyle.PrimitiveElement.PE_PanelLineEdit)

# The two checkbox states the app draws outright rather than through
# Fusion: ticked, and the tristate middle. Both put a mark on a filled
# box, and a fill cannot be painted under something Fusion has already
# painted its own background for -- see ``_draw_checked_indicator``.
_CHECKED_STATES = (QStyle.StateFlag.State_On
                   | QStyle.StateFlag.State_NoChange)

# The tick and the tristate bar, as points on the indicator's own unit
# square, so both follow the box at any size, text scale or device pixel
# ratio rather than being drawn at a pixel count that is right once.
#
# The tick is two segments rather than three points on a curve because
# that is what a check mark is; what makes it read as smoother than the
# one it replaces is the round cap and join in ``_draw_mark`` plus
# antialiasing, not the path.
_CHECK_MARK = ((0.25, 0.52), (0.43, 0.71), (0.76, 0.29))
_TRISTATE_MARK = ((0.26, 0.50), (0.74, 0.50))

# How thick that mark is drawn, as a fraction of the indicator's shorter
# side. A fraction for the same reason the points above are fractions --
# a 14px indicator and the same indicator at 150% text want the same
# drawing, not the same pen.
_MARK_WIDTH_FRACTION = 0.13

# The one state that moves an enabled control's face: being held down, or
# being a checked button, which reads the same way.
#
# The pointer is deliberately absent. It moves the *edge* -- see
# ``overlay_color`` -- and a hovered control's face is its resting face to
# the channel, which is what the reference look does and what two rounds
# of the alternative were turned down for on the real desktop.
_PRESSED_STATES = (QStyle.StateFlag.State_Sunken | QStyle.StateFlag.State_On)

# Whatever concrete QStyleOption subclass Qt handed down, _dimmed gives the
# same one back -- drawComplexControl in particular is typed to accept only
# a QStyleOptionComplex.
_Option = TypeVar("_Option", bound=QStyleOption)


class ControlStyle(QProxyStyle):
    """A `QProxyStyle` over Fusion that paints a push button's panel
    outright, overlays a theme-derived rounded border on the checkbox
    indicator and the combo and spin frames, gives a bare push button the
    app's own button metrics, and hands Fusion the app's own disabled
    colours -- every other primitive, control and metric is Fusion's, drawn
    or answered through unmodified."""

    def __init__(self) -> None:
        super().__init__(QStyleFactory.create("fusion"))

    # ----- disabled treatment -----

    @staticmethod
    def _dimmed(option: _Option) -> _Option:
        """``option`` with the app's own disabled fill and label colours,
        or ``option`` untouched when it is not disabled.

        One rule for every element the style draws, rather than a per-widget
        list: whatever Fusion is about to render, if it is disabled it
        renders from ``theme().disabled_fill`` and ``theme().disabled_text``.

        Expressed as a substituted palette rather than as a wash painted over
        the result, because it has to survive nesting. A push button reaches
        this method four times for one repaint (``CE_PushButton``, then
        ``CE_PushButtonBevel``, ``PE_PanelButtonCommand`` and
        ``CE_PushButtonLabel``) and a combo box twice from two separate
        top-level calls, so anything that compounds -- a translucent overlay
        above all -- would dim a control's middle harder than its edges and
        leave a visible block behind its text. Rewriting colours is
        idempotent, so the nesting simply does not matter.

        The copy is deliberate: Qt hands the option down as a const
        reference and the caller reuses the object for its next draw call.
        It is also what makes ``_dimmed_icon`` below safe to write in
        place -- what it mutates is this copy, never Qt's own object.
        """
        if option.state & QStyle.StateFlag.State_Enabled:
            return option
        tokens = theme()
        palette = QPalette(option.palette)
        for role in _DISABLED_FILL_ROLES:
            palette.setColor(QPalette.ColorGroup.Disabled, role,
                             tokens.disabled_fill)
        for role in _DISABLED_TEXT_ROLES:
            palette.setColor(QPalette.ColorGroup.Disabled, role,
                             tokens.disabled_text)
        # Set explicitly rather than inherited from the copy: every read
        # below resolves through the current group, and the whole
        # substitution is inert if it is not the disabled one.
        palette.setCurrentColorGroup(QPalette.ColorGroup.Disabled)
        dimmed = type(option)(option)
        dimmed.palette = palette
        return dimmed

    def _dimmed_icon(self, option: QStyleOption,
                     widget: QWidget | None) -> QStyleOption:
        """``option`` with a disabled button's icon recoloured to
        ``theme().disabled_text``, or ``option`` untouched otherwise.

        A ``QIcon`` is the one part of a control a palette substitution
        cannot reach: ``_dimmed`` above rewrites colours, and an icon is
        pixels. Qt does not leave it alone either -- asked for a mode it
        holds no pixmap for, ``QIcon`` synthesises one, grey-ramping the
        glyph toward the *application* palette's Disabled Window colour.
        That is the group this app cannot rely on (measured on the
        maintainer's desktop it repeats the Active one), it ignores the
        option's palette entirely, and it is unrelated to the
        ``disabled_text`` the label right beside the icon is drawn in. So
        the icon is recoloured here instead, through the same pixmap
        machinery the sidebar and the log page already use, which is
        rendered at the display's pixel ratio and so stays crisp on HiDPI.

        Registered under ``QIcon.Mode.Disabled`` rather than the default
        Normal, or Qt would find no Disabled pixmap on the tinted icon and
        ramp *that* -- making the app's chosen colour the input to Qt's
        dimming instead of the result.
        """
        if option.state & QStyle.StateFlag.State_Enabled:
            return option
        if not isinstance(option, QStyleOptionButton) or option.icon.isNull():
            return option
        extent = option.iconSize.width()
        if extent <= 0:
            extent = self.pixelMetric(
                QStyle.PixelMetric.PM_ButtonIconSize, option, widget)
        option.icon = tinted_icon(option.icon, theme().disabled_text, extent,
                                  QIcon.Mode.Disabled)
        return option

    # ----- painting -----

    def drawControl(  # pylint: disable=invalid-name
            self,
            element: QStyle.ControlElement,
            option: QStyleOption,
            painter: QPainter,
            widget: QWidget | None = None) -> None:
        prepared = self._dimmed(option)
        if element == QStyle.ControlElement.CE_PushButtonLabel:
            prepared = self._dimmed_icon(prepared, widget)
            if self._draw_spaced_label(prepared, painter, widget):
                return
        super().drawControl(element, prepared, painter, widget)

    def drawPrimitive(  # pylint: disable=invalid-name
            self,
            primitive: QStyle.PrimitiveElement,
            option: QStyleOption,
            painter: QPainter,
            widget: QWidget | None = None) -> None:
        if primitive == QStyle.PrimitiveElement.PE_PanelButtonCommand:
            # Painted outright, with no call to Fusion underneath -- see the
            # module docstring on why a second rounded rectangle beneath
            # this one is what protruded past its corners.
            self._draw_button_panel(painter, option, widget)
            return
        if (primitive == QStyle.PrimitiveElement.PE_IndicatorCheckBox
                and option.state & _CHECKED_STATES):
            # Painted outright for the same reason the button panel is,
            # arrived at from the other end: this one has a fill to put
            # *under* a mark, and Fusion paints its own background before
            # its own glyph, so there is no order in which an overlay can
            # leave both visible.
            self._draw_checked_indicator(painter, option)
            return
        dimmed = self._dimmed(option)
        if not self._takes_the_apps_frame(primitive, widget):
            super().drawPrimitive(primitive, dimmed, painter, widget)
            return
        painter.save()
        self._clip_to_frame(painter, option.rect)
        super().drawPrimitive(primitive, dimmed, painter, widget)
        painter.restore()
        self._overlay(painter, option, option.rect, theme().border)

    def drawComplexControl(  # pylint: disable=invalid-name
            self,
            control: QStyle.ComplexControl,
            option: QStyleOptionComplex,
            painter: QPainter,
            widget: QWidget | None = None) -> None:
        dimmed = self._dimmed(option)
        frame = _FRAME_SUBCONTROLS.get(control)
        # A control that asked for no frame keeps none. Both option types
        # carry the flag that QComboBox.setFrame(False) and
        # QAbstractSpinBox.setFrame(False) set, Fusion honours it and draws
        # nothing, and a stroke ignoring it would hand back a border the
        # widget had explicitly switched off. Nothing in the app sets it
        # today; a delegate-created editor is where it would show up.
        frameless = (isinstance(option, (QStyleOptionComboBox,
                                         QStyleOptionSpinBox))
                     and not option.frame)
        if frame is None or frameless:
            super().drawComplexControl(control, dimmed, painter, widget)
            return
        # PySide6's stub types the widget argument as non-optional, while
        # Qt's own signature takes a nullable one and the base style handles
        # it -- which is what an override called for a synthetic option gets.
        rect = self.stroked_frame_rect(
            control,
            self.subControlRect(control, option, frame, widget))  # type: ignore[arg-type]
        painter.save()
        self._clip_to_frame(painter, rect)
        super().drawComplexControl(control, dimmed, painter, widget)
        painter.restore()
        self._overlay(painter, option, rect, theme().border)

    def _draw_spaced_label(self, option: QStyleOption, painter: QPainter,
                           widget: QWidget | None) -> bool:
        """Lay a push button's icon and label out with the app's own gap
        between them, returning whether it did.

        The gap is the one button metric Qt hardcodes and exposes no metric
        for. ``QPushButton``'s size hint reserves four logical pixels
        between the pixmap and the text, and ``QCommonStyle`` then offsets
        the text by half of that, so the *drawn* clear space is two pixels
        on every font, at every size, on both this style and plain Fusion
        -- measured identically under each, which is what says this is the
        toolkit's own layout and not something this app's own paint code
        did to it. It is also the one metric that does not follow the text:
        at 150% the label grows and the two pixels beside it do not.

        Rather than reimplement the label, the base style is asked to draw
        it twice -- once with the text removed and once with the icon
        removed -- in the two rects ``widgets.spaced_label_parts`` places.
        Each half is therefore still rendered by Fusion, with its own
        mnemonic underlining, elision, disabled treatment and sunken-state
        shift intact; the only thing taken over is *where* the two halves
        go. The placement is shared with ``widgets.primary_button``, which
        has to do the same job for itself because its stylesheet keeps this
        style out of its label entirely.

        Declines, leaving the whole label to Fusion, for a button that has
        only one of the two -- there is nothing to space -- and for one
        whose icon reports no size it can be laid out from.
        """
        if not isinstance(option, QStyleOptionButton):
            return False
        parts = spaced_label_parts(option, option.rect)
        if parts is None:
            return False
        for part in parts:
            super().drawControl(QStyle.ControlElement.CE_PushButtonLabel,
                                part, painter, widget)  # type: ignore[arg-type]
        return True

    # ----- geometry -----

    def sizeFromContents(  # pylint: disable=invalid-name
            self,
            contents: QStyle.ContentsType,
            option: QStyleOption,
            size: QSize,
            widget: QWidget | None = None) -> QSize:
        """Fusion's answer, except that every control a layout puts in a row
        stands at one height, and a push button gets the app's own width.

        The height is ``theme.control_height`` for all four -- a push
        button, a line edit, a combo and a spin box -- so a settings row
        lines up by construction rather than because anything measured one
        control against another. Fusion sizes each from its own contents
        and lands them apart; the button is the reference because it is the
        one this app already sized deliberately.

        Nothing here reads another widget's geometry or names a pixel
        count. The height is derived from the line height, so a user at
        150% text gets a proportionally taller row rather than four
        controls that disagree by more the larger the font gets.

        It is deliberately *not* the button's own contents height, which is
        what it used to be. That measures the bounding box of the label's
        actual glyphs, so it exceeded the line height at some font sizes
        and not others -- putting the button a pixel above the row at 11,
        13, 16 and 22pt while agreeing at 10, 12, 14 and 18 -- and it made
        a button's height depend on which letters were in it.

        Fusion's own answer is the floor rather than being replaced, because
        it carries minimums this has no opinion about (a push button's 80px
        minimum width among them) and dropping those would make buttons
        *narrower*, which nobody asked for.

        The width also has to make room for the app's own icon-to-label gap
        (``_draw_spaced_label``), less what Qt already reserved for its
        own, or the wider gap would be bought out of the label's own space
        and elide the last letter off it.
        """
        # PySide6's stub types the widget argument as non-optional, while
        # Qt's own signature takes a nullable one, and Qt itself passes
        # None for a style option with no widget behind it.
        base = super().sizeFromContents(contents, option, size, widget)  # type: ignore[arg-type]
        if contents in _ROW_HEIGHT_CONTENTS and self._stands_in_a_row(widget):
            return QSize(base.width(),
                         max(base.height(),
                             control_height(option.fontMetrics.height())))
        if contents != QStyle.ContentsType.CT_PushButton:
            return base
        edges = 2 * BORDER_WIDTH
        return QSize(
            max(base.width(), size.width() + 2 * BUTTON_PADDING_H + edges
                + self._extra_icon_gap(option)),
            control_height(option.fontMetrics.height()))

    def pixelMetric(  # pylint: disable=invalid-name
            self,
            metric: QStyle.PixelMetric,
            option: QStyleOption | None = None,
            widget: QWidget | None = None) -> int:
        """Fusion's answer, except that a checkbox indicator is sized from
        the label beside it.

        The only metric this style has an opinion about, and the opinion is
        that Qt's is a constant. ``PM_IndicatorWidth`` is a hardcoded 14
        that does not move with the font, so the box shrinks relative to
        its own label at every text scale above 100%. ``theme`` derives it
        from the line height instead, from the same kind of fraction the
        button padding and the icon gap already use.

        Floored at the base style's own answer rather than replacing it, so
        this can only ever make the indicator larger. Everything that
        follows from the metric -- ``subElementRect``'s indicator box, the
        label's offset, the widget's size hint -- is Qt's own arithmetic
        over it and needs no second override.

        Falls straight through when there is no font to read: Qt asks for
        pixel metrics with no option and no widget during style setup, and
        an indicator sized from a default font would be a different box
        from the one that gets drawn.
        """
        # PySide6's stub types both trailing arguments as non-optional,
        # while Qt's own signature takes nullable ones and passes null
        # itself.
        base = super().pixelMetric(metric, option, widget)  # type: ignore[arg-type]
        if metric not in _INDICATOR_METRICS:
            return base
        if option is not None:
            line_height = option.fontMetrics.height()
        elif widget is not None:
            line_height = widget.fontMetrics().height()
        else:
            return base
        return max(base, checkbox_extent(line_height))

    @classmethod
    def _takes_the_apps_frame(cls, primitive: QStyle.PrimitiveElement,
                              widget: QWidget | None) -> bool:
        """Whether this style strokes its own edge over ``primitive``.

        Everything in ``_OVERLAID_PRIMITIVES`` does, with one exception:
        a line edit that is another control's *editor* rather than a
        control of its own. A spin box draws its own frame through
        ``CC_SpinBox``, and its editor asks for ``PE_PanelLineEdit``
        inside it, so stroking both put a second box around the text --
        reported from the real desktop as a double border on every
        spinner.

        This is the same question ``_stands_in_a_row`` answers for the row
        height, asked for the same reason: an embedded editor is not a
        control in its own right, and whatever the app has an opinion
        about belongs to its host.
        """
        if primitive not in _OVERLAID_PRIMITIVES:
            return False
        if primitive != QStyle.PrimitiveElement.PE_PanelLineEdit:
            return True
        return cls._stands_in_a_row(widget)

    @staticmethod
    def _stands_in_a_row(widget: QWidget | None) -> bool:
        """Whether ``widget`` is a control a layout places, rather than an
        editor living inside another control.

        Asked in two places, and one concept answers both. The row height
        is about controls sitting beside each other, so it belongs to the
        thing the layout positions: a spin box's internal line edit is not
        that thing, and flooring it too makes the host three pixels taller
        than the row, because Qt sizes the editor first and feeds the
        answer into the host's own calculation. The app's own frame is the
        same story drawn instead of measured -- the host already strokes
        one, so stroking the editor's as well is a box inside a box.

        A widget Qt does not name is treated as standing in a row, which
        is the common case and the one that matters; an embedded editor is
        always passed with its parent attached.
        """
        if widget is None:
            return True
        return not isinstance(widget.parentWidget(), _EMBEDDING_CONTROLS)

    @staticmethod
    def _extra_icon_gap(option: QStyleOption) -> int:
        """``theme.extra_icon_gap`` for a button carrying both an icon and
        a label, and zero for anything else -- there is nothing to space.

        The number itself lives in ``theme.py`` because
        ``widgets.primary_button`` has to add the same one to its own size
        hint; only the question of whether this option has two things to
        put a gap between is settled here.
        """
        if not isinstance(option, QStyleOptionButton):
            return 0
        if option.icon.isNull() or not option.text:
            return 0
        return extra_icon_gap(option.fontMetrics.height())

    @staticmethod
    def stroked_frame_rect(element: QStyle.ComplexControl,
                           reported: QRect) -> QRect:
        """Where Fusion actually strokes ``element``'s frame.

        ``subControlRect`` answers where the frame *is* for hit-testing and
        layout; Fusion's paint code can stroke a smaller rect than that, and
        for a spin box it does. The app's own stroke has to follow the
        stroke, not the report, or the two land on different pixels and the
        user sees both. See ``_FRAME_INSETS`` above for the measurement.

        Public, and a separate method, so a test can hold it against a
        plain-Fusion render without reproducing the paint path.
        """
        vertical, horizontal = _FRAME_INSETS[element]
        return reported.adjusted(horizontal, vertical, -horizontal, -vertical)

    # ----- colour rules -----

    @staticmethod
    def overlay_color(option: QStyleOption, resting: QColor,
                      emphasized: bool = False) -> QColor:
        """``resting``, or what being unusable, having keyboard focus or
        lying under the pointer replaces it with.

        ``resting`` is the caller's own edge colour, so this method says
        only what those three states do to a stroke and never which stroke.
        Every caller passes ``theme().border`` today; the parameter is what
        kept it that way through a period when the framed controls and the
        push button carried different edge tokens. ``emphasized`` is for a
        state the option's own flags do not carry -- a dialog's default
        button, which reads as focus does.

        One rule for both routes that draw an edge here, the push button's
        panel and the overlay stroked on the framed controls, so the order
        below cannot come apart between them. It starts with *disabled*
        deliberately: Qt reports ``State_MouseOver`` for a disabled widget
        under the pointer, so a control nobody can use would otherwise take
        the accent exactly like one they can. ``theme().disabled_border``
        rather than skipping the stroke, which left the frame to the
        palette's Disabled colour group -- the one group this app knows it
        cannot rely on, since on the maintainer's desktop it repeats the
        Active one and dims nothing -- and rather than stroking at resting
        strength, which shipped once and made a disabled combo box darker
        than an enabled one had been.

        **Focus outranks hover, and the two are told apart by weight.**
        Hovering a focused control leaves it reading as focused, because
        focus is the persistent state and the one that says where the keys
        go. They cannot both be the accent outright or a pointer crossing
        the pane would look exactly like Tab landing on it, so ``hovered``
        takes ``theme().hover_border`` -- the same edge carried most of the
        way to the accent -- and focus keeps the accent itself.
        ``theme.py`` documents the weight and the measured separation.

        Accent-coloured when focused, rather than skipped: measured, a
        non-editable QComboBox -- what this app actually builds -- gets
        zero pixels of Fusion's own focus indication under ordinary Tab
        navigation, so skipping it here would leave the control with no
        keyboard-focus feedback at all. A QSpinBox already recolours its
        frame toward accent on focus, so this stays colour-consistent with
        that rather than regressing it to a flat grey. A push button drawn
        outright has no Fusion focus rendering left underneath at all, which
        makes this its only focus affordance.

        The token is ``accent``, not ``accent_border``. ``accent_border``
        is a half-way mix of the accent *into the surface* -- the border of
        the accent-filled segmented-button state, where it sits on
        ``accent_fill`` rather than on a card. Measured against ``card_bg``
        it reads 1.82:1 light and 2.72:1 dark, against the 3.36:1 and
        4.45:1 the resting edge carried at the time, so taking keyboard
        focus made a control's outline roughly half as visible as leaving
        it alone -- a de-emphasis, not a focus indicator. ``accent`` is the
        palette's own Highlight and reads at or above the resting weight in
        both schemes.

        Public, and a separate method, so the direction can be asserted
        directly on the colours this style will actually paint: the
        invariant is that neither focus nor hover is ever fainter than
        rest, not any fixed ratio (D-05 dropped the ratio).
        """
        tokens = theme()
        if not option.state & QStyle.StateFlag.State_Enabled:
            return tokens.disabled_border
        if emphasized or option.state & QStyle.StateFlag.State_HasFocus:
            return tokens.accent
        if option.state & QStyle.StateFlag.State_MouseOver:
            return tokens.hover_border
        return resting

    @staticmethod
    def button_face(state: QStyle.StateFlag) -> QColor:
        """The fill of the button panel drawn in ``state``.

        Three steps along one axis, all of them ``theme()``'s and all of
        them measured from the card the control sits on rather than from
        any fixed colour, so the ordering survives a light palette, a dark
        one and anything in between. ``theme.py`` documents the ramp above
        ``button_fill``.

        One ramp, and it answers for every control whose panel this style
        paints -- which by Fusion's own dispatch is a combo box as well as
        a push button, since a combo's whole body arrives here as
        ``PE_PanelButtonCommand`` carrying a ``QStyleOptionButton``. That
        is why the *resting* face matters more than its own control: a
        combo box has no other fill, so a face stepped well off the card
        made every dropdown in the app read as switched off beside the
        spin box next to it, which keeps Fusion's own Base fill.

        ``State_MouseOver`` is not consulted at all. The pointer moves the
        edge and leaves the face alone; ``overlay_color`` is where it is
        answered.

        Public so a test can assert the ordering against the colours this
        style will actually paint, rather than re-deriving the rule.
        """
        tokens = theme()
        if not state & QStyle.StateFlag.State_Enabled:
            return tokens.disabled_fill
        if state & _PRESSED_STATES:
            return tokens.button_pressed_fill
        return tokens.button_fill

    @staticmethod
    def checkbox_fill(state: QStyle.StateFlag) -> QColor:
        """The fill inside a ticked or tristate checkbox drawn in ``state``.

        ``theme().accent_fill`` -- the palette's own Highlight laid thinly
        on the card, the same token the app already fills a selected row
        and a primary button with. So a ticked box carries the colour the
        user chose for his desktop without this style naming a colour, and
        it matches the reference look, where a ticked box is a light tint
        of the accent rather than a neutral one.

        The edge goes with it, to ``theme().accent_border`` -- see the
        module docstring, which records why that is the one exemption from
        the app's single-edge-token rule and why the three edge states
        stay ordered despite it. A neutral ring around this fill was built
        first and turned down on the real desktop.

        Disabled first, and from ``theme()`` rather than the palette's own
        Disabled group, for the reason ``_dimmed`` documents -- a ticked
        box nobody can use would otherwise be the accent-coloured thing on
        a card full of grey.

        Public so a test can assert it against the colours this style will
        actually paint, the way ``button_face`` is.
        """
        tokens = theme()
        if not state & QStyle.StateFlag.State_Enabled:
            return tokens.disabled_fill
        return tokens.accent_fill

    @classmethod
    def panel_face(cls, state: QStyle.StateFlag,
                   widget: QWidget | None = None) -> QColor:
        """The fill of the panel this style paints for ``widget``: the
        button ramp, except that a combo box at rest is a *field*.

        Fusion routes a combo box's whole body through
        ``PE_PanelButtonCommand``, so without this it takes a button's
        face, and that is not what a dropdown is. In the reference look a
        combo reads as something you type into rather than something you
        press: it fills with the card's own colour, exactly like the spin
        box beside it in the same column, which keeps ``QPalette::Base``
        from Fusion and never entered the ramp at all. So the two agreed
        with each other only by coincidence, and stopped agreeing as soon
        as the ramp moved -- which is what was reported, twice, as the
        dropdowns looking wrong beside their neighbours.

        Only *at rest*: a combo that is disabled or has its popup open
        still answers from the ramp, because those two say something about
        the control's state rather than about what kind of control it is,
        and a field with no disabled treatment reads as usable.

        The widget's class is asked directly, which is the one per-widget
        test in this module. It earns that by being a question about a
        control's kind rather than about a particular instance -- every
        ``QComboBox`` this app builds and every one it never thought of
        answer the same way.
        """
        if (state & QStyle.StateFlag.State_Enabled
                and not state & _PRESSED_STATES
                and isinstance(widget, QComboBox)):
            return theme().card_bg
        return cls.button_face(state)

    @classmethod
    def button_edge(cls, option: QStyleOption) -> QColor:
        """The edge colour of a push button drawn for ``option``.

        The app's own edge token, put through ``overlay_color``'s rule --
        which is the same rule the framed controls' overlay goes through,
        so a hovered button and a hovered combo cannot drift apart.

        The one thing that is this route's alone is the dialog's default
        button: its emphasis is Fusion's to draw, and this style no longer
        calls Fusion for the panel, so it has to be restated here or it is
        silently lost.
        """
        default = isinstance(option, QStyleOptionButton) and bool(
            option.features & QStyleOptionButton.ButtonFeature.DefaultButton)
        return cls.overlay_color(option, theme().border, default)

    # ----- the primitives those rules are spent on -----

    @classmethod
    def _draw_button_panel(cls, painter: QPainter, option: QStyleOption,
                           widget: QWidget | None = None) -> None:
        """A push button's whole panel: fill, edge and corner, one pass."""
        cls._stroke_rounded(painter, option.rect, cls.button_edge(option),
                            cls.panel_face(option.state, widget))

    @classmethod
    def _draw_checked_indicator(cls, painter: QPainter,
                                option: QStyleOption) -> None:
        """A ticked or tristate checkbox: fill, edge and mark, one pass.

        The same shape as ``_draw_button_panel`` and for the same reason --
        an indicator has no sub-controls, so owning it outright costs
        nothing that has to be enumerated back. The edge goes through
        ``overlay_color`` exactly as every other edge here does, so a
        ticked box still lights under the pointer, still takes the accent
        on focus and still goes flat when it cannot be used.
        """
        cls._stroke_rounded(painter, option.rect,
                            cls.overlay_color(option, theme().accent_border),
                            cls.checkbox_fill(option.state))
        cls._draw_mark(painter, option)

    @classmethod
    def _draw_mark(cls, painter: QPainter, option: QStyleOption) -> None:
        """The tick, or the tristate bar, inside ``option``'s indicator.

        Drawn from ``_CHECK_MARK`` / ``_TRISTATE_MARK`` on the box's own
        unit square, with a round cap and a round join, which is the whole
        of what makes it read as a smoother mark than the one it replaces.
        Antialiased, and stroked at a fraction of the box rather than at a
        pixel count, so it is the same drawing on a HiDPI display and at
        150% text.

        In ``theme().text``, or ``disabled_text`` -- a mark is ink, and it
        is the only ink inside a control the app draws, so it follows the
        same pair of tokens every label in this style already does.
        """
        rect = QRectF(option.rect)
        if rect.width() < 2 or rect.height() < 2:
            return
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        tokens = theme()
        points = (_CHECK_MARK if option.state & QStyle.StateFlag.State_On
                  else _TRISTATE_MARK)
        path = QPainterPath()
        for index, (across, down) in enumerate(points):
            point = QPointF(rect.left() + across * rect.width(),
                            rect.top() + down * rect.height())
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        pen = QPen(tokens.text if enabled else tokens.disabled_text,
                   max(1.0, min(rect.width(), rect.height())
                       * _MARK_WIDTH_FRACTION))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(pen)
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawPath(path)
        painter.restore()

    @classmethod
    def _overlay(cls, painter: QPainter, option: QStyleOption, rect: QRect,
                 resting: QColor) -> None:
        """Paint one rounded stroke over ``rect``, ``resting``-coloured
        unless the control is under the pointer, has keyboard focus, or
        cannot be used.

        Which of those four colours it is comes from ``overlay_color``, the
        same method the push button's panel asks, so that a hovered combo
        box and a hovered button carry one answer rather than two that have
        to be kept in step by hand. What the app's own disabled token buys,
        and why the stroke is not simply skipped, is documented there.
        """
        cls._stroke_rounded(painter, rect,
                            cls.overlay_color(option, resting), None)

    @staticmethod
    def frame_radius(rect: QRect) -> float:
        """The app's control radius, clamped to ``rect``.

        One rule, one place, so the curve Fusion is clipped to and the curve
        the app strokes are the same curve -- a millimetre of disagreement
        between them is precisely the artefact this module exists to remove.
        """
        return corner_radius(CONTROL_RADIUS,
                             min(rect.width(), rect.height()) - 1.0)

    @classmethod
    def _clip_to_frame(cls, painter: QPainter, rect: QRect) -> None:
        """Confine whatever is painted next to the app's own rounded frame.

        This is how a control whose sub-controls must stay Fusion's gets the
        app's corner anyway. Fusion rounds a frame at its own, squarer
        radius, so its corner arc stands outside the app's curve and shows
        as a nick past each corner; intersecting the clip with the app's own
        rounded rectangle drops exactly those pixels and touches nothing
        else, where taking the frame over outright would mean reimplementing
        the arrows and stepper faces inside it.

        The clip is hard-edged -- Qt's raster engine does not antialias a
        path clip -- and that is invisible in practice because the app's own
        1px stroke is centred on the same curve immediately afterwards and
        covers the step. The caller owns the ``save``/``restore`` around it;
        nothing here can restore a clip it did not set.
        """
        path = QPainterPath()
        radius = cls.frame_radius(rect)
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.setClipPath(path, Qt.ClipOperation.IntersectClip)

    @classmethod
    def _stroke_rounded(cls, painter: QPainter, rect: QRect, edge: QColor,
                        fill: QColor | None) -> None:
        """One rounded rectangle at the app's control radius: ``edge``
        stroked at the app's border weight, ``fill`` inside it or nothing.

        The base style's own draw call leaves the painter's pen, brush and
        render hints in an unspecified state, so ``save``/``restore`` is not
        optional -- an unbalanced painter here leaks into whatever Qt paints
        next.
        """
        # A rect too small to inset by half a pixel on each side would be
        # given a negative size below, and Qt answers that with geometry
        # warnings on stderr -- journald, in the shipped app. No real
        # widget reaches it; a synthetic style option can.
        if rect.width() < 2 or rect.height() < 2:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(edge, BORDER_WIDTH))
        painter.setBrush(QBrush(fill) if fill is not None
                         else QBrush(Qt.BrushStyle.NoBrush))
        # Inset by half a pixel on every side so a 1px pen centred on the
        # boundary lands inside the control rather than half outside it.
        stroke_rect = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = cls.frame_radius(rect)
        painter.drawRoundedRect(stroke_rect, radius, radius)
        painter.restore()
