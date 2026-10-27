# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline content and publication boundaries for bundled wheels."""

import hashlib
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUN = subprocess.run


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def fetch_project(tmp_path):
    """Run the real shell orchestration with tiny offline tool boundaries."""
    project = tmp_path / "project"
    for directory in ("scripts", "packaging", "src/idasen_companion", "bin", "fixtures"):
        (project / directory).mkdir(parents=True)
    (project / "src/idasen_companion/__init__.py").write_text('__version__ = "1.0"\n')
    (project / "scripts/verify-interpreter-metadata.py").write_text("# unrelated gate\n")
    helper = ROOT / "scripts/bundled-wheel-hashes.py"
    if helper.exists():
        shutil.copy2(helper, project / "scripts" / helper.name)
    groups = {"runtime": {}, "build-backend": {}}
    for group, filename in (("runtime", "alpha_pkg-1.0-py3-none-any.whl"),
                            ("build-backend", "backend-2.0-py3-none-any.whl")):
        directory = project / "fixtures" / group
        directory.mkdir()
        wheel = directory / filename
        wheel.write_bytes(group.encode())
        groups[group][filename] = digest(wheel)
    (project / "packaging/bundled-wheel-hashes.json").write_text(json.dumps({
        "schema": 1, **groups,
    }))
    interpreter = tmp_path / "python3.14"
    interpreter.write_text(f"#!{sys.executable}\n" + '''import json, os, pathlib, shutil, sys
args = sys.argv[1:]
dest = pathlib.Path(args[args.index("--dest") + 1])
group = "build-backend" if dest.name == "build-backend" else "runtime"
requirements = pathlib.Path(args[args.index("--requirement") + 1]).read_text() if "--requirement" in args else None
with open("pip-calls.jsonl", "a") as stream:
    stream.write(json.dumps({"args": args, "requirements": requirements}) + "\\n")
for wheel in (pathlib.Path("fixtures") / group).iterdir():
    shutil.copyfile(wheel, dest / wheel.name)
''')
    interpreter.chmod(0o755)
    archive = project / "fixtures/interpreter.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(interpreter, arcname="python/bin/python3.14")
    fetcher = (ROOT / "scripts/fetch-bundled-runtime.sh").read_text()
    fetcher = re.sub(r'^INTERPRETER_SHA256="[a-f0-9]+"',
                     f'INTERPRETER_SHA256="{digest(archive)}"', fetcher, flags=re.M)
    fetcher = re.sub(r'^PINS=\(.*?^\)', 'PINS=(\n    "alpha-pkg==1.0"\n)', fetcher,
                     flags=re.M | re.S)
    fetcher = re.sub(r'^BUILD_BACKEND=\(.*?^\)', 'BUILD_BACKEND=(\n    "backend==2.0"\n)',
                     fetcher, flags=re.M | re.S)
    (project / "scripts/fetch-bundled-runtime.sh").write_text(fetcher)
    curl = project / "bin/curl"
    curl.write_text(f"#!{sys.executable}\n" + '''import pathlib, shutil, sys
shutil.copyfile("fixtures/interpreter.tar.gz", sys.argv[sys.argv.index("-o") + 1])
''')
    curl.chmod(0o755)
    return project


def run_fetch(project, monkeypatch):
    monkeypatch.setattr(subprocess, "run", RUN)
    return RUN(["bash", str(project / "scripts/fetch-bundled-runtime.sh"), str(project / "output")],
               env={**os.environ, "PYTHON": sys.executable,
                    "PATH": str(project / "bin") + os.pathsep + os.environ["PATH"]},
               capture_output=True, text=True, check=False)


def test_happy_path_hashes_both_groups_before_publication(fetch_project, monkeypatch):
    result = run_fetch(fetch_project, monkeypatch)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in (fetch_project / "pip-calls.jsonl").read_text().splitlines()]
    assert len(calls) == 2
    for call in calls:
        assert all(flag in call["args"] for flag in
                   ("--only-binary=:all:", "--no-deps", "--require-hashes", "--requirement"))
        assert not any(arg.startswith("--index") or arg == "--python-version" for arg in call["args"])
        assert "--hash=sha256:" in call["requirements"]
    with tarfile.open(fetch_project / "output/idasen-companion-wheels-1.0.tar.gz") as bundle:
        assert {member.name for member in bundle if member.isfile()} == {
            "wheels/alpha_pkg-1.0-py3-none-any.whl", "build-backend/backend-2.0-py3-none-any.whl",
        }


