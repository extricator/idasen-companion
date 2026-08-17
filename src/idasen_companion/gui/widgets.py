"""Reusable building blocks for the redesigned screens: cards, section
headers, status dots, and a segmented control (Qt Widgets has no native
one). Everything colors itself from :mod:`.theme` so it follows the
platform palette."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QStyle, QStyleOptionButton, QVBoxLayout,
    QWidget,
)

from . import restyle
from .theme import (
    BORDER_WIDTH, BUTTON_PADDING_H, BUTTON_PADDING_V, CONTROL_RADIUS,
    SURFACE_RADIUS, button_icon_gap, control_height, css, extra_icon_gap,
    theme,
)

# paintEvent, sizeHint, mousePressEvent, mouseMoveEvent and mouseReleaseEvent
# below are Qt virtual overrides, dispatched by name from Qt's C++
# meta-object machinery.
# setCurrentIndex and currentIndex on SegmentedControl are this project's own
# methods, deliberately mirroring QComboBox's API shape on a custom widget.
# Both groups carry their own inline naming-check suppression rather than a
# file-level one.


def icon(*names: str) -> QIcon:
    """First available icon from the platform theme."""
    for name in names:
        candidate = QIcon.fromTheme(name)
        if not candidate.isNull():
            return candidate
    return QIcon()


def _dpr() -> float:
    # instance() is typed as the QCoreApplication base, which knows nothing
    # about screens, and is None before the application exists.
    app = QApplication.instance()
    return app.devicePixelRatio() if isinstance(app, QApplication) else 1.0


def _recolor(pix: QPixmap, color) -> QPixmap:
    """Tint a (monochrome/symbolic) pixmap to ``color``, keeping alpha."""
    out = QPixmap(pix.size())
    out.setDevicePixelRatio(pix.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.drawPixmap(0, 0, pix)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), color)
    painter.end()
    return out


def tinted_icon(base: QIcon, color, size: int = 16,
                mode: QIcon.Mode = QIcon.Mode.Normal) -> QIcon:
    """A themed icon recoloured to ``color``, returned as a plain-pixmap
    icon (so item-view selection can't re-tint it). Rendered at the
    display's pixel ratio so it stays crisp on HiDPI.

    ``mode`` is which of ``QIcon``'s modes the tinted pixmap is registered
    under, and it is not cosmetic. ``QIcon`` synthesises any mode it has no
    pixmap for -- ask a Normal-only icon for its Disabled pixmap and Qt
    grey-ramps it for you, on top of whatever tint is already there. So an
    icon tinted *because* its control is disabled has to be filed under
    ``QIcon.Mode.Disabled``, or the colour chosen here is the input to
    Qt's own dimming rather than the result.
    """
    if base.isNull():
        return base
    out = QIcon()
    out.addPixmap(_recolor(base.pixmap(QSize(size, size), _dpr()), color), mode)
    return out


def selectable_icon(base: QIcon, selected_color, resting_color,
                    box: int = 22, normal: int = 16,
                    selected: int = 22) -> QIcon:
    """Sidebar icon that grows and takes the caller's selected colour when
    its row is selected.

    Both colours are the caller's and both are required, because the
    resting glyph used to be the icon theme's own, uncoloured. That made
    it the one thing in the sidebar that did not follow the palette: on a
    live switch to dark it stayed dark-on-dark until the app was
    relaunched, since an icon is pixels rather than a colour a palette can
    rewrite, and ``QIcon.fromTheme`` caches what it resolved anyway.
    Recolouring it from ``theme()`` sidesteps both -- the glyph follows the
    scheme with no dependence on the desktop shipping a dark icon theme.

    Both states are baked as exact ``box``-sized pixmaps — the glyph is
    drawn at ``normal`` px (centred, with padding) for the resting state
    and at ``selected`` px (filling the box) for the active state. Because
    the view's icon size equals ``box`` and each pixmap is that exact
    size, nothing is rescaled at paint time, and the row height doesn't
    jump since the icon box is constant. ``normal`` and ``selected`` must
    be *native* icon-theme sizes (16/22/24) — an in-between size like 19
    is rasterised off the nearest native size and looks blurry.

    The selected state is recoloured too, and separately, because it is
    drawn on a different surface from the resting one: its row is filled
    with the desktop's own selection colour, so the glyph has to be the
    colour that reads on *that* rather than on the sidebar. Leaving both
    states one colour is the bug this parameter pair exists to prevent --
    the glyph disappears into whichever of the two surfaces it was not
    chosen for."""
    if base.isNull():
        return base
    dpr = _dpr()

    def render(glyph_px: int, color) -> QPixmap:
        canvas = QPixmap(round(box * dpr), round(box * dpr))
        canvas.setDevicePixelRatio(dpr)
        canvas.fill(Qt.GlobalColor.transparent)
        glyph = base.pixmap(QSize(glyph_px, glyph_px), dpr)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        offset = (box - glyph_px) / 2.0
        painter.drawPixmap(QPointF(offset, offset), glyph)
        painter.end()
        return _recolor(canvas, color) if color is not None else canvas

    out = QIcon()
    out.addPixmap(render(normal, resting_color), QIcon.Mode.Normal)
    out.addPixmap(render(selected, selected_color), QIcon.Mode.Selected)
    return out


class Card(QFrame):
    """Card surface (palette Base) with 1px border and 6px radius; owns a
    QVBoxLayout. Follows the platform theme, so it is dark under a dark one."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        restyle.register(self, self._restyle)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(10)

    def _restyle(self) -> None:
        tokens = theme()
        self.setStyleSheet(
            f"QFrame#Card {{ background: {css(tokens.card_bg)};"
            f" border: 1px solid {css(tokens.border)};"
            f" border-radius: {SURFACE_RADIUS}px; }}")


def emphasize(font: QFont) -> QFont:
    """Return a copy of ``font`` at the app's standard emphasis weight, so
    every emphasised label — the Overview position word, the Automation
    status / countdown, the preset names — reads the same from one
    definition. Emphasis is weight only (no letter-spacing): plain, standard,
    and applied uniformly via ``QFont`` rather than RichText ``<b>``."""
    emphasized = QFont(font)
    emphasized.setWeight(QFont.Weight.DemiBold)
    return emphasized


def section_label(text: str) -> QLabel:
    """Uppercase card section header (small, semibold, letterspaced)."""
    label = QLabel(text.upper())
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 0.82)
    font.setWeight(font.Weight.DemiBold)
    font.setLetterSpacing(font.SpacingType.PercentageSpacing, 108)
    label.setFont(font)

    def _restyle(target: QLabel = label) -> None:
        target.setStyleSheet(f"color: {css(theme().muted)}; border: none;")

    restyle.register(label, _restyle)
    return label


def separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)

    def _restyle(target: QFrame = line) -> None:
        target.setStyleSheet(f"background: {css(theme().separator)}; border: none;")

    restyle.register(line, _restyle)
    return line


def pill_css(foreground, border=None) -> str:
    """Extracted from :func:`pill` so a caller whose colours are its own
    tokens (not `pill`'s to re-derive) can recompute them on a restyle
    without duplicating this rule."""
    return (
        f"color: {css(foreground)}; border: 1px solid {css(border or foreground)};"
        f" border-radius: {SURFACE_RADIUS}px; padding: 0 7px;")


def pill(text: str, foreground, border=None) -> QLabel:
    """Small outlined pill label (status chips, badges, trigger tags)."""
    label = QLabel(text)
    label.setStyleSheet(pill_css(foreground, border))
    return label


def card_scroll() -> tuple[QScrollArea, QVBoxLayout]:
    """Transparent scroll area for use inside a Card; returns the scroll
    widget and the zero-margin layout to fill."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    inner = QWidget()
    # Qualified by object name, not written bare. An unqualified rule applies
    # to this widget *and every descendant*, and a stylesheet that names a
    # background takes that widget off its style's own box model -- where the
    # border defaults to none. So a bare `background: transparent` here
    # silently unframed every control inside a scrolling page that the app
    # does not draw itself, which is how the Settings page's Bluetooth
    # address field came to render with no border at all. `Card` above
    # already qualifies its own rule the same way, for the same reason.
    inner.setObjectName("ScrollBody")

    def _restyle_transparency(area: QScrollArea = scroll,
                              body: QWidget = inner) -> None:
        """Re-apply both rules on a palette change, though neither names a
        colour.

        This looks pointless and is not. A widget under a stylesheet is
        rendered by ``QStyleSheetStyle``, which caches the rules it
        resolved for that widget and its descendants -- and a palette
        change does not invalidate that cache, while setting a stylesheet
        does. So a scroll area whose rule never changes keeps whatever its
        scrollbar resolved to at construction: measured on a live
        light-to-dark switch, the bar stayed at its light ``#f7f7f7``
        slider where a window built dark rendered ``#42474b``, and only a
        relaunch fixed it. Re-setting the same strings makes the switched
        window pixel-identical to the fresh one.

        Registered here rather than in ``theme.py``'s usual pattern
        because every other entry in the restyle registry exists to
        recompute a colour, and this one exists to drop a cache.
        """
        area.setStyleSheet("QScrollArea { background: transparent; }")
        body.setStyleSheet("QWidget#ScrollBody { background: transparent; }")

    _restyle_transparency()
    restyle.register(scroll, _restyle_transparency)
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    scroll.setWidget(inner)
    return scroll, layout


def page_scroll() -> tuple[QScrollArea, QVBoxLayout]:
    """Scrolling card column for a whole page; returns the scroll widget and
    the layout to add Cards to.

    Like :func:`card_scroll`, but for the pages whose cards scroll over the
    window background rather than inside an opaque Card (Settings, Automation,
    About). Those need an explicit viewport fill — Breeze otherwise leaves the
    unpainted area black at sizes where the content actually scrolls. The
    fill colour is read fresh from ``theme()`` at restyle time rather than
    passed in, so it follows a live theme switch.
    """
    scroll, layout = card_scroll()
    layout.setContentsMargins(0, 0, 4, 0)
    layout.setSpacing(12)
    viewport = scroll.viewport()
    viewport.setAutoFillBackground(True)

    def _restyle(target: QWidget = viewport) -> None:
        palette = target.palette()
        palette.setColor(target.backgroundRole(), theme().window)
        target.setPalette(palette)
        target.update()

    restyle.register(viewport, _restyle)
    return scroll, layout


def clear_layout(layout) -> None:
    """Remove and delete every item in a layout."""
    while (item := layout.takeAt(0)) is not None:
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def equal_height_row(*controls: QWidget, spacing: int = 10) -> QWidget:
    """A row whose controls all lay out at one height — the tallest of
    their own size hints — wherever that height ends up.

    This is *not* how two buttons are made to match. Buttons match because
    ``theme``'s button padding sizes both kinds of them — `primary_button`
    through its stylesheet, a bare ``QPushButton`` through
    ``gui/style.py``'s ``CT_PushButton`` override — so a row of buttons is
    level by construction and needs nothing here.

    What this is for is the one pairing that cannot be reached that way: a
    spin box beside a button. A `Card` sets a stylesheet, which routes its
    children through ``QStyleSheetStyle``, and for a spin box that style
    computes the whole size itself and never consults the application
    style at all — measured, ``ControlStyle.sizeFromContents`` is not
    called once for a ``QDoubleSpinBox`` inside a `Card`, so no metric the
    app overrides can move it. Its hint is not even stable: 26px
    unparented and 22px once it is added to a `Card`, measured offscreen.
    Reading either widget's hint and pinning the other to it therefore
    produces a pair that matches only if the reading happened to be taken
    at the right moment — which is how the Overview page's Move button
    ended up 4px taller than the spin box beside it.

    Nothing is measured or captured here. The row's own height is its
    layout's hint (the tallest control's), each control is made vertically
    expanding so it fills that, and the row is capped at its hint so a
    taller parent cell cannot stretch it. Every one of those is resolved
    afresh on each layout pass, so re-parenting, a live theme switch that
    rewrites a stylesheet's padding, and a font or DPI change all keep the
    controls level without anything having to notice they happened.

    Add the result to its parent layout with ``AlignTop`` if it should sit
    at the top of a taller row; the alignment chooses where the row goes,
    not how tall it is.
    """
    row_widget = QWidget()
    row_widget.setSizePolicy(QSizePolicy.Policy.Preferred,
                             QSizePolicy.Policy.Fixed)
    row = QHBoxLayout(row_widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(spacing)
    for control in controls:
        policy = control.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Expanding)
        control.setSizePolicy(policy)
        row.addWidget(control)
    return row_widget


def segment_css(first: bool, last: bool, padding: str = "4px 12px") -> str:
    """Stylesheet for one segment of a joined button strip. With
    first=last=True it doubles as a standalone chip (Schedule days).
    Checked rules are inert on non-checkable buttons (Presets footer).

    The :disabled rules aren't optional decoration: a stylesheet that names a
    color wins over the style's own disabled rendering, so without them a
    checked segment keeps its full accent inside a switched-off section — the
    Schedule days stayed vividly selected with "Use schedule" unticked while
    the plain QTimeEdits beside them greyed out correctly."""
    tokens = theme()
    radius_left = f"{CONTROL_RADIUS}px" if first else "0"
    radius_right = f"{CONTROL_RADIUS}px" if last else "0"
    left_border = "" if first else "border-left: none;"
    return (
        f"QPushButton {{ background: {css(tokens.card_bg)};"
        f" color: {css(tokens.secondary)};"
        f" border: 1px solid {css(tokens.border)}; {left_border}"
        f" border-top-left-radius: {radius_left};"
        f" border-bottom-left-radius: {radius_left};"
        f" border-top-right-radius: {radius_right};"
        f" border-bottom-right-radius: {radius_right};"
        f" padding: {padding}; }}"
        f"QPushButton:checked {{ background: {css(tokens.accent_fill)};"
        f" color: {css(tokens.accent_text)};"
        f" border-color: {css(tokens.accent_border)}; font-weight: 600; }}"
        f"QPushButton:hover:!checked {{ background: {css(tokens.hover)}; }}"
        # Both carry more pseudo-states than the rules above, so they win.
        f"QPushButton:disabled {{ color: {css(tokens.muted)};"
        f" border-color: {css(tokens.separator)}; }}"
        f"QPushButton:checked:disabled {{ background: {css(tokens.hover)};"
        f" color: {css(tokens.muted)}; border-color: {css(tokens.separator)};"
        # Keep the weight: which days are picked should still read at a
        # glance while the schedule is off — dimmed, not erased.
        f" font-weight: 600; }}")


class StatusDot(QWidget):
    """8px colored circle."""

    def __init__(self, color=None, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = color or theme().muted
        # True for a dot no caller has ever explicitly coloured -- the
        # only population a restyle sweep may repaint. set_color() clears
        # this, since a caller that has coloured the dot owns it from then
        # on and a sweep must not stomp a domain-driven colour (e.g. a
        # dot currently red for a real error) back to muted.
        self._follows_palette = color is None
        self.setFixedSize(8, 8)
        restyle.register(self, self._restyle)

    def _restyle(self) -> None:
        if self._follows_palette:
            self._color = theme().muted
            self.update()

    def set_color(self, color) -> None:
        self._color = color
        self._follows_palette = False
        self.update()

    def paintEvent(self, event) -> None:  # pylint: disable=invalid-name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.rect())


class ConnectionChip(QWidget):
    """Pill with a status dot and a short label (used in the DESK card)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Chip")
        # QWidget subclasses ignore background/border stylesheets unless
        # styled backgrounds are opted into.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 3, 10, 3)
        row.setSpacing(6)
        self.dot = StatusDot()
        self.label = QLabel()
        row.addWidget(self.dot)
        row.addWidget(self.label)
        restyle.register(self, self._restyle)

    def _restyle(self) -> None:
        tokens = theme()
        # Deliberately neither token (D-16): this is a stadium/capsule
        # at roughly half its own ~22px height, not a rounded rectangle.
        # Collapsing it to the shared radius gives it visible flat sides.
        # Left as its own literal until the maintainer judges it against
        # the surface radius on a real desktop.
        self.setStyleSheet(
            f"QWidget#Chip {{ background: {css(tokens.window)};"
            f" border: 1px solid {css(tokens.border)}; border-radius: 11px; }}")
        self.label.setStyleSheet(f"color: {css(tokens.secondary)}; border: none;")

    def set_state(self, color, text: str) -> None:
        self.dot.set_color(color)
        self.label.setText(text)


