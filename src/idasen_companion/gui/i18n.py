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
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

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
    # translators alone aren't enough to make numbers agree with the words
    # around them. Setting the default QLocale before anything else is built
    # is also what lets util.py — which has no access to config — read the
    # effective locale for QLocale()-based formatting, and what gives every
    # QDoubleSpinBox/QSpinBox/QTimeEdit its decimal separator for free (Qt
    # resolves a widget's locale from QLocale::default() at construction).
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
