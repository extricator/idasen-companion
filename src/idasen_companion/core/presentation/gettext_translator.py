"""The Qt-free :class:`Translator` backend, delegating to the gettext catalog.

Everything a Qt-free caller under ``core/presentation/`` needs to look up a
message already lives in :mod:`idasen_companion.core.i18n` — the one process
current gettext catalog, bound by ``set_language()``. This module is the
:class:`~idasen_companion.core.presentation.protocols.Translator`
implementation that reaches for it.

**The PRES-02 exemption, named here.** PRES-02 forbids a function under
``core/presentation/`` from resolving language, locale or unit for itself —
each capability must arrive as an argument or on an injected context, never
read from a module global. ``GettextTranslator`` is the single, deliberate
exception: gettext is designed around exactly one current catalog per
process, so wrapping it in the ``Translator`` protocol necessarily means
delegating to that process-wide state rather than threading a catalog
object through every call. The failure PRES-02 exists to prevent is a
*formatter* reading a startup-set global from a code path that runs
*before* startup binds it — a value silently frozen wrong. That is a
different shape from a translator backend delegating, on every call, to
the catalog it exists to wrap: there is no earlier value to freeze, and a
later ``set_language()`` call is visible on the next lookup. A second
module under ``core/presentation/`` reaching for ``core.i18n``'s catalog
would not get this exemption; this is the one place it's granted. Both of
this class's lookups — the plain message and the plural selection — go
through this same exemption; it is one reason, covering both calls into
``core.i18n``, not two.
"""

from __future__ import annotations

from ..i18n import _, ngettext


class GettextTranslator:
    """Looks up a message through the process-wide gettext catalog."""

    def message(self, source: str, **values: object) -> str:
        text = _(source)  # exempt: the one process-wide catalog lookup
        return text % values if values else text

    def plural(self, singular: str, plural: str, count: int,
               **values: object) -> str:
        text = ngettext(singular, plural, count)  # exempt: see message()
        return text % values if values else text
