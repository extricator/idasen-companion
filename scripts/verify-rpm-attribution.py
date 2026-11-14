#!/usr/bin/env python3
"""Verify the reviewed Qt 6.12 RPM attribution snapshot offline.

Publisher target relationships are conservative attribution, not proof that
every listed source unit was compiled. --payload-root checks the PySide6 tree
before packaging by default. --payload-stage rpm additionally accounts for
the reviewed strip outputs and checked-hash caches. Run that stage with the
carried interpreter to inspect bytecode without importing packaged modules.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packaging/attribution/rpm-qt.json"
NOTICE = ROOT / "packaging/licenses/qt/THIRD-PARTY-NOTICES.txt"
ANCHORS = {
    "packaged_payload": "176fd0d01a06cb71c5430cb194d3da4d0a1bc706d78167066ad86ac858b6de8a",
    "source_documents": "0d0460b737b5b705ee5c4ee9aa8ae6b210ecfd8cc2eef850990a7c2d0aa160bb",
    "publisher": "c747c87bfa83cf2f5bb5f6de46da780be1717c3b5aac5374ac3c883d7d57a82f",
    "retained_payload": "f838f2c251d008805104cc46269f89788f8952f864c1a7bf247db9f9fc8a17b3",
    "candidates": "a87616720038c605c13be7863559dbffdc1ab34152875ae2a96186f950e67d22",
    "wayland_ivi": "010806f7c1da1387cbfc398e72cf4021e78fa6a75df7874ba0571ee0b40ae751",
    "binding_source": "0053ef5449dfca0003a4b11db467a5a3e518a8a8cb246bfffa6d2597c7dce037",
}
WHEEL = "16f4b5e41daf49235ae048458243da9efe5f3d8040f9cc5aa454ce69893d3bd9"

BYTECODE_CHECK = r"""
import importlib.util
import io
import json
import marshal
from pathlib import Path
import sys
import types

request = json.load(sys.stdin)
root = Path(request["root"])
contract = request["contract"]
if (sys.implementation.cache_tag != contract["cache_tag"]
        or importlib.util.MAGIC_NUMBER.hex() != contract["magic_hex"]):
    raise ValueError("carried interpreter does not match reviewed bytecode format")
for member in contract["sources"]:
    source = root / member
    cache = source.parent / "__pycache__" / (source.stem + "." + contract["cache_tag"] + ".pyc")
    data = cache.read_bytes()
    if (len(data) <= 16 or data[:4] != importlib.util.MAGIC_NUMBER
            or data[4:8] != b"\x03\0\0\0"
            or data[8:16] != importlib.util.source_hash(source.read_bytes())):
        raise ValueError("invalid checked-hash cache: " + member)
    stream = io.BytesIO(data[16:])
    actual = marshal.load(stream)
    filename = contract["installed_site"] + "/" + member
    expected = compile(source.read_bytes(), filename, "exec", dont_inherit=True, optimize=0)
    if stream.read() or not isinstance(actual, types.CodeType) or actual != expected:
        raise ValueError("cache does not compile from retained source: " + member)
    pending = [actual]
    while pending:
        code = pending.pop()
        if code.co_filename != filename:
            raise ValueError("cache has wrong installed filename: " + member)
        pending.extend(value for value in code.co_consts if isinstance(value, types.CodeType))
print("Reviewed packaged bytecode matches retained sources and installed paths")
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _payload_path(root, member):
    """Keep resolved inventory members inside the explicitly selected payload."""
    path = os.path.realpath(os.path.join(root, member))
    if not path.startswith(os.path.realpath(root).rstrip(os.sep) + os.sep):
        raise ValueError(f"path escapes payload: {member}")
    return Path(path)


def _verify_payload(root, retained, packaged=None):
    root = Path(os.path.realpath(root))
    if (root / "PySide6").is_symlink():
        raise ValueError("payload symlinks are not reviewed")
    pyside = _payload_path(root, "PySide6")
    entries = [pyside, *pyside.rglob("*")]
    if any(path.is_symlink() for path in entries):
        raise ValueError("payload symlinks are not reviewed")
    observed = {str(path.relative_to(root)) for path in entries if path.is_file()}
    expected = {item["member"]: item["sha256"] for item in retained}
    if packaged is not None:
        for item in packaged["native_transform"]["members"]:
            if expected.get(item["member"]) != item["original_sha256"]:
                raise ValueError("strip transformation has no retained parent")
            expected[item["member"]] = item["sha256"]
        bytecode = packaged["bytecode"]
        if set(bytecode["sources"]) != {name for name in expected if name.endswith(".py")}:
            raise ValueError("bytecode source membership differs")
        caches = {
            str(Path(name).parent / "__pycache__" / (Path(name).stem + "." + bytecode["cache_tag"] + ".pyc"))
            for name in bytecode["sources"]
        }
    else:
        caches = set()
    if observed != set(expected) | caches:
        raise ValueError("trimmed payload members differ")
    for member, expected_digest in expected.items():
        if digest(_payload_path(root, member).read_bytes()) != expected_digest:
            raise ValueError(f"payload differs: {member}")
    if packaged is not None:
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-c", BYTECODE_CHECK],
                input=json.dumps({"root": str(root), "contract": bytecode}),
                text=True, capture_output=True, timeout=60, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("packaged bytecode verification timed out") from exc
        if result.returncode:
            raise ValueError("packaged bytecode verification failed: " + result.stderr.strip())