class SegmentedControl(QWidget):
    """Joined row of exclusive checkable buttons ("segmented button").

    Qt Widgets has no native equivalent, so this styles plain buttons:
    selected segment gets the accent fill, segments share borders.
    """

    currentChanged = Signal(int)

    def __init__(self, items: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        button_row = QHBoxLayout(self)
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, text in enumerate(items):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            is_first = index == 0
            is_last = index == len(items) - 1

            # Bound via default arguments, not a closure over the loop
            # variables -- a bare closure over `button` would leave every
            # entry restyling the last button once the loop finished.
            def _restyle_segment(
                target: QPushButton = button, first: bool = is_first,
                last: bool = is_last,
            ) -> None:
                target.setStyleSheet(segment_css(first, last))

            restyle.register(button, _restyle_segment)
            # The selected segment renders DemiBold (segment_css :checked),
            # which is a few px wider than the normal weight the sizeHint
            # reserves — enough to clip the longest label once it's selected.
            # Reserve the bold width up front so a segment never clips on check.
            bold_extra = (QFontMetrics(emphasize(button.font())).horizontalAdvance(text)
                          - button.fontMetrics().horizontalAdvance(text))
            if bold_extra > 0:
                button.setMinimumWidth(button.sizeHint().width() + bold_extra)
            self._group.addButton(button, index)
            button_row.addWidget(button)
        button_row.addStretch()
        self._group.idClicked.connect(self.currentChanged.emit)

    def setCurrentIndex(self, index: int) -> None:  # pylint: disable=invalid-name
        button = self._group.button(index)
        if button and not button.isChecked():
            button.setChecked(True)
            # Emit for a programmatic change too, the way QComboBox does for
            # currentIndexChanged. Wiring it to idClicked alone made this the
            # one control on a settings page whose signal fired for the user
            # but not for load(), so anything derived from the selection --
            # the per-segment help line in SettingsFormPage._settings_row --
            # went stale the moment the page reloaded from disk.
            self.currentChanged.emit(index)

    def currentIndex(self) -> int:  # pylint: disable=invalid-name
        return self._group.checkedId()


def spaced_label_parts(
        option: QStyleOptionButton,
        content: QRect) -> tuple[QStyleOptionButton, QStyleOptionButton] | None:
    """A push button's label split in two -- the icon alone and the text
    alone -- each in its own rect inside ``content``, with the app's own
    gap between them. ``None`` when there is nothing to space.

    Split rather than laid out from scratch, because each half is then
    still *drawn* by whichever style the caller hands it to, keeping that
    style's mnemonic underlining, elision, disabled treatment and
    sunken-state shift. The only thing taken over is where the two halves
    go. They are centred in ``content`` as one block, so the button reads
    as Qt's own layout with a wider gap rather than as a left-aligned
    label, and both rects come back through ``QStyle.visualRect``, so a
    right-to-left layout mirrors the pair and keeps the gap rather than
    closing it.

    Shared between the two things in this app that lay a button's label
    out, and it has to be shared because they must not disagree:
    ``gui/style.py`` does it for every bare ``QPushButton``, and
    ``primary_button`` below does it for itself because a widget declaring
    a border in a stylesheet is rendered by ``QStyleSheetStyle``, which
    lays out the label too and never reaches the application style. Two
    copies of this rule is exactly the drift that once left Move sitting
    in a row with Sit, Stand and Stop at a visibly tighter gap than theirs.

    Declines for a button carrying only one of the two -- there is nothing
    to space -- and for one whose icon reports no size it can be laid out
    from.
    """
    if option.icon.isNull() or not option.text:
        return None
    icon_size = option.icon.actualSize(option.iconSize)
    if icon_size.width() <= 0:
        return None
    icon_gap = button_icon_gap(option.fontMetrics.height())
    text_width = option.fontMetrics.boundingRect(
        content, int(Qt.TextFlag.TextShowMnemonic), option.text).width()
    left = content.left() + (content.width()
                             - (icon_size.width() + icon_gap
                                + text_width)) // 2
    icon_only = QStyleOptionButton(option)
    icon_only.text = ""
    text_only = QStyleOptionButton(option)
    text_only.icon = QIcon()
    for part, logical in (
            (icon_only,
             QRect(left, content.top(), icon_size.width(), content.height())),
            (text_only,
             QRect(left + icon_size.width() + icon_gap, content.top(),
                   text_width, content.height()))):
        part.rect = QStyle.visualRect(option.direction, content, logical)
    return icon_only, text_only


class _PrimaryButton(QPushButton):
    """A push button that lays its own icon and label out.

    Everything else about it is its stylesheet's, which is the point: a
    widget that declares a border in one is drawn by ``QStyleSheetStyle``,
    and ``QStyleSheetStyle`` renders a push button's label through
    ``QCommonStyle`` directly rather than through the application style, so
    ``gui/style.py``'s spacing never reached this button. Measured, its gap
    stayed at the toolkit's ~2px while every bare button beside it took the
    app's, and Move sat in the Overview row visibly tighter than Sit,
    Stand and Stop.

    Qt's stylesheet syntax has no icon-spacing property to declare it with
    (``spacing`` is not one of the properties a ``QPushButton`` rule
    supports -- measured, it changes nothing), so the layout is taken over
    here instead. The panel is still drawn by the stylesheet, and each half
    of the label is still drawn by ``QStyleSheetStyle``: only *where* the
    two halves go is this class's. So the rule's colour, weight, radius,
    padding and its ``:hover`` and ``:disabled`` variants all still apply,
    unchanged.
    """

    # sizeHint and paintEvent are Qt virtual overrides, dispatched by name
    # from Qt's C++ meta-object machinery.
    def sizeHint(self) -> QSize:  # pylint: disable=invalid-name
        # The height is the app's own row height, restated here because
        # this button is sized by QStyleSheetStyle from its stylesheet's
        # padding, and that padding is added to the *contents* box -- the
        # bounding box of the label's actual glyphs, which exceeds the line
        # height at some font sizes and not others. Left alone it stood a
        # pixel above the bare buttons beside it at 15 and 22pt while
        # matching them at 10, 12 and 14, and its height depended on which
        # letters were in it. Taken rather than floored, for that reason:
        # the extra pixel is the thing being discarded.
        hint = super().sizeHint()
        height = control_height(self.fontMetrics().height())
        if self.icon().isNull() or not self.text():
            return QSize(hint.width(), height)
        return QSize(
            hint.width() + extra_icon_gap(self.fontMetrics().height()),
            height)

    def paintEvent(self, event) -> None:  # pylint: disable=invalid-name
        option = QStyleOptionButton()
        self.initStyleOption(option)
        content = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, option, self)
        parts = spaced_label_parts(option, content)
        if parts is None:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        # The panel first, with the label emptied out, so the stylesheet
        # draws its own background, border and corner exactly as it does
        # for any other state -- and then draws nothing where the label
        # would have gone.
        bare = QStyleOptionButton(option)
        bare.text = ""
        bare.icon = QIcon()
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, bare,
                                 painter, self)
        for part in parts:
            self.style().drawControl(
                QStyle.ControlElement.CE_PushButtonLabel, part, painter, self)


