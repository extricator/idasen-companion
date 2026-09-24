"""Whether the Qt-free path stays Qt-free is measured, in a process that has
never imported Qt -- not asserted in-process.

Two things defeat an in-process check of the same claim. First, any earlier
test in the same pytest session may already have imported PySide6 (this
suite's own conftest.py does, conditionally, in more than one autouse
fixture) -- by the time a test body runs, ``"PySide6" in sys.modules`` can
already be true for a reason that has nothing to do with the module under
test. Second, an ``import PySide6`` reached *transitively*, through a helper
two calls deep, still passes every functional test in a GUI-capable venv --
functional behaviour does not depend on which backend answered it, only on
what it answered. Only a fresh interpreter that imports nothing else first,
then reports its own ``sys.modules``, answers the actual question.

This is also the gate the Qt backend's placement depends on: the Qt-aware
formatter lives under ``gui/`` specifically because it is allowed to import
Qt, and the shared ``core/presentation/`` package is only usable from the
daemon (which links no Qt at all) *because* nothing under it does either. A
Qt import that crept into that package would silently pull Qt into the
daemon's process the next time someone wired the two together, so this test
covers the daemon's own import path as a second, independent leg -- proving
the package is Qt-free says nothing about whether the daemon's entry point
reaches it through some other route.

``tests/conftest.py``'s ``no_real_subprocesses`` autouse fixture replaces
``subprocess.run`` for every test in this suite with a callable that raises
``FileNotFoundError``, to keep the suite off the machine it runs on. The
child process this file spawns is real and load-bearing -- there is no
in-process substitute for the property under test -- so it cannot go through
that stub. The established idiom (``tests/test_hooks.py``) is to capture the
real ``subprocess.run`` at *module import time*, before the autouse fixture's
per-test setup has run, and hand it back with ``monkeypatch`` inside the one
test that needs it. A handler around the call that catches the stub's
refusal would "fix" the symptom by silently downgrading this gate to a
no-op: it would swallow that error, report nothing spawned, and the test
would pass whether or not the code under test imports Qt -- exactly the
class of check-that-checks-nothing this milestone exists to catch elsewhere.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "idasen_companion"
PRESENTATION_DIR = SRC / "core" / "presentation"
PACKAGE_SPEC = importlib.util.find_spec("idasen_companion")
assert PACKAGE_SPEC is not None and PACKAGE_SPEC.origin is not None
PACKAGE_ROOT = str(Path(PACKAGE_SPEC.origin).parent.parent)

# Captured here, at module import time, before no_real_subprocesses' per-test
# setup replaces subprocess.run -- see the module docstring.
_REAL_SUBPROCESS_RUN = subprocess.run

# Sentinels the child prints, deliberately not the bare words "True"/"False":
# a report has to match one of these two exactly, so an empty stdout (a child
# that died before reaching the print) or any other unexpected text fails the
# assertion instead of being read as "absent" by accident.
_ABSENT = "PYSIDE6_ABSENT"
_PRESENT = "PYSIDE6_PRESENT"

# The child imports each name in turn and then reports once, at the end, on
# its own sys.modules -- so a report of _ABSENT means none of the imports
# along the way pulled PySide6 in either.
_CHILD_PROGRAM = """
import importlib
import sys

sys.path.insert(0, {package_root!r})

for _name in {modules!r}:
    importlib.import_module(_name)

sys.stdout.write({present!r} if "PySide6" in sys.modules else {absent!r})
""".strip()

# The third leg's child program goes further than an import: it drives every
# public Formatter method through a real call, from the same shared table
# tests/test_golden_presentation_contract.py pins against, plus the one
# daemon-reader sentence table that gets no Formatter method at all
# (core/presentation/daemon_errors.py). ``-I`` strips PYTHONPATH, so the
# repository's own src/ and tests/ directories are injected here, from the
# parent process's own ROOT, rather than relied on to already be importable.
_CALLABILITY_CHILD_PROGRAM = """
import sys

sys.path.insert(0, {tests_dir!r})
sys.path.insert(0, {src_dir!r})

import presentation_samples
from idasen_companion.core.presentation import daemon_errors
from idasen_companion.core.presentation.english import EnglishTranslator

formatter = presentation_samples.build_plain_formatter()
for row in presentation_samples.SAMPLES:
    result = getattr(formatter, row.method)(*row.args, **row.kwargs)
    if isinstance(result, tuple):
        assert result, (row.case, result)
        for part in result:
            assert isinstance(part, str) and part, (row.case, result)
    else:
        assert isinstance(result, str) and result, (row.case, result)

detail = daemon_errors.daemon_error_message(EnglishTranslator(), "MoveFailed")
assert isinstance(detail, str) and detail

