"""``apply_language`` binds app gettext, QLocale and Qtbase together.

Proves a config language binds the app catalog and native Qt locale from one
call. Qt's translator is only the prebuilt Qtbase catalog; app messages never
depend on it.

Skipped where PySide6 is missing, and forces the offscreen platform before
any ``QtWidgets`` import -- see ``tests/test_settings_form.py`` for why both
matter.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402
from pathlib import Path  # noqa: E402

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import shiboken6  # noqa: E402
from PySide6.QtCore import QLocale, Qt  # noqa: E402
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
        # Qt's own translator never touches) is the one that moved.
        assert (core_i18n.pgettext("shared.presentation", "Try now")
                == "Intentar ahora")
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


def test_apply_language_sets_direction_from_locale_without_a_catalog(qapp):
    original_direction = qapp.layoutDirection()
    installed = apply_language(qapp, "ar_EG")
    try:
        assert qapp.layoutDirection() == Qt.LayoutDirection.RightToLeft
    finally:
        for translator in installed:
            qapp.removeTranslator(translator)
            shiboken6.delete(translator)
        qapp.setLayoutDirection(original_direction)
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


def test_available_languages_follows_po_and_mo_catalogs(tmp_path, monkeypatch):
    locale_dir = tmp_path / "repo/src/idasen_companion/locale"
    mo = locale_dir / "es/LC_MESSAGES/idasen_companion.mo"
    mo.parent.mkdir(parents=True)
    mo.write_bytes(b"compiled")
    po = tmp_path / "repo/po/fr.po"
    po.parent.mkdir(parents=True)
    po.write_text("", encoding="utf-8")
    monkeypatch.setattr(core_i18n, "LOCALE_DIR", Path(locale_dir))
    assert core_i18n.available_languages() == ["es", "fr"]
