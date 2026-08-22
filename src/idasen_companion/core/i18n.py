"""Runtime translation machinery for Qt-free callers.

Qt-free code can't use Qt's ``tr()`` like the GUI does, so it looks up
messages here instead: the stdlib ``gettext`` catalog compiled from
``po/<lang>.po`` into ``locale/<lang>/LC_MESSAGES/idasen_companion.mo`` (see
``scripts/build-translations.sh``). Today the only caller is the daemon,
translating its desktop **notifications** (pre-move warnings and their
action buttons).

Everything else the daemon emits stays English *at the source*, which is not
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

``daemon/i18n.py``'s ``human_delay`` reaches this catalog indirectly, through
``core/presentation/gettext_translator.py``'s ``GettextTranslator`` — see that
module's docstring for the one deliberate exemption that lets a Translator
backend delegate to this process-wide state at all.
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


def ngettext(singular: str, plural: str, count: int) -> str:
    return _current.ngettext(singular, plural, count)


# Default to the environment locale until a caller applies the config value.
set_language(SYSTEM)
