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
(out / Path(report).name).write_text("[{}]" if canary else "[]")
print("\\x1b[32m12:00PM INF scanned ~18 bytes (18 bytes) in 1ms\\x1b[0m")
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

    def scan(mode="staged", *, log="12:00PM INF no leaks found"):
        result = _REAL_RUN(
            ["bash", str(repo / "scripts" / SCANNER.name), mode,
             str(tmp_path / "evidence")], cwd=repo,
            env={**env, "FAKE_LOG": log}, capture_output=True, text=True,
            timeout=20,
        )
        calls = [json.loads(line) for line in
                 (tmp_path / "calls.jsonl").read_text().splitlines()]
        scans = [call for call in calls if any(
            arg.startswith("--report-path=") for arg in call)]
        assert len(scans) == 2
        assert any("/out/canary-" in arg for arg in scans[0])
        assert not any("/out/canary-" in arg for arg in scans[1])
        return result

    return repo, git, scan


def test_staged_incomplete_read(scan_repo):
    repo, git, scan = scan_repo
    (repo / "added.txt").write_text("ordinary staged text\n")
    git("add", "added.txt")
    result = scan(log="12:00PM ERR [git] fatal: unable to read staged input")
    assert result.returncode != 0, result.stdout + result.stderr


def test_staged_clean_positive(scan_repo):
    repo, git, scan = scan_repo
    (repo / "added.txt").write_text("ordinary staged text\n")
    git("add", "added.txt")
    result = scan()
    assert result.returncode == 0, result.stdout + result.stderr
