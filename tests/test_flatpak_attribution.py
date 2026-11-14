"""Focused regressions for source and retained binding evidence."""
import importlib.util
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('flatpak_attribution', ROOT / 'scripts/verify-flatpak-attribution.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.fixture
def snapshot():
    return json.loads(verifier.SNAPSHOT.read_text())


def test_current_binding_evidence(snapshot):
    verifier.verify(snapshot, verifier.NOTICE)


def test_missing_binding_is_rejected(snapshot):
    snapshot['binding_source_attribution_superset']['retained_members'].pop()
    with pytest.raises(ValueError, match='publisher index mismatch'):
        verifier.verify(snapshot, verifier.NOTICE)


def test_changed_notice_is_rejected(snapshot, tmp_path):
    notice = tmp_path / 'notice'
    notice.write_bytes(verifier.NOTICE.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='notice mismatch'):
        verifier.verify(snapshot, notice)


def test_wrong_parent_is_rejected(snapshot):
    snapshot['parents']['baseapp'] = 'other'
    with pytest.raises(ValueError, match='wrong BaseApp'):
        verifier.verify(snapshot, verifier.NOTICE)


def test_payload_symlink_cannot_escape(tmp_path):
    root = tmp_path / 'payload'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.write_text('not a payload file')
    (root / 'link').symlink_to(outside)
    with pytest.raises(ValueError, match='escapes payload'):
        verifier.within(root, 'link')
    with pytest.raises(ValueError, match='absolute parent path'):
        verifier.parent_path(root, str(outside))


def test_changed_document_relationship_is_rejected(snapshot):
    snapshot['publisher_component_attestations']['documents'][0]['packages'].pop()
    with pytest.raises(ValueError, match='publisher index mismatch'):
        verifier.verify(snapshot, verifier.NOTICE)


def test_parent_absolute_usr_symlink_resolves_within_payload(tmp_path):
    (tmp_path / 'share').mkdir()
    (tmp_path / 'share' / 'notice').write_text('publisher notice')
    (tmp_path / 'link').symlink_to('/usr/share/notice')
    assert verifier.parent_path(tmp_path, 'link').read_text() == 'publisher notice'


def test_complete_gate_requires_real_payload_roots(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['verify-flatpak-attribution.py', '--complete'])
    with pytest.raises(SystemExit) as error:
        verifier.main()
    assert error.value.code != 0
    assert 'requires --platform-root' in capsys.readouterr().err


@pytest.mark.parametrize('unexpected_kind', ('nested_library', 'native_symlink'))
def test_unreviewed_native_member_is_rejected(tmp_path, unexpected_kind):
    package = tmp_path / 'PySide6'
    package.mkdir()
    binding = package / 'QtCore.abi3.so'
    binding.write_bytes(b'reviewed binding')
    members = [{'path': 'PySide6/QtCore.abi3.so', 'sha256': hashlib.sha256(binding.read_bytes()).hexdigest()}]
    verifier.verify_binding_members(tmp_path, members)
    if unexpected_kind == 'nested_library':
        nested = package / 'Qt' / 'lib'
        nested.mkdir(parents=True)
        (nested / 'libQt6Core.so.6').write_bytes(b'unreviewed Qt library')
    else:
        (package / 'extra.so').symlink_to(binding.name)
    with pytest.raises(ValueError, match='membership mismatch'):
        verifier.verify_binding_members(tmp_path, members)