@pytest.fixture
def catalog_case(tmp_path):
    helper = runpy.run_path(str(ROOT / "scripts/bundled-wheel-hashes.py"))
    directory = tmp_path / "wheels"
    directory.mkdir()
    wheel = directory / "alpha_pkg-1.0-py3-none-any.whl"
    wheel.write_bytes(b"approved wheel")
    catalog = {"schema": 1, "runtime": {wheel.name: digest(wheel)},
               "build-backend": {"backend-2.0-py3-none-any.whl": "b" * 64}}
    return helper, catalog, directory, wheel


@pytest.mark.parametrize("fault", ["duplicate-key", "schema", "basename", "digest", "cross-group"])
def test_catalog_rejects_ambiguous_or_unsafe_input(catalog_case, tmp_path, fault):
    helper, catalog, _directory, wheel = catalog_case
    if fault == "schema":
        catalog["unknown"] = {}
    elif fault == "basename":
        catalog["runtime"]["../" + wheel.name] = catalog["runtime"].pop(wheel.name)
    elif fault == "digest":
        catalog["runtime"][wheel.name] = "not a sha256"
    elif fault == "cross-group":
        catalog["build-backend"] = dict(catalog["runtime"])
    raw = json.dumps(catalog)
    if fault == "duplicate-key":
        raw = raw.replace('"schema": 1', '"schema": 1, "schema": 1')
    path = tmp_path / "catalog.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        helper["load_catalog"](path)


@pytest.mark.parametrize("pins", [["alpha-pkg==2.0"], ["alpha-pkg==1.0", "missing==1"],
                                  ["alpha-pkg==1.0", "Alpha_Pkg==1.0"]])
def test_catalog_requires_exact_complete_unique_pins(catalog_case, pins):
    helper, catalog, _directory, _wheel = catalog_case
    destination = io.StringIO("preserve existing input\n")
    with pytest.raises(ValueError):
        helper["prepare"](catalog, "runtime", pins, destination)
    assert destination.getvalue() == "preserve existing input\n"


def test_approved_alternatives_emit_all_hashes_but_accept_only_one(catalog_case):
    helper, catalog, directory, wheel = catalog_case
    alternate = directory / "alpha_pkg-1.0-cp314-cp314-manylinux_2_41_x86_64.whl"
    alternate.write_bytes(b"approved alternative")
    catalog["runtime"][alternate.name] = digest(alternate)
    destination = io.StringIO()
    helper["prepare"](catalog, "runtime", ["alpha-pkg==1.0"], destination)
    assert destination.getvalue().split() == ["alpha-pkg==1.0"] + [
        "--hash=sha256:" + value for value in sorted(catalog["runtime"].values())]
    with pytest.raises(ValueError, match="multiple wheels"):
        helper["verify"](catalog, "runtime", ["alpha-pkg==1.0"], directory)
    original_bytes = wheel.read_bytes()
    wheel.unlink()
    helper["verify"](catalog, "runtime", ["alpha-pkg==1.0"], directory)
    alternate.unlink()
    wheel.write_bytes(original_bytes)
    helper["verify"](catalog, "runtime", ["alpha-pkg==1.0"], directory)


@pytest.mark.parametrize("fault,message", [("bytes", "SHA256 mismatch"),
                                           ("rename", "unapproved wheel"),
                                           ("symlink", "non-symlink"),
                                           ("directory", "non-symlink"),
                                           ("missing", "missing downloaded pins")])
def test_downloaded_content_must_match_exact_identity(catalog_case, fault, message):
    helper, catalog, directory, wheel = catalog_case
    if fault == "bytes":
        wheel.write_bytes(wheel.read_bytes() + b"tampered")
    elif fault == "rename":
        wheel.rename(directory / "alpha_pkg-1.0-1-py3-none-any.whl")
    elif fault == "symlink":
        target = directory.parent / "outside.whl"
        wheel.rename(target)
        wheel.symlink_to(target)
    elif fault == "directory":
        wheel.unlink()
        wheel.mkdir()
    else:
        wheel.unlink()
    with pytest.raises(ValueError, match=message):
        helper["verify"](catalog, "runtime", ["alpha-pkg==1.0"], directory)


@pytest.mark.parametrize("group", ["runtime", "build-backend"])
def test_neither_output_is_published_when_either_group_fails(fetch_project, monkeypatch, group):
    wheel = next((fetch_project / "fixtures" / group).iterdir())
    wheel.write_bytes(b"unexpected arriving bytes")
    output = fetch_project / "output"
    output.mkdir()
    sentinel = output / "idasen-companion-wheels-1.0.tar.gz"
    sentinel.write_bytes(b"previous output")
    result = run_fetch(fetch_project, monkeypatch)
    assert result.returncode != 0 and "SHA256 mismatch" in result.stderr
    assert sentinel.read_bytes() == b"previous output"
    assert list(output.iterdir()) == [sentinel]
