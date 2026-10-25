# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline contracts for exact bundled-pin advisory lookup."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

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
        'PINS=("Example_Pkg==1.2.3")\n', encoding="utf-8",
    )
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    def fake_run(command, **_kwargs):
        assert "--no-deps" in command and "--disable-pip" in command
        assert "--fix" not in command
        requirements = Path(command[command.index("-r") + 1]).read_text()
        assert requirements == "Example_Pkg==1.2.3\n"
        if payload is not None:
            Path(command[command.index("-o") + 1]).write_text(
                payload if isinstance(payload, str) else json.dumps(payload),
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
