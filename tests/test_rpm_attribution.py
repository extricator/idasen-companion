"""Regression checks for the reviewed, offline RPM attribution gate."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_rpm_attribution", ROOT / "scripts/verify-rpm-attribution.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


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
