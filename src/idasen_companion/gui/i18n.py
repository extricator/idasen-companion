"""Runtime translation loading for the GUI.

All user-facing GUI strings are wrapped in ``tr()`` /
``QCoreApplication.translate()``. This module installs the ``QTranslator``s
that make those calls resolve to the user's locale at startup:

- the **app catalog** — our own strings, compiled from
  ``translations/idasen_companion_<locale>.ts`` into ``.qm`` files shipped in
  ``gui/translations/`` (see ``scripts/build-translations.sh``);
- the **Qt base catalog** — Qt's own translations for standard widgets
  (dialog buttons, etc.), shipped with PySide6.

Everything degrades gracefully: a missing catalog just leaves the English
source strings in place, so the app is fully functional untranslated.

**The two catalogs, and the silent failure closed by ``apply_language``.**
``core/i18n.py`` binds its own process-wide gettext catalog at import time
from the POSIX environment (``set_language(SYSTEM)`` at that module's
bottom), while :func:`install_translators` here binds Qt's catalog from
``[ui] language``. Once the window renders shared messages through gettext
too, a ``[ui] language = "es"`` on an English desktop would otherwise render
half the window in each language, with both catalogs complete and no gate
red. :func:`apply_language` binds both from the one config value, at every
place the language is decided, so there is no second call to forget.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

from ..core.i18n import set_language

#: Base name of our compiled catalogs, e.g. ``idasen_companion_es.qm``.
CATALOG = "idasen_companion"

#: Directory holding the shipped ``.qm`` files (populated by the build).
TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"

#: Config value meaning "follow the desktop locale".
SYSTEM = "system"


def available_languages() -> list[str]:
    """Locale codes we ship a compiled ``.qm`` for (e.g. ``["es"]``), sorted.

    English is the source language and needs no catalog, so it isn't listed
    here — callers offer it (and "system") separately.
    """
    prefix = f"{CATALOG}_"
    return sorted(
        p.stem[len(prefix):]
        for p in TRANSLATIONS_DIR.glob(f"{prefix}*.qm")
    )


def language_display_name(code: str) -> str:
    """Human, self-named label for a locale code, e.g. ``es`` -> ``Español``."""
    loc = QLocale(code)
    name = (loc.nativeLanguageName() or "").strip()
    # Qt sometimes qualifies the endonym with a territory (notably the "es"
    # catalog -> "español de España"); show just the language in the menu.
    territory = loc.nativeTerritoryName()
    if territory and name.endswith(territory):
        name = name[: -len(territory)].rstrip()
        for connector in ("de", "del", "di", "do", "da"):
            if name.endswith(" " + connector):
                name = name[: -(len(connector) + 1)]
                break
        name = name.rstrip(" ,(").strip()
    return name[:1].upper() + name[1:] if name else code


def resolve_locale(language: str) -> QLocale:
    """Map a config ``language`` value to a QLocale (``"system"`` -> system)."""
    return QLocale.system() if language == SYSTEM else QLocale(language)


def install_translators(app, language: str = SYSTEM) -> list[QTranslator]:
    """Load and install translators for ``language`` (config value).

    ``"system"`` (default) follows the desktop locale; any other value is a
    catalog code like ``"es"``. Returns the installed translators, parented to
    ``app`` so they outlive this call — ``installTranslator`` does *not* take
    ownership, and a garbage-collected ``QTranslator`` silently stops
    translating.
    """
    locale = resolve_locale(language)
    # The config's language can differ from the desktop locale, so the
    # translators alone aren't enough to make native controls agree with the
    # words around them. App-owned labels use Babel's LocaleProfile; setting
    # QLocale here gives QDoubleSpinBox/QSpinBox/QTimeEdit the same locale for
    # their native editing behavior and supplies Qt's layout direction.
    QLocale.setDefault(locale)
    installed: list[QTranslator] = []

    # Qt's own catalog first, so our strings can override if ever needed.
    qt_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    qt_tr = QTranslator(app)
    if qt_tr.load(locale, "qtbase", "_", qt_dir):
        app.installTranslator(qt_tr)
        installed.append(qt_tr)

    app_tr = QTranslator(app)
    if app_tr.load(locale, CATALOG, "_", str(TRANSLATIONS_DIR)):
        app.installTranslator(app_tr)
        installed.append(app_tr)

    return installed


def apply_language(app, language: str = SYSTEM) -> list[QTranslator]:
    """Bind BOTH catalogs to ``language`` — the Qt catalog and the shared
    gettext catalog core-side code renders through.

    One call for one operation, so a place that decides the language cannot
    bind only one of the two catalogs by mistake — see the module docstring
    for the failure this closes. :func:`install_translators` keeps its own
    name and does only its own job — binding gettext there too would leave
    its name no longer describing what it does.
    """
    set_language(language)
    return install_translators(app, language)
