"""Keep the hand-reviewed component register tied to its authoritative inputs."""
import json
import hashlib
from pathlib import Path
import re
import copy

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


def test_pcre2_source_binary_and_notice_association():
    snapshot = load('packaging/attribution/rpm-qt.json')
    rows = {row['id']: row for row in load('packaging/bundled-components.json')['components']}
    pcre = snapshot['pcre2']

    def consistent(data, entries):
        row = entries.get(data['register_id'], {})
        evidence = row.get('evidence', {})
        return (evidence.get('parent_sha256') == snapshot['wheel']['sha256']
                and evidence.get('member_sha256') == data['binary_sha256']
                and evidence.get('notice_section') == data['notice']
                and row.get('selected_version') == '10.48')

    assert consistent(pcre, rows)
    missing = dict(rows)
    del missing[pcre['register_id']]
    assert not consistent(pcre, missing)
    substituted = copy.deepcopy(rows)
    substituted[pcre['register_id']]['evidence']['notice_section']['sha256'] = '0' * 64
    assert not consistent(pcre, substituted)


def test_confirmed_qt_units_link_to_their_individual_notices():
    rows = {row['id']: row for row in load('packaging/bundled-components.json')['components']}
    for component, expected in {
        'libpng': {'libpng 1.6.58'},
        'harfbuzz': {'HarfBuzz 14.5.0'},
        'libjpeg-turbo': {'libjpeg-turbo 3.2.0', 'IJG', 'libjpeg copyright'},
        'icu': {'ICU 73.2'},
    }.items():
        sections = rows['qt-embedded:' + component]['evidence']['notice_sections']
        assert {section['component'] for section in sections} == expected
        for section in sections:
            data = (ROOT / section['file']).read_bytes()
            data = data[section['offset']:section['offset'] + section['size']]
            assert hashlib.sha256(data).hexdigest() == section['sha256']