def primary_button(text: str) -> QPushButton:
    """Accent-filled button (the mock's "primary" style).

    The radius, the padding and the border weight below are the app's own
    button metrics, named from ``theme`` rather than written out here,
    because ``gui/style.py`` hands the *same* three to a push button that
    carries no stylesheet at all. That is what makes an accent-filled
    button and a neutral one the same size wherever they share a row --
    Move beside Sit, Stand and Stop on the Overview page -- without either
    being measured against the other.

    The icon-to-label gap is the one metric a stylesheet cannot carry, so
    ``_PrimaryButton`` above lays that pair out itself. Everything else
    about the button is the rule below.
    """
    button = _PrimaryButton(text)

    def _restyle(target: QPushButton = button) -> None:
        tokens = theme()
        target.setStyleSheet(
            f"QPushButton {{ background: {css(tokens.accent_fill)};"
            f" color: {css(tokens.accent_text)};"
            f" border: {BORDER_WIDTH}px solid {css(tokens.accent_border)};"
            f" border-radius: {CONTROL_RADIUS}px;"
            f" padding: {BUTTON_PADDING_V}px {BUTTON_PADDING_H}px;"
            f" font-weight: 600; }}"
            f"QPushButton:hover {{ background: {css(tokens.accent_border)}; }}"
            f"QPushButton:disabled {{ color: {css(tokens.muted)};"
            f" background: {css(tokens.hover)}; border-color: {css(tokens.border)}; }}")

    restyle.register(button, _restyle)
    return button


