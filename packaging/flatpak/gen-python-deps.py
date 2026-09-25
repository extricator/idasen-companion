#!/usr/bin/env python3
"""Regenerate packaging/flatpak/python3-deps.json.

Resolves the runtime dependency closure for the Flatpak runtime's Python
(CPython 3.13, x86_64 manylinux — org.kde.Platform//6.10) and emits a
flatpak-builder 'simple' module that pip-installs those wheels offline from
their canonical pythonhosted URL + sha256.

PySide6 is deliberately excluded — it comes from io.qt.PySide.BaseApp, not pip.

Usage (host needs network + pip):
    python3 packaging/flatpak/gen-python-deps.py

Bump the pins here if pyproject.toml's runtime deps change.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# The app's runtime deps from pyproject.toml [project.dependencies] (minus
# PySide6, which the BaseApp provides). Downloaded with --no-deps: idasen's
# own packaging metadata declares a hard dependency that exists solely for
# its optional CLI submodule (idasen.cli) — this app only ever imports
# idasen.IdasenDesk from the top-level package and never touches that
# submodule, so pulling that dependency in offline would be dead weight.
# Every package this project actually needs is already named here
# explicitly.
TOP = ["Babel", "idasen", "bleak", "dbus-fast", "PyYAML", "tomlkit"]

OUT = Path(__file__).with_name("python3-deps.json")


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        wheels = Path(td)
        subprocess.run(
            [sys.executable, "-m", "pip", "download", "--dest", str(wheels),
             "--only-binary=:all:", "--no-deps",
             "--python-version", "313", "--implementation", "cp",
             "--abi", "cp313",
             "--platform", "manylinux2014_x86_64",
             "--platform", "manylinux_2_17_x86_64",
             "--platform", "manylinux_2_28_x86_64",
             *TOP],
            check=True,
        )
        sources, pkgs = [], []
        for whl in sorted(wheels.glob("*.whl")):
            name, version = whl.name.split("-")[0], whl.name.split("-")[1]
            local_sha = hashlib.sha256(whl.read_bytes()).hexdigest()
            api = f"https://pypi.org/pypi/{name}/{version}/json"
            with urllib.request.urlopen(api) as r:
                files = json.load(r)["urls"]
            match = next(f for f in files if f["filename"] == whl.name)
            assert match["digests"]["sha256"] == local_sha, whl.name
            sources.append(
                {"type": "file", "url": match["url"], "sha256": local_sha})
            pkgs.append(f"{name}=={version}")

    module = {
        "name": "python3-deps",
        "buildsystem": "simple",
        "build-commands": [
            'pip3 install --no-index --find-links="file://${PWD}" '
            "--prefix=${FLATPAK_DEST} --no-build-isolation --no-deps "
            + " ".join(pkgs)
        ],
        "sources": sources,
    }
    OUT.write_text(json.dumps(module, indent=4) + "\n")
    print(f"wrote {OUT} with {len(sources)} wheels")


if __name__ == "__main__":
    main()
