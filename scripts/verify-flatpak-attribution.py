#!/usr/bin/env python3
"""Verify retained Flatpak binding evidence; native completeness remains open."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'packaging/attribution/flatpak-native.json'
NOTICE = ROOT / 'packaging/licenses/flatpak/THIRD-PARTY-NOTICES.txt'
NOTICE_PATH = 'share/licenses/io.github.extricator.IdasenCompanion/THIRD-PARTY-NOTICES.txt'
SITE = 'lib/python3.13/site-packages'
BASEAPP = '25537519d4e093f4b32515f89d24ae7ca6eddfa2ff5dd21e1a82a7bad9189572'
PLATFORM = 'fb23e178d082b117df7924f9a84710992ec233ebc007385feb85d349c4c81415'
INDEX_DIGESTS = {
    'publisher_component_attestations': '1c5c364df53ec768faf2a5721877344bf97f4a87aee1e1314343861fd187a3d1',
    'publisher_notice_inventory': '22f09c48059e3baa8c74ed715e4e824c0e9a9b2bc3b498abac7805efe85b3c0f',
    'binding_source_attribution_superset': '70849fe8725df84effc83ce5cb7bbd5800fbfd923d0715a8aba7460f9091d92f',
}
MANIFESTS = (
    ('platform', 'manifest.json', '84448a7c768e103171180c1964d73692efbde7a78030dbf9f1d3f337e43898c2'),
    ('baseapp', 'manifest-base-1.json', 'adb93e8011c7283683040972a67435ec9dd55a34fd83ac71e7b5883354ce3e8f'),
    ('baseapp', 'manifest.json', '21f7960ab2230f967f18d4bf72b2eb8356a1168450c8f844d6ccf2a8f31ed5b9'),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def within(root, name):
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'path escapes payload: {name}')
    return path


def parent_path(root, name):
    """Resolve deployed /usr links inside the parent, never on the host."""
    root = root.resolve()
    parts = Path(name).parts
    path = root
    links = 0
    while parts:
        part, *parts = parts
        if part in ('', '.'):
            continue
        if part == '..':
            path = path.parent
            if not path.is_relative_to(root):
                raise ValueError('parent link escapes payload')
            continue
        path = path / part
        if path.is_symlink():
            links += 1
            if links > 40:
                raise ValueError('parent link loop')
            target = path.readlink()
            if target.is_absolute():
                if not target.is_relative_to('/usr'):
                    raise ValueError('invalid absolute parent link')
                path = root
                parts = list(target.relative_to('/usr').parts) + parts
            else:
                path = path.parent
                parts = list(target.parts) + parts
    if not path.is_file():
        raise ValueError(f'missing parent file: {name}')
    return path


def verify(snapshot, notice, baseapp=None, app=None, source=None, platform=None, sdk=None):
    if snapshot['parents']['baseapp'] != BASEAPP or snapshot['parents']['platform'] != PLATFORM:
        raise ValueError('wrong BaseApp or Platform parent')
    for key, expected in INDEX_DIGESTS.items():
        encoded = json.dumps(snapshot[key], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        if hashlib.sha256(encoded).hexdigest() != expected:
            raise ValueError(f'publisher index mismatch: {key}')
    for owner, path, expected in MANIFESTS:
        parent = platform if owner == 'platform' else baseapp
        if parent and digest(parent_path(parent, path)) != expected:
            raise ValueError(f'publisher manifest mismatch: {path}')
    binding = snapshot['binding_source_attribution_superset']
    if binding['source_commit'] != 'd03d006d7b1db58074ca9cae26356376788a769e':
        raise ValueError('wrong binding source')
    if digest(notice) != binding['supplemental_notice_sha256']:
        raise ValueError('supplemental notice mismatch')
    members = binding['retained_members']
    if len(members) != 32 or len({m['path'] for m in members}) != 32:
        raise ValueError('binding membership mismatch')
    for member in members:
        if member['sha256'] != member['baseapp_sha256']:
            raise ValueError('binding parent mismatch')
        for payload in (baseapp, app):
            if payload and digest(within(payload, f"{SITE}/{member['path']}")) != member['sha256']:
                raise ValueError(f"binding content mismatch: {member['path']}")
    for payload in (baseapp, app):
        if payload is app and payload:
            site = payload / SITE
            found = {str(path.relative_to(site)) for directory in ('PySide6', 'shiboken6') for path in (site / directory).glob('*.so*') if path.is_file() and not path.is_symlink()}
            if found != {m['path'] for m in members}:
                raise ValueError('actual retained binding membership mismatch')
    groups = binding['groups']
    files = [item for group in groups for item in group['files']]
    if len(groups) != 36 or len(files) != 309 or len({f['source'] for f in files}) != 309:
        raise ValueError('binding source inventory mismatch')
    notice_text = notice.read_text()
    for item in files:
        if source and digest(within(source, item['source'])) != item['sha256']:
            raise ValueError(f"binding source mismatch: {item['source']}")
        record = '\nSource: ' + item['source'] + '\nSHA-256: ' + item['sha256'] + '\n' + ''.join(line + '\n' for line in item['declarations'])
        if record not in notice_text:
            raise ValueError(f"missing source attribution: {item['source']}")
    if app and digest(within(app, NOTICE_PATH)) != digest(notice):
        raise ValueError('installed notice mismatch')
    docs = snapshot['publisher_component_attestations']['documents']
    if len(docs) != 34 or snapshot['publisher_component_attestations']['external_resolution_gaps']:
        raise ValueError('incomplete publisher document references')
    for doc in docs:
        parent = platform if doc['parent'] == 'platform' else baseapp
        if parent and digest(parent_path(parent, doc['path'])) != doc['sha256']:
            raise ValueError(f"publisher document mismatch: {doc['path']}")
        for package in doc['packages']:
            if 'publisher_source_attribution' in package and not (package['publisher_source_notice_paths'] or package['publisher_license_text_paths']):
                raise ValueError(f"missing publisher license text: {package['id']}")
    groups = snapshot['publisher_notice_inventory']['groups']
    if len(groups) != 473 or any(not g['manifest_candidates'] or not g['notices'] for g in groups):
        raise ValueError('incomplete publisher notice inventory')
    avahi = next(g['version_evidence'] for g in groups if g['notice_group'] == 'freedesktop-sdk' and g['component'] == 'avahi')
    if sdk:
        if digest(parent_path(sdk, avahi['sdk_metadata'])) != avahi['sdk_metadata_sha256']:
            raise ValueError('Avahi SDK metadata mismatch')
        for path, expected in avahi['matching_platform_sdk_files'].items():
            if digest(parent_path(sdk, path)) != expected:
                raise ValueError(f'Avahi SDK binary mismatch: {path}')
    if platform:
        for path, expected in avahi['matching_platform_sdk_files'].items():
            if digest(parent_path(platform, path)) != expected:
                raise ValueError(f'Avahi runtime mismatch: {path}')
        license_root = platform / 'share/licenses'
        actual_groups = {(kind, path.name) for kind in ('freedesktop-sdk', 'kde', 'org.kde.Platform') for path in (license_root / kind).iterdir() if path.is_dir()}
        expected_groups = {(g['notice_group'], Path(g['notices'][0]['path']).parts[3]) for g in groups}
        if actual_groups != expected_groups:
            raise ValueError('actual publisher notice groups mismatch')
        for group in groups:
            directory = license_root / group['notice_group'] / Path(group['notices'][0]['path']).parts[3]
            actual = {str(path.relative_to(platform)) for path in directory.rglob('*') if path.is_file() or path.is_symlink()}
            if actual != {entry['path'] for entry in group['notices']}:
                raise ValueError(f"publisher notice paths mismatch: {group['component']}")
            for entry in group['notices']:
                resolved = parent_path(platform, entry['path'])
                if str(resolved.relative_to(platform.resolve())) != entry['target'] or digest(resolved) != entry['sha256']:
                    raise ValueError(f"publisher notice mismatch: {entry['path']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseapp-root', type=Path)
    parser.add_argument('--app-root', type=Path)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--platform-root', type=Path)
    parser.add_argument('--sdk-root', type=Path)
    args = parser.parse_args()
    try:
        verify(json.loads(SNAPSHOT.read_text()), NOTICE, args.baseapp_root, args.app_root, args.source_root, args.platform_root, args.sdk_root)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f'Flatpak binding verification failed: {error}\n')
    print('Binding source and notice evidence verified; native completeness remains unresolved.')


if __name__ == '__main__':
    main()
