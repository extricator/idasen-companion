"""The PRES-02 gate: nothing under `core/presentation/` resolves its own
language, locale or unit.

Every formatter and translator backend in that package must receive its
capability as an argument or on an injected context. A formatter that instead
reaches for a module global, a default locale object, or the process
environment renders correctly in every test that happens to run *after*
whatever sets that global, and wrongly on the one path that runs *before* it
— a failure a rendered-string assertion cannot distinguish from a locale bug.
Worse, when the test failure looks like a wrong Spanish string, it gets fixed
in the wrong layer: the locale policy, not the capability that leaked in
unannounced. Phases 13-15 move roughly twenty formatters into this package
one at a time, at a scale no reviewer can hold this property against by eye,
which is why the property is checked here instead.

Each rule below walks the parsed syntax tree of every module in the package,
never the file's raw text, so an explanatory comment near an offending line
cannot satisfy the rule it is being checked against.

`core/i18n.py`'s process-wide gettext translator is the one deliberate
exception, tracked as data in `_PROCESS_WIDE_CATALOG_EXEMPTIONS` below and
also documented at its own call site in `gettext_translator.py`: gettext is
built around exactly one catalog per process, so a backend that wraps it
necessarily delegates to that shared state on every call rather than
threading a catalog object through every formatter signature. That is a
different shape from the failure this file exists to catch — there is no
earlier value to freeze, and a later language change is visible on the very
next lookup.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "idasen_companion"
PRESENTATION_DIR = SRC / "core" / "presentation"

#: Every module under the package, discovered rather than hand-listed so a
#: module Phase 13 adds is covered the moment it exists.
_MODULES = sorted(PRESENTATION_DIR.rglob("*.py"))

#: The one module allowed to reach `core/i18n.py`'s process-wide catalog,
#: mapped to why — see the module docstring above and `gettext_translator.py`
#: itself for the full reasoning. Widening this map is the failure PRES-02
#: exists to catch, so its length is asserted below as well as its reason.
_PROCESS_WIDE_CATALOG_EXEMPTIONS = {
    PRESENTATION_DIR / "gettext_translator.py": (
        "the sole Translator backend wrapping core/i18n.py's one "
        "process-wide gettext catalog; gettext has exactly one current "
        "catalog per process, so this delegation is unavoidable, and it "
        "carries no startup-frozen value for a later call to see stale"
    ),
}

#: Names whose call, made with no positional or keyword argument, constructs
#: a locale object bound to whatever the process or environment currently
#: says — the "default locale object" half of the rule. Unreachable today
#: because nothing under the package imports a Qt or stdlib locale type; kept
#: here for when a formatter migrates into this package and could.
_LOCALE_CONSTRUCTOR_SUFFIX = "Locale"

#: A name shaped like a Qt class (`QSomething`), the `Qt` namespace itself, or
#: the `PySide6` package — any of which under this package means a Qt-aware
#: value reached a supposedly Qt-free formatter.
def _looks_like_a_qt_name(name: str) -> bool:
    if name in ("Qt", "PySide6"):
        return True
    return len(name) > 1 and name[0] == "Q" and name[1].isupper()


#: Calls that read the process environment directly, bypassing whatever
#: capability object a caller was supposed to inject.
_ENVIRONMENT_READS = frozenset({"getenv"})
_ENVIRONMENT_ATTRIBUTES = frozenset({"environ"})

#: stdlib `locale` module entry points that bind or read the process locale
#: category rather than accepting one as a value.
_LOCALE_SETTING_CALLS = frozenset({
    "setlocale", "getlocale", "getdefaultlocale", "resetlocale",
})

#: A message-lookup or extraction-marker call name. A string literal handed
#: to one of these under this package would be invisible to today's narrower
#: extraction scope (D-08) — see `test_no_translatable_literal_appears_yet`
#: below for the retirement note.
_TRANSLATION_CALLS = frozenset({
    "_", "ngettext", "gettext", "tr", "translate", "QT_TRANSLATE_NOOP",
})


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _module_level_binding_offenders(tree: ast.Module, path: Path) -> list[str]:
    """Every module-level assignment whose target is not an upper-case
    constant name, plus every `global` statement anywhere in the module —
    caught at the binding, not the read, so it cannot be dodged by reading
    a global through a helper function instead of by name."""
    offenders = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            targets = [stmt.target]
        else:
            continue
        for target in targets:
            for name_node in ast.walk(target):
                if isinstance(name_node, ast.Name) and not name_node.id.isupper():
                    offenders.append(
                        f"{path.name}:{stmt.lineno}: module-level binding "
                        f"'{name_node.id}'")
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            offenders.append(
                f"{path.name}:{node.lineno}: global statement "
                f"({', '.join(node.names)})")
    return offenders


def _default_locale_offenders(tree: ast.Module, path: Path) -> list[str]:
    """A no-argument call to a `...Locale`-named constructor, or any
    reference to a Qt name — an import, a bare name, or an attribute."""
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if (name and name.endswith(_LOCALE_CONSTRUCTOR_SUFFIX)
                    and not node.args and not node.keywords):
                offenders.append(
                    f"{path.name}:{node.lineno}: default locale "
                    f"construction '{name}()'")
        if isinstance(node, ast.Name) and _looks_like_a_qt_name(node.id):
            offenders.append(f"{path.name}:{node.lineno}: Qt name '{node.id}'")
        elif isinstance(node, ast.Attribute) and _looks_like_a_qt_name(node.attr):
            offenders.append(f"{path.name}:{node.lineno}: Qt name '.{node.attr}'")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if base == "PySide6":
                    offenders.append(
                        f"{path.name}:{node.lineno}: Qt import '{alias.name}'")
    return offenders


def _self_resolved_locale_offenders(tree: ast.Module, path: Path) -> list[str]:
    """A read of the process environment, or a call to a stdlib `locale`
    function that binds or reads the process locale category."""
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _ENVIRONMENT_ATTRIBUTES:
            offenders.append(
                f"{path.name}:{node.lineno}: environment read '.{node.attr}'")
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name in _ENVIRONMENT_READS or name in _LOCALE_SETTING_CALLS:
                offenders.append(f"{path.name}:{node.lineno}: call '{name}()'")
    return offenders


def _process_wide_catalog_offenders(tree: ast.Module, path: Path) -> list[str]:
    """An import of, or attribute access naming, the module holding the
    process-wide gettext catalog (`core/i18n.py`) — from any module except
    the one named exemption above."""
    if path in _PROCESS_WIDE_CATALOG_EXEMPTIONS:
        return []
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.rsplit(".", maxsplit=1)[-1] == "i18n":
                offenders.append(f"{path.name}:{node.lineno}: 'from {module} import ...'")
            for alias in node.names:
                if alias.name == "i18n":
                    offenders.append(
                        f"{path.name}:{node.lineno}: 'from ... import i18n'")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.rsplit(".", maxsplit=1)[-1] == "i18n":
                    offenders.append(
                        f"{path.name}:{node.lineno}: 'import {alias.name}'")
        elif isinstance(node, ast.Attribute) and node.attr == "i18n":
            offenders.append(f"{path.name}:{node.lineno}: attribute '.i18n'")
    return offenders


def _translatable_literal_offenders(tree: ast.Module, path: Path) -> list[str]:
    """A string literal passed to a translation marker or lookup call —
    deliberately temporary (D-08). Retire this rule in Phase 13's CAT-05
    commit, the one that widens `scripts/build-translations.sh`'s extraction
    scope to cover this package: before that commit a marked literal landing
    here would be extracted by nothing and no completeness gate would notice,
    so today the only safe answer is that none may land here at all.
    Deleting this rule earlier reopens that window; leaving it after CAT-05
    lands merely forbids a call this package is then meant to make.
    """
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in _TRANSLATION_CALLS:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                offenders.append(
                    f"{path.name}:{node.lineno}: {name}({arg.value!r})")
    return offenders


@pytest.mark.parametrize("path", _MODULES, ids=lambda p: p.name)
def test_no_module_level_mutable_state(path):
    tree = _parse(path)
    offenders = _module_level_binding_offenders(tree, path)
    assert not offenders, (
        "a module-level binding here is process-wide state a formatter can "
        "read instead of receiving its value as an argument: "
        + "; ".join(offenders))


@pytest.mark.parametrize("path", _MODULES, ids=lambda p: p.name)
def test_no_default_locale_object_or_qt_reference(path):
    tree = _parse(path)
    offenders = _default_locale_offenders(tree, path)
    assert not offenders, (
        "a default-constructed locale or a Qt reference resolves its value "
        "from process/toolkit state rather than an injected capability: "
        + "; ".join(offenders))


@pytest.mark.parametrize("path", _MODULES, ids=lambda p: p.name)
def test_no_self_resolved_environment_or_locale(path):
    tree = _parse(path)
    offenders = _self_resolved_locale_offenders(tree, path)
    assert not offenders, (
        "reading the environment or binding the process locale category "
        "resolves language/locale for this module instead of an injected "
        "capability: " + "; ".join(offenders))


@pytest.mark.parametrize("path", _MODULES, ids=lambda p: p.name)
def test_no_unexempted_reach_for_the_process_wide_catalog(path):
    tree = _parse(path)
    offenders = _process_wide_catalog_offenders(tree, path)
    assert not offenders, (
        "only the named exemption may reach core/i18n.py's process-wide "
        "catalog: " + "; ".join(offenders))


@pytest.mark.parametrize("path", _MODULES, ids=lambda p: p.name)
def test_no_translatable_literal_appears_yet(path):
    tree = _parse(path)
    offenders = _translatable_literal_offenders(tree, path)
    assert not offenders, (
        "this package's literals aren't in today's extraction scope, so a "
        "marked one here would ship untranslated with nothing to notice: "
        + "; ".join(offenders))


def test_process_wide_catalog_exemption_has_exactly_one_named_reason():
    assert len(_PROCESS_WIDE_CATALOG_EXEMPTIONS) == 1, (
        "widening this exemption is the failure this file exists to catch; "
        "if a second module genuinely needs it, that is a deliberate, "
        "visible edit to this test, not a silent addition")
    for module_path, reason in _PROCESS_WIDE_CATALOG_EXEMPTIONS.items():
        assert module_path in _MODULES, (
            f"{module_path} is exempted but is not a module this file walks")
        assert reason.strip(), f"{module_path} is exempted with no reason recorded"
