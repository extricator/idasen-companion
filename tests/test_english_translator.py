"""Tests for the English-only :class:`Translator` backend.

``EnglishTranslator`` returns source text directly, keeping stable journal
output independent from the process-wide gettext catalog.
"""

from __future__ import annotations

from idasen_companion.core.presentation import EnglishTranslator
from idasen_companion.core.i18n import Translator


def test_message_returns_the_source_unchanged():
    translator = EnglishTranslator()
    assert translator.message("Not a real catalog entry") == \
        "Not a real catalog entry"


def test_message_substitutes_named_values():
    translator = EnglishTranslator()
    assert translator.message("%(a)s cm", a="110.5") == "110.5 cm"


def test_plural_picks_the_singular_form_at_one():
    translator = EnglishTranslator()
    assert translator.plural("%d minute", "%d minutes", 1) == "%d minute"


def test_plural_picks_the_plural_form_at_zero():
    translator = EnglishTranslator()
    assert translator.plural("%d minute", "%d minutes", 0) == "%d minutes"


def test_plural_picks_the_plural_form_at_two():
    translator = EnglishTranslator()
    assert translator.plural("%d minute", "%d minutes", 2) == "%d minutes"


def test_plural_substitutes_named_values():
    translator = EnglishTranslator()
    rendered = translator.plural(
        "%(n)s item", "%(n)s items", 3, n=3)
    assert rendered == "3 items"


def test_english_translator_satisfies_the_translator_protocol():
    assert isinstance(EnglishTranslator(), Translator)
