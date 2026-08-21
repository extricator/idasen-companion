"""The shared presentation layer: one formatter, injected capability backends.

This package is deliberately Qt-free and IO-free, like every other module
under :mod:`idasen_companion.core`. A surface backend — the window's
``QLocale``-backed one, or the plain Qt-free one a headless process uses —
may decide *how* an atomic value is rendered (which digits, which
separator) and *how* a message is looked up (which catalog, which
fallback). It may not independently decide *product formatting policy*:
which places show two decimals versus one, which duration splits at a
minute, which words a status renders as. That policy lives once, in the
formatters this package holds, not once per backend.

Every English message literal this app translates lives in a register of
marked constants — the pattern already used at ``gui/main_window.py``'s
``NAV_ITEMS``, ``gui/util.py`` and ``gui/background_portal.py`` — with
formatters referencing the register's names rather than writing string
literals inline. That register stays under ``gui/`` for the whole of this
phase and does not move here until Phase 13's commit that widens
``scripts/build-translations.sh``'s extraction scope in the same change.
Being early would open a window in which a literal under ``core/`` is
extracted by nothing and no completeness gate notices; being late is
harmless. This package therefore carries no translatable literal today —
no gettext lookup, no plural-selecting lookup, no register marker and no
Qt translation call anywhere under it.

Nothing is exported here. Callers import the sibling modules
(``.protocols``, ``.specs``, ``.formatter``) directly by module path, so
this file is written once, in this plan, and stays free of re-exports for
the rest of the phase — later plans in the same wave add sibling modules
without needing to touch this one.
"""
