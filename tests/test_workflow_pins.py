"""Third-party GitHub Actions must be pinned to a commit, not a moving tag.

A release tag can be moved by whoever owns the action after the fact, but the
commit it pointed to when a maintainer reviewed it cannot change under us.
The workflow that builds and publishes this project's release artifacts is
exactly the place a supply-chain compromise would land, so this test is what
stops a future edit from quietly substituting a tag back in.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

pytestmark = pytest.mark.skipif(
    not WORKFLOWS.is_dir(),
    reason="CI configuration is deliberately not part of the source "
    "distribution, so this check only runs from a git checkout, not from "
    "the RPM's unpacked-sdist %check",
)

_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _iter_uses_lines():
    """Yield (filename, lineno, line, ref) for every `uses:` line across all
    workflow files, third-party and this repository's own alike."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith("uses:"):
                continue
            value = stripped[len("uses:") :].strip()
            ref = value.split()[0] if value else ""
            yield path.name, lineno, line, ref


def _third_party_references():
    """The subset of `uses:` references that name another org's action --
    this repository's own dot-prefixed reusable-workflow references are
    excluded."""
    return [
        (filename, lineno, line, ref)
        for filename, lineno, line, ref in _iter_uses_lines()
        if not ref.startswith(".")
    ]


def test_every_third_party_action_is_pinned_to_a_commit_sha():
    """A tag, a branch or a shortened hash all fail this the same way a
    floating major version would -- only a full 40-character commit hash
    proves what will actually run."""
    offenders = []
    for filename, lineno, _line, ref in _third_party_references():
        version = ref.rsplit("@", 1)[-1] if "@" in ref else ""
        if not _COMMIT_SHA.fullmatch(version):
            offenders.append(f"{filename}:{lineno} references {ref!r}")
    assert not offenders, (
        "third-party action(s) not pinned to a commit sha: " + ", ".join(offenders)
    )


def test_every_pinned_reference_still_names_its_version_to_a_reader():
    """A bare commit hash tells a reviewer nothing about which release they
    are looking at without resolving it first, so every pin keeps its
    human-readable tag alongside it as a trailing comment."""
    offenders = []
    for filename, lineno, line, _ref in _third_party_references():
        if "#" not in line:
            offenders.append(f"{filename}:{lineno}")
    assert not offenders, (
        "pinned reference(s) missing a trailing version comment: "
        + ", ".join(offenders)
    )


def test_the_repositorys_own_reusable_workflows_are_not_pinned():
    """Guards the other direction: a future edit must not start pinning this
    repository's own `uses: ./...` references against themselves."""
    local_references = [
        ref for _filename, _lineno, _line, ref in _iter_uses_lines() if ref.startswith(".")
    ]
    assert local_references, "expected at least one local reusable-workflow reference"
    pinned = [ref for ref in local_references if "@" in ref]
    assert not pinned, f"local reusable-workflow reference(s) unexpectedly pinned: {pinned}"
