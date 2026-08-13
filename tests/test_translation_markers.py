"""Strings that `lupdate` cannot see ship untranslated, silently.

`gui/util.py` is imported before `main()` installs the QTranslator, so it
cannot call `tr()` at import time. Its strings are marked with
QT_TRANSLATE_NOOP and translated at each call through the module-private
`_tr()` — and a bare `_tr("literal")` hides that literal from `lupdate`
completely. Nothing fails: the build succeeds, the catalog ships, and the
string is simply never translated. `fmt_days`' empty case shipped that way.

This walks the source rather than the catalog, so it catches the mistake at
the point it is made instead of after a translator notices.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "idasen_companion"

#: Modules whose user-facing strings must be marked, not passed as literals.
#: Both wrap QCoreApplication.translate in a helper for the reason above.
MARKED_MODULES = [
    (SRC / "gui" / "util.py", "_tr"),
    (SRC / "gui" / "log_catalog.py", "_tr"),
]


def _wrapper_calls(tree, wrapper):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == wrapper
                and node.args):
            yield node


@pytest.mark.parametrize("path,wrapper", MARKED_MODULES,
                         ids=lambda v: getattr(v, "name", v))
def test_translation_wrappers_are_never_handed_a_bare_literal(path, wrapper):
    tree = ast.parse(path.read_text())
    offenders = [
        f"{path.name}:{call.lineno}: {wrapper}({ast.unparse(call.args[0])!s})"
        for call in _wrapper_calls(tree, wrapper)
        if isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ]
    assert not offenders, (
        "these strings are invisible to lupdate and will ship untranslated; "
        "mark them with QT_TRANSLATE_NOOP: " + "; ".join(offenders))


def test_qt_translate_noop_contexts_are_string_literals():
    """`QT_TRANSLATE_NOOP(_CONTEXT, "...")` extracts *nothing*, even with
    `_CONTEXT = "LogMessage"` on the line above — lupdate reads source text and
    does not resolve names. It once hid 64 of 67 new strings in log_catalog.py.
    """
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "QT_TRANSLATE_NOOP"
                    and node.args):
                continue
            context = node.args[0]
            if not (isinstance(context, ast.Constant)
                    and isinstance(context.value, str)):
                offenders.append(
                    f"{path.name}:{node.lineno}: context is "
                    f"{ast.unparse(context)}, not a literal")
    assert not offenders, "; ".join(offenders)
