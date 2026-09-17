"""Transitional Qt adapters for the presentation seam.

``QtLocaleFormatter`` converts a ``QLocale`` name into the application's
shared Babel-backed ``LocaleProfile``; it does not use Qt to render values.
``QtTranslator`` retains Qt catalog lookup until the catalog consolidation
phase. Product formatting policy remains in the shared core layer.

Lives under ``gui/``, never under ``core/``: it imports Qt, and the
dependency rule this project follows is one-directional -- ``gui``/
``daemon`` -> ``core`` -> nothing. ``core/presentation/protocols.py``
declares the capability protocols these adapters satisfy structurally.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QLocale

from ..core.locale_profile import LocaleProfile


class QtLocaleFormatter(LocaleProfile):
    """Transitional adapter from a ``QLocale`` to the shared Babel profile."""

    def __init__(self, locale: QLocale) -> None:
        super().__init__(locale.name().replace("-", "_"))


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
