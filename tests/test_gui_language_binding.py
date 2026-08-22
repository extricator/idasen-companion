"""``apply_language`` binds both catalogs from one config value.

Proves the silent-failure shape closed by ``gui/i18n.py``'s
``apply_language``: before it, a call site could bind Qt's catalog
(``install_translators``) without also binding the shared gettext catalog
``core/i18n.py`` owns, and a ``[ui] language`` different from the process
locale would render half the window in each language. One call here has to
move both.

Skipped where PySide6 is missing, and forces the offscreen platform before
any ``QtWidgets`` import -- see ``tests/test_settings_form.py`` for why both
matter.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import shiboken6  # noqa: E402
from PySide6.QtCore import QLocale  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core import i18n as core_i18n  # noqa: E402
from idasen_companion.gui.i18n import apply_language  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restore_gettext_language():
    """Undo this module's own gettext binding for later tests.

    ``core/i18n.py``'s catalog is a module global that outlives a single
    test; each test below removes its own installed ``QTranslator``s and
    resets the default ``QLocale`` itself, in its own ``finally``.
    """
    yield
    core_i18n.set_language(core_i18n.SYSTEM)


def test_apply_language_binds_the_gettext_catalog(qapp):
    installed = apply_language(qapp, "es")
    try:
        # A known po/es.po msgid -- proves core/i18n.py's catalog (which
        # QtTranslator never touches) is the one that moved.
        assert core_i18n._("Try now") == "Intentar ahora"
    finally:
        for translator in installed:
            qapp.removeTranslator(translator)
            shiboken6.delete(translator)
        QLocale.setDefault(QLocale("en_US"))


def test_apply_language_binds_the_qt_locale(qapp):
    installed = apply_language(qapp, "es")
    try:
        # Proves the same one call also moved Qt's side -- QLocale.setDefault
        # is what install_translators does today, unchanged by this plan.
        assert QLocale().name().startswith("es")
    finally:
        for translator in installed:
            qapp.removeTranslator(translator)
            shiboken6.delete(translator)
        QLocale.setDefault(QLocale("en_US"))


def test_apply_language_defaults_to_system(qapp):
    installed = apply_language(qapp)
    try:
        assert core_i18n._("Try now") == "Try now"
    finally:
        for translator in installed:
            qapp.removeTranslator(translator)
            shiboken6.delete(translator)
        QLocale.setDefault(QLocale("en_US"))
