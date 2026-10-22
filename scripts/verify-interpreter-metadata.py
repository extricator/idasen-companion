#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline exact-build inventory; explicit, digest-bound local archive refresh.

No interpreter or other code from an archive is ever executed. Source associations
identify bytes and components; they do not decide legal substitutability.
"""

import argparse
import ast
from contextlib import contextmanager
import fnmatch
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path("packaging/interpreter")
MAX_TEXT = 512 * 1024
MAX_METADATA = 1024 * 1024
MAX_MEMBER = 256 * 1024 * 1024
MAX_ARCHIVE_CONTENT = 2 * 1024 * 1024 * 1024
SOURCE_URL = "https://github.com/astral-sh/python-build-standalone"
ZSTD_MEMBER = "cpython-source-deps-zstd-1.5.7/LICENSE"
ZSTD_ASSET = "zstd-1.5.7.tar.gz"
ZSTD_URL = "https://github.com/python/cpython-source-deps/archive/refs/tags/zstd-1.5.7.tar.gz"
OPENSSL_NOTICE_SELECTION = {
    "source_commit": "38d35dcf0e212ca02eed8ebc11d0c92906387d56",
    "metadata_sha256": "8798ef645956bc2c91e6b2733ba26ffa59f6a15b7932de85c10c86fbfaf10685",
    "version": "3.5.7",
    "selected": "licenses/LICENSE.openssl-3.txt",
    "metadata_alternate": "licenses/LICENSE.openssl-1.1.txt",
    "evidence": "pythonbuild/downloads.py:267-274 and cpython-unix/build-openssl-3.5.sh at the reviewed source commit",
}
LIMITATIONS = [
    "Install-only archives omit PYTHON.json; metadata comes from the optimized full build.",
    "licenses/LICENSE.zstd.txt is absent from the full archive; use the digest-bound source LICENSE.",
    "licenses/LICENSE.zlib-ng.txt is absent: upstream alternate path, not a shipping component; Unix uses ordinary zlib.",
    "OpenSSL metadata retains both alternate paths; this reviewed build uses OpenSSL 3.5.7 and selects LICENSE.openssl-3.txt only.",
    "Source associations identify exact notices, not legal substitutability or a compliance finding.",
]


class MetadataError(ValueError):
    """An input cannot support the reviewed inventory."""


def require(condition, message):
    if not condition:
        raise MetadataError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(data):
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(data):
    try:
        return json.loads(data, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as exc:
        raise MetadataError(f"invalid JSON: {exc}") from exc


def safe_path(name):
    require(isinstance(name, str) and name and not name.startswith("/")
            and "\\" not in name and "\x00" not in name
            and all(part not in (".", "..", "") for part in name.rstrip("/").split("/")),
            f"unsafe member path: {name!r}")
    return str(PurePosixPath(name))


def strings(value, label, allow_empty=False):
    require(isinstance(value, list) and (allow_empty or value)
            and all(isinstance(item, str) and item for item in value)
            and len(set(value)) == len(value), f"invalid {label}")
    return value


def parse_fetcher_identity(path):
    text = Path(path).read_text()
    pins = {}
    for key in ("URL", "ASSET", "SHA256"):
        matches = re.findall(rf'^INTERPRETER_{key}="([^"\n]+)"$', text, re.M)
        require(len(matches) == 1, f"expected one literal INTERPRETER_{key}")
        pins[key.lower()] = matches[0]
    match = re.fullmatch(r"cpython-([0-9]+\.[0-9]+\.[0-9]+)\+([0-9]{8})-(x86_64-unknown-linux-gnu)-install_only_stripped.tar.gz", pins["asset"])
    require(match is not None, "unsupported install asset identity")
    version, release, target = match.groups()
    require(re.fullmatch(r"[0-9a-f]{64}", pins["sha256"]), "invalid install SHA256")
    url = f"{SOURCE_URL}/releases/download/{release}/{pins['asset'].replace('+', '%2B')}"
    require(pins["url"] == url, "install URL disagrees with asset/release")
    return dict(pins, python_version=version, release=release, target_triple=target,
                build_options="pgo+lto", full_asset=f"cpython-{version}+{release}-{target}-pgo+lto-full.tar.zst")


def trim_patterns(path):
    tree = ast.parse(Path(path).read_text())
    values = [ast.literal_eval(node.value) for node in tree.body
              if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "REMOVED" for target in node.targets)]
    require(len(values) == 1 and isinstance(values[0], dict), "missing literal trim REMOVED map")
    return strings(list(values[0]), "trim patterns")


def validate_metadata(metadata, identity):
    require(isinstance(metadata, dict) and metadata.get("version") == "8", "unsupported metadata schema (expected version 8)")
    for key in ("python_version", "target_triple", "build_options"):
        require(metadata.get(key) == identity[key], f"metadata {key} disagrees with optimized build identity")
    require(metadata.get("python_implementation_name") == "cpython", "metadata is not CPython")
    minor = ".".join(identity["python_version"].split(".")[:2])
    require(metadata.get("python_major_minor_version") == minor
            and metadata.get("python_exe") == f"install/bin/python{minor}", "metadata interpreter path/minor disagrees")
    strings(metadata.get("licenses"), "CPython licenses")
    safe_path(metadata.get("license_path"))
    build = metadata.get("build_info")
    require(isinstance(build, dict) and isinstance(build.get("extensions"), dict)
            and build["extensions"], "missing extension metadata")
    for name, variants in build["extensions"].items():
        require(isinstance(name, str) and isinstance(variants, list) and len(variants) == 1
                and isinstance(variants[0], dict) and variants[0].get("variant") == "default",
                f"unsupported extension variant: {name}")
        links = variants[0].get("links")
        require(isinstance(links, list) and all(isinstance(link, dict)
                and isinstance(link.get("name"), str) for link in links), f"invalid links: {name}")


def derive_components(metadata, install_members, patterns):
    """Select licensed dependency records; absence of shared_lib means built-in."""
    require(isinstance(install_members, list) and install_members == sorted(set(install_members)),
            "invalid install membership")
    members = set(install_members)
    for path in members:
        safe_path(path)
    binary = f"python/bin/python{metadata['python_major_minor_version']}"
    require(binary in members, "missing installed interpreter evidence for built-ins")
    selected, excluded = {}, {}
    for name, variants in sorted(metadata["build_info"]["extensions"].items()):
        record = variants[0]
        dependencies = sorted(link["name"] for link in record["links"] if not link.get("system", False))
        if not dependencies and "licenses" not in record and "license_public_domain" not in record:
            continue
        terms = strings(record.get("licenses"), f"{name} licenses", allow_empty=True)
        public_domain = record.get("license_public_domain")
        require(type(public_domain) is bool and (terms or public_domain), f"unknown licensing for {name}")
        paths = strings(record.get("license_paths"), f"{name} license_paths")
        for path in paths:
            safe_path(path)
        shared = record.get("shared_lib")
        matches = []
        if shared is not None:
            safe_path(shared)
            require(shared.startswith("install/"), f"unsupported shared path for {name}")
            relative = shared.removeprefix("install/")
            require(f"python/{relative}" in members, f"missing installed shared extension: {name}")
            matches = [pattern for pattern in patterns if fnmatch.fnmatchcase(relative, pattern)]
        component = {"dependencies": dependencies, "licenses": sorted(terms),
                     "license_public_domain": public_domain, "license_paths": sorted(paths),
                     "shared_lib": shared}
        if matches:
            excluded[name] = dict(component, trim_patterns=matches)
        else:
            selected[name] = component
    terms = sorted(set(metadata["licenses"]).union(*(record["licenses"] for record in selected.values())))
    return {"components": selected, "excluded": excluded, "terms": terms,
            "cpython": {"licenses": metadata["licenses"], "license_path": metadata["license_path"]},
            "build_only": ["setuptools"]}


def load_snapshot(root=ROOT):
    base = Path(root) / SNAPSHOT
    raw = (base / "PYTHON.json").read_bytes()
    require(len(raw) <= MAX_METADATA, "oversized PYTHON.json")
    provenance = read_json((base / "PROVENANCE.json").read_bytes())
    require(isinstance(provenance, dict) and provenance.get("schema") == 1, "unsupported provenance schema")
    require(provenance.get("metadata") == {"member": "python/PYTHON.json", "sha256": digest(raw), "size": len(raw)},
            "PYTHON.json hash/size disagrees with reviewed provenance")
    return read_json(raw), provenance


def selected_notice_paths(paths, metadata_sha256, source_commit):
    """Apply the one reviewed OpenSSL alternate-path choice for this exact build."""
    require(metadata_sha256 == OPENSSL_NOTICE_SELECTION["metadata_sha256"]
            and source_commit == OPENSSL_NOTICE_SELECTION["source_commit"],
            "OpenSSL notice selection needs review for this exact build")
    return set(paths) - {OPENSSL_NOTICE_SELECTION["metadata_alternate"]}


def verify_metadata(root=ROOT):
    root = Path(root)
    metadata, provenance = load_snapshot(root)
    identity = parse_fetcher_identity(root / "scripts/fetch-bundled-runtime.sh")
    require(provenance.get("identity") == identity, "fetcher identity disagrees with reviewed snapshot; refresh metadata")
    require(re.fullmatch(r"[0-9a-f]{40}", provenance.get("source_commit", "")), "invalid release source commit")
    require(provenance.get("source_url") == f"{SOURCE_URL}/tree/{provenance['source_commit']}"
            and provenance.get("zstd_source_url") == ZSTD_URL, "source URL disagrees with reviewed identity")
    validate_metadata(metadata, identity)
    archives = provenance.get("archives", {})
    require(isinstance(archives, dict), "invalid archive provenance")
    for key, asset in (("install", identity["asset"]), ("full", identity["full_asset"]), ("zstd", ZSTD_ASSET)):
        entry = archives.get(key, {})
        require(isinstance(entry, dict) and entry.get("asset") == asset and type(entry.get("size")) is int and entry["size"] > 0
                and re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")), f"invalid {key} archive provenance")
    require(archives["install"]["sha256"] == identity["sha256"], "install archive hash disagrees with fetcher")
    patterns = trim_patterns(root / "scripts/trim-cpython.py")
    require(patterns == provenance.get("trim_patterns"), "actual trim rules changed; refresh metadata")
    inventory = derive_components(metadata, provenance.get("install_members"), patterns)
    require(inventory == provenance.get("inventory"), "retained components/terms disagree with reviewed inventory")
    # This is a narrow check of the owned staging call, not an RPM parser.
    spec = (root / "packaging/idasen-companion-bundled.spec").read_text()
    backend = re.findall(r"^%\{install_driver\} -m pip install --no-index --find-links build-backend \\\n([^\n]+)", spec, re.M)
    require(len(backend) == 1 and "--target" not in backend[0]
            and "build-backend/*.whl" in backend[0], "build-only backend staging changed")
    require(provenance.get("limitations") == LIMITATIONS, "source limitations changed")
    require(provenance.get("openssl_notice_selection") == OPENSSL_NOTICE_SELECTION,
            "OpenSSL notice selection disagrees with reviewed build evidence")
    expected_paths = {metadata["license_path"]}
    for record in inventory["components"].values():
        expected_paths.update(record["license_paths"])
    expected_paths.discard("licenses/LICENSE.zlib-ng.txt")
    expected_paths = selected_notice_paths(expected_paths, provenance["metadata"]["sha256"], provenance["source_commit"])
    notices = provenance.get("notices", {})
    require(isinstance(notices, dict) and set(notices) == expected_paths, "missing/unexpected source notice associations")
    for path, notice in notices.items():
        fallback = path == "licenses/LICENSE.zstd.txt"
        require(isinstance(notice, dict) and notice.get("archive") == ("zstd" if fallback else "full")
                and notice.get("member") == (ZSTD_MEMBER if fallback else f"python/{path}")
                and notice.get("file") == f"packaging/licenses/interpreter/{PurePosixPath(path).name}"
                and type(notice.get("size")) is int and 0 < notice["size"] <= MAX_TEXT
                and re.fullmatch(r"[0-9a-f]{64}", notice.get("sha256", "")), f"invalid notice association: {path}")
    return inventory, provenance


def verify_notice_sources(root=ROOT, components=()):
    inventory, provenance = verify_metadata(root)
    require(components, "specify at least one --component")
    paths = set()
    for name in components:
        require(name == "cpython" or name in inventory["components"], f"unknown retained component: {name}")
        paths.update([inventory["cpython"]["license_path"]] if name == "cpython"
                     else inventory["components"][name]["license_paths"])
    paths.discard("licenses/LICENSE.zlib-ng.txt")
    paths = selected_notice_paths(paths, provenance["metadata"]["sha256"], provenance["source_commit"])
    for path in sorted(paths):
        notice = provenance["notices"][path]
        raw = (Path(root) / notice["file"]).read_bytes()
        require(len(raw) == notice["size"] and digest(raw) == notice["sha256"], f"source notice bytes disagree: {path}")
    return len(paths)


@contextmanager
def archive_stream(path):
    """Only explicit refresh calls this; offline verification imports no decoder."""
    if str(path).endswith(".zst"):
        try:
            from compression import zstd  # pylint: disable=import-outside-toplevel
        except ImportError:
            with tempfile.TemporaryFile() as errors:
                with subprocess.Popen(["zstd", "-dc", "--", str(path)], stdout=subprocess.PIPE, stderr=errors) as process:
                    try:
                        yield process.stdout
                    except BaseException:
                        process.stdout.close()
                        process.terminate()
                        process.wait()
                        raise
                    require(process.wait() == 0, "zstd failed to decode complete archive")
        else:
            with zstd.open(path, "rb") as stream:
                yield stream
    elif str(path).endswith(".gz"):
        with gzip.open(path, "rb") as stream:
            yield stream
    else:
        with Path(path).open("rb") as stream:
            yield stream


def read_archive(path, wanted, collect_install=False):
    """Inspect complete tar stream; never extract paths or follow archive links."""
    found, installed, seen = {}, [], set()
    total = 0
    with archive_stream(path) as stream:
        with tarfile.open(fileobj=stream, mode="r|*") as archive:
            for member in archive:
                name = safe_path(member.name)
                require(name not in seen, f"duplicate archive member: {name}")
                seen.add(name)
                require(len(seen) <= 50000, "too many archive members")
                total += member.size
                require(0 <= member.size <= MAX_MEMBER and total <= MAX_ARCHIVE_CONTENT, f"oversized archive member/content: {name}")
                require(member.isfile() or member.isdir() or member.issym() or member.islnk(), f"special archive member: {name}")
                if name in wanted:
                    require(member.isfile(), f"accepted member is not a regular file: {name}")
                    require(member.size <= wanted[name], f"oversized accepted member: {name}")
                    raw = archive.extractfile(member).read(wanted[name] + 1)
                    require(len(raw) == member.size, f"truncated member: {name}")
                    found[name] = raw
                if collect_install and name in collect_install:
                    require(member.isfile(), f"install evidence is not a regular file: {name}")
                    installed.append(name)
        # Read past tar end markers to verify the compression trailer as well.
        while stream.read(1024 * 1024):
            total += 1024 * 1024
            require(total <= MAX_ARCHIVE_CONTENT, "oversized trailing archive content")
    require(set(wanted) <= set(found), f"missing archive members: {sorted(set(wanted) - set(found))}")
    if collect_install:
        require(set(installed) == set(collect_install), "missing installed interpreter/shared extension members")
    return found, sorted(installed)


def checked_archive(path, expected_hash, expected_size, asset):
    require(re.fullmatch(r"[0-9a-f]{64}", expected_hash or ""), f"invalid reviewed hash: {asset}")
    with Path(path).open("rb") as stream:
        require(Path(path).stat().st_size == expected_size and expected_size > 0,
                f"archive size disagrees: {asset}")
        require(hashlib.file_digest(stream, "sha256").hexdigest() == expected_hash, f"archive hash disagrees: {asset}")
    return {"asset": asset, "sha256": expected_hash, "size": expected_size}


def refresh(args):
    identity = parse_fetcher_identity(args.root / "scripts/fetch-bundled-runtime.sh")
    require(args.release == identity["release"], "reviewed release disagrees with fetcher")
    require(re.fullmatch(r"[0-9a-f]{40}", args.source_commit), "invalid reviewed source commit")
    require(args.install_sha256 == identity["sha256"], "reviewed install hash disagrees with fetcher")
    archives = {}
    for key, asset in (("install", identity["asset"]), ("full", identity["full_asset"]), ("zstd", ZSTD_ASSET)):
        archives[key] = checked_archive(getattr(args, f"{key}_archive"), getattr(args, f"{key}_sha256"), getattr(args, f"{key}_size"), asset)
    # All complete archive digests pass before any accepted member is read.
    full, _ = read_archive(args.full_archive, {"python/PYTHON.json": MAX_METADATA})
    raw = full["python/PYTHON.json"]
    require(len(raw) == args.metadata_size and digest(raw) == args.metadata_sha256, "reviewed metadata hash/size disagrees")
    metadata = read_json(raw)
    validate_metadata(metadata, identity)
    relevant = {f"python/bin/python{metadata['python_major_minor_version']}"}
    for variants in metadata["build_info"]["extensions"].values():
        record = variants[0]
        if "licenses" in record or any(not link.get("system", False) for link in record["links"]):
            if record.get("shared_lib"):
                relevant.add("python/" + record["shared_lib"].removeprefix("install/"))
    _, installed = read_archive(args.install_archive, {}, relevant)
    patterns = trim_patterns(args.root / "scripts/trim-cpython.py")
    inventory = derive_components(metadata, installed, patterns)
    paths = {metadata["license_path"]}
    for component in inventory["components"].values():
        paths.update(component["license_paths"])
    # Exact upstream alternate-path gap; Unix build uses ordinary zlib.
    paths.discard("licenses/LICENSE.zlib-ng.txt")
    paths = selected_notice_paths(paths, digest(raw), args.source_commit)
    paths.discard("licenses/LICENSE.zstd.txt")
    full_notices, _ = read_archive(args.full_archive, {f"python/{path}": MAX_TEXT for path in paths})
    source, _ = read_archive(args.zstd_archive, {ZSTD_MEMBER: MAX_TEXT})
    require(digest(source[ZSTD_MEMBER]) == args.zstd_license_sha256, "reviewed Zstandard LICENSE hash disagrees")
    notices = {}
    for path in sorted(paths | {"licenses/LICENSE.zstd.txt"}):
        fallback = path == "licenses/LICENSE.zstd.txt"
        member = ZSTD_MEMBER if fallback else f"python/{path}"
        data = source[member] if fallback else full_notices[member]
        notices[path] = {"archive": "zstd" if fallback else "full", "member": member,
                         "sha256": digest(data), "size": len(data),
                         "file": f"packaging/licenses/interpreter/{PurePosixPath(path).name}"}
    provenance = {"schema": 1, "identity": identity, "source_commit": args.source_commit,
                  "source_url": f"{SOURCE_URL}/tree/{args.source_commit}", "zstd_source_url": ZSTD_URL,
                  "archives": archives, "metadata": {"member": "python/PYTHON.json", "sha256": digest(raw), "size": len(raw)},
                  "install_members": installed, "trim_patterns": patterns, "inventory": inventory,
                  "notices": notices, "limitations": LIMITATIONS,
                  "openssl_notice_selection": OPENSSL_NOTICE_SELECTION}
    # All validation and archive reads finish before creating/replacing outputs.
    args.output.mkdir(parents=True, exist_ok=True)
    for name, data in (("PYTHON.json", raw), ("PROVENANCE.json", json_bytes(provenance))):
        with tempfile.NamedTemporaryFile(dir=args.output, delete=False) as temporary:
            temporary.write(data)
            pending = Path(temporary.name)
        pending.replace(args.output / name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify-metadata")
    notices = commands.add_parser("verify-notices")
    notices.add_argument("--component", action="append", required=True)
    update = commands.add_parser("refresh")
    for key in ("install", "full", "zstd"):
        update.add_argument(f"--{key}-archive", type=Path, required=True)
        update.add_argument(f"--{key}-sha256", required=True)
        update.add_argument(f"--{key}-size", type=int, required=True)
    update.add_argument("--metadata-sha256", required=True)
    update.add_argument("--metadata-size", type=int, required=True)
    update.add_argument("--zstd-license-sha256", required=True)
    update.add_argument("--release", required=True)
    update.add_argument("--source-commit", required=True)
    update.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "refresh":
            refresh(args)
            print(f"Refreshed reviewed snapshot: {args.output}")
        elif args.command == "verify-notices":
            count = verify_notice_sources(args.root, args.component)
            print(f"Verified {count} exact source notices")
        else:
            inventory, _ = verify_metadata(args.root)
            print(f"Verified exact interpreter metadata: {len(inventory['components'])} retained extensions, {len(inventory['terms'])} terms; notice bytes checked separately")
        return 0
    except (MetadataError, OSError, ValueError, TypeError, KeyError, tarfile.TarError, EOFError) as exc:
        print(f"interpreter-metadata: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
