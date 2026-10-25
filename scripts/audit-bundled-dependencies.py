#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Look up advisories for exact bundled Python pins without resolving packages."""

import html
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pin_pairs(pins):
    """Validate exact requirements and reject repeated normalized names."""
    pairs = {}
    if not pins:
        raise ValueError("empty inventory")
    for pin in pins:
        if not isinstance(pin, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*==[0-9][A-Za-z0-9.!+_-]*", pin,
        ):
            raise ValueError(f"not an exact name/version pin: {pin!r}")
        name, version = pin.split("==")
        name = re.sub(r"[-_.]+", "-", name).lower()
        if name in pairs:
            raise ValueError(f"duplicate package: {name}")
        pairs[name] = version
    return pairs


def shell_pins(source, variable):
    """Read a constrained shell array as data; never execute shell text."""
    if len(re.findall(rf"^{variable}(?:\+)?=", source, re.M)) != 1:
        raise ValueError(f"expected one {variable} assignment")
    matches = re.findall(
        rf"^{variable}=\((.*?)\)[ \t]*(?:#[^\n]*)?$", source, re.M | re.S,
    )
    if len(matches) != 1:
        raise ValueError(f"expected one {variable} array")
    pins = shlex.split(matches[0], comments=True)
    pin_pairs(pins)
    return pins


def flatpak_pins(source):
    """Read the generated Flatpak install command, rejecting unknown syntax."""
    payload = json.loads(source)
    commands = payload.get("build-commands") if isinstance(payload, dict) else None
    if not isinstance(commands, list) or len(commands) != 1 or not isinstance(commands[0], str):
        raise ValueError("expected one Flatpak install command")
    tokens = shlex.split(commands[0])
    if tokens[:2] != ["pip3", "install"]:
        raise ValueError("expected pip3 install")
    options = {
        "--no-index", "--find-links=file://${PWD}", "--prefix=${FLATPAK_DEST}",
        "--no-build-isolation", "--no-deps",
    }
    pins = [token for token in tokens[2:] if token not in options]
    pin_pairs(pins)
    return pins


def audit_inventory(pins):
    """Return (status, report), requiring a complete exact-version response."""
    expected = pin_pairs(pins)
    with tempfile.TemporaryDirectory(prefix="idasen-pin-audit-") as temporary:
        requirements = Path(temporary) / "requirements.txt"
        output = Path(temporary) / "audit.json"
        requirements.write_text("\n".join(pins) + "\n", encoding="utf-8")
        command = [
            sys.executable, "-m", "pip_audit", "-r", str(requirements),
            "--no-deps", "--disable-pip", "--format", "json", "-o", str(output),
            "--progress-spinner", "off", "--timeout", "15",
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=100, check=False,
        )
        diagnostics = "\n".join(filter(None, [result.stdout, result.stderr])).strip()
        try:
            if result.returncode not in (0, 1):
                raise ValueError(f"pip-audit exited {result.returncode}")
            payload = json.loads(output.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("dependencies"), list):
                raise ValueError("missing dependencies array")
            observed = {}
            findings = []
            for dependency in payload["dependencies"]:
                if not isinstance(dependency, dict):
                    raise ValueError("malformed dependency record")
                if "skip_reason" in dependency:
                    raise ValueError(f"unaudited package: {dependency}")
                name = dependency.get("name")
                version = dependency.get("version")
                if not isinstance(name, str) or not isinstance(version, str):
                    raise ValueError("missing dependency name/version")
                pair = pin_pairs([f"{name}=={version}"])
                normalized = next(iter(pair))
                if normalized in observed:
                    raise ValueError(f"duplicate audit result: {normalized}")
                observed.update(pair)
                vulnerabilities = dependency.get("vulns")
                if not isinstance(vulnerabilities, list):
                    raise ValueError(f"missing vulnerability list: {name}")
                for vulnerability in vulnerabilities:
                    if not isinstance(vulnerability, dict):
                        raise ValueError("malformed advisory")
                    identifier = vulnerability.get("id")
                    fixes = vulnerability.get("fix_versions")
                    if not isinstance(identifier, str) or not identifier or not isinstance(fixes, list):
                        raise ValueError("missing advisory ID/fix versions")
                    if not all(isinstance(fix, str) and fix for fix in fixes):
                        raise ValueError("malformed advisory fix versions")
                    findings.append(f"{name}=={version}: {identifier}; fixes: {', '.join(fixes) or 'none listed'}")
            if observed != expected:
                raise ValueError(f"incomplete or mismatched inventory: expected {expected}, received {observed}")
            if result.returncode != int(bool(findings)):
                raise ValueError("pip-audit exit status contradicts its findings")
            status = int(bool(findings))
            report = "\n".join(findings) or f"No known advisories for all {len(pins)} exact pins."
        except (OSError, ValueError) as error:
            status, report = 2, str(error)
        if diagnostics:
            report += "\npip-audit diagnostics:\n" + diagnostics
        return status, report


def main(root=ROOT):
    """Print labeled reports and append the same evidence to Actions summary."""
    status = 0
    reports = []
    fetcher = root / "scripts/fetch-bundled-runtime.sh"
    inventories = [
        ("RPM shipped", fetcher, lambda source: shell_pins(source, "PINS")),
        ("RPM build backend", fetcher, lambda source: shell_pins(source, "BUILD_BACKEND")),
        ("Flatpak installed", root / "packaging/flatpak/python3-deps.json", flatpak_pins),
    ]
    for label, path, extract in inventories:
        try:
            pins = extract(path.read_text(encoding="utf-8"))
            result, detail = audit_inventory(pins)
            detail = "Requested pins:\n" + "\n".join(pins) + "\n" + detail
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            result, detail = 2, str(error)
        state = ["CLEAN", "VULNERABLE", "ERROR"][result]
        report = f"{label}: {state}\n{detail}"
        print(report, flush=True)
        reports.append(report)
        status = max(status, result)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with Path(summary).open("a", encoding="utf-8") as stream:
                stream.write("## Exact bundled Python dependency audit\n\n")
                for report in reports:
                    stream.write("<pre>" + html.escape(report) + "</pre>\n\n")
        except OSError as error:
            print(f"Summary: ERROR\n{error}", file=sys.stderr)
            return 2
    return status


if __name__ == "__main__":
    sys.exit(main())
