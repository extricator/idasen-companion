#!/usr/bin/env python3
"""Validate and retire GitHub Actions release artifacts by exact run and ID."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def api(path, method="GET"):
    command = ["gh", "api", "--method", method, f"repos/{os.environ['GITHUB_REPOSITORY']}/{path}"]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run_provenance(run_id, sha, version, main_branch="main"):
    require(str(run_id).isdecimal() and int(run_id) > 0, "a positive source run ID is required")
    run = api(f"actions/runs/{run_id}")
    require(run["id"] == int(run_id), "source run ID differs")
    require(run["head_branch"] == main_branch, "source must be on main")
    require(run["head_sha"] == sha and run["status"] == "completed" and
            run["conclusion"] == "success", "source run must succeed at the release SHA")
    require(run.get("run_attempt") == 1, "rerun attempts cannot be promoted")
    main_ci = run["event"] == "push" and run.get("path") == ".github/workflows/ci.yml"
    dry_run = (run["event"] == "workflow_dispatch" and
               run.get("path") == ".github/workflows/release.yml")
    require(main_ci or dry_run, "source is not trusted main CI or a release dry run")
    jobs = api(f"actions/runs/{run_id}/jobs?per_page=100")["jobs"]
    require(len(jobs) < 100, "source has too many jobs for one-page proof")
    required = {"Tests / Python " + v for v in ("3.11", "3.12", "3.13", "3.14")}
    required |= {"Quality / Code", "Quality / Distribution and supply chain",
                 "Packages / RPM", "Packages / Debian", "Packages / Flatpak",
                 "Assemble and checksum the release assets"}
    required.add("Plan package proofs" if main_ci else
                 "The requested version agrees with __version__")
    for name in required:
        matches = [job for job in jobs if job["name"].endswith(name)]
        require(len(matches) == 1 and matches[0]["conclusion"] == "success",
                f"required source job did not succeed exactly once: {name}")
    if dry_run:
        publish = [job for job in jobs if job["name"].endswith("Publish the release")]
        require(len(publish) == 1 and publish[0]["conclusion"] == "skipped",
                "source was not a dry run")
    artifacts = api(f"actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    require(len(artifacts) < 100, "source has too many artifacts for one-page proof")
    matches = [a for a in artifacts if a["name"] == "release-assets"]
    require(len(matches) == 1 and not matches[0]["expired"] and matches[0]["size_in_bytes"] > 0,
            "source must have one live assembled artifact")
    require(matches[0]["workflow_run"]["id"] == int(run_id) and
            matches[0]["workflow_run"]["head_sha"] == sha,
            "artifact provenance differs from the selected run")
    return matches[0]["id"]


def asset_patterns(version):
    return [rf"idasen-companion-{re.escape(version)}-[^/]+\.rpm",
            rf"idasen-companion-headless-{re.escape(version)}-[^/]+\.rpm",
            rf"idasen-companion_{re.escape(version)}-[^/]+\.deb",
            rf"idasen-companion-headless_{re.escape(version)}-[^/]+\.deb",
            rf"idasen-companion-{re.escape(version)}\.flatpak"]


def assemble_assets(root, version, sha, run_id):
    root = Path(root)
    files = list((root / "artifacts").iterdir())
    names = {p.name for p in files}
    require(len(files) == 5 and all(p.is_file() and not p.is_symlink() for p in files),
            "release candidate must contain exactly five regular files")
    selected = []
    for pattern in asset_patterns(version):
        matches = [name for name in names if re.fullmatch(pattern, name)]
        require(len(matches) == 1, f"expected one asset matching {pattern}")
        selected.extend(matches)
    require(names == set(selected), "unexpected release candidate asset")

    subprocess.run(["bash", "scripts/verify-release-artifacts.sh", str(root / "artifacts")],
                   check=True)
    checksum = ""
    for name in selected:
        with (root / "artifacts" / name).open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        checksum += f"{digest}  {name}\n"
    (root / "artifacts" / "SHA256SUMS").write_text(checksum)

    notes = subprocess.run(["scripts/extract-changelog.sh", version], check=True,
                           capture_output=True, text=True).stdout
    notes += (f"\nInstallation and checksum verification: see the "
              f"[README](https://github.com/{os.environ['GITHUB_REPOSITORY']}"
              f"/blob/v{version}/README.md#install).\n")
    tags = subprocess.run(["git", "tag", "--list", "v*"], check=True,
                          capture_output=True, text=True).stdout.splitlines()
    ordered = subprocess.run(["sort", "-u", "-V", "-r"], check=True,
                             input="\n".join([*tags, f"v{version}"]) + "\n",
                             capture_output=True, text=True).stdout.splitlines()
    position = ordered.index(f"v{version}")
    if position + 1 < len(ordered):
        notes += (f"\n**Full changelog**: https://github.com/"
                  f"{os.environ['GITHUB_REPOSITORY']}/compare/"
                  f"{ordered[position + 1]}...v{version}\n")
    (root / "release-notes.md").write_text(notes)
    (root / "provenance.json").write_text(json.dumps(
        {"run_id": int(run_id), "sha": sha, "version": version, "candidate": True}))
    return validate_assets(root, version, sha, run_id)


def validate_assets(root, version, sha, run_id):
    root = Path(root)
    provenance = json.loads((root / "provenance.json").read_text())
    require(provenance == {"run_id": int(run_id), "sha": sha, "version": version,
                           "candidate": True}, "assembled provenance differs")
    notes = (root / "release-notes.md").read_text()
    require(notes.strip() and f"/blob/v{version}/README.md" in notes,
            "release notes are missing or name the wrong version")
    files = list((root / "artifacts").iterdir())
    require(all(p.is_file() and not p.is_symlink() for p in files), "non-file asset found")
    names = {p.name for p in files}
    selected = []
    for pattern in asset_patterns(version):
        matches = [name for name in names if re.fullmatch(pattern, name)]
        require(len(matches) == 1, f"expected one asset matching {pattern}")
        selected.extend(matches)
    require(names == set(selected) | {"SHA256SUMS"}, "unexpected asset in assembled set")
    checksum_lines = (root / "artifacts" / "SHA256SUMS").read_text().splitlines()
    checksums = {}
    for line in checksum_lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
        require(match is not None and match[2] not in checksums, "invalid checksum entry")
        checksums[match[2]] = match[1]
    require(set(checksums) == set(selected), "checksums do not name exactly five assets")
    for name in selected:
        file = root / "artifacts" / name
        digest = hashlib.sha256()
        with file.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        require(file.stat().st_size > 0 and digest.hexdigest() == checksums[name],
                f"asset checksum differs: {name}")
    return selected


def cleanup(run_id, names):
    require(str(run_id).isdecimal() and int(run_id) > 0, "invalid cleanup run ID")
    artifacts = api(f"actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    require(len(artifacts) < 100, "too many artifacts for safe cleanup")
    for artifact in artifacts:
        if artifact["name"] in names:
            require(artifact["workflow_run"]["id"] == int(run_id), "cleanup run mismatch")
            api(f"actions/artifacts/{artifact['id']}", "DELETE")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    provenance = sub.add_parser("provenance")
    provenance.add_argument("run_id")
    provenance.add_argument("sha")
    provenance.add_argument("version")
    assets = sub.add_parser("assets")
    assets.add_argument("directory")
    assets.add_argument("version")
    assets.add_argument("sha")
    assets.add_argument("run_id")
    assemble = sub.add_parser("assemble")
    assemble.add_argument("directory")
    assemble.add_argument("version")
    assemble.add_argument("sha")
    assemble.add_argument("run_id")
    retire = sub.add_parser("cleanup")
    retire.add_argument("run_id")
    retire.add_argument("names", nargs="+")
    args = parser.parse_args()
    if args.command == "provenance":
        print(run_provenance(args.run_id, args.sha, args.version))
    elif args.command == "assets":
        print("\n".join(validate_assets(args.directory, args.version, args.sha, args.run_id)))
    elif args.command == "assemble":
        print("\n".join(assemble_assets(args.directory, args.version, args.sha, args.run_id)))
    else:
        cleanup(args.run_id, set(args.names))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f"release asset validation failed: {error}", file=sys.stderr)
        sys.exit(1)
