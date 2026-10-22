# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared scanner verdicts, with disposable Git and a scanner-only runtime fake."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SCANNER = Path(__file__).resolve().parent.parent / "scripts" / "scan-secrets.sh"
# Keep conftest's global refusal intact; only the named disposable Git/shell
# calls below use the original callable, captured before autouse setup.
_REAL_RUN = subprocess.run


@pytest.fixture
def scan_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(SCANNER, repo / "scripts" / SCANNER.name)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    runtime = bin_dir / "docker"
    runtime.write_text(f"#!{sys.executable}\n" + '''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as calls:
    calls.write(json.dumps(args) + "\\n")
if args[0] == "pull":
    sys.exit(0)
if args == ["--version"]:
    print("disposable scanner runtime")
    sys.exit(0)
if args[-1] == "version":
    print("8.30.1")
    sys.exit(0)
mounts = [args[i + 1] for i, value in enumerate(args) if value == "-v"]
out = Path(next(value.removesuffix(":/out:Z") for value in mounts
                if value.endswith(":/out:Z")))
report = next(value.split("=", 1)[1] for value in args
              if value.startswith("--report-path="))
canary = Path(report).name.startswith("canary-")
if canary or os.environ["FAKE_REPORT"] != "<missing>":
    (out / Path(report).name).write_text("[{}]" if canary else os.environ["FAKE_REPORT"])
receipt = "scanned ~18 bytes (18 bytes) in 1ms" if canary else os.environ["FAKE_RECEIPT"]
if receipt:
    print("\\x1b[32m12:00PM INF " + receipt + "\\x1b[0m")
if not canary:
    print(os.environ.get("FAKE_LOG", "12:00PM INF no leaks found"))
sys.exit(1 if canary else 0)
''')
    runtime.chmod(0o755)
    env.update(PATH=str(bin_dir) + os.pathsep + env["PATH"],
               FAKE_CALLS=str(tmp_path / "calls.jsonl"))

    def git(*args, check=True):
        return _REAL_RUN(["git", "-C", str(repo), *args], env=env,
                         capture_output=True, text=True, check=check, timeout=10)

    git("init", "-q")
    git("config", "user.name", "scanner fixture")
    git("config", "user.email", "scanner@example.invalid")
    git("config", "core.hooksPath", str(tmp_path / "no-hooks"))

    def scan(mode="staged", *, log="12:00PM INF no leaks found",
             receipt="scanned ~18 bytes (18 bytes) in 1ms", report="[]",
             metadata=None):
        if metadata is not None:
            # Only inject the independent numstat failure/record. Every other
            # Git invocation remains real and confined to the disposable root.
            real_git = shutil.which("git")
            shim = bin_dir / "git"
            shim.write_text(f"#!{sys.executable}\n" +
                            "import os, sys\n" +
                            "if '--numstat' in sys.argv:\n" +
                            ("    sys.exit(7)\n" if metadata == "failure" else
                             f"    sys.stdout.buffer.write({metadata!r}); sys.exit(0)\n") +
                            f"os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n")
            shim.chmod(0o755)
        result = _REAL_RUN(
            ["bash", str(repo / "scripts" / SCANNER.name), mode,
             str(tmp_path / "evidence")], cwd=repo,
            env={**env, "FAKE_LOG": log, "FAKE_RECEIPT": receipt,
                 "FAKE_REPORT": report}, capture_output=True, text=True,
            timeout=20,
        )
        calls = [json.loads(line) for line in
                 (tmp_path / "calls.jsonl").read_text().splitlines()]
        scans = [call for call in calls if any(
            arg.startswith("--report-path=") for arg in call)]
        assert len(scans) in (1, 2)
        assert any("/out/canary-" in arg for arg in scans[0])
        if len(scans) == 2:
            assert not any("/out/canary-" in arg for arg in scans[1])
        return result

    return repo, git, scan


def test_staged_incomplete_read(scan_repo):
    repo, git, scan = scan_repo
    (repo / "added.txt").write_text("ordinary staged text\n")
    git("add", "added.txt")
    # Enough following progress to exceed a pipe buffer: a quiet grep can
    # close early, give sed SIGPIPE under pipefail, and invert the verdict.
    result = scan(log="12:00PM ERR [git] fatal: unable to read staged input\n" +
                  "12:00PM INF ordinary progress\n" * 2500)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "scanner errors or unread input" in result.stderr


