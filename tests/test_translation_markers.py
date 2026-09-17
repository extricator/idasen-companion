"""Deferred gettext wrappers remain extractable and whole-message safe."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "idasen_companion"

#: Modules whose user-facing strings must be marked, not passed as literals.
#: Both translate deferred ``P_`` keys through a small helper.
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
        "these deferred literals bypass P_ and will ship untranslated: "
        + "; ".join(offenders))


def test_no_qt_app_translation_markers_remain():
    """Qtbase is runtime-only; every app-owned marker belongs to gettext."""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "QT_TRANSLATE_NOOP"
                    and node.args):
                continue
            offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, "Qt app translation markers remain: " + "; ".join(offenders)


def test_no_qobject_or_qcore_app_lookup_remains():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "tr":
                offenders.append(f"{path.name}:{node.lineno}: QObject.tr")
            if (isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "QCoreApplication"
                    and node.func.attr == "translate"):
                offenders.append(
                    f"{path.name}:{node.lineno}: QCoreApplication.translate")
    assert not offenders, "; ".join(offenders)


def _markable_definitions(tree):
    """`{name: definition node}` for everything in `tree` that could carry
    the mark: a `def` or `async def` at module level or in a class body, and
    a name bound to a `lambda` in either place.

    Reading `tree.body` filtered to `ast.FunctionDef` would see only the
    first of those four. The other three are not hypothetical shapes -- the
    sibling `_tr` module `gui/log_catalog.py` already builds its formatter
    table out of module-level lambdas that call `_tr` -- and a helper
    written any of those ways would be asked for no mark, which is the
    silent blinding of the concatenation check that this guard exists to
    prevent.

    A nested definition is deliberately absent: it is reached through its
    enclosing definition's own body, and a name that only exists while its
    enclosing call runs cannot carry a registry entry anyway.
    """
    definitions = {}

    def collect(body):
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions[stmt.name] = stmt
            elif isinstance(stmt, ast.ClassDef):
                collect(stmt.body)
            elif isinstance(stmt, ast.Assign) and isinstance(stmt.value,
                                                             ast.Lambda):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        definitions[target.id] = stmt.value

    collect(tree.body)
    return definitions


def _lambda_definitions(tree):
    """The subset of :func:`_markable_definitions` bound to a `lambda`.

    A lambda takes no decorator, so a lambda that reaches `_tr()` cannot be
    marked where it is written and has to become a `def` first. Kept apart
    from the rest so the guard can say that, rather than asking for a mark
    that cannot be applied.
    """
    return {name for name, node in _markable_definitions(tree).items()
            if isinstance(node, ast.Lambda)}


#: The calls that count as reaching a translator directly. `gui/util.py` has
#: three ways to ask for translated text: the module-private wrapper; the
#: shared presentation layer's Qt-free translator backend, which a forwarder
#: constructs on the spot and hands to `core/presentation/words.py`; and a
#: `Formatter` the *caller* supplies, whose message-rendering methods reach
#: that same backend. Each such forwarder's return value is still translated
#: text -- it is simply looked up one layer further down -- so it must keep
#: its mark, and this seed set is what lets it. Deleting the mark to make the
#: check agree is forbidden; widening the seed is the correction.
#:
#: The `Formatter` entries are the message-rendering methods `gui/util.py`
#: actually reaches. They resolve by attribute name alone, so an unrelated
#: method of the same name would over-reach and ask for a mark that was not
#: needed -- a loud failure at the definition, which is the trade this whole
#: rule already documents.
#: Attribute names that *are* a translator when read, rather than names that
#: return one when called. A helper taking `fmt` and passing
#: `fmt.context.translator` down constructs nothing, so the call-name walk
#: sees no seed and would call the helper's mark spurious -- which is exactly
#: what happened when gui/util.py's fmt_countdown stopped building its own
#: backend. Structural rather than a second hand-list.
_TRANSLATOR_ATTRIBUTES = frozenset({"translator"})

_TRANSLATOR_SEEDS = frozenset({
    "_tr", "GettextTranslator",
    "day_and_clock", "snooze_line", "later_label",
})


def _reaches_tr(tree):
    """Names in `tree` that can carry the mark and whose body reaches
    a translator, directly or through another such name.

    Walks each definition's whole body with `ast.walk`, so a call made from
    inside a nested `FunctionDef` or `Lambda` counts too -- a future helper
    cannot evade this by tucking its `_tr()` call inside a closure. A call
    written as an attribute counts by its attribute name, so a method
    reaching `_tr()` through a sibling method is caught; that resolves by
    name alone and can over-reach, which asks for a mark that was not needed
    -- a loud failure at the definition, not a silent one at a call site.
    `_tr` itself is never included in the result.
    """
    definitions = _markable_definitions(tree)

    def _called_names(node):
        names = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    names.add(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    names.add(child.func.attr)
            # A translator handed *in* rather than constructed. Reading
            # `fmt.context.translator` and passing it on is the same reach as
            # calling GettextTranslator(), and it is a call to nothing, so the
            # call-name walk above cannot see it. This is structural -- any
            # attribute named `translator`, from any object -- so a helper
            # that switches to the injected form stays caught without anyone
            # remembering to add its name to the seed set.
            elif (isinstance(child, ast.Attribute)
                    and child.attr in _TRANSLATOR_ATTRIBUTES):
                names.add(child.attr)
        return names

    calls = {name: _called_names(node) for name, node in definitions.items()}
    seeds = _TRANSLATOR_SEEDS | _TRANSLATOR_ATTRIBUTES
    reached = {name for name, called in calls.items()
               if called & seeds}
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

def test_an_injected_translator_reaches_tr():
    """A helper handed a translator reaches one as surely as a helper that
    builds one.

    This is the shape gui/util.py's fmt_countdown moved to when it stopped
    constructing its own backend: it calls no translator factory, so a
    call-name-only walk saw nothing and called its mark spurious. Nothing
    was mis-translated -- but the concatenation check had quietly stopped
    following its result.
    """
    tree = ast.parse(
        "def f(fmt, x):\n"
        "    return words.thing(fmt.context.translator, x)\n")
    assert _reaches_tr(tree) == {"f"}


def test_a_locale_only_helper_does_not_reach_tr():
    """The other half of the rule: reading `.locale` off the same object is
    not reaching a translator, and marking such a helper would make the
    concatenation check flag legitimate composition."""
    tree = ast.parse(
        "def f(fmt, x):\n"
        "    return dates.day_short(fmt.context.locale, x)\n")
    assert _reaches_tr(tree) == set()


def test_a_direct_tr_call_reaches_tr():
    tree = ast.parse("def f():\n    return _tr('x')\n")
    assert _reaches_tr(tree) == {"f"}


def test_a_call_through_a_second_function_reaches_tr():
    tree = ast.parse(
        "def f():\n    return _tr('x')\n"
        "def g():\n    return f()\n")
    assert _reaches_tr(tree) == {"f", "g"}


def test_a_forwarder_constructing_the_gettext_translator_reaches_tr():
    """A `gui/util.py` forwarder that delegates the word itself to
    `core/presentation/` no longer calls the module-private wrapper -- it
    builds the Qt-free translator backend and hands it over. Its result is
    still translated text, so it must still be seen to reach a translator.
    """
    tree = ast.parse(
        "def f(key):\n"
        "    return words.connection_phrases(GettextTranslator(), key)\n")
    assert _reaches_tr(tree) == {"f"}


def test_a_forwarder_delegating_to_a_supplied_formatter_reaches_tr():
    """A `gui/util.py` forwarder that takes a `Formatter` and asks it for a
    whole message reaches a translator through it -- the caller supplied the
    translator instead of the forwarder constructing one, and the result is
    translated text either way.
    """
    tree = ast.parse(
        "def f(fmt, when):\n"
        "    return fmt.day_and_clock(when)\n")
    assert _reaches_tr(tree) == {"f"}


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


def test_an_async_definition_reaches_tr():
    tree = ast.parse("async def f():\n    return _tr('x')\n")
    assert _reaches_tr(tree) == {"f"}


def test_a_method_reaches_tr():
    tree = ast.parse("class C:\n    def f(self):\n        return _tr('x')\n")
    assert _reaches_tr(tree) == {"f"}


def test_a_method_calling_a_sibling_method_reaches_tr():
    tree = ast.parse(
        "class C:\n"
        "    def f(self):\n        return _tr('x')\n"
        "    def g(self):\n        return self.f()\n")
    assert _reaches_tr(tree) == {"f", "g"}


def test_a_name_bound_to_a_lambda_reaches_tr():
    tree = ast.parse("g = lambda k: _tr(k)\n")
    assert _reaches_tr(tree) == {"g"}
    assert _lambda_definitions(tree) == {"g"}


def test_a_def_is_not_reported_as_undecoratable():
    tree = ast.parse("def f():\n    return _tr('x')\n")
    assert _lambda_definitions(tree) == set()


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

    undecoratable = reaches_tr & _lambda_definitions(tree)
    assert not undecoratable, (
        "these gui/util.py names are bound to a lambda that reaches _tr() -- "
        "a lambda takes no decorator, so it cannot carry the mark where it "
        "is written; give it a def instead: " + str(sorted(undecoratable)))
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


# ---------------------------------------------------------------------------
# A sentence assembled from translated pieces is a sentence no translator can
# reorder, and the two halves ship looking fine in English -- the parts read
# naturally next to each other in the language they were written in, and
# nothing fails: the build succeeds, the catalog ships, and only a language
# whose word order or agreement differs discovers the seam. `fmt_days`'
# empty case above is the same failure shape one level up: a string invisible
# to `lupdate`. This is a string visible to `lupdate` but glued to something
# else, which is just as unreviewable by a translator working message by
# message.
#
# What this reads: a "translated value" is a call to one of the translation
# entry points named in `_TRANSLATING_CALLS`, or a call to a name in the
# caller-supplied marked set (`gui/util.py`'s `RETURNS_TRANSLATED`, so a
# helper's result counts the same as a direct call). Either counts whether it
# is written as a bare name or as an attribute of the module it lives in.
# A value glued with `+`, interpolated into an f-string, or handed to
# `.join()` is flagged; a translated template substituted with `%` is not --
# that is the shape every conversion in this phase converts *to*, not a
# glue. Accumulating with `+=` is the same glue written as a statement, and
# reads the same way.
#
# Every scope is read, not only function bodies: a module-level constant is
# this project's house style for a string that has to exist before the
# translator is installed, so module and class bodies are where a future glue
# would land rather than somewhere it cannot.
#
# It does not follow a value into or out of a function. Resolution stops at
# the boundary of the enclosing scope: a name is traced back only to an
# assignment (or `.append()`/`.extend()` accumulation, for a join) inside
# the same scope, and a value arriving through a parameter or a different
# file is invisible by construction. Stacking whole lines through a helper
# that *returns* a joined string is therefore out of this check's reach on
# purpose -- interprocedural tracing would mean reading every helper's own
# body to know whether its return value is "translated," which is exactly
# the analysis `RETURNS_TRANSLATED` already does once, by hand, at each
# helper's own definition. This is why the tray tooltip's and the About
# page's newline joins (D-13) and the setup wizard's paragraph join need no
# exemption entry anywhere: their join arguments are method calls, not a
# name or a list literal this check traces into.
# ---------------------------------------------------------------------------

#: Every way the tree asks for a translated string: Qt's two, gettext's two,
#: and the module-private wrapper the two MARKED_MODULES above translate
#: through -- a helper in either of those is marked and so counts already,
#: but a glue written directly against the wrapper is not covered by that.
_TRANSLATING_CALLS = frozenset({"tr", "translate", "_", "ngettext", "_tr"})
_TRANSLATING_ATTRS = frozenset({"tr", "translate", "_tr"})


def _is_translated_call(node, marked):
    """Is `node` itself a call whose result is translated text.

    A marked helper counts whichever way it is called. Several files reach
    `gui/util.py` through the module object rather than importing each name,
    so reading only a bare `Name` here would leave the check blind at every
    call site that follows that local convention.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _TRANSLATING_CALLS or func.id in marked
    if isinstance(func, ast.Attribute):
        return func.attr in _TRANSLATING_ATTRS or func.attr in marked
    return False