def _clamp01(fraction: float) -> float:
    """A fractional position along a rail, held inside its own track."""
    return max(0.0, min(1.0, fraction))


class HeightRail(QWidget):
    """Horizontal desk-height rail: filled track = current height, a
    draggable handle = target, small labeled ticks at the sit and stand
    preset heights. Dragging only proposes a target (emits
    ``targetChanged`` in meters); the Move button commits it."""

    targetChanged = Signal(float)

    _PAD = 10          # room for the handle at either end
    _TRACK_Y = 14      # track centerline
    _TRACK_H = 6

    def __init__(self, min_height: float, max_height: float, parent: QWidget | None = None):
        super().__init__(parent)
        self._lo, self._hi = min_height, max_height
        self._height = min_height
        self._target = min_height
        self._dragging = False
        self._marks: list[tuple[str, float]] = []   # (label, meters)
        self.setMinimumHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def dragging(self) -> bool:
        return self._dragging

    # ----- data -----

    def set_height(self, meters: float) -> None:
        self._height = meters
        self.update()

    def set_target(self, meters: float) -> None:
        self._target = min(max(meters, self._lo), self._hi)
        self.update()

    def set_marks(self, marks: list[tuple[str, float]]) -> None:
        """Labeled tick positions, e.g. [("Sit", 0.62), ("Stand", 1.144)]."""
        self._marks = marks
        self.update()

    # ----- geometry -----

    def _x(self, meters: float) -> float:
        span = self.width() - 2 * self._PAD
        frac = (meters - self._lo) / (self._hi - self._lo)
        return self._PAD + _clamp01(frac) * span

    def _meters(self, pixel_x: float) -> float:
        span = self.width() - 2 * self._PAD
        frac = (pixel_x - self._PAD) / max(1.0, span)
        return self._lo + _clamp01(frac) * (self._hi - self._lo)

    # ----- interaction -----

    def mousePressEvent(self, event) -> None:  # pylint: disable=invalid-name
        self._dragging = True
        self._drag_to(event.position().x())

    def mouseMoveEvent(self, event) -> None:  # pylint: disable=invalid-name
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._drag_to(event.position().x())

    def mouseReleaseEvent(self, event) -> None:  # pylint: disable=invalid-name
        self._dragging = False

    def _drag_to(self, pixel_x: float) -> None:
        self._target = round(self._meters(pixel_x), 3)
        self.targetChanged.emit(self._target)
        self.update()

    # ----- painting -----

    def paintEvent(self, event) -> None:  # pylint: disable=invalid-name
        tokens = theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track_y = self._TRACK_Y
        left, right = self._PAD, self.width() - self._PAD

        track = QRectF(left, track_y - self._TRACK_H / 2,
                       right - left, self._TRACK_H)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tokens.separator)
        painter.drawRoundedRect(track, 3, 3)

        fill_x = self._x(self._height)
        if fill_x > left:
            fill = QRectF(left, track_y - self._TRACK_H / 2,
                          fill_x - left, self._TRACK_H)
            painter.setBrush(tokens.accent)
            painter.drawRoundedRect(fill, 3, 3)

        # Preset ticks + labels under the track.
        from .util import fmt_height_value

        small = painter.font()
        small.setPointSizeF(small.pointSizeF() * 0.82)
        painter.setFont(small)
        metrics = painter.fontMetrics()
        for label, meters in self._marks:
            tick_x = self._x(meters)
            painter.setPen(QPen(tokens.muted, 1.4))
            painter.drawLine(QPointF(tick_x, track_y + 5), QPointF(tick_x, track_y + 11))
            text = f"{label} · {fmt_height_value(meters, trim=True)}"
            text_width = metrics.horizontalAdvance(text)
            text_x = min(max(tick_x - text_width / 2, left - self._PAD + 2),
                         self.width() - text_width - 2)
            painter.setPen(tokens.muted)
            painter.drawText(QPointF(text_x, track_y + 12 + metrics.ascent()), text)

        # Target handle.
        handle_x = self._x(self._target)
        painter.setPen(QPen(tokens.accent, 2))
        painter.setBrush(tokens.card_bg)
        painter.drawEllipse(QPointF(handle_x, track_y), 7, 7)
        painter.end()


