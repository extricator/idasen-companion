"""Transitional Qt adapters for the presentation seam.

``QtLocaleFormatter`` converts a ``QLocale`` name into the application's
shared Babel-backed ``LocaleProfile``; it does not use Qt to render values.
``QtTranslator`` is a compatibility name that delegates app message lookup to
gettext until Phase 7 removes the adapter. Product formatting policy remains
in the shared core layer.

Lives under ``gui/``, never under ``core/``: it imports Qt, and the
dependency rule this project follows is one-directional -- ``gui``/
``daemon`` -> ``core`` -> nothing. ``core/presentation/protocols.py``
declares the capability protocols these adapters satisfy structurally.
"""

from __future__ import annotations

from PySide6.QtCore import QLocale

from ..core.i18n import npgettext, pgettext
from ..core.locale_profile import LocaleProfile


class QtLocaleFormatter(LocaleProfile):
    """Transitional adapter from a ``QLocale`` to the shared Babel profile."""

    def __init__(self, locale: QLocale) -> None:
        super().__init__(locale.name().replace("-", "_"))


class QtTranslator:
    """Compatibility adapter that now delegates app messages to gettext.

    Takes one semantic gettext context at construction. Missing entries fall
    back to the English source, matching the catalog's normal behavior.
    """

    def __init__(self, context: str) -> None:
        self._context = context

    def message(self, source: str, **values: object) -> str:
        rendered = pgettext(self._context, source)
        return rendered % values if values else rendered

    def plural(
            self, singular: str, plural: str, count: int,
            **values: object) -> str:
        """Look up a plural through gettext's contextual plural rule."""
        rendered = npgettext(self._context, singular, plural, count)
        return rendered % values if values else rendered
