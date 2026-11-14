"""Regression checks for the reviewed, offline RPM attribution gate."""
import copy
import importlib.util
import json
import marshal
from pathlib import Path
import py_compile
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_rpm_attribution", ROOT / "scripts/verify-rpm-attribution.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
_REAL_RUN = subprocess.run


def test_reviewed_catalog_parent_and_notice_fail_closed():
    snapshot = json.loads(VERIFY.SNAPSHOT.read_text())
    notice = VERIFY.NOTICE.read_bytes()
    VERIFY.verify(snapshot, notice)

    omitted = copy.deepcopy(snapshot)
    omitted["candidates"].pop()
    with pytest.raises(ValueError):
        VERIFY.verify(omitted, notice)

    wrong_parent = copy.deepcopy(snapshot)
    wrong_parent["candidates"][0]["parent_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        VERIFY.verify(wrong_parent, notice)

    changed_notice = bytearray(notice)
    changed_notice[snapshot["candidates"][0]["source_notices"][0]["offset"]] ^= 1
    with pytest.raises(ValueError):
        VERIFY.verify(snapshot, bytes(changed_notice))

    changed_transform = copy.deepcopy(snapshot)
    changed_transform["packaged_payload"]["native_transform"]["members"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="reviewed packaged_payload differs"):
        VERIFY.verify(changed_transform, notice)


@pytest.fixture
def packaged_payload(tmp_path, monkeypatch):
    # Exercise the real isolated bytecode child, while retaining the suite's
    # prohibition on unrelated subprocesses such as systemctl and journalctl.
    def bytecode_child_only(command, **kwargs):
        assert command == [sys.executable, "-I", "-S", "-B", "-c", VERIFY.BYTECODE_CHECK]
        return _REAL_RUN(command, **kwargs)

    monkeypatch.setattr(VERIFY.subprocess, "run", bytecode_child_only)
    root = tmp_path / "site-packages"
    contents = {
        "PySide6/__init__.py": b"raise RuntimeError('must not execute')\ndef answer():\n    return 42\n",
        "PySide6/QtCore.abi3.so": b"unchanged native member",
        "PySide6/Qt/lib/libicuuc.so.73": b"original native member",
    }
    retained = [{"member": name, "sha256": VERIFY.digest(data)} for name, data in contents.items()]
    for name, data in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    contract = {
        "native_transform": {"members": [{
            "member": "PySide6/Qt/lib/libicuuc.so.73",
            "original_sha256": VERIFY.digest(contents["PySide6/Qt/lib/libicuuc.so.73"]),
            "sha256": VERIFY.digest(b"stripped native member"),
        }]},
        "bytecode": {
            "cache_tag": sys.implementation.cache_tag,
            "magic_hex": importlib.util.MAGIC_NUMBER.hex(),
            "installed_site": "/usr/lib/idasen-companion/python/lib/python"
                              + f"{sys.version_info.major}.{sys.version_info.minor}/site-packages",
            "sources": ["PySide6/__init__.py"],
        },
    }
    VERIFY._verify_payload(root, retained)
    (root / "PySide6/Qt/lib/libicuuc.so.73").write_bytes(b"stripped native member")
    py_compile.compile(str(root / "PySide6/__init__.py"),
                       dfile=contract["bytecode"]["installed_site"] + "/PySide6/__init__.py",
                       doraise=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
    return root, retained, contract


def test_packaged_transforms_preserve_trimmed_stage(packaged_payload):
    root, retained, contract = packaged_payload
    with pytest.raises(ValueError, match="payload members differ"):
        VERIFY._verify_payload(root, retained)
    VERIFY._verify_payload(root, retained, contract)


@pytest.mark.parametrize("change", ["unexpected", "missing"])
def test_packaged_membership_is_exact(packaged_payload, change):
    root, retained, contract = packaged_payload
    if change == "unexpected":
        (root / "PySide6/__pycache__/unreviewed.pyc").write_bytes(b"extra")
    else:
        (root / "PySide6/QtCore.abi3.so").unlink()
    with pytest.raises(ValueError, match="payload members differ"):
        VERIFY._verify_payload(root, retained, contract)


@pytest.mark.parametrize("member", ["PySide6/__init__.py", "PySide6/Qt/lib/libicuuc.so.73",
                                    "PySide6/QtCore.abi3.so"])
def test_packaged_sources_and_native_bytes_remain_exact(packaged_payload, member):
    root, retained, contract = packaged_payload
    (root / member).write_bytes(b"changed")
    with pytest.raises(ValueError, match="payload differs"):
        VERIFY._verify_payload(root, retained, contract)


@pytest.mark.parametrize("change", ["flags", "magic", "source_hash", "code", "filename", "trailing"])
def test_packaged_cache_is_checked_against_source_and_installed_path(packaged_payload, change):
    root, retained, contract = packaged_payload
    cache = root / "PySide6/__pycache__" / ("__init__." + sys.implementation.cache_tag + ".pyc")
    data = bytearray(cache.read_bytes())
    if change == "flags":
        data[4:8] = b"\0" * 4
    elif change == "magic":
        data[0] ^= 1
    elif change == "source_hash":
        data[8] ^= 1
    elif change == "trailing":
        data += b"unreviewed"
    else:
        code = marshal.loads(data[16:])
        code = (compile("answer = 99", code.co_filename, "exec") if change == "code"
                else code.replace(co_filename="/unreviewed/buildroot/PySide6/__init__.py"))
        data[16:] = marshal.dumps(code)
    cache.write_bytes(data)
    with pytest.raises(ValueError, match="packaged bytecode verification failed"):
        VERIFY._verify_payload(root, retained, contract)


def test_packaged_cache_requires_the_matching_interpreter(packaged_payload):
    root, retained, contract = packaged_payload
    contract["bytecode"]["magic_hex"] = "00000000"
    with pytest.raises(ValueError, match="carried interpreter does not match"):
        VERIFY._verify_payload(root, retained, contract)


def test_payload_cannot_follow_symlink_outside_root(packaged_payload, tmp_path):
    root, retained, contract = packaged_payload
    outside = tmp_path / "outside.so"
    member = root / "PySide6/QtCore.abi3.so"
    outside.write_bytes(member.read_bytes())
    member.unlink()
    member.symlink_to(outside)
    with pytest.raises(ValueError, match="payload symlinks"):
        VERIFY._verify_payload(root, retained, contract)


def test_payload_cannot_traverse_a_symlinked_package_directory(packaged_payload, tmp_path):
    root, retained, contract = packaged_payload
    (root / "PySide6").rename(tmp_path / "outside")
    (root / "PySide6").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(ValueError, match="payload symlinks"):
        VERIFY._verify_payload(root, retained, contract)
