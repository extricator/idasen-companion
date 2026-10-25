# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline contracts for exact bundled-pin advisory lookup."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/audit-bundled-dependencies.py"


def load_audit():
    """Load the shipped entrypoint without running its CLI."""
    assert SCRIPT.is_file(), "The exact-pin audit entrypoint must exist"
    spec = importlib.util.spec_from_file_location("dependency_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rpm_inventory_is_extracted_without_executing_source(tmp_path):
    audit = load_audit()
    sentinel = tmp_path / "executed"
    source = f'PINS=(\n "Example_Pkg==1.2.3" # a pin\n)\ntouch {sentinel}\n'
    assert audit.shell_pins(source, "PINS") == ["Example_Pkg==1.2.3"]
    assert not sentinel.exists()
    for invalid in (
        "", "PINS=()", 'PINS=("pkg>=1")',
        'PINS=("pkg==1" "PKG==2")', 'PINS=("pkg==$(touch x)")',
        'PINS=("pkg==1")\nPINS=("other==2")', 'PINS=("pkg==1"',
    ):
        with pytest.raises(ValueError):
            audit.shell_pins(invalid, "PINS")


@pytest.mark.parametrize("returncode,payload,status,word", [
    (0, {"dependencies": [{"name": "example-pkg", "version": "1.2.3", "vulns": []}]}, 0, "CLEAN"),
    (1, {"dependencies": [{"name": "example-pkg", "version": "1.2.3", "vulns": [{"id": "PYSEC-TEST", "fix_versions": ["2"]}]}]}, 1, "VULNERABLE"),
    (2, {"dependencies": []}, 2, "ERROR"),
    (0, "invalid json", 2, "ERROR"),
    (0, None, 2, "ERROR"),
    (0, {"dependencies": []}, 2, "ERROR"),
    (0, {"dependencies": [{"name": "example-pkg", "skip_reason": "unsupported"}]}, 2, "ERROR"),
    (0, {"dependencies": [{"name": "example-pkg", "version": "9", "vulns": []}]}, 2, "ERROR"),
    (1, {"dependencies": [{"name": "example-pkg", "version": "1.2.3", "vulns": []}]}, 2, "ERROR"),
    (0, {"dependencies": [{"name": "example-pkg", "version": "1.2.3", "vulns": [{}]}]}, 2, "ERROR"),
])
def test_audit_outcomes_distinguish_clean_findings_and_errors(
    tmp_path, monkeypatch, capsys, returncode, payload, status, word,
):
    audit = load_audit()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/fetch-bundled-runtime.sh").write_text(
        'PINS=("Example_Pkg==1.2.3")\nBUILD_BACKEND=("Backend_Pkg==1.2.3")\n',
        encoding="utf-8",
    )
    flatpak = tmp_path / "packaging/flatpak"
    flatpak.mkdir(parents=True)
    (tmp_path / "packaging/bundled-wheel-hashes.json").write_text(json.dumps({
        "schema": 1,
        "runtime": {"example_pkg-1.2.3-py3-none-any.whl": "a" * 64},
        "build-backend": {"backend_pkg-1.2.3-py3-none-any.whl": "b" * 64},
    }))
    (flatpak / "python3-deps.json").write_text(json.dumps({
        "build-commands": ['pip3 install --no-index --find-links="file://${PWD}" --prefix=${FLATPAK_DEST} --no-build-isolation --no-deps Example_Pkg==1.2.3'],
    }))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    def fake_run(command, **_kwargs):
        assert "--no-deps" in command and "--disable-pip" in command
        assert "--fix" not in command
        requirements = Path(command[command.index("-r") + 1]).read_text()
        assert requirements in ("Example_Pkg==1.2.3\n", "Backend_Pkg==1.2.3\n")
        if payload is not None:
            report = payload if isinstance(payload, str) else json.dumps(payload)
            if requirements.startswith("Backend_Pkg"):
                report = report.replace("example-pkg", "backend-pkg")
            Path(command[command.index("-o") + 1]).write_text(
                report,
            )
        return subprocess.CompletedProcess(command, returncode, "", "diagnostic")

    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    assert audit.main(tmp_path) == status
    output = capsys.readouterr().out
    assert f"RPM shipped: {word}" in output
    assert f"RPM shipped: {word}" in summary.read_text()
    if status:
        assert "CLEAN" not in output
    if status == 1:
        assert "PYSEC-TEST" in output and "2" in output


