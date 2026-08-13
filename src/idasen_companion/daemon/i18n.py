"""Runtime translation for the *daemon*'s user-facing strings.

The daemon is deliberately Qt-free, so it can't use Qt's ``tr()`` like the
GUI does. The only daemon strings a user actually reads are the desktop
**notifications** (pre-move warnings and their action buttons); those are
localized here with the stdlib ``gettext`` catalog compiled from
``po/<lang>.po`` into ``locale/<lang>/LC_MESSAGES/idasen_companion.mo`` (see
``scripts/build-translations.sh``).

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
source strings, so the daemon runs fine untranslated. ``_``/``ngettext`` are
stable module functions that delegate to the current catalog, so importers
(``from .i18n import _``) see language changes without re-importing.
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


# Default to the environment locale until the daemon applies the config value.
set_language(SYSTEM)


def human_delay(seconds: int) -> str:
    """A short, localized, correctly-pluralized delay for notifications.

    Unlike ``core.durations.format_duration_human`` (English, shared with the
    English-only journald/Activity-Log path), this renders through the
    ``gettext`` catalog so "2 minutes" / "30 seconds" translate.
    """
    if seconds >= 60:
        count = round(seconds / 60)
        return ngettext("%d minute", "%d minutes", count) % count
    count = max(1, seconds)
    return ngettext("%d second", "%d seconds", count) % count
