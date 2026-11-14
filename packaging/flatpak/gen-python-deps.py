#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regenerate packaging/flatpak/python3-deps.json.

Resolves the runtime dependency closure for the Flatpak runtime's Python
(CPython 3.13, x86_64 manylinux — org.kde.Platform//6.11) and emits a
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
TOP = ["Babel==2.18.0", "idasen==0.14.0", "bleak==3.1.0",
       "dbus-fast==5.2.0", "PyYAML==6.0.3", "tomlkit==0.15.2"]

OUT = Path(__file__).with_name("python3-deps.json")


def checked_sources(wheels: Path, metadata) -> tuple[list, list]:
    """Require precisely the reviewed closure and PyPI's complete byte identities."""
    sources, pkgs = [], []
    expected = {pin.lower().replace("-", "_") for pin in TOP}
    observed = set()
    for whl in sorted(wheels.iterdir()):
        if not whl.is_file() or whl.is_symlink() or whl.suffix != ".whl":
            raise ValueError(f"unexpected source: {whl.name}")
        parts = whl.name.split("-")
        if len(parts) < 5:
            raise ValueError(f"invalid wheel: {whl.name}")
        name, version = parts[:2]
        pin = f"{name.lower()}=={version}"
        if pin not in expected or pin in observed:
            raise ValueError(f"unexpected or duplicate wheel: {whl.name}")
        observed.add(pin)
        local_sha = hashlib.sha256(whl.read_bytes()).hexdigest()
        match = next((f for f in metadata(name, version) if f["filename"] == whl.name), None)
        if not match or match["digests"]["sha256"] != local_sha or match["size"] != whl.stat().st_size:
            raise ValueError(f"wheel bytes differ from PyPI: {whl.name}")
        sources.append({"type": "file", "url": match["url"], "sha256": local_sha})
        pkgs.append(f"{name}=={version}")
    if observed != expected:
        raise ValueError(f"missing wheels: {sorted(expected - observed)}")
    return sources, pkgs


def pypi_files(name: str, version: str) -> list:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json") as response:
        return json.load(response)["urls"]


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
        sources, pkgs = checked_sources(wheels, pypi_files)

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