def _unwrap_subscript(node):
    while isinstance(node, ast.Subscript):
        node = node.value
    return node


def _resolves_to_translated(node, marked, assigns, seen=frozenset()):
    """Does `node` -- possibly a `Name` bound earlier in the same function --
    evaluate to a translated value.

    Unwraps a `Subscript` down to its base, and an `IfExp` into both
    branches (either being translated is enough, since the check does not
    know which branch runs). A `%`-substitution of a translated template
    yields a translated value too, since the result is still translated
    text -- this is deliberately a pass-through, not a flagged shape; see
    the module-level note above for why `%` is exempt by design rather than
    by exemption. A bare `Name` resolves through every assignment made to it
    earlier in the enclosing function, including assignments in different
    branches of an `if`/`elif` chain -- only one branch runs, but statically
    either could have, which is how the Overview's status reason is bound
    across an eleven-branch chain before its one use.
    """
    node = _unwrap_subscript(node)
    if isinstance(node, ast.Call):
        return _is_translated_call(node, marked)
    if isinstance(node, ast.IfExp):
        return (_resolves_to_translated(node.body, marked, assigns, seen)
                or _resolves_to_translated(node.orelse, marked, assigns, seen))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return _resolves_to_translated(node.left, marked, assigns, seen)
    if isinstance(node, ast.Name):
        if node.id in seen:
            return False
        return any(
            _resolves_to_translated(value, marked, assigns, seen | {node.id})
            for value in assigns.get(node.id, ()))
    return False


