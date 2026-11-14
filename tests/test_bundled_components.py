"""Keep the hand-reviewed component register tied to its authoritative inputs."""
import json
import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text())


def test_register_structure_and_bounded_ownership():
    register = load('packaging/bundled-components.json')
    assert register['schema'] == 1
    parents = register['parents']
    assert {'interpreter', 'wheels', 'baseapp', 'platform', 'flatpak-app', 'host'} <= parents.keys()
    rows = register['components']
    assert len({row['id'] for row in rows}) == len(rows)
    for row in rows:
        assert row['parents'] and set(row['parents']) <= parents.keys()
        assert row['ownership'] in {'rpm-app', 'flatpak-app', 'BaseApp', 'Platform', 'host', 'build-only', 'removed'}
        assert row['decision'] in {'update', 'already-current', 'compatibility-hold', 'removed', 'build-only', 'host'}
        assert set(row['presence']) == {'rpm-full', 'rpm-headless', 'flatpak'}
        assert all(value in {'present', 'absent', 'unknown', 'not-owned', 'external', 'build-only'} for value in row['presence'].values())
        assert row['evidence'] and row['notice']
        for version in (row['current_version'], row['selected_version']):
            assert isinstance(version, str) and version
            assert version not in {'MIT', 'X11', 'Zlib', 'Apache-2.0', 'BSD-3-Clause', '0BSD', 'Sleepycat'}


def test_interpreter_membership_and_native_inventory_match_provenance():
    register = load('packaging/bundled-components.json')
    provenance = load('packaging/interpreter/PROVENANCE.json')
    rows = {row['id']: row for row in register['components']}
    parent = register['parents']['interpreter']
    assert parent['artifact'] == provenance['identity']['asset']
    assert parent['sha256'] == provenance['identity']['sha256']
    assert parent['source_commit'] == provenance['source_commit']
    assert rows['cpython']['selected_version'] == provenance['identity']['python_version']
    for name, component in provenance['inventory']['components'].items():
        row = rows['python-module:' + name]
        assert row['evidence']['dependencies'] == component['dependencies']
        assert row['notice'] == component['license_paths']
        for dependency in component['dependencies']:
            assert name in rows['native:' + dependency]['evidence']['modules']


def test_pins_and_inspected_parent_tiers_are_explicit():
    rows = {row['id']: row for row in load('packaging/bundled-components.json')['components']}
    fetcher = (ROOT / 'scripts/fetch-bundled-runtime.sh').read_text()
    pins = dict(re.findall(r'"([\w-]+)==([\d.]+)"', fetcher))
    for name, version in pins.items():
        assert rows['wheel:' + name.lower()]['selected_version'] == version
    manifest = (ROOT / 'packaging/flatpak/io.github.extricator.IdasenCompanion.yaml').read_text()
    assert "runtime-version: '" + rows['platform']['selected_version'] + "'" in manifest
    assert "base-version: '" + rows['baseapp']['selected_version'] + "'" in manifest
    assert rows['qt-native']['decision'] == 'compatibility-hold'
    for name in ('baseapp', 'platform', 'flatpak-app'):
        assert rows[name]['evidence']['status'] == 'observed'
    assert 'include packaging/bundled-components.json' in (ROOT / 'MANIFEST.in').read_text().splitlines()


def test_qt_notices_match_each_recorded_source_section():
    rows = {row['id']: row for row in load('packaging/bundled-components.json')['components']}
    notices = rows['qt-native']['evidence']['confirmed_notices']
    assert {entry['component'] for entry in notices} == {
        'PCRE2 10.48', 'PCRE2 SLJIT', 'libpng 1.6.58', 'HarfBuzz 14.5.0',
        'libjpeg-turbo 3.2.0', 'IJG', 'libjpeg copyright', 'ICU 73.2',
    }
    for notice in notices:
        data = (ROOT / notice['file']).read_bytes()
        section = data[notice['offset']:notice['offset'] + notice['size']]
        assert hashlib.sha256(section).hexdigest() == notice['sha256']
