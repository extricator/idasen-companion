"""The Qt half of the presentation seam.

Wraps ``QLocale``'s own value-to-string conversions -- nothing else. A
surface backend may decide how an atomic value is rendered; it may not
decide product formatting policy -- that boundary, and everything on the
policy side of it, belongs to ``core/units.py`` (plan 12-03), not here.

Lives under ``gui/``, never under ``core/``: it imports Qt, and the
dependency rule this project follows is one-directional -- ``gui``/
``daemon`` -> ``core`` -> nothing. ``core/presentation/protocols.py``
declares the capability protocol this module implements structurally
(``LocaleFormatter``); nothing here inherits from it -- Python's structural
typing (``runtime_checkable``) is the whole contract.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QLocale, QTime

from ..core.presentation.specs import (
    DateStyle, IntegerSpec, NumberSpec, TimeStyle,
)


class QtLocaleFormatter:
    """Renders atomic values through an injected ``QLocale``.

    The locale is taken at construction and copied into an instance
    attribute, never read from the process default inside a method -- a
    formatter built for one locale must not silently start answering for
    another because something elsewhere called ``QLocale.setDefault``.
    """

    def __init__(self, locale: QLocale) -> None:
        self._locale = QLocale(locale)

    def number(self, value: float, spec: NumberSpec) -> str:
        """A floating-point number at ``spec``'s decimal count.

        The whole-value trim is expressed as a *decimal count* handed to
        Qt's own conversion, never as character-stripping on the already
        formatted string -- a hand-rolled trim would risk the locale's own
        zero digit and decimal point for a non-Latin digit set, which Qt's
        conversion already gets right. Grouping is suppressed unless
        ``spec`` asks for it, on a locale copy so the instance's own locale
        is never mutated.
        """
        value = float(value)
        decimals = spec.decimals
        if spec.trim_trailing_zeroes and value == int(value):
            decimals = 0
        locale = QLocale(self._locale)
        if not spec.grouping:
            locale.setNumberOptions(
                locale.numberOptions()
                | QLocale.NumberOption.OmitGroupSeparator)
        return locale.toString(value, "f", decimals)

    def integer(self, value: int, spec: IntegerSpec) -> str:
        """A whole number, zero-padded to ``spec.min_digits``.

        The padding goes through Python's own formatting rather than Qt:
        ``QLocale`` offers no padded-integer overload, and today's
        hour/minute substitutions are plain Python integers padded the same
        way (``f"{minutes:02d}"`` in ``gui/util.py``'s ``fmt_hm``) -- so this
        is what reproduces current output exactly. It is a mechanism
        choice, not a policy one. Grouping, where ``spec`` asks for it,
        still goes through the locale.
        """
        value = int(value)
        rendered = (QLocale(self._locale).toString(value)
                    if spec.grouping else f"{value:d}")
        return rendered.rjust(spec.min_digits, "0")

    def time(self, value: datetime, style: TimeStyle) -> str:
        if style is TimeStyle.HOUR_AND_MINUTE:
            return self._locale.toString(
                QTime(value.hour, value.minute),
                QLocale.FormatType.ShortFormat)
        raise ValueError(f"unsupported time style: {style!r}")

    def date(self, value: datetime, style: DateStyle) -> str:
        moment = QDate(value.year, value.month, value.day)
        if style is DateStyle.WEEKDAY_AND_DAY:
            return self._locale.toString(moment, "ddd dd")
        if style is DateStyle.WEEKDAY_DAY_MONTH_YEAR:
            return self._locale.toString(moment, "ddd dd MMM yyyy")
        raise ValueError(f"unsupported date style: {style!r}")
