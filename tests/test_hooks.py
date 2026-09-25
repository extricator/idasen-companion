"""The local hook is the only layer that acts before a commit exists, and it
is worth nothing if it stops shipping executable or if the one command that
installs it stops being written down.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".githooks" / "pre-commit"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
SCANNER = ROOT / "scripts" / "scan-secrets.sh"

# Read at collection time, not inside a test, so a missing MANIFEST.in entry
# for this file reproduces the same failure mode project documentation documents for
# scripts/check_naming_span.py: the RPM's %check dies at collection from an
# unpacked sdist while every local run passes, because the file sits right
# there in the working tree.
CONTRIBUTING_TEXT = CONTRIBUTING.read_text()

# conftest.py's no_real_subprocesses autouse fixture replaces subprocess.run
# for every test, since most of the suite must stay off the machine it runs
# on. Captured here, at import time, before that fixture's per-test setup
# runs -- reading git's own recorded mode for a tracked file has no side
# effect on the machine, the same reasoning test_service_ctl.py's own tests
# already rely on when they hand the fixture a real (or realistic) callable
# instead of accepting its default refusal.
_REAL_SUBPROCESS_RUN = subprocess.run


def test_the_hook_file_exists():
    """A contributor who runs the documented install command needs
    something to actually be there at the path git is pointed at."""
    assert HOOK.is_file(), f"{HOOK} does not exist"


def test_git_records_the_hook_as_executable(monkeypatch):
    """A fresh clone restores whatever mode git recorded, not whatever mode
    the filesystem happens to carry after packing -- so the invariant that
    matters is the tree object's mode, not os.access() on this checkout.

    Skipped when there is no git index to ask: an unpacked source tarball
    has no .git directory, the same situation
    test_the_user_unit_ships_under_the_filename_the_helper_resolves already
    skips for in tests/test_packaging.py.
    """
    if not (ROOT / ".git").exists():
        pytest.skip("no git checkout present (running from the sdist)")
    monkeypatch.setattr(subprocess, "run", _REAL_SUBPROCESS_RUN)
    result = subprocess.run(
        ["git", "ls-files", "-s", str(HOOK.relative_to(ROOT))],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    mode = result.stdout.split()[0] if result.stdout else ""
    assert mode == "100755", f"git records {HOOK} at mode {mode!r}, not 100755"


def test_contributing_documents_the_hookspath_install():
    """The install is one command; if CONTRIBUTING.md stops naming it, a
    contributor who clones the repository gets no protection and no error,
    silently. The expected text is assembled from parts rather than written
    as one literal here, so this assertion can only be satisfied by
    CONTRIBUTING.md's real content, never by this test file's own prose."""
    parts = ["git", "config", "core.hooksPath", ".githooks"]
    install_command = " ".join(parts)
    assert install_command in CONTRIBUTING_TEXT, (
        "CONTRIBUTING.md no longer documents the hooksPath install command"
    )


def test_the_hook_still_delegates_to_a_scanner_that_exists():
    """The hook calls the shared scanner rather than re-implementing it, so
    local and CI cannot disagree about what counts as a secret. A future
    rename of the scanner that forgets this hook would leave a hook that
    exits non-zero on every commit for the wrong reason -- this reads the
    path the hook actually invokes and confirms it resolves."""
    text = HOOK.read_text()
    match = re.search(r"bash (scripts/\S+\.sh)", text)
    assert match, f"{HOOK} does not appear to delegate to a scripts/*.sh scanner"
    invoked = ROOT / match.group(1)
    assert invoked == SCANNER, (
        f"{HOOK} delegates to {invoked}, not the scanner this test expects ({SCANNER})"
    )
    assert invoked.exists(), f"{invoked} does not exist"
