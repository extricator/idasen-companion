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
Qt, and the shared ``core/presentation.py`` package is only usable from the
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


def test_the_presentation_module_never_imports_qt(monkeypatch):
    """The consolidated presentation module imports without loading Qt."""
    modules = ["idasen_companion.core.presentation"]
    monkeypatch.setattr(subprocess, "run", _REAL_SUBPROCESS_RUN)
    program = _CHILD_PROGRAM.format(
        modules=modules, package_root=PACKAGE_ROOT,
        present=_PRESENT, absent=_ABSENT)
    result = _run_isolated(program)
    _assert_qt_free(result, "core/presentation.py")


def test_the_daemon_entry_point_never_imports_qt(monkeypatch):
    """The daemon's own import path is Qt-free too -- a claim about
    core/presentation.py alone says nothing about whether idasen-companiond's
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
