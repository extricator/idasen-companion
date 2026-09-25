"""Tests for the Qt-free ``Translator`` backend.

``GettextTranslator`` delegates to ``core/i18n.py``'s process-wide catalog
(the one named PRES-02 exemption); these tests bind and release that
catalog explicitly so no state leaks into other test modules.
"""

from __future__ import annotations

import pytest

from idasen_companion.core import i18n
from idasen_companion.core.i18n import (
    GettextTranslator,
)
from idasen_companion.core.i18n import Translator
from idasen_companion.core import i18n as register


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    i18n.set_language(i18n.SYSTEM)


def test_gettext_translator_satisfies_the_translator_protocol():
    assert isinstance(GettextTranslator(), Translator)


def test_message_with_no_catalog_installed_returns_the_source_unchanged():
    i18n.set_language(i18n.SYSTEM)
    translator = GettextTranslator()
    assert translator.message("Not a real catalog entry") == \
        "Not a real catalog entry"


def test_message_substitutes_named_values():
    i18n.set_language(i18n.SYSTEM)
    translator = GettextTranslator()
    assert translator.message("%(count)s items", count=3) == "3 items"


def test_message_returns_spanish_for_a_bound_catalog():
    i18n.set_language("es")
    translator = GettextTranslator()
    assert translator.message(register.MINUTES[0]) == "%d minuto"


def test_plural_selects_the_singular_form_under_the_untranslated_catalog():
    i18n.set_language(i18n.SYSTEM)
    translator = GettextTranslator()
    assert translator.plural("%d minute", "%d minutes", 1) == "%d minute"


def test_plural_selects_the_plural_form_under_the_untranslated_catalog():
    i18n.set_language(i18n.SYSTEM)
    translator = GettextTranslator()
    assert translator.plural("%d minute", "%d minutes", 2) == "%d minutes"
