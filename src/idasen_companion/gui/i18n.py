"""Bind app gettext and install Qt's standard-widget translations.

App-owned GUI strings use the same contextual gettext catalog as daemon and
shared code. Qt contributes only its prebuilt ``qtbase`` catalog for native
dialog buttons and other standard widget text. ``apply_language`` binds the
app catalog, sets the default ``QLocale`` for widget behavior/direction and
installs that Qtbase translator from one selected language.
"""

from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

from ..core.i18n import available_languages, set_language

#: Config value meaning "follow the desktop locale".
SYSTEM = "system"


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

    # Only Qt's own catalog is installed. App-owned strings use gettext.
    qt_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    qt_tr = QTranslator(app)
    if qt_tr.load(locale, "qtbase", "_", qt_dir):
        app.installTranslator(qt_tr)
        installed.append(qt_tr)

    return installed


def apply_language(app, language: str = SYSTEM) -> list[QTranslator]:
    """Bind app gettext and Qt widget locale/Qtbase from one config value."""
    set_language(language)
    return install_translators(app, language)