def test_staged_clean_positive(scan_repo):
    repo, git, scan = scan_repo
    (repo / "added.txt").write_text("ordinary staged text\n")
    git("add", "added.txt")
    result = scan()
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("receipt", ["", "scanned ~many bytes (unknown)",
                                    "scanned ~0 bytes (0) in 1ms"])
def test_staged_positive_requires_byte_receipt(scan_repo, receipt):
    repo, git, scan = scan_repo
    (repo / "added.txt").write_text("ordinary text\n")
    git("add", "added.txt")
    result = scan(receipt=receipt)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "byte receipt" in result.stderr or "read zero bytes" in result.stderr


@pytest.mark.parametrize("kind", ["empty-index", "deletion", "rename", "empty-file", "binary"])
def test_staged_zero_text_boundaries(scan_repo, kind):
    repo, git, scan = scan_repo
    name = "tabs\tand\nnewlines.txt"
    if kind in {"deletion", "rename"}:
        (repo / name).write_text("ordinary text\n")
        git("add", name)
        git("commit", "-qm", "base")
        if kind == "deletion":
            git("rm", name)
        else:
            git("mv", name, "new\tname\n.txt")
    elif kind in {"empty-file", "binary"}:
        (repo / name).write_bytes(b"" if kind == "empty-file" else b"\x00binary\n")
        git("add", name)
    result = scan(receipt="scanned ~0 bytes (0) in 1ms")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("metadata", ["failure", b"bad\t0\tfile\0",
                                      b"0\t0\t\0old\0", b"0\t0\tfile"])
def test_staged_metadata_failure_is_not_empty(scan_repo, metadata):
    _, _, scan = scan_repo
    result = scan(metadata=metadata, receipt="scanned ~0 bytes (0) in 1ms")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "staged input metadata" in result.stderr


def test_staged_copy_and_added_path_records(scan_repo):
    _, _, scan = scan_repo
    # Rename/copy records share Git's two-path grammar; the following text
    # addition must still be consumed, despite tabs/newlines in each path.
    result = scan(metadata=b"0\t0\t\0old\tpath\0new\npath\0" +
                  b"1\t0\tadded\tpath\n.txt\0",
                  receipt="scanned ~0 bytes (0) in 1ms")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "read zero bytes" in result.stderr


def test_worktree_requires_positive_input(scan_repo):
    _, _, scan = scan_repo
    result = scan("worktree", receipt="scanned ~0 bytes (0) in 1ms")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "read zero bytes" in result.stderr


@pytest.mark.parametrize("warning", ["skipping file: permission denied",
                                     'skipping directory error="permission denied"',
                                     'issue reading file error="I/O error"',
                                     'skipping error="stat failed"',
                                     "partial scan completed in 1ms"])
def test_worktree_unread_positive_input(scan_repo, warning):
    _, _, scan = scan_repo
    result = scan("worktree", log="12:00PM WRN " + warning)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "scanner errors or unread input" in result.stderr


def test_partial_history_despite_positive_counts(scan_repo):
    repo, git, scan = scan_repo
    for number in range(3):
        (repo / f"file{number}.txt").write_text("ordinary history\n")
        git("add", f"file{number}.txt")
        git("commit", "-qm", "history")
    result = scan("history", log="12:00PM INF 2 commits scanned\n"
                  "12:00PM ERR [git] fatal: partial walk")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "commits the scanner reported walking:  2" in result.stdout
    assert "scanner errors or unread input" in result.stderr


@pytest.mark.parametrize("report", ["<missing>", "{", "{}"])
def test_real_report_must_be_array(scan_repo, report):
    _, _, scan = scan_repo
    result = scan(report=report)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "no valid JSON-array report" in result.stderr


def test_warning_finding_summary_with_humanized_receipt(scan_repo):
    _, _, scan = scan_repo
    result = scan("worktree", log="12:00PM WRN leaks found: 0",
                  receipt="scanned ~2048 bytes (2 KB) in 1ms")
    assert result.returncode == 0, result.stdout + result.stderr
