#!/usr/bin/env python3
"""Verify the reviewed Qt 6.12 RPM attribution snapshot offline.

Publisher target relationships are conservative attribution, not proof that
every listed source unit was compiled. --payload-root additionally checks the
actual trimmed tree; it must contain the PySide6 directory.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packaging/attribution/rpm-qt.json"
NOTICE = ROOT / "packaging/licenses/qt/THIRD-PARTY-NOTICES.txt"
ANCHORS = {
    "source_documents": "0d0460b737b5b705ee5c4ee9aa8ae6b210ecfd8cc2eef850990a7c2d0aa160bb",
    "publisher": "c747c87bfa83cf2f5bb5f6de46da780be1717c3b5aac5374ac3c883d7d57a82f",
    "retained_payload": "f838f2c251d008805104cc46269f89788f8952f864c1a7bf247db9f9fc8a17b3",
    "candidates": "a87616720038c605c13be7863559dbffdc1ab34152875ae2a96186f950e67d22",
    "wayland_ivi": "010806f7c1da1387cbfc398e72cf4021e78fa6a75df7874ba0571ee0b40ae751",
    "binding_source": "0053ef5449dfca0003a4b11db467a5a3e518a8a8cb246bfffa6d2597c7dce037",
}
WHEEL = "16f4b5e41daf49235ae048458243da9efe5f3d8040f9cc5aa454ce69893d3bd9"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def verify(snapshot, notice, payload_root=None):
    for key, expected in ANCHORS.items():
        if digest(canonical(snapshot[key])) != expected:
            raise ValueError(f"reviewed {key} differs")
    if snapshot["wheel"]["sha256"] != WHEEL:
        raise ValueError("wrong wheel parent")
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
        root = Path(payload_root)
        observed = {str(p.relative_to(root)) for p in (root / "PySide6").rglob("*") if p.is_file()}
        expected = {item["member"] for item in snapshot["retained_payload"]}
        if observed != expected:
            raise ValueError("trimmed payload members differ")
        for item in snapshot["retained_payload"]:
            if digest((root / item["member"]).read_bytes()) != item["sha256"]:
                raise ValueError(f"payload differs: {item['member']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload-root", type=Path)
    args = parser.parse_args()
    try:
        verify(json.loads(SNAPSHOT.read_text()), NOTICE.read_bytes(), args.payload_root)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"RPM attribution verification failed: {exc}\n")
    print("Reviewed RPM Qt source coverage and notices verified" + (" with trimmed payload" if args.payload_root else ""))


if __name__ == "__main__":
    main()