def test_inventories_preserve_provenance_and_report_all_results(monkeypatch, capsys):
    audit = load_audit()
    source = (ROOT / "scripts/fetch-bundled-runtime.sh").read_text()
    rpm = audit.shell_pins(source, "PINS")
    backend = audit.shell_pins(source, "BUILD_BACKEND")
    flatpak = audit.flatpak_pins((ROOT / "packaging/flatpak/python3-deps.json").read_text())
    assert any(pin.startswith("PySide6-Essentials==") for pin in rpm)
    assert any(pin.startswith("setuptools==") for pin in backend)
    assert not any(pin.startswith("setuptools==") for pin in rpm)
    assert any(pin.startswith("dbus_fast==") for pin in flatpak)
    assert any(pin.startswith("dbus-fast==") for pin in rpm)
    seen = []

    def fake_audit(pins):
        seen.append(pins)
        return [(1, "finding"), (0, "complete"), (2, "unavailable")][len(seen) - 1]

    monkeypatch.setattr(audit, "audit_inventory", fake_audit)
    assert audit.main(ROOT) == 2
    assert seen == [rpm, backend, flatpak]
    output = capsys.readouterr().out
    assert "RPM shipped: VULNERABLE" in output
    assert "RPM build backend: CLEAN" in output
    assert "Flatpak installed: ERROR" in output


def test_flatpak_inventory_rejects_missing_or_unpinned_installation():
    audit = load_audit()
    for commands in ([], ["echo hello"], ["pip3 install pkg"],
                     ["pip3 install pkg==1 pkg==2"], ["pip3 install pkg==1 && echo hidden"],
                     ["pip3 install pkg==1", "pip3 install other==2"]):
        with pytest.raises(ValueError):
            audit.flatpak_pins(json.dumps({"build-commands": commands}))
    with pytest.raises(ValueError):
        audit.flatpak_pins("not json")


def test_missing_sources_report_every_inventory_as_error(tmp_path, monkeypatch, capsys):
    audit = load_audit()

    def forbidden_run(*_args, **_kwargs):
        pytest.fail("Missing inventory must not launch the audit tool")

    monkeypatch.setattr(audit.subprocess, "run", forbidden_run)
    assert audit.main(tmp_path) == 2
    output = capsys.readouterr().out
    for label in ("RPM shipped", "RPM build backend", "Flatpak installed"):
        assert f"{label}: ERROR" in output
    assert "CLEAN" not in output


def test_stale_wheel_catalog_blocks_rpm_audit_and_preserves_other_reports(
    tmp_path, monkeypatch, capsys,
):
    audit = load_audit()
    for relative in ("scripts/fetch-bundled-runtime.sh", "packaging/flatpak/python3-deps.json",
                     "packaging/bundled-wheel-hashes.json"):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    catalog_path = tmp_path / "packaging/bundled-wheel-hashes.json"
    catalog = json.loads(catalog_path.read_text())
    del catalog["runtime"][next(iter(catalog["runtime"]))]
    catalog_path.write_text(json.dumps(catalog))
    seen = []

    def fake_audit(pins):
        seen.append(pins)
        return 0, "complete"

    monkeypatch.setattr(audit, "audit_inventory", fake_audit)
    assert audit.main(tmp_path) == 2
    assert seen == [audit.shell_pins((tmp_path / "scripts/fetch-bundled-runtime.sh").read_text(),
                                    "BUILD_BACKEND"),
                    audit.flatpak_pins((tmp_path / "packaging/flatpak/python3-deps.json").read_text())]
    output = capsys.readouterr().out
    assert "RPM shipped: ERROR" in output and "missing catalog pins" in output
    assert "RPM build backend: CLEAN" in output and "Flatpak installed: CLEAN" in output


@pytest.mark.skipif(not (ROOT / ".github/workflows").is_dir(),
                    reason="Workflows are intentionally excluded from the sdist")
def test_weekly_audit_is_read_only_advisory_and_bounded():
    workflow = ROOT / ".github/workflows/dependency-audit.yml"
    assert workflow.is_file(), "The weekly advisory workflow must exist"
    config = yaml.load(workflow.read_text(), Loader=yaml.BaseLoader)
    assert config["on"] == {"schedule": [{"cron": "17 9 * * 1"}], "workflow_dispatch": ""}
    assert config["permissions"] == {"contents": "read"}
    assert len(config["jobs"]) == 1
    job = config["jobs"]["audit"]
    assert job["runs-on"] == "ubuntu-latest"
    assert 0 < int(job["timeout-minutes"]) <= 10
    assert "permissions" not in job and "continue-on-error" not in job
    steps = job["steps"]
    assert [step["uses"].split("@")[0] for step in steps if "uses" in step] == [
        "actions/checkout", "actions/setup-python",
    ]
    assert [step["run"] for step in steps if "run" in step] == [
        "python -m pip install --disable-pip-version-check pip-audit==2.10.1",
        "python scripts/audit-bundled-dependencies.py",
    ]
    assert not any("continue-on-error" in step or "if" in step for step in steps)