def verify(snapshot, notice, payload_root=None, *, payload_stage="trimmed"):
    if payload_stage not in ("trimmed", "rpm"):
        raise ValueError("unknown payload stage")
    if payload_stage == "rpm" and payload_root is None:
        raise ValueError("RPM stage requires --payload-root")
    for key, expected in ANCHORS.items():
        if digest(canonical(snapshot[key])) != expected:
            raise ValueError(f"reviewed {key} differs")
    if snapshot["wheel"]["sha256"] != WHEEL:
        raise ValueError("wrong wheel parent")
    if snapshot["packaged_payload"]["parent_sha256"] != WHEEL:
        raise ValueError("wrong packaged wheel parent")
    documents = snapshot["source_documents"]
    candidates = snapshot["candidates"]
    expected_keys = {f"{doc['member']}#{i}" for doc in documents for i, _ in enumerate(doc["records"])}
    if len(documents) != 78 or len(candidates) != 90 or {c["key"] for c in candidates} != expected_keys:
        raise ValueError("source catalog coverage differs")
    targets = snapshot["publisher"]["targets"]
    if len(targets) != 25 or any(not t["byte_identical"] or t["sdk_sha256"] != t["retained_sha256"] for t in targets):
        raise ValueError("publisher target identity differs")
    members = {item["member"]: item["sha256"] for item in snapshot["retained_payload"]}
    if any(members.get("PySide6/Qt/" + target["retained"]) != target["retained_sha256"] for target in targets):
        raise ValueError("publisher target is not in the retained payload")
    for candidate in candidates:
        if candidate["parent_sha256"] != WHEEL or not candidate["source_notices"]:
            raise ValueError("missing parent or source notice")
        header = ("=== " + candidate["key"] + " (" + candidate["id"] + ") ===\nCopyright: "
                  + json.dumps(candidate["copyright"], ensure_ascii=False) + "\nLicense: "
                  + str(candidate["license"]) + "\n").encode()
        first_offset = candidate["source_notices"][0]["offset"]
        if header not in notice[max(0, first_offset - len(header) - 1024):first_offset]:
            raise ValueError(f"copyright association differs: {candidate['key']}")
        for source in candidate["source_notices"]:
            part = notice[source["offset"]:source["offset"] + source["size"]]
            if len(part) != source["size"] or digest(part) != source["sha256"]:
                raise ValueError(f"notice differs: {candidate['key']}")
    ivi = snapshot["wayland_ivi"]
    if digest(notice[ivi["notice_offset"]:ivi["notice_offset"] + ivi["notice_size"]]) != ivi["license_sha256"]:
        raise ValueError("Wayland IVI notice differs")
    for source in snapshot["binding_source"]["source_notices"]:
        if digest(notice[source["offset"]:source["offset"] + source["size"]]) != source["sha256"]:
            raise ValueError(f"binding notice differs: {source['source']}")
    for source in snapshot["binding_source"]["first_party_copyright"]:
        if digest(notice[source["offset"]:source["offset"] + source["size"]]) != source["sha256"]:
            raise ValueError("binding copyright differs")
    if payload_root is not None:
        _verify_payload(payload_root, snapshot["retained_payload"],
                        snapshot["packaged_payload"] if payload_stage == "rpm" else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload-root", type=Path)
    parser.add_argument("--payload-stage", choices=("trimmed", "rpm"), default="trimmed")
    args = parser.parse_args()
    try:
        verify(json.loads(SNAPSHOT.read_text()), NOTICE.read_bytes(), args.payload_root,
               payload_stage=args.payload_stage)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"RPM attribution verification failed: {exc}\n")
    print("Reviewed RPM Qt source coverage and notices verified"
          + (f" with {args.payload_stage} payload" if args.payload_root else ""))


if __name__ == "__main__":
    main()
