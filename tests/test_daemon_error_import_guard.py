"""Nothing under ``daemon/`` may render a daemon error sentence.

The daemon raises ``DBusError`` with an English body that crosses the wire.
The sentence a user actually reads has to come from the *reader's* catalog,
keyed on the stable error name — render it daemon-side and a Spanish user
sees the daemon's language instead of their own, with a green build, a
shipped catalog and nothing anywhere to notice. Moving the table out of
``gui/`` and into ``core/presentation/`` is what lets the future CLI reach it
without a second copy, and it is also what makes that mistake newly
*reachable*: the daemon can import ``core/`` freely. A comment relies on a
future reader reading it; this fails the build instead.

Structural rather than runtime, following ``tests/test_qt_free_imports.py``:
importing ``daemon/main.py`` to watch what it pulls in is expensive and is
already done, for a different property, by that module's subprocess leg.
Reading the source answers this question directly.

Standard library and pytest only. The RPM's ``%check`` runs this suite from
an unpacked sdist, and the packaging manifest sweeps this directory but not
the repository's helper-program directory — a test that read a file from
there would die at collection inside the package build while every local run
passed, which has shipped once already.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "idasen_companion"
DAEMON_DIR = SRC / "daemon"

#: The module that owns the sentences, and the name it exposes.
_FORBIDDEN_MODULE = "daemon_errors"
_FORBIDDEN_NAME = "daemon_error_message"


def _daemon_sources():
    """Every ``*.py`` under ``daemon/``, walked rather than listed.

    A hardcoded module list would leave a daemon module added tomorrow
    uncovered on the day it is added, which is the day it is most likely to
    reach for something it shouldn't.
    """
    paths = sorted(DAEMON_DIR.rglob("*.py"))
    assert paths, f"no daemon sources found under {DAEMON_DIR}"
    return [(path, ast.parse(path.read_text(encoding="utf-8")))
            for path in paths]


def _imports_the_module(tree):
    """Every import in `tree` that names the sentence-owning module.

    Reads both spellings: a dotted ``import a.b.daemon_errors`` (or a
    ``from`` whose module path ends in it) and a relative
    ``from ..core.presentation import daemon_errors``, where the module name
    is an alias rather than part of the path.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _FORBIDDEN_MODULE in alias.name.split("."):
                    yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _FORBIDDEN_MODULE in module.split("."):
                yield node.lineno, module
            for alias in node.names:
                if alias.name == _FORBIDDEN_MODULE:
                    yield node.lineno, f"{module}.{alias.name}"


def _names_the_function(tree):
    """Every place `tree` writes the function's name.

    Attributes count, not only bare names: the shape worth catching is a
    future ``self.fmt.daemon_error_message(...)``, which no import check
    would ever see because the daemon legitimately holds a ``Formatter``.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == _FORBIDDEN_NAME:
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute) and node.attr == _FORBIDDEN_NAME:
            yield node.lineno, f".{node.attr}"
        elif isinstance(node, ast.alias) and node.name == _FORBIDDEN_NAME:
            yield getattr(node, "lineno", 0), node.name


def test_no_daemon_module_imports_the_daemon_error_sentences():
    offenders = [
        f"{path.relative_to(SRC)}:{lineno}: imports {what}"
        for path, tree in _daemon_sources()
        for lineno, what in _imports_the_module(tree)
    ]
    assert not offenders, (
        "the daemon must not import the D-Bus error sentences -- they are "
        "the reader's to render, from the reader's catalog, or a Spanish "
        "user reads the daemon's language: " + "; ".join(offenders))


def test_no_daemon_module_names_the_daemon_error_function():
    offenders = [
        f"{path.relative_to(SRC)}:{lineno}: names {what}"
        for path, tree in _daemon_sources()
        for lineno, what in _names_the_function(tree)
    ]
    assert not offenders, (
        "the daemon must not render a D-Bus error sentence, however it "
        "reaches the function -- an attribute access through its own "
        "Formatter counts: " + "; ".join(offenders))


def test_the_formatter_offers_no_door_to_the_daemon_error_sentences():
    """Every other word this phase moved got two doors: a plain function and
    a ``Formatter`` method. This one gets one. The daemon builds a
    ``Formatter`` from its own config, so a method here would put the table
    one attribute access away from the process that must never render it.
    """
    from idasen_companion.core.presentation.formatter import (  # pylint: disable=import-outside-toplevel
        Formatter,
    )

    assert not hasattr(Formatter, _FORBIDDEN_NAME), (
        "Formatter must not expose the daemon error sentences -- the daemon "
        "holds a Formatter, and this would be a second door to a table only "
        "a D-Bus *reader* may render")
