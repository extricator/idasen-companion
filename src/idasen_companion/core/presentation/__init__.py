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
``NAV_ITEMS``, ``gui/util.py`` and ``gui/background_portal.py``, and now
also at ``.register``, this package's own gettext-flavour register — with
formatters referencing the register's names rather than writing string
literals inline. A literal marked with ``.register``'s ``N_``/``NP_`` is
reachable because ``scripts/build-translations.sh``'s extraction scope
covers the whole package except ``gui/``; ``tests/test_extraction_scope.py``
enforces that every marked literal outside ``gui/`` actually landed in the
regenerated ``.pot``, so a marker call added somewhere that scope doesn't
reach fails the suite instead of shipping untranslated with nothing to
notice.

Nothing is exported here. Callers import the sibling modules
(``.protocols``, ``.specs``, ``.formatter``) directly by module path, so
this file is written once, in this plan, and stays free of re-exports for
the rest of the phase — later plans in the same wave add sibling modules
without needing to touch this one.
"""
