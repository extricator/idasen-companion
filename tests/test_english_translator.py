"""Tests for the English-only :class:`Translator` backend.

``EnglishTranslator`` must never reach the process-wide gettext catalog —
that absence is checked here directly, by reading the module's own source
with `ast` and asserting no import names ``i18n``, rather than by comment,
since the absence is the decision D-03 makes (see the module docstring).
"""

from __future__ import annotations

import ast
from pathlib import Path

from idasen_companion.core.presentation.english import EnglishTranslator
from idasen_companion.core.presentation.protocols import Translator

MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "src" / "idasen_companion" / "core" / "presentation" / "english.py"
)


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


def test_the_module_imports_nothing_from_core_i18n():
    """The absence of a `core.i18n` import is the decision (D-03), so it
    gets an assertion rather than a comment."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.rsplit(".", maxsplit=1)[-1] == "i18n":
                offenders.append(f"line {node.lineno}: from {module} import ...")
            for alias in node.names:
                if alias.name == "i18n":
                    offenders.append(f"line {node.lineno}: from ... import i18n")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.rsplit(".", maxsplit=1)[-1] == "i18n":
                    offenders.append(f"line {node.lineno}: import {alias.name}")
    assert not offenders, offenders
