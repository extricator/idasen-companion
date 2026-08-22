"""The gettext-flavour register of marked translatable constants.

The pattern already used at ``gui/main_window.py``'s ``NAV_ITEMS``,
``gui/util.py`` and ``gui/background_portal.py``: every translatable
literal lives once, as a module-level constant marked for extraction, and
a formatter references the constant's name rather than writing a string
literal inline. This module is that register for the code under
``core/`` — the half of the app that has no Qt translator to mark
literals with.

Two divergences from the Qt-flavour register are load-bearing.

**No context argument.** ``QT_TRANSLATE_NOOP`` takes a context name because
each ``.ts`` file keeps per-context sections; ``po/idasen_companion.pot`` is
one flat catalog with no such split, so there is nothing for a context
argument to select and :func:`N_`/:func:`NP_` take none.

**One call carries both plural forms.** :func:`NP_` takes the singular and
the plural literal together and returns them as a pair, so
``scripts/build-translations.sh``'s ``--keyword=NP_:1,2`` reads them as one
``(msgid, msgid_plural)`` entry from a single call site — unlike gettext's
own ``ngettext(singular, plural, count)``, which needs both literals again
at every *call*, this register needs them written down exactly once. This
matches Phase 12 D-02's already-committed register shape.

Do not import these markers from ``core/i18n.py`` — that module is the
process-wide gettext lookup, not a place literals are declared, and this is
not the phase to give it that second job.
"""

from __future__ import annotations


def N_(source: str) -> str:  # pylint: disable=invalid-name  # gettext's own extraction-marker convention, not a project abbreviation
    """Mark ``source`` for extraction. Returns it unchanged."""
    return source


def NP_(singular: str, plural: str) -> tuple[str, str]:  # pylint: disable=invalid-name  # gettext's own extraction-marker convention, not a project abbreviation
    """Mark a plural pair for extraction. Returns the pair unchanged."""
    return singular, plural


#: A count of whole hours. Source strings carried over byte-identically from
#: ``daemon/i18n.py``'s pre-merge literals so the extracted msgids match what
#: ``po/es.po`` already holds.
HOURS = NP_("%d hour", "%d hours")

#: A count of whole minutes. Byte-identical to the existing msgid/msgid_plural
#: in ``po/es.po`` — see the module docstring above.
MINUTES = NP_("%d minute", "%d minutes")

#: A count of whole seconds. Byte-identical to the existing msgid/msgid_plural
#: in ``po/es.po`` — see the module docstring above.
SECONDS = NP_("%d second", "%d seconds")

#: Joins two already-whole, already-translated duration messages (an hours
#: message and a minutes message) into one sentence fragment, e.g.
#: "1 hour 5 minutes". Both %(hours)s and %(minutes)s are substituted as
#: complete translated values, never assembled fragments — see
#: ``core/presentation/formatter.py``'s ``Formatter.duration_verbose`` for
#: the caller and the reasoning that substitution is not a whole-message-rule
#: violation.
HOURS_AND_MINUTES = N_("%(hours)s %(minutes)s")