def _join_arg_resolves(arg, marked, assigns, appends, extends, seen=frozenset()):
    """Does a `.join()` call's argument resolve to, or accumulate, a
    translated value.

    A list/tuple literal is translated if any element is; a comprehension is
    translated if its element expression is. A bare `Name` additionally
    resolves through `.append(...)`/`.extend(...)` calls onto it made
    earlier in the same function -- the shape `fmt_days` used to build its
    list before this phase converted it. Anything else -- in particular a
    call to some other method -- is left alone: tracing into a method's
    return value would need to read that method's whole body, which is
    exactly the per-definition marking `RETURNS_TRANSLATED` already does by
    hand, not something this check re-derives at every call site.
    """
    arg = _unwrap_subscript(arg)
    if isinstance(arg, (ast.List, ast.Tuple)):
        return any(_resolves_to_translated(elt, marked, assigns)
                   for elt in arg.elts)
    if isinstance(arg, (ast.ListComp, ast.GeneratorExp)):
        return _resolves_to_translated(arg.elt, marked, assigns)
    if isinstance(arg, ast.Name):
        if arg.id in seen:
            return False
        seen = seen | {arg.id}
        for value in assigns.get(arg.id, ()):
            if (_resolves_to_translated(value, marked, assigns)
                    or _join_arg_resolves(
                        value, marked, assigns, appends, extends, seen)):
                return True
        for value in appends.get(arg.id, ()):
            if _resolves_to_translated(value, marked, assigns):
                return True
        for value in extends.get(arg.id, ()):
            if _join_arg_resolves(value, marked, assigns, appends, extends, seen):
                return True
        return False
    return False


