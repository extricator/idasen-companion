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


@dataclass(frozen=True)
class Theme:
    is_dark: bool
    window: QColor        # app background
    card_bg: QColor       # card surfaces
    sidebar_bg: QColor    # slightly darker than content
    text: QColor
    secondary: QColor
    muted: QColor
    border: QColor        # card / input borders
    separator: QColor     # row separators inside cards
    hover: QColor         # row hover highlight
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

    result = Theme(
        is_dark=is_dark,
        window=window,
        card_bg=base,
        sidebar_bg=_mix(window, text, 0.04),
        text=text,
        secondary=_mix(window, text, 0.72),
        muted=_mix(window, text, 0.52),
        border=_mix(base, text, 0.22),
        separator=_mix(base, text, 0.09),
        hover=_mix(base, text, 0.05),
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
