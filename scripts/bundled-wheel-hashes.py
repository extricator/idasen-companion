#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Consume reviewed wheel identities; never approve newly downloaded bytes."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

GROUPS = ("runtime", "build-backend")


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def pin_pairs(pins):
    """Keep the caller's exact versions as the only version authority."""
    pairs = {}
    if not pins:
        raise ValueError("empty pin inventory")
    for pin in pins:
        if not isinstance(pin, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*+==[0-9][A-Za-z0-9.!+_]*+", pin,
        ):
            raise ValueError(f"not an exact name/version pin: {pin!r}")
        name, version = pin.split("==")
        name = normalized(name)
        if name in pairs:
            raise ValueError(f"duplicate pin: {name}")
        pairs[name] = version
    return pairs


def wheel_pair(filename):
    """Read identity only; pip remains responsible for compatibility selection."""
    parts = filename.removesuffix(".whl").split("-")
    if not filename.endswith(".whl") or len(parts) not in (5, 6):
        raise ValueError(f"invalid wheel basename: {filename!r}")
    name, version, *tags = parts
    build = tags.pop(0) if len(tags) == 4 else None
    if (not re.fullmatch(r"[A-Za-z0-9_]++", name)
            or not re.fullmatch(r"[0-9][A-Za-z0-9_.!+]*+", version)
            or (build is not None and not re.fullmatch(r"[0-9][A-Za-z0-9_]*+", build))
            or not all(re.fullmatch(r"[A-Za-z0-9_.]++", tag) for tag in tags)):
        raise ValueError(f"invalid wheel basename: {filename!r}")
    return normalized(name), version


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate catalog key: {key}")
        result[key] = value
    return result


def load_catalog(path):
    """Validate the entire bounded catalog, including the unselected group."""
    with Path(path).open("rb") as stream:
        return read_catalog(stream)


def read_catalog(stream):
    """Read a bounded catalog from a caller-opened input."""
    raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("wheel catalog exceeds 1 MiB")
    catalog = json.loads(raw, object_pairs_hook=unique_object)
    if (not isinstance(catalog, dict) or set(catalog) != {"schema", *GROUPS}
            or type(catalog["schema"]) is not int or catalog["schema"] != 1):
        raise ValueError("expected wheel catalog schema 1 and exactly runtime/build-backend groups")
    owners = {}
    for group in GROUPS:
        entries = catalog[group]
        if not isinstance(entries, dict) or not 0 < len(entries) <= 1000:
            raise ValueError(f"{group}: expected a nonempty wheel map (at most 1000 entries)")
        for filename, digest in entries.items():
            name, _version = wheel_pair(filename)
            if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError(f"{group}: invalid SHA256 for {filename}")
            if name in owners and owners[name] != group:
                raise ValueError(f"package appears across groups: {name}")
            owners[name] = group
    return catalog


def approved_wheels(catalog, group, pins):
    """Require every pin and only its exact version in the selected group."""
    expected = pin_pairs(pins)
    entries = catalog[group]
    observed = set()
    for filename in entries:
        name, version = wheel_pair(filename)
        if expected.get(name) != version:
            raise ValueError(f"{group}: unpinned or stale catalog wheel: {filename}")
        observed.add(name)
    missing = set(expected) - observed
    if missing:
        raise ValueError(f"{group}: missing catalog pins: {', '.join(sorted(missing))}")
    return entries


def prepare(catalog, group, pins, output):
    """Write complete approved requirements to a caller-owned stream."""
    entries = approved_wheels(catalog, group, pins)
    lines = []
    for pin in pins:
        name = normalized(pin.split("==")[0])
        hashes = sorted({digest for filename, digest in entries.items()
                         if wheel_pair(filename)[0] == name})
        lines.append(pin + "".join(f" --hash=sha256:{digest}" for digest in hashes))
    output.write("\n".join(lines) + "\n")


def verify(catalog, group, pins, directory):
    """Reject extras, links, wrong identities/bytes and incomplete closure."""
    entries = approved_wheels(catalog, group, pins)
    expected = pin_pairs(pins)
    observed = set()
    for wheel in sorted(directory.iterdir()):
        if wheel.is_symlink() or not wheel.is_file():
            raise ValueError(f"{group}: not a regular non-symlink wheel: {wheel.name}")
        if wheel.name not in entries:
            raise ValueError(f"{group}: unapproved wheel basename: {wheel.name}")
        name, _version = wheel_pair(wheel.name)
        if name in observed:
            raise ValueError(f"{group}: multiple wheels for pin: {name}")
        with wheel.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != entries[wheel.name]:
            raise ValueError(f"{group}: SHA256 mismatch: {wheel.name}")
        observed.add(name)
    missing = set(expected) - observed
    if missing:
        raise ValueError(f"{group}: missing downloaded pins: {', '.join(sorted(missing))}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify"))
    parser.add_argument("--catalog", required=True, type=argparse.FileType("rb"))
    parser.add_argument("--group", required=True, choices=GROUPS)
    parser.add_argument("--pin", required=True, action="append")
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    if args.command == "prepare" and args.directory is not None:
        parser.error("prepare writes requirements to stdout and accepts no --directory")
    if args.command == "verify" and args.directory is None:
        parser.error("verify needs --directory")
    try:
        with args.catalog:
            catalog = read_catalog(args.catalog)
        if args.command == "prepare":
            prepare(catalog, args.group, args.pin, sys.stdout)
        else:
            verify(catalog, args.group, args.pin, args.directory)
    except (OSError, ValueError, RecursionError) as error:
        print(f"wheel hashes: {error}", file=sys.stderr)
        return 2
    print(f"wheel hashes: {args.command} {args.group} OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