#: Every node that owns its own names, and so gets its own pass. A nested
#: one is skipped by the pass that encloses it rather than attributed to it.
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _scopes(tree):
    """The module, and every scope nested anywhere inside it.

    A module body and a class body are scanned as scopes of their own, not
    just walked past on the way to a function: a module-level constant is
    this project's house style for a string that has to exist before the
    translator is installed -- `gui/util.py` is built out of them and
    `gui/main_window.py` keeps its navigation labels that way -- so module
    scope is precisely where a future glue would land.
    """
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, _SCOPES):
            yield node


def _scope_body(scope):
    """`scope`'s body as a list. A lambda's body is a single expression."""
    body = scope.body
    return body if isinstance(body, list) else [body]


def _scope_bindings(scope):
    """{name: [assigned value expressions]}, and the same shape for every
    `.append(...)`/`.extend(...)` call onto a name, gathered from `scope`'s
    own body -- never descending into a nested scope, which owns its own
    names.

    An augmented assignment is recorded as one more value the name can hold,
    so a value accumulated onto stays resolvable afterwards. An unpacking
    records the whole right-hand side against each name it binds -- as
    precise as this check gets anywhere, since it already discards a
    subscript's index when resolving and so cannot tell which member of a
    returned tuple a name took.
    """
    assigns: dict[str, list] = {}
    appends: dict[str, list] = {}
    extends: dict[str, list] = {}

    def bind(target, value):
        if isinstance(target, ast.Name):
            assigns.setdefault(target.id, []).append(value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                bind(element, value)

    def visit(stmts):
        for stmt in stmts:
            if isinstance(stmt, _SCOPES):
                continue
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    bind(target, stmt.value)
            elif isinstance(stmt, ast.AugAssign):
                bind(stmt.target, stmt.value)
            elif (isinstance(stmt, ast.AnnAssign) and stmt.value is not None
                    and isinstance(stmt.target, ast.Name)):
                assigns.setdefault(stmt.target.id, []).append(stmt.value)
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if (isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.args):
                    name = call.func.value.id
                    if call.func.attr == "append":
                        appends.setdefault(name, []).append(call.args[0])
                    elif call.func.attr == "extend":
                        extends.setdefault(name, []).append(call.args[0])
            if isinstance(stmt, ast.Try):
                for handler in stmt.handlers:
                    visit(handler.body)
            for field in ("body", "orelse", "finalbody"):
                block = getattr(stmt, field, None)
                if isinstance(block, list):
                    visit(block)

    visit(_scope_body(scope))
    return assigns, appends, extends


def _own_body(scope):
    """Every node in `scope`'s body, skipping the contents of a nested
    scope -- each of those gets its own pass with its own names, so a node
    inside one must not be attributed to the enclosing scope's
    assignments."""
    stack = list(_scope_body(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, _SCOPES):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _glued_in_ast(tree, marked):
    """`[(lineno, shape, unparsed expression), ...]` for every translated
    value glued to something else anywhere in `tree`."""
    offenders = []
    for scope in _scopes(tree):
        assigns, appends, extends = _scope_bindings(scope)
        for node in _own_body(scope):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                if (_resolves_to_translated(node.left, marked, assigns)
                        or _resolves_to_translated(node.right, marked, assigns)):
                    offenders.append((node.lineno, "+", ast.unparse(node)))
            elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
                if (_resolves_to_translated(node.target, marked, assigns)
                        or _resolves_to_translated(node.value, marked, assigns)):
                    offenders.append((node.lineno, "+=", ast.unparse(node)))
            elif isinstance(node, ast.JoinedStr):
                if any(isinstance(value, ast.FormattedValue)
                       and _resolves_to_translated(value.value, marked, assigns)
                       for value in node.values):
                    offenders.append(
                        (node.lineno, "f-string", ast.unparse(node)))
            elif (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "join" and node.args
                    and _join_arg_resolves(
                        node.args[0], marked, assigns, appends, extends)):
                offenders.append((node.lineno, ".join()", ast.unparse(node)))
    return offenders


def _glued_translations(root, marked):
    """Sorted `"<path relative to root>:<lineno>: [<shape>] <expression>"`
    offenders for every `*.py` file under `root`.

    Takes `root` and `marked` as parameters rather than reading `SRC` and
    `RETURNS_TRANSLATED` directly: the reconciliation this check's own
    D-08 obligation requires runs it over a different tree (the phase's base
    commit, in a throwaway worktree), and the synthetic tests below run
    `_glued_in_ast` over parsed snippets -- a function that only ever works
    on one hardcoded path could serve neither.
    """
    offenders = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        rel = path.relative_to(root)
        for lineno, shape, expr in _glued_in_ast(tree, marked):
            offenders.append(f"{rel}:{lineno}: [{shape}] {expr}")
    return sorted(offenders)


# ---- Unit tests for the gluing rule itself --------------------------------
# Synthetic snippets, so a future edit to src/ cannot make the rule vacuous
# without a test noticing.

def _glued(source, marked):
    return _glued_in_ast(ast.parse(source), marked)


def test_a_direct_call_glued_with_plus_is_flagged():
    offenders = _glued(
        "def f():\n"
        "    return '\u2713 ' + tr('copied')\n",
        marked=set())
    assert [shape for _, shape, _ in offenders] == ["+"]


def test_a_marked_helpers_result_interpolated_in_an_fstring_is_flagged():
    offenders = _glued(
        "def f(a, b):\n"
        "    return f'{position_label(a)} to {position_label(b)}'\n",
        marked={"position_label"})
    assert [shape for _, shape, _ in offenders] == ["f-string"]


def test_a_name_bound_in_one_if_branch_and_glued_after_is_flagged():
    offenders = _glued(
        "def f(cond):\n"
        "    if cond:\n"
        "        reason = tr('a')\n"
        "    elif not cond:\n"
        "        reason = tr('b')\n"
        "    return f'\u2014 {reason}'\n",
        marked=set())
    assert [shape for _, shape, _ in offenders] == ["f-string"]


def test_a_join_over_a_list_built_by_append_is_flagged():
    offenders = _glued(
        "def f(items):\n"
        "    parts = []\n"
        "    for item in items:\n"
        "        parts.append(tr(item))\n"
        "    return ', '.join(parts)\n",
        marked=set())
    assert [shape for _, shape, _ in offenders] == [".join()"]


def test_a_percent_substitution_of_a_translated_template_is_not_flagged():
    offenders = _glued(
        "def f(value):\n"
        "    return tr('%(value)s cm') % {'value': value}\n",
        marked=set())
    assert offenders == []


def test_a_join_whose_argument_is_a_method_call_is_not_flagged():
    offenders = _glued(
        "class C:\n"
        "    def f(self):\n"
        "        return '\\n'.join(self._tooltip_lines())\n",
        marked=set())
    assert offenders == []


def test_an_fstring_interpolating_an_unmarked_locale_formatter_is_not_flagged():
    offenders = _glued(
        "def f(when):\n"
        "    return f'{fmt_day_label(when)} {fmt_clock(when)}'\n",
        marked=set())
    assert offenders == []


def test_a_marked_helper_called_through_its_module_is_flagged():
    """Several files reach `gui/util.py` as a module rather than importing
    each name, so a check that only reads a bare `Name` gives every call site
    following that convention a free pass."""
    offenders = _glued(
        "def f(x):\n"
        "    return f'{util.fmt_height(x)} left'\n",
        marked={"fmt_height"})
    assert [shape for _, shape, _ in offenders] == ["f-string"]


def test_an_unmarked_method_call_in_an_fstring_is_not_flagged():
    offenders = _glued(
        "class C:\n"
        "    def f(self):\n"
        "        return f'{self._lib_version()} · x'\n",
        marked=set())
    assert offenders == []


def test_glue_at_module_scope_is_flagged():
    offenders = _glued("MSG = tr('a') + tr('b')\n", marked=set())
    assert [shape for _, shape, _ in offenders] == ["+"]


def test_glue_in_a_class_body_is_flagged():
    offenders = _glued(
        "class C:\n"
        "    MSG = tr('a') + tr('b')\n",
        marked=set())
    assert [shape for _, shape, _ in offenders] == ["+"]


def test_glue_inside_a_lambda_is_flagged():
    offenders = _glued("render = lambda x: tr('a') + x\n", marked=set())
    assert [shape for _, shape, _ in offenders] == ["+"]


def test_accumulating_onto_a_translated_value_is_flagged():
    offenders = _glued(
        "def f():\n"
        "    line = tr('a')\n"
        "    line += ' ✓'\n"
        "    return line\n",
        marked=set())
    assert [shape for _, shape, _ in offenders] == ["+="]


def test_accumulating_a_translated_value_onto_something_is_flagged():
    offenders = _glued(
        "def f(line):\n"
        "    line += tr('a')\n"
        "    return line\n",
        marked=set())
    assert [shape for _, shape, _ in offenders] == ["+="]


def test_a_name_bound_by_tuple_unpacking_and_glued_after_is_flagged():
    offenders = _glued(
        "def f(tokens):\n"
        "    color, footer, chip = connection_state(tokens)\n"
        "    return f'{footer} —'\n",
        marked={"connection_state"})
    assert [shape for _, shape, _ in offenders] == ["f-string"]


def test_a_glue_against_the_module_private_wrapper_is_flagged():
    offenders = _glued(
        "def f(key):\n"
        "    return _tr(key) + ':'\n",
        marked=set())
    assert [shape for _, shape, _ in offenders] == ["+"]


# ---- Integration test against the real tree -------------------------------

def test_no_translated_value_is_glued_to_anything():
    """A sentence assembled from translated pieces is a sentence no
    translator can reorder, and the two halves ship looking fine in English
    -- nothing fails until a language whose word order differs discovers the
    seam. This walks every file under `src/idasen_companion` and fails when
    a translated value -- the result of `tr()`/`translate()`/`_()`/
    `ngettext()`, or of a `gui/util.py` helper marked `RETURNS_TRANSLATED`
    -- is an operand of `+`, interpolated into an f-string, or handed to
    `.join()`.

    It does not follow a value into or out of a function -- see the
    module-level note above `_is_translated_call` for why that is a design
    boundary, not a gap: stacking whole lines through a helper that returns
    a joined string (the tray tooltip, the About page's clipboard blob, the
    setup wizard's success dialog) is out of this check's reach on purpose,
    and needs no exemption entry here because of it.

    Ships no list of exempt sites. The `RETURNS_TRANSLATED` registry it
    reads is the only "list" this check depends on, and that one lives at
    each helper's own definition in `gui/util.py`, self-enforced by
    `test_util_helpers_that_reach_tr_carry_the_mark` above.
    """
    from idasen_companion.gui.util import (  # pylint: disable=import-outside-toplevel
        RETURNS_TRANSLATED,
    )

    offenders = _glued_translations(SRC, RETURNS_TRANSLATED)
    assert not offenders, (
        "a translated value is glued to something else with +, an f-string, "
        "or .join() -- pull it into one whole message with named "
        "substitutions instead: " + "; ".join(offenders))
