# SPDX-License-Identifier: GPL-3.0-or-later
"""Release promotion rejects unproved runs and altered asset sets."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "release-assets.py"
spec = importlib.util.spec_from_file_location("release_assets", SCRIPT)
release_assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_assets)


def source_fixture():
    required = ["Tests / Python " + v for v in ("3.11", "3.12", "3.13", "3.14")]
    required += ["Quality / Code", "Quality / Distribution and supply chain",
                 "Packages / RPM", "Packages / Debian", "Packages / Flatpak",
                 "The requested version agrees with __version__",
                 "Assemble and checksum the release assets"]
    run = {"id": 123, "event": "workflow_dispatch", "head_branch": "main",
           "head_sha": "a" * 40, "status": "completed", "conclusion": "success",
           "run_attempt": 1, "path": ".github/workflows/release.yml"}
    jobs = {"jobs": [{"name": name, "conclusion": "success"} for name in required] +
            [{"name": "Publish the release", "conclusion": "skipped"}]}
    assembly = next(job for job in jobs["jobs"] if
                    job["name"] == "Assemble and checksum the release assets")
    assembly.update(started_at="2026-11-01T04:00:00Z", completed_at="2026-11-01T04:05:00Z")
    artifacts = {"artifacts": [{"id": 7, "name": "release-assets", "expired": False,
                               "size_in_bytes": 100, "created_at": "2026-11-01T04:04:00Z",
                               "workflow_run": {"id": 123, "head_sha": "a" * 40}}]}
    return run, jobs, artifacts


def test_provenance_requires_successful_exact_main_dry_run(monkeypatch):
    run, jobs, artifacts = source_fixture()
    monkeypatch.setattr(release_assets, "api", lambda path: run if path == "actions/runs/123"
                        else jobs if "/jobs?" in path else artifacts)
    assert release_assets.run_provenance("123", "a" * 40, "1.2.0") == 7
    for mutation, value in [("head_sha", "b" * 40), ("head_branch", "feature"),
                            ("conclusion", "failure"), ("run_attempt", 0)]:
        old = run[mutation]
        run[mutation] = value
        with pytest.raises(ValueError):
            release_assets.run_provenance("123", "a" * 40, "1.2.0")
        run[mutation] = old
    jobs["jobs"][0]["conclusion"] = "skipped"
    with pytest.raises(ValueError, match="required source job"):
        release_assets.run_provenance("123", "a" * 40, "1.2.0")


def test_retry_accepts_successful_jobs_and_assembly_carried_forward(monkeypatch):
    run, jobs, artifacts = source_fixture()
    run["run_attempt"] = 3
    # A later cleanup retry retains earlier proof times and the existing bundle.
    jobs["jobs"][0].update(started_at="2026-10-31T23:00:00Z",
                           completed_at="2026-10-31T23:01:00Z")

    def fake_api(path):
        if path == "actions/runs/123":
            return run
        if "/jobs?" in path:
            assert path == "actions/runs/123/jobs?filter=latest&per_page=100"
            return jobs
        return artifacts

    monkeypatch.setattr(release_assets, "api", fake_api)
    assert release_assets.run_provenance("123", "a" * 40, "1.2.0") == 7


@pytest.mark.parametrize("created_at", ["2026-11-01T03:59:59Z", "2026-11-01T04:05:01Z"])
def test_candidate_must_come_from_successful_assembly_window(monkeypatch, created_at):
    run, jobs, artifacts = source_fixture()
    run["run_attempt"] = 2
    artifacts["artifacts"][0]["created_at"] = created_at
    monkeypatch.setattr(release_assets, "api", lambda path: run if path == "actions/runs/123"
                        else jobs if "/jobs?" in path else artifacts)
    with pytest.raises(ValueError, match="successful assembly job"):
        release_assets.run_provenance("123", "a" * 40, "1.2.0")


def test_source_rerun_started_during_validation_is_rejected(monkeypatch):
    run, jobs, artifacts = source_fixture()
    reads = 0

    def fake_api(path):
        nonlocal reads
        if path == "actions/runs/123":
            reads += 1
            return run if reads == 1 else run | {"run_attempt": 2, "status": "in_progress"}
        return jobs if "/jobs?" in path else artifacts

    monkeypatch.setattr(release_assets, "api", fake_api)
    with pytest.raises(ValueError, match="source run changed"):
        release_assets.run_provenance("123", "a" * 40, "1.2.0")


def test_asset_manifest_requires_exact_names_hashes_and_candidate_provenance(tmp_path):
    root = tmp_path
    files = ["idasen-companion-1.2.0-1.x86_64.rpm",
             "idasen-companion-headless-1.2.0-1.x86_64.rpm",
             "idasen-companion_1.2.0-1_amd64.deb",
             "idasen-companion-headless_1.2.0-1_amd64.deb",
             "idasen-companion-1.2.0.flatpak"]
    (root / "artifacts").mkdir()
    for name in files:
        (root / "artifacts" / name).write_bytes(name.encode())
    (root / "artifacts" / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(name.encode()).hexdigest()}  {name}\n" for name in files))
    (root / "provenance.json").write_text(json.dumps(
        {"run_id": 123, "sha": "a" * 40, "version": "1.2.0", "candidate": True}))
    (root / "release-notes.md").write_text(
        "Notes\nhttps://github.com/owner/repo/blob/v1.2.0/README.md")
    assert set(release_assets.validate_assets(root, "1.2.0", "a" * 40, "123")) == set(files)
    (root / "artifacts" / files[0]).write_bytes(b"altered")
    with pytest.raises(ValueError, match="checksum"):
        release_assets.validate_assets(root, "1.2.0", "a" * 40, "123")
    (root / "artifacts" / files[0]).write_bytes(files[0].encode())
    (root / "artifacts" / "unexpected").write_bytes(b"extra")
    with pytest.raises(ValueError, match="unexpected asset"):
        release_assets.validate_assets(root, "1.2.0", "a" * 40, "123")


def test_provenance_accepts_only_complete_main_ci_candidate(monkeypatch):
    run, jobs, artifacts = source_fixture()
    run.update(event="push", path=".github/workflows/ci.yml")
    jobs["jobs"] = [job for job in jobs["jobs"] if job["name"] not in {
        "The requested version agrees with __version__", "Publish the release"}]
    jobs["jobs"].append({"name": "Plan package proofs", "conclusion": "success"})
    monkeypatch.setattr(release_assets, "api", lambda path: run if path == "actions/runs/123"
                        else jobs if "/jobs?" in path else artifacts)
    assert release_assets.run_provenance("123", "a" * 40, "1.2.0") == 7
    for mutation, value in [("event", "pull_request"), ("head_branch", "feature"),
                            ("path", ".github/workflows/other.yml")]:
        old = run[mutation]
        run[mutation] = value
        with pytest.raises(ValueError):
            release_assets.run_provenance("123", "a" * 40, "1.2.0")
        run[mutation] = old
    jobs["jobs"][-1]["conclusion"] = "skipped"
    with pytest.raises(ValueError, match="required source job"):
        release_assets.run_provenance("123", "a" * 40, "1.2.0")
    jobs["jobs"][-1]["conclusion"] = "success"
    artifacts["artifacts"][0]["expired"] = True
    with pytest.raises(ValueError, match="one live assembled artifact"):
        release_assets.run_provenance("123", "a" * 40, "1.2.0")


def test_assemble_main_candidate_reuses_five_packages(tmp_path, monkeypatch):
    files = ["idasen-companion-1.2.0-1.x86_64.rpm",
             "idasen-companion-headless-1.2.0-1.x86_64.rpm",
             "idasen-companion_1.2.0-1_all.deb",
             "idasen-companion-headless_1.2.0-1_all.deb",
             "idasen-companion-1.2.0.flatpak"]
    directory = tmp_path / "artifacts"
    directory.mkdir()
    for name in files:
        (directory / name).write_bytes(name.encode())
    smoke_calls = []

    def mock_smoke(command, **kwargs):
        if command[:2] == ["bash", "scripts/verify-release-artifacts.sh"]:
            smoke_calls.append(command)
            return subprocess.CompletedProcess(command, 0)
        if command[0] == "scripts/extract-changelog.sh":
            return subprocess.CompletedProcess(command, 0, stdout="## [1.2.0] - Test\nRelease notes.\n")
        if command[:2] == ["git", "tag"]:
            return subprocess.CompletedProcess(command, 0, stdout="v1.1.0\nv1.2.0\n")
        if command[0] == "sort":
            return subprocess.CompletedProcess(command, 0, stdout="v1.2.0\nv1.1.0\n")
        raise AssertionError(f"unexpected subprocess: {command}")

    monkeypatch.setattr(release_assets.subprocess, "run", mock_smoke)
    monkeypatch.setenv("GITHUB_REPOSITORY", "extricator/idasen-companion")
    assert set(release_assets.assemble_assets(tmp_path, "1.2.0", "a" * 40, "123")) == set(files)
    assert len(smoke_calls) == 1
    assert json.loads((tmp_path / "provenance.json").read_text())["candidate"] is True
    assert len((directory / "SHA256SUMS").read_text().splitlines()) == 5


def test_cleanup_deletes_only_named_artifacts_from_named_run(monkeypatch):
    _, _, artifacts = source_fixture()
    artifacts["artifacts"].append({"id": 8, "name": "unrelated",
                                   "workflow_run": {"id": 123}})
    deleted = []
    def fake_api(path, method="GET"):
        if method == "DELETE":
            deleted.append(path)
        else:
            return artifacts
    monkeypatch.setattr(release_assets, "api", fake_api)
    release_assets.cleanup("123", {"release-assets"})
    assert deleted == ["actions/artifacts/7"]