class RangeRail(QWidget):
    """Vertical desk-range rail (Presets screen): grey ticks with names
    for each preset, a blue tick with the bold live height. When the desk
    sits at a preset's height the preset's own tick/label turns blue and
    absorbs the height value ("name · 62")."""

    _PAD = 14
    _TRACK_X = 10
    MATCH = 0.0075  # meters within which the desk counts as "at" a preset

    def __init__(self, min_height: float, max_height: float, parent: QWidget | None = None):
        super().__init__(parent)
        self._lo, self._hi = min_height, max_height
        self._height = 0.0
        self._presets: dict[str, float] = {}
        self.setMinimumWidth(96)
        self.setMinimumHeight(180)

    def set_height(self, meters: float) -> None:
        self._height = meters
        self.update()

    def set_presets(self, presets: dict[str, float]) -> None:
        self._presets = dict(presets)
        self.update()

    def _y(self, meters: float) -> float:
        span = self.height() - 2 * self._PAD
        frac = (self._hi - meters) / (self._hi - self._lo)
        return self._PAD + _clamp01(frac) * span

    def paintEvent(self, event) -> None:  # pylint: disable=invalid-name
        from .util import fmt_height_value, suffix_height

        tokens = theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track_x = self._TRACK_X

        painter.setPen(QPen(tokens.separator, 2))
        painter.drawLine(QPointF(track_x, self._PAD), QPointF(track_x, self.height() - self._PAD))

        small = painter.font()
        small.setPointSizeF(small.pointSizeF() * 0.86)
        bold = QFont(small)
        bold.setWeight(QFont.Weight.DemiBold)

        # Range extremes, right-aligned at the track's top and bottom.
        # Skip an extreme that a preset already sits on, so the two
        # labels don't collide (sit is usually at the minimum height).
        painter.setFont(small)
        painter.setPen(tokens.muted)
        metrics = painter.fontMetrics()
        for meters, label_y in ((self._hi, metrics.ascent()),
                                (self._lo, self.height() - metrics.descent())):
            if any(abs(pm - meters) < 0.03 for pm in self._presets.values()):
                continue
            label = fmt_height_value(meters, trim=True) + suffix_height()
            painter.drawText(QPointF(self.width() - metrics.horizontalAdvance(label),
                               label_y), label)

        live_shown = False
        for name, meters in sorted(self._presets.items(),
                                   key=lambda kv: -kv[1]):
            tick_y = self._y(meters)
            at_preset = (self._height > 0
                  and abs(meters - self._height) <= self.MATCH)
            color = tokens.accent_text if at_preset else tokens.muted
            painter.setPen(QPen(tokens.accent if at_preset else tokens.muted, 2))
            painter.drawLine(QPointF(track_x - 4, tick_y), QPointF(track_x + 4, tick_y))
            painter.setFont(bold if at_preset else small)
            painter.setPen(color)
            text = (f"{name} · {fmt_height_value(meters)}" if at_preset else name)
            painter.drawText(QPointF(track_x + 9, tick_y + painter.fontMetrics().ascent() / 2 - 1),
                       text)
            live_shown = live_shown or at_preset

        if self._height > 0 and not live_shown:
            tick_y = self._y(self._height)
            painter.setPen(QPen(tokens.accent, 2))
            painter.drawLine(QPointF(track_x - 5, tick_y), QPointF(track_x + 5, tick_y))
            painter.setFont(bold)
            painter.setPen(tokens.accent_text)
            painter.drawText(QPointF(track_x + 9, tick_y + painter.fontMetrics().ascent() / 2 - 1),
                       fmt_height_value(self._height))
        painter.end()