sys.stdout.write({present!r} if "PySide6" in sys.modules else {absent!r})
""".strip()


def _dotted_module_names(package_dir: Path, package: str) -> list[str]:
    """Every module under ``package_dir``, as a dotted import path.

    Discovered by walking the directory rather than listed by hand, so this
    gate keeps covering the package as it grows -- a hardcoded list stops
    covering a module the moment a later phase adds one.
    """
    names = []
    for path in sorted(package_dir.rglob("*.py")):
        parts = path.relative_to(package_dir).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.append(".".join((package, *parts)) if parts else package)
    return names


def _run_isolated(program: str) -> subprocess.CompletedProcess:
    """Run ``program`` in a fresh, isolated child interpreter.

    Isolated (``-I``) the same way the launcher and the RPM's own ``%check``
    run every subprocess it spawns (see ``packaging/idasen-companion-launcher.sh``
    and ``packaging/idasen-companion-bundled.spec``): otherwise the working
    directory, the user's own site directory, or a ``PYTHON*``/``PYTHONPATH``
    variable in the environment could answer the import a different way than
    what actually ships. ``-B`` keeps the run from writing bytecode caches for
    the same reason those callers do -- a check should not leave a trace that
    changes what a later run measures.
    """
    return _REAL_SUBPROCESS_RUN(
        [sys.executable, "-I", "-B", "-c", program],
        capture_output=True, text=True, check=False,
    )


def _assert_qt_free(result: subprocess.CompletedProcess, leg: str) -> None:
    assert result.returncode == 0, (
        f"{leg}: the child process exited {result.returncode}, not 0 -- "
        f"stderr:\n{result.stderr}"
    )
    report = result.stdout.strip()
    assert report == _ABSENT, (
        f"{leg}: expected the child to report {_ABSENT!r} (PySide6 absent "
        f"from its own sys.modules after the import), got {report!r} -- "
        f"stderr:\n{result.stderr}"
    )


def test_the_presentation_package_never_imports_qt(monkeypatch):
    """core/presentation/ is importable, whole, in a process that has never
    loaded Qt -- covering every module under the package, discovered, not
    hardcoded."""
    modules = _dotted_module_names(
        PRESENTATION_DIR, "idasen_companion.core.presentation")
    assert modules, "no presentation modules discovered -- the walk is broken"
    monkeypatch.setattr(subprocess, "run", _REAL_SUBPROCESS_RUN)
    program = _CHILD_PROGRAM.format(
        modules=modules, package_root=PACKAGE_ROOT,
        present=_PRESENT, absent=_ABSENT)
    result = _run_isolated(program)
    _assert_qt_free(result, "core/presentation/")


def test_the_daemon_entry_point_never_imports_qt(monkeypatch):
    """The daemon's own import path is Qt-free too -- a claim about
    core/presentation/ alone says nothing about whether idasen-companiond's
    entry point reaches Qt through some other route, and the daemon holds
    the desk's single BLE connection as a systemd user service, so an
    accidental Qt link there is a packaging and attack-surface regression as
    well as a correctness one."""
    assert importlib.util.find_spec("idasen_companion.daemon.main") is not None
    monkeypatch.setattr(subprocess, "run", _REAL_SUBPROCESS_RUN)
    program = _CHILD_PROGRAM.format(
        modules=["idasen_companion.daemon.main"], package_root=PACKAGE_ROOT,
        present=_PRESENT, absent=_ABSENT)
    result = _run_isolated(program)
    _assert_qt_free(result, "daemon/main.py")


def test_the_cli_entry_point_never_imports_qt(monkeypatch):
    """The standalone CLI must remain usable in the headless artifact."""
    assert importlib.util.find_spec("idasen_companion.cli") is not None
    monkeypatch.setattr(subprocess, "run", _REAL_SUBPROCESS_RUN)
    program = _CHILD_PROGRAM.format(
        modules=["idasen_companion.cli"], package_root=PACKAGE_ROOT,
        present=_PRESENT, absent=_ABSENT)
    result = _run_isolated(program)
    _assert_qt_free(result, "cli.py")


def test_every_shared_formatter_is_callable_with_no_qt_loaded(monkeypatch):
    """PRES-01 asks for more than the two legs above prove. Those cover
    *importability* -- that ``core/presentation/`` and the daemon's entry
    point load with no windowing toolkit in ``sys.modules`` -- but say
    nothing about a method that raises the moment it is actually invoked
    without one backing it. This leg drives every public ``Formatter``
    method, from the same ``tests/presentation_samples.py`` table
    ``tests/test_golden_presentation_contract.py`` pins against, through a
    real call in a process that has never loaded Qt, plus the one
    daemon-reader sentence table that gets no ``Formatter`` method at all.
    """
    monkeypatch.setattr(subprocess, "run", _REAL_SUBPROCESS_RUN)
    program = _CALLABILITY_CHILD_PROGRAM.format(
        tests_dir=str(ROOT / "tests"), src_dir=str(ROOT / "src"),
        present=_PRESENT, absent=_ABSENT)
    result = _run_isolated(program)
    _assert_qt_free(result, "every shared formatter, called")
