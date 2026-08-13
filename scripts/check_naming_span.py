#!/usr/bin/env python3
"""Tier 2 of the project's naming rule: scope span.

CONTRIBUTING.md, "Naming things", tier 2: "The further a name's declaration
is from its last use, the more descriptive it needs to be. Short names are
fine near their assignment." Tier 1 (accuracy) and tier 3 (glossary) are
covered elsewhere -- accuracy stays a human-review norm permanently, and the
glossary is pylint's `invalid-name`/`disallowed-name`. This script is the
only thing that checks tier 2.

For every function, span = (highest line a name is *read*) minus (lowest
line the name is *assigned*) -- usage span, not the name's binding scope.
Measuring binding scope instead of usage span misreads an unused `for`
target as living the whole rest of the function; measuring usage span reads
it for what it actually is, however long the loop body runs.

Stdlib-only (`ast`, `argparse`, `pathlib`, `sys`) so it runs under a bare
`python3`, no venv required.
"""

import argparse
import ast
import pathlib
import sys

# Name length (leading underscores stripped) -> maximum usage span, in
# source lines, between a name's first assignment and its last read. No
# entry means unlimited. Measured against this project's own src/ tree, not
# chosen by taste: banding 4- and 5-character names too pushes the count from
# 71 to 96-101 and starts flagging `layout`, `window`, `height`, `status`,
# `client` -- names that are simply descriptive and live a long time, which
# is not what the rule forbids.
LIMITS = {1: 5, 2: 8, 3: 12}

# Node types that open their own scope. A nested function/lambda is analysed
# as its own unit by the outer walk below, and a comprehension's target and
# body are their own scope in Python 3 -- either way, none of their names
# belong to whatever function textually encloses them.
_SCOPE_BOUNDARY = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def _own_bindings(scope_node):
    """Names a Load inside `scope_node` resolves to *within that scope* --
    its parameters (for a function/lambda) plus whatever it Stores directly,
    not counting anything inside a scope nested within it.

    This is what makes a nested scope's own variable shadow an outer one of
    the same name, so a closure that reassigns a name is not mistaken for a
    read of the enclosing function's name of the same spelling.
    """
    names = set()
    if isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        params = scope_node.args
        for arg in (*params.posonlyargs, *params.args, *params.kwonlyargs):
            names.add(arg.arg)
        if params.vararg:
            names.add(params.vararg.arg)
        if params.kwarg:
            names.add(params.kwarg.arg)

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
                continue
            # `except E as name:` binds `name` as a plain string attribute,
            # not a Name node -- ast.iter_child_nodes never surfaces it, so
            # it needs its own check to count as a binding at all.
            if isinstance(child, ast.ExceptHandler) and child.name:
                names.add(child.name)
            if isinstance(child, _SCOPE_BOUNDARY):
                continue  # a deeper scope's own locals are its own business
            walk(child)

    walk(scope_node)
    return names


def _usage(func):
    """first_store/last_load for every name `func` itself assigns.

    A name's last read can be inside a nested def/lambda/comprehension --
    reading a name through a closure is exactly what keeps it alive that
    long -- but only when that nested scope doesn't itself rebind the name
    as its own local (a parameter, or its own assignment/comprehension
    target), which makes it a different variable that merely shares a
    spelling.
    """
    first_store = {}
    last_load = {}

    def visit(node, shadow, in_own_body):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store) and in_own_body:
                seen = first_store.get(node.id)
                if seen is None or node.lineno < seen:
                    first_store[node.id] = node.lineno
            elif isinstance(node.ctx, ast.Load) and node.id not in shadow:
                seen = last_load.get(node.id)
                if seen is None or node.lineno > seen:
                    last_load[node.id] = node.lineno
            return
        if isinstance(node, _SCOPE_BOUNDARY):
            nested_shadow = shadow | _own_bindings(node)
            for child in ast.iter_child_nodes(node):
                visit(child, nested_shadow, in_own_body=False)
            return
        if isinstance(node, ast.ExceptHandler) and node.name and in_own_body:
            # See _own_bindings: `as name` never surfaces as a Name node.
            seen = first_store.get(node.name)
            if seen is None or node.lineno < seen:
                first_store[node.name] = node.lineno
        for child in ast.iter_child_nodes(node):
            visit(child, shadow, in_own_body)

    for stmt in func.body:
        visit(stmt, set(), True)
    return first_store, last_load


def _function_hits(func):
    """Yield (line, name, span, limit) for every over-span name in `func`."""
    first_store, last_load = _usage(func)
    for name, store_line in sorted(first_store.items()):
        if name == "_":
            continue
        load_line = last_load.get(name)
        if load_line is None:
            continue
        limit = LIMITS.get(len(name.lstrip("_")))
        if limit is None:
            continue
        span = load_line - store_line
        if span > limit:
            yield store_line, name, span, limit


def check_file(path):
    """Return sorted (path, line, message) hits for one source file."""
    try:
        source = path.read_text()
    except (UnicodeDecodeError, OSError):
        return []
    tree = ast.parse(source, filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line, name, span, limit in _function_hits(node):
                message = (
                    f"{path}:{line}: '{name}' in {node.name}() "
                    f"lives {span} lines (max {limit})"
                )
                hits.append((str(path), line, message))
    return hits


def iter_source_files(roots):
    for root in roots:
        path = pathlib.Path(root)
        if path.is_file():
            yield path
        else:
            yield from sorted(path.rglob("*.py"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["src"],
                         help="files or directories to check (default: src)")
    args = parser.parse_args(argv)

    hits = []
    for source_file in iter_source_files(args.paths):
        hits.extend(check_file(source_file))
    hits.sort(key=lambda hit: (hit[0], hit[1]))

    for _path, _line, message in hits:
        print(message)

    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
