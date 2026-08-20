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


def _reaches_tr(tree):
    """Module-level function names in `tree` whose body reaches `_tr()`,
    directly or through another module-level function that already reaches
    it. Walks each function's whole body with `ast.walk`, so a call made
    from inside a nested `FunctionDef` or `Lambda` counts too -- a future
    helper cannot evade this by tucking its `_tr()` call inside a closure.
    `_tr` itself is never included in the result.
    """
    functions = {node.name: node for node in tree.body
                 if isinstance(node, ast.FunctionDef)}

    def _called_names(node):
        return {call.func.id for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)}

    calls = {name: _called_names(node) for name, node in functions.items()}
    reached = {name for name, called in calls.items() if "_tr" in called}
    changed = True
    while changed:
        changed = False
        for name, called in calls.items():
            if name not in reached and called & reached:
                reached.add(name)
                changed = True
    return reached - {"_tr"}


# ---- Unit tests for the reachability rule itself ------------------------
# Synthetic snippets, so the rule is provable independently of what
# gui/util.py happens to contain today.

def test_a_direct_tr_call_reaches_tr():
    tree = ast.parse("def f():\n    return _tr('x')\n")
    assert _reaches_tr(tree) == {"f"}


def test_a_call_through_a_second_function_reaches_tr():
    tree = ast.parse(
        "def f():\n    return _tr('x')\n"
        "def g():\n    return f()\n")
    assert _reaches_tr(tree) == {"f", "g"}


def test_a_call_made_inside_a_nested_closure_reaches_tr():
    tree = ast.parse(
        "def f():\n"
        "    def inner():\n"
        "        return _tr('x')\n"
        "    return inner()\n")
    assert _reaches_tr(tree) == {"f"}


def test_a_function_reaching_neither_does_not_reach_tr():
    tree = ast.parse("def f():\n    return 1\n")
    assert _reaches_tr(tree) == set()


# ---- Integration test against the real module ----------------------------

def test_util_helpers_that_reach_tr_carry_the_mark():
    """A `gui/util.py` helper gains a translated string, nobody decorates it
    with `@returns_translated`, and the concatenation check this registry
    feeds goes quietly blind at every call site that glues its result to
    something else -- the mark stops meaning what it says without the
    build failing anywhere. This holds the marked set against the module's
    own call graph in both directions: a name that reaches `_tr()` without
    the mark is a helper the concatenation check would not recognise, and a
    marked name that does not reach `_tr()` is a locale formatter that would
    make the check flag legitimate composition.

    `RETURNS_TRANSLATED` is imported inside the test body, not at module
    scope -- `gui/util.py` imports `PySide6.QtCore`, and a module-scope
    import would take the two pure-AST checks above down with it in an
    environment without PySide6.
    """
    from idasen_companion.gui.util import (  # pylint: disable=import-outside-toplevel
        RETURNS_TRANSLATED,
    )

    path = SRC / "gui" / "util.py"
    tree = ast.parse(path.read_text())
    reaches_tr = _reaches_tr(tree)

    missing_mark = reaches_tr - RETURNS_TRANSLATED
    spurious_mark = RETURNS_TRANSLATED - reaches_tr
    assert not missing_mark, (
        "these gui/util.py helpers reach _tr() but carry no "
        "@returns_translated mark -- the concatenation check would not "
        f"recognise their result as translated text: {sorted(missing_mark)}")
    assert not spurious_mark, (
        "these gui/util.py names carry @returns_translated but do not "
        "reach _tr() -- they are locale formatters, and marking them would "
        f"make the concatenation check flag legitimate composition: "
        f"{sorted(spurious_mark)}")
