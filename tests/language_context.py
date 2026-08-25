"""The one language-switching context manager the Qt-bearing tests share.

Installing a language is process-wide, two-catalog state: ``QLocale``'s
default, Qt's own ``QTranslator`` stack, and the gettext catalog
``core/i18n.py`` binds. Three test modules were each keeping their own copy
of the block that installs and unwinds all three, and the copies had already
drifted -- two of them leaked every ``QTranslator`` they installed for the
rest of the session, which CLAUDE.md's GUI-test rules name as a real hazard
(a Qt object collected after the offscreen platform is gone segfaults the
interpreter at exit, failing the RPM's ``%check`` with every test passing).

So this is the surviving copy, in the shape ``tests/test_sidebar_width.py``
had arrived at: it diffs the application's ``QTranslator`` children around
the block rather than trusting a pre-recorded list, so a translator some
*other* code installs mid-block (``AppContext.reload_config`` does) is
unwound too, and it destroys each one it removes rather than leaving it
parented to the session ``QApplication``.

Importing this module needs Qt, so it is for the Qt-bearing test modules
only. ``tests/presentation_samples.py`` is the Qt-free counterpart and must
stay that way -- do not reach for this module from there.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import shiboken6
from PySide6.QtCore import QCoreApplication, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from idasen_companion.core import i18n as core_i18n
from idasen_companion.gui import i18n

#: Every language a real install can be running in. English is the source
#: language and ships no compiled catalog, so the GUI's own enumeration does
#: not list it and each caller adds it -- the same way ``gui/pages/settings.py``
#: builds its own language menu, which is what makes a newly shipped catalog
#: covered by every loop below the day it lands rather than needing a second
#: edit (D-10).
SHIPPED_LANGUAGES: tuple[str, ...] = ("en", *i18n.available_languages())


def qt_locale_for(language: str) -> QLocale:
    """The ``QLocale`` a real run installs for a shipped language code.

    ``"en"`` resolves to ``en_US`` rather than to a bare ``QLocale("en")``,
    which is what :func:`installed_language` binds as the default below, so
    a test constructing a ``QtLocaleFormatter`` directly and a test reading
    the process default agree on what "English" renders as.
    """
    return QLocale("en_US") if language == "en" else QLocale(language)


@contextmanager
def installed_language(language: str) -> Iterator[None]:
    """Install exactly what a real run installs for ``language``, then undo it.

    ``"en"`` needs no catalog -- it is the source language -- but still pins
    the default ``QLocale`` explicitly rather than trusting whatever the
    surrounding suite happened to leave behind, and binds gettext's own
    fallback, which is deterministic regardless of the surrounding process's
    environment in the way ``SYSTEM`` is not. Any other language goes through
    ``gui.i18n.apply_language``, the same call ``gui.main.main()`` makes at
    startup, so a test records what that install actually ships rather than a
    hand-rolled approximation of it -- and ``apply_language`` rather than the
    bare ``install_translators`` because the shared presentation register
    renders through the gettext catalog, not the Qt one, so binding only the
    Qt translators would leave those renderings in English regardless of
    ``language``.

    The teardown diffs the application's translators rather than unwinding a
    list captured before the block: a translator installed mid-block by
    something other than this call would otherwise survive it. Each one is
    destroyed, not merely removed.
    """
    app = QApplication.instance()
    previous_locale = QLocale()
    before = set(app.findChildren(QTranslator))
    if language == "en":
        QLocale.setDefault(qt_locale_for("en"))
        core_i18n.set_language("en")
    else:
        i18n.apply_language(app, language)
    try:
        yield
    finally:
        after = set(app.findChildren(QTranslator))
        for translator in after - before:
            QCoreApplication.removeTranslator(translator)
            shiboken6.delete(translator)
        QLocale.setDefault(previous_locale)
        core_i18n.set_language(core_i18n.SYSTEM)