class DailyBarsChart(QWidget):
    """14 horizontal stacked duration bars (sitting neutral, standing
    accent-blue), scaled to the longest day. Neutral-vs-accent is the
    mock's deliberate encoding: identity is carried by the legend, the
    fixed segment order and the share labels, not by hue alone."""

    ROW_H = 20
    BAR_H = 12
    LABEL_W = 56
    SHARE_W = 44
    GAP = 2          # surface gap between the stacked segments

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # rows: (label, sit_seconds, stand_seconds, is_today)
        self._rows: list[tuple[str, float, float, bool]] = []
        self.setMouseTracking(True)

    # Already scheme-aware (branches on is_dark below) and called from
    # paintEvent, so it re-derives on every repaint without needing the
    # restyle registry -- exempt from the sweep, not overlooked.
    @staticmethod
    def series_colors() -> tuple:
        tokens = theme()
        if tokens.is_dark:
            return QColor("#5a6068"), QColor("#6ba7dd")
        return QColor("#c5cdd6"), QColor("#5b9bd1")

    def set_rows(self, rows: list[tuple[str, float, float, bool]]) -> None:
        self._rows = rows
        self.setMinimumHeight(self.ROW_H * max(1, len(rows)))
        self.update()

    def _tooltip_for(self, index: int) -> str:
        from .util import fmt_hm
        label, sit, stand, _ = self._rows[index]
        return (f"{label}: sitting {fmt_hm(sit)}, standing {fmt_hm(stand)}"
                if sit or stand else f"{label}: no data")

    def mouseMoveEvent(self, event) -> None:  # pylint: disable=invalid-name
        from PySide6.QtWidgets import QToolTip
        index = int(event.position().y() // self.ROW_H)
        if 0 <= index < len(self._rows):
            QToolTip.showText(event.globalPosition().toPoint(),
                              self._tooltip_for(index), self)
        else:
            QToolTip.hideText()

    def paintEvent(self, event) -> None:  # pylint: disable=invalid-name
        tokens = theme()
        sit_color, stand_color = self.series_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = painter.font()
        small.setPointSizeF(small.pointSizeF() * 0.86)
        today_font = QFont(small)
        today_font.setWeight(QFont.Weight.DemiBold)

        left = self.LABEL_W + 8
        right = self.width() - self.SHARE_W - 8
        span = max(1, right - left)
        max_total = max((sit + stand for _, sit, stand, _ in self._rows),
                        default=0) or 1

        for i, (label, sit_seconds, stand, is_today) in enumerate(self._rows):
            bar_y = i * self.ROW_H + (self.ROW_H - self.BAR_H) / 2
            baseline = i * self.ROW_H + self.ROW_H / 2 \
                + painter.fontMetrics().ascent() / 2 - 1

            painter.setFont(today_font if is_today else small)
            painter.setPen(tokens.accent_text if is_today else tokens.secondary)
            painter.drawText(QPointF(4, baseline), label)

            sit_w = span * sit_seconds / max_total
            stand_w = span * stand / max_total
            painter.setPen(Qt.PenStyle.NoPen)
            if sit_w > 0:
                # Round the baseline (outer) end; the inner end facing the
                # gap stays square (rounded only when it's the whole bar).
                rect = QRectF(left, bar_y, sit_w, self.BAR_H)
                painter.setBrush(sit_color)
                self._draw_segment(painter, rect, round_left=True,
                                   round_right=stand_w <= 0)
            if stand_w > 0:
                stand_x = left + sit_w + (self.GAP if sit_w > 0 else 0)
                rect = QRectF(stand_x, bar_y, max(2.0, stand_w - self.GAP), self.BAR_H)
                painter.setBrush(stand_color)
                self._draw_segment(painter, rect, round_left=sit_w <= 0,
                                   round_right=True)

            total = sit_seconds + stand
            painter.setFont(small)
            painter.setPen(tokens.secondary if total else tokens.muted)
            share = f"{stand / total * 100:.0f}%" if total else "—"
            share_w = painter.fontMetrics().horizontalAdvance(share)
            painter.drawText(QPointF(self.width() - share_w - 2, baseline), share)
        painter.end()

    @staticmethod
    def _draw_segment(painter: QPainter, rect: QRectF, round_left: bool = False,
                      round_right: bool = False) -> None:
        radius = min(4.0, rect.width() / 2, rect.height() / 2)
        if radius < 0.75 or not (round_left or round_right):
            painter.drawRect(rect)
            return
        # Round all four corners, then square off whichever ends should
        # stay flat by overpainting them in the same brush. (Unioning a
        # rounded rect and a square into one filled path leaves an even-odd
        # sliver at the seam.)
        painter.drawRoundedRect(rect, radius, radius)
        if not round_left:
            painter.drawRect(QRectF(rect.x(), rect.y(), radius, rect.height()))
        if not round_right:
            painter.drawRect(QRectF(rect.right() - radius, rect.y(),
                              radius, rect.height()))


class ToolIconButton(QPushButton):
    """28px ghost icon button used in list rows (Presets). ``fallback``
    is a short text glyph shown when the icon theme resolves nothing
    (headless / minimal sessions), so the buttons never go blank."""

    def __init__(self, preferred_icon: QIcon, tooltip: str, fallback: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        if preferred_icon.isNull() and fallback:
            self.setText(fallback)
        else:
            self.setIcon(preferred_icon)
        self.setIconSize(QSize(16, 16))
        self.setFixedSize(28, 28)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        restyle.register(self, self._restyle)

    def _restyle(self) -> None:
        tokens = theme()
        self.setStyleSheet(
            f"QPushButton {{ background: transparent;"
            f" border: 1px solid {css(tokens.separator)};"
            f" border-radius: {CONTROL_RADIUS}px; }}"
            f"QPushButton:hover {{ background: {css(tokens.hover)};"
            f" border-color: {css(tokens.border)}; }}")
