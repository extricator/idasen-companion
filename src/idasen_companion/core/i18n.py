"""The process-wide application message catalog.

GUI, daemon and CLI code all look up app-owned messages here: the stdlib
``gettext`` catalog compiled from
``po/<lang>.po`` into ``locale/<lang>/LC_MESSAGES/idasen_companion.mo`` (see
``scripts/build-translations.sh``). Today the only caller is the daemon,
translating its desktop **notifications** (pre-move warnings and their
action buttons).

Journald output stays English *at the source*, which is not
the same as untranslated. journald is kept stable and greppable because that
is what a bug report needs. Activity lines cross the wire as a catalogued id
plus raw parameters (``Log1.Entry``), and the GUI re-renders them in the
reader's language from ``gui/log_catalog.py`` — so the Activity Log translates
like every other string in the app. Only free-form *diagnostic* lines
(``RingLog.diag``) are English by design; see ``docs/LOGGING.md``.

The active language is set by ``set_language()`` from the ``[ui] language``
config value (the same setting the GUI uses): ``"system"`` follows the
environment (``LANGUAGE``/``LC_ALL``/``LC_MESSAGES``/``LANG``), anything else is
a catalog code like ``"es"``. The daemon calls it at startup and on config
hot-reload, so notifications localize even when the systemd user service didn't
inherit ``LANG``. ``fallback=True`` means a missing catalog yields the English
source strings, so a Qt-free caller runs fine untranslated. ``_``/``ngettext``
are stable module functions that delegate to the current catalog, so importers
(e.g. ``from ..core.i18n import _``) see language changes without
re-importing.

Every Qt-free caller reaches this catalog indirectly, through
``pgettext`` and ``npgettext`` provide semantic disambiguation without opaque
message ids.  All four lookup functions remain stable delegates, so a later
``set_language`` call is visible even to modules that imported them earlier.
"""

from __future__ import annotations

import gettext
from pathlib import Path

DOMAIN = "idasen_companion"
LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"
SYSTEM = "system"

_current: gettext.NullTranslations = gettext.NullTranslations()


def set_language(language: str = SYSTEM) -> None:
    """Bind the notification catalog to ``language`` (config value)."""
    global _current
    languages = None if language == SYSTEM else [language]
    _current = gettext.translation(DOMAIN, localedir=str(LOCALE_DIR),
                                   languages=languages, fallback=True)


def _(message: str) -> str:
    return _current.gettext(message)


def pgettext(context: str, message: str) -> str:
    return _current.pgettext(context, message)


def ngettext(singular: str, plural: str, count: int) -> str:
    return _current.ngettext(singular, plural, count)


def npgettext(context: str, singular: str, plural: str, count: int) -> str:
    return _current.npgettext(context, singular, plural, count)


def available_languages() -> list[str]:
    """Sorted language codes backed by an editable or compiled catalog."""
    po_dir = LOCALE_DIR.parents[2] / "po"
    languages = {path.stem for path in po_dir.glob("*.po")}
    languages.update(path.parent.parent.name
                     for path in LOCALE_DIR.glob("*/LC_MESSAGES/*.mo"))
    return sorted(languages)


# Default to the environment locale until a caller applies the config value.
set_language(SYSTEM)
