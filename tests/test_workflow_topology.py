"""Executable contracts for the GitHub Actions planner and aggregate checks."""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
pytestmark = pytest.mark.skipif(not WORKFLOWS.is_dir(), reason="workflows are omitted from sdists")


@pytest.fixture(autouse=True)
def no_real_subprocesses():
    """This module runs only git and bash against disposable fixtures."""


def workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def plan_for(tmp_path, paths, *, event="pull_request", action="synchronize",
             draft="false", before=None, mode="", prior_paths=()):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "ci@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "CI"], check=True)
    (tmp_path / "base.txt").write_text("base")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    for path in prior_paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("prior change")
    if prior_paths:
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "prior change"], check=True)
    prior_head = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("changed")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "change"], check=True)
    head = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    step = workflow("ci.yml")["jobs"]["plan"]["steps"][1]
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    env = os.environ | step["env"] | {
        "EVENT_NAME": event,
        "EVENT_ACTION": action,
        "PR_DRAFT": draft,
        "PR_BASE": base,
        "PR_HEAD": head,
        "UPDATE_BEFORE": before if before is not None else prior_head,
        "UPDATE_AFTER": head,
        "MODE": mode,
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    subprocess.run(["bash", "-e", "-c", step["run"]], cwd=tmp_path, env=env, check=True)
    return dict(line.split("=", 1) for line in output.read_text().splitlines())


@pytest.mark.parametrize(("paths", "expected"), [
    (["docs/note.md", "src/idasen_companion/example.py", "tests/test_example.py"], set()),
    (["packaging/idasen-companion-bundled.spec"], {"rpm"}),
    (["debian/control"], {"deb"}),
    (["packaging/flatpak/python3-deps.json"], {"flatpak"}),
    (["scripts/verify-rpm-portability.sh"], {"rpm", "rpm_portability"}),
    (["scripts/build-release-variants.sh"], {"rpm", "deb", "flatpak"}),
    (["data/icons/app.svg"], {"rpm", "deb", "flatpak"}),
])
def test_planner_path_classes(tmp_path, paths, expected):
    result = plan_for(tmp_path, paths)
    assert {key for key, value in result.items() if value == "true"} == expected


def test_draft_pr_defers_packages_then_ready_event_rechecks_full_diff(tmp_path):
    assert all(value == "false" for value in plan_for(tmp_path / "draft", ["debian/control"], draft="true").values())
    result = plan_for(tmp_path / "ready", ["debian/control"], action="ready_for_review")
    assert result["deb"] == "true"


def test_unavailable_update_falls_back_to_full_pr_diff(tmp_path):
    result = plan_for(tmp_path, ["packaging/flatpak/python3-deps.json"], before="0" * 40)
    assert result["flatpak"] == "true"


def test_synchronize_ignores_package_changes_from_earlier_updates(tmp_path):
    result = plan_for(tmp_path, ["docs/readme.md"], prior_paths=["debian/control"])
    assert all(value == "false" for value in result.values())


def test_main_and_manual_modes(tmp_path):
    assert all(value == "true" for value in plan_for(tmp_path / "main", ["docs/readme.md"], event="push").values())
    core = plan_for(tmp_path / "core", ["debian/control"], event="workflow_dispatch", mode="core")
    assert all(value == "false" for value in core.values())
    portability = plan_for(tmp_path / "portability", ["docs/readme.md"], event="workflow_dispatch", mode="rpm-portability")
    assert {key for key, value in portability.items() if value == "true"} == {"rpm", "rpm_portability"}


def test_reusable_topology_and_release_keep_all_package_proofs():
    assert {p.name for p in WORKFLOWS.glob("*.yml")} == {
        "ci.yml", "full-ci.yml", "verify.yml", "packages.yml", "release.yml"
    }
    for name in ("verify.yml", "packages.yml"):
        assert set(workflow(name)["on"]) == {"workflow_call"}
    release = workflow("release.yml")
    assert release["jobs"]["packages"]["with"] == {
        "rpm": "true", "deb": "true", "flatpak": "true", "rpm_portability": "true"
    }
    assert "packages" in release["jobs"]["package"]["needs"]
    assert "verify" in release["jobs"]["package"]["needs"]
    assert release["jobs"]["verify"]["uses"] == "./.github/workflows/verify.yml"


def test_release_modes_are_explicit_and_publishing_requires_proofs():
    release = workflow("release.yml")
    gate = release["jobs"]["gate"]
    resolve = next(step for step in gate["steps"] if step.get("id") == "resolve")["run"]
    assert "MODE=promote" in resolve and "MODE=rebuild" in resolve
    assert "Select exactly one real-release mode" in resolve
    publish = release["jobs"]["publish"]
    assert "needs.promote.result == 'success'" in publish["if"]
    for job in ("verify", "packages", "package"):
        assert f"needs.{job}.result == 'success'" in publish["if"]
    assert publish["permissions"] == {"contents": "write"}
    assert release["jobs"]["promote"]["permissions"] == {
        "contents": "read", "actions": "read"}
    assert release["jobs"]["cleanup"]["permissions"]["actions"] == "write"


def test_main_ci_assembles_candidate_before_retiring_package_artifacts():
    ci = workflow("ci.yml")
    candidate = ci["jobs"]["candidate"]
    assert candidate["if"] == "github.event_name == 'push'"
    assert set(candidate["needs"]) == {"plan", "verify", "packages"}
    assert candidate["name"] == "Assemble and checksum the release assets"
    assert any("release-assets.py assemble" in step.get("run", "")
               for step in candidate["steps"])
    upload = next(step for step in candidate["steps"] if step.get("with", {}).get("name") ==
                  "release-assets")
    assert int(upload["with"]["retention-days"]) == 1
    cleanup = ci["jobs"]["cleanup"]
    assert "candidate" in cleanup["needs"]
    assert "needs.candidate.result == 'success'" in cleanup["if"]
    assert "release-assets" not in cleanup["steps"][0]["run"]


def test_every_runnable_job_has_a_timeout():
    for name in ("ci.yml", "full-ci.yml", "verify.yml", "packages.yml", "release.yml"):
        for job in workflow(name)["jobs"].values():
            if "runs-on" in job:
                assert int(job["timeout-minutes"]) > 0


def test_ci_ok_requires_approval_or_label_and_successful_callers():
    full = workflow("full-ci.yml")
    gate = full["jobs"]["gate"]["steps"][0]["run"]
    assert '"$REVIEW_STATE" == approved' in gate
    assert '"$REVIEW_COMMIT" == "$head"' in gate
    assert '"$decision" == APPROVED' in gate
    assert '"$EVENT_ACTION" == labeled && "$LABEL_NAME" == full-ci' in gate
    aggregate = full["jobs"]["ci-ok"]
    assert aggregate["if"] == "always()"
    assert set(aggregate["needs"]) == {"gate", "verify", "packages", "candidate"}
    run = aggregate["steps"][0]["run"]
    for result in ("GATE_RESULT", "VERIFY_RESULT", "PACKAGES_RESULT", "CANDIDATE_RESULT"):
        assert re.search(rf'"\${result}" == success', run)
    candidate = full["jobs"]["candidate"]
    assert candidate["name"] == "Verify release assembly"
    assert set(candidate["needs"]) == {"gate", "verify", "packages"}
    assert any("release-assets.py assemble" in step.get("run", "")
               for step in candidate["steps"])
    assert workflow("ci.yml")["jobs"]["pr-ci"]["name"] == "PR CI"
    assert "ci-ok" not in workflow("ci.yml")["jobs"]


@pytest.mark.parametrize(("required", "packages_result", "should_pass"), [
    ("false", "skipped", True),
    ("false", "success", True),
    ("false", "failure", False),
    ("true", "success", True),
    ("true", "skipped", False),
    ("true", "failure", False),
])
def test_pr_ci_accepts_only_expected_package_caller_result(required, packages_result, should_pass):
    """A draft's empty package caller skips; a selected proof must succeed."""
    step = workflow("ci.yml")["jobs"]["pr-ci"]["steps"][0]
    env = os.environ | {
        "PLAN_RESULT": "success",
        "VERIFY_RESULT": "success",
        "PACKAGES_RESULT": packages_result,
        "PACKAGE_REQUIRED": required,
    }
    result = subprocess.run(["bash", "-e", "-c", step["run"]], env=env, check=False)
    assert (result.returncode == 0) is should_pass
