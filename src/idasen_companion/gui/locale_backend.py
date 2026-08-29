"""The Qt half of the presentation seam.

Wraps ``QLocale``'s own value-to-string conversions and Qt's own translate
call, nothing else. A surface backend may decide how an atomic value is
rendered; it may not decide product formatting policy -- that boundary, and
everything on the policy side of it, belongs to ``core/units.py`` (plan
12-03), not here.

Lives under ``gui/``, never under ``core/``: it imports Qt, and the
dependency rule this project follows is one-directional -- ``gui``/
``daemon`` -> ``core`` -> nothing. ``core/presentation/protocols.py``
declares the two capability protocols this module implements structurally
(``LocaleFormatter``, ``Translator``); nothing here inherits from either --
Python's structural typing (``runtime_checkable``) is the whole contract.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QCoreApplication, QDate, QLocale, QTime

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
        ``QLocale`` offers no padded-integer overload, and this is what
        reproduces the zero-padded minutes
        (``core/presentation/formatter.py``'s ``duration_hm``, e.g.
        "1h 05m") exactly. It is a mechanism choice, not a policy one.
        Grouping, where ``spec`` asks for it, still goes through the
        locale.
        """
        value = int(value)
        rendered = (QLocale(self._locale).toString(value)
                    if spec.grouping else f"{value:d}")
        return rendered.rjust(spec.min_digits, "0")

    def time(self, value: datetime, style: TimeStyle) -> str:
        """A wall-clock time on the clock the style names.

        The explicit patterns below deliberately bypass Qt's short-time
        format, which picks the twelve-or-twenty-four answer out of the
        locale — the very choice this app now makes once, in ``core/``,
        from ``[ui] clock_format``. Asking the locale again here would let
        the window disagree with the setting.
        """
        if style is TimeStyle.HOUR_AND_MINUTE:
            return self._locale.toString(
                QTime(value.hour, value.minute),
                QLocale.FormatType.ShortFormat)
        moment = QTime(value.hour, value.minute, value.second)
        if style is TimeStyle.HOUR_AND_MINUTE_24:
            return self._locale.toString(moment, "HH:mm")
        if style is TimeStyle.HOUR_AND_MINUTE_12:
            return self._locale.toString(moment, "h:mm AP")
        if style is TimeStyle.HOUR_MINUTE_AND_SECOND_24:
            return self._locale.toString(moment, "HH:mm:ss")
        if style is TimeStyle.HOUR_MINUTE_AND_SECOND_12:
            return self._locale.toString(moment, "h:mm:ss AP")
        raise ValueError(f"unsupported time style: {style!r}")

    def date(self, value: datetime, style: DateStyle) -> str:
        moment = QDate(value.year, value.month, value.day)
        if style is DateStyle.WEEKDAY_AND_DAY:
            return self._locale.toString(moment, "ddd dd")
        if style is DateStyle.WEEKDAY_DAY_MONTH_YEAR:
            return self._locale.toString(moment, "ddd dd MMM yyyy")
        raise ValueError(f"unsupported date style: {style!r}")


class QtTranslator:
    """Looks a message up through Qt's own translate call.

    Takes its Qt translation context once, at construction, from a literal
    at the construction site -- never as a per-``message`` argument. Qt
    keys a translation on the pair of context and source text, and the
    context is a class or module name; a caller free to invent one per call
    could key into a context no catalog entry has ever used, which fails by
    silently falling back to the English source rather than by anything
    going red. Fixing it at construction is what keeps "renamed the class,
    forgot the catalog" a mistake ``lupdate``'s own extraction still
    catches, instead of one this backend could hide a second way.

    Raises nothing on a missing catalog entry, deliberately: Qt's own
    ``translate`` already degrades to the English source text, and
    wrapping it in a ``try``/``except`` here would only hide that.
    """

    def __init__(self, context: str) -> None:
        self._context = context

    def message(self, source: str, **values: object) -> str:
        rendered = QCoreApplication.translate(self._context, source)
        return rendered % values if values else rendered

    def plural(
            self, singular: str, plural: str, count: int,
            **values: object) -> str:
        """Looks up a plural message through Qt's ``%n`` mechanism.

        ``plural`` is deliberately unused. Qt encodes every numerus form
        under one ``%n``-bearing source entry rather than two separate
        literals, so there is no Qt counterpart for a second string the
        way gettext's ``ngettext(singular, plural, count)`` has one --
        ``singular`` is used as that one ``%n``-templated source, and the
        installed catalog's own numerus forms (or Qt's built-in fallback
        where none is installed) decide which form ``count`` selects.
        Consequently, a source handed to this method must carry ``%n``,
        and the register's gettext-shaped ``%d`` pairs (D-06) are not
        usable through this backend.
        """
        rendered = QCoreApplication.translate(
            self._context, singular, None, count)
        return rendered % values if values else rendered
