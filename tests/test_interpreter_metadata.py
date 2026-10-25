# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline exact-build interpreter metadata and refresh boundaries."""

import io
import json
import os
import runpy
from subprocess import run as run_process
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify-interpreter-metadata.py"


@pytest.fixture
def tool():
    return runpy.run_path(str(SCRIPT))


@pytest.fixture
def tree(tmp_path):
    """Only the repository inputs the offline command actually reads."""
    for relative in (
        "scripts/fetch-bundled-runtime.sh", "scripts/trim-cpython.py",
        "packaging/idasen-companion-bundled.spec",
        "packaging/interpreter/PYTHON.json", "packaging/interpreter/PROVENANCE.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    return tmp_path


@pytest.fixture
def package_tree(tree):
    for source in (ROOT / "packaging/licenses").rglob("*.txt"):
        target = tree / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return tree


def test_complete_package_verification_and_effective_variants(tool):
    variants = tool["verify_package_variants"]()
    assert variants["full"]["licenses"] - variants["headless"]["licenses"] == {"LICENSE.LGPL-3.0.txt"}
    assert "LICENSE.sqlite.txt" in variants["headless"]["licenses"]
    assert "LICENSE.cpython" in variants["headless"]["licenses"]
    assert tool["main"](["verify"]) == 0


@pytest.mark.parametrize("state", ["missing", "empty", "wrong-bytes"])
def test_component_notice_requires_exact_source_bytes(tool, package_tree, state):
    path = package_tree / "packaging/licenses/interpreter/LICENSE.sqlite.txt"
    if state == "missing":
        path.unlink()
    else:
        path.write_bytes(b"" if state == "empty" else b"substitute public-domain text")
    with pytest.raises(tool["MetadataError"], match="sqlite"):
        tool["verify_package_variants"](package_tree)


@pytest.mark.parametrize("old,new,error", [
    ("License:", "Missing-License:", "exactly one License"),
    (" AND bzip2-1.0.6", "", "headless.*terms"),
    (" AND bzip2-1.0.6", " AND bzip2-1.0.6 AND TCL", "headless.*terms"),
    ("(LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only)", "LGPL-3.0-only", "full.*Qt"),
    (" LICENSE.LGPL-3.0.txt", "", "Qt notice delta"),
    ('%if "%{release_flavor}" == "headless"', '%if "%{release_flavor}" == "minimal"', "selector"),
    ("packaging/licenses/interpreter/*.txt", "packaging/licenses/absent/*.txt", "full.*staging"),
    (" LICENSE.sqlite.txt", "", "full.*_sqlite3.*sqlite"),
    ("cp python/lib/python%{bundled_minor}/LICENSE.txt LICENSE.cpython", "", "full.*cpython.*copy"),
])
def test_effective_package_rejects_declaration_selector_and_staging_drift(tool, package_tree, old, new, error):
    path = package_tree / "packaging/idasen-companion-bundled.spec"
    original = path.read_text()
    assert old in original
    path.write_text(original.replace(old, new))
    with pytest.raises(tool["MetadataError"], match=error):
        tool["verify_package_variants"](package_tree)


def test_expanded_specs_must_match_offline_observations(tool, tmp_path):
    variants = tool["verify_package_variants"]()
    paths = []
    for flavor in ("full", "headless"):
        observed = variants[flavor]
        path = tmp_path / flavor
        path.write_text("License: " + observed["expression"] + "\n%license "
                        + " ".join(sorted(observed["licenses"])) + "\n")
        paths.append(str(path))
    argv = ["verify-expanded", "--full-spec", paths[0], "--headless-spec", paths[1]]
    assert tool["main"](argv) == 0
    path.write_text(path.read_text().replace(" LICENSE.sqlite.txt", ""))
    assert tool["main"](argv) == 1


def change_json(path, change):
    data = json.loads(path.read_bytes())
    change(data)
    path.write_text(json.dumps(data))


def archive_bytes(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, contents, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(contents) if kind == tarfile.REGTYPE else 0
            if kind == tarfile.SYMTYPE:
                member.linkname = "elsewhere"
            archive.addfile(member, io.BytesIO(contents))
    return output.getvalue()


def test_current_snapshot_verifies(capsys):
    assert SCRIPT.is_file(), "offline metadata verifier is missing"
    tool = runpy.run_path(str(SCRIPT))
    assert tool["main"](["verify-metadata"]) == 0
    output = capsys.readouterr().out
    assert "16 retained extensions" in output
    assert "12 terms" in output


def test_builtin_shared_trim_and_public_domain_are_distinct(tool):
    metadata, provenance = tool["load_snapshot"]()
    inventory = tool["derive_components"](metadata, provenance["install_members"], provenance["trim_patterns"])
    assert len(inventory["components"]) == 16
    assert inventory["components"]["_ssl"]["shared_lib"] is None
    assert inventory["components"]["_dbm"]["shared_lib"]
    assert inventory["components"]["_sqlite3"]["licenses"] == []
    assert inventory["components"]["_sqlite3"]["license_public_domain"] is True
    assert set(inventory["excluded"]) == {"_tkinter"}
    assert inventory["build_only"] == ["setuptools"]
    assert "TCL" not in inventory["terms"]
    assert provenance["notices"]["licenses/LICENSE.zstd.txt"]["archive"] == "zstd"
    assert "licenses/LICENSE.zlib-ng.txt" not in provenance["notices"]
    assert "licenses/LICENSE.openssl-1.1.txt" in inventory["components"]["_ssl"]["license_paths"]
    assert "licenses/LICENSE.openssl-1.1.txt" not in provenance["notices"]
    assert "licenses/LICENSE.openssl-3.txt" in provenance["notices"]


@pytest.mark.parametrize("pin", ["URL", "ASSET", "SHA256"])
def test_each_fetcher_pin_is_bound_to_snapshot(tool, tree, pin):
    fetcher = tree / "scripts/fetch-bundled-runtime.sh"
    text = fetcher.read_text()
    old = next(line for line in text.splitlines() if line.startswith(f"INTERPRETER_{pin}="))
    fetcher.write_text(text.replace(old, old[:-1] + "0\""))
    with pytest.raises(tool["MetadataError"]):
        tool["verify_metadata"](tree)


@pytest.mark.parametrize("field,value", [
    ("version", "9"), ("build_options", "debug"),
    ("python_version", "3.14.8"), ("target_triple", "aarch64-unknown-linux-gnu"),
    ("build_info", {"extensions": []}),
])
def test_metadata_identity_and_schema_fail_closed(tool, field, value):
    metadata, provenance = tool["load_snapshot"]()
    metadata[field] = value
    with pytest.raises(tool["MetadataError"]):
        tool["validate_metadata"](metadata, provenance["identity"])


def test_raw_metadata_hash_and_duplicate_json_keys_are_rejected(tool, tree):
    raw = tree / "packaging/interpreter/PYTHON.json"
    raw.write_bytes(raw.read_bytes() + b" ")
    with pytest.raises(tool["MetadataError"], match="hash/size"):
        tool["load_snapshot"](tree)
    with pytest.raises(tool["MetadataError"], match="duplicate JSON"):
        tool["read_json"](b'{"version":"8","version":"9"}')


@pytest.mark.parametrize("state", [None, False])
def test_empty_licenses_require_explicit_public_domain(tool, state):
    metadata, provenance = tool["load_snapshot"]()
    record = metadata["build_info"]["extensions"]["_sqlite3"][0]
    if state is None:
        del record["license_public_domain"]
    else:
        record["license_public_domain"] = state
    with pytest.raises(tool["MetadataError"], match="unknown licensing"):
        tool["derive_components"](metadata, provenance["install_members"], provenance["trim_patterns"])


def test_shared_extension_requires_install_evidence(tool):
    metadata, provenance = tool["load_snapshot"]()
    members = [member for member in provenance["install_members"] if "/_dbm." not in member]
    with pytest.raises(tool["MetadataError"], match="missing installed shared extension: _dbm"):
        tool["derive_components"](metadata, members, provenance["trim_patterns"])


def test_builtin_requires_installed_interpreter(tool):
    metadata, provenance = tool["load_snapshot"]()
    members = [member for member in provenance["install_members"] if "/bin/" not in member]
    with pytest.raises(tool["MetadataError"], match="missing installed interpreter"):
        tool["derive_components"](metadata, members, provenance["trim_patterns"])


@pytest.mark.parametrize("mutation", ["component", "term", "trim", "backend", "notice"])
def test_reviewed_inventory_and_owned_shipping_rules_are_checked(tool, tree, mutation):
    provenance = tree / "packaging/interpreter/PROVENANCE.json"
    if mutation == "component":
        change_json(provenance, lambda data: data["inventory"]["components"].pop("_ssl"))
    elif mutation == "term":
        change_json(provenance, lambda data: data["inventory"]["terms"].append("TCL"))
    elif mutation == "notice":
        change_json(provenance, lambda data: data["notices"].pop("licenses/LICENSE.zlib.txt"))
    else:
        path = tree / ("scripts/trim-cpython.py" if mutation == "trim" else "packaging/idasen-companion-bundled.spec")
        before = path.read_text()
        path.write_text(before.replace("_tkinter*.so", "other*.so") if mutation == "trim"
                        else before.replace("--no-deps --no-warn-script-location build-backend", "--target shipping --no-deps --no-warn-script-location build-backend"))
    with pytest.raises(tool["MetadataError"]):
        tool["verify_metadata"](tree)


@pytest.mark.parametrize("entries,limit", [
    ([("../escape", b"", tarfile.REGTYPE)], 8),
    ([("/absolute", b"", tarfile.REGTYPE)], 8),
    ([("python/notice", b"x", tarfile.REGTYPE)] * 2, 8),
    ([("python/notice", b"too long", tarfile.REGTYPE)], 3),
    ([("python/notice", b"", tarfile.SYMTYPE)], 8),
    ([("python/device", b"", tarfile.CHRTYPE)], 8),
])
def test_archive_rejects_unsafe_duplicate_oversized_and_nonregular_evidence(tool, tmp_path, entries, limit):
    path = tmp_path / "input.tar.gz"
    path.write_bytes(archive_bytes(entries))
    with pytest.raises(tool["MetadataError"]):
        tool["read_archive"](path, {"python/notice": limit})


def test_archive_ignores_unrelated_links_without_resolving_them(tool, tmp_path):
    path = tmp_path / "input.tar.gz"
    path.write_bytes(archive_bytes([
        ("python/unrelated", b"", tarfile.SYMTYPE),
        ("python/notice", b"exact bytes", tarfile.REGTYPE),
    ]))
    found, _ = tool["read_archive"](path, {"python/notice": 100})
    assert found == {"python/notice": b"exact bytes"}


def test_complete_archive_digest_is_required_before_member_use(tool, tmp_path):
    path = tmp_path / "input.tar.gz"
    data = archive_bytes([("python/notice", b"exact bytes", tarfile.REGTYPE)])
    path.write_bytes(data)
    with pytest.raises(tool["MetadataError"], match="archive hash"):
        tool["checked_archive"](path, "0" * 64, len(data), "reviewed.tar.gz")
    path.write_bytes(data[:-10])
    with pytest.raises(tool["MetadataError"], match="archive size"):
        tool["checked_archive"](path, tool["digest"](data), len(data), "reviewed.tar.gz")
    with pytest.raises((EOFError, tarfile.TarError)):
        tool["read_archive"](path, {"python/notice": 100})


def test_refresh_is_deterministic_and_refuses_failure_before_replacement(tool, tree, tmp_path):
    """Small local archives exercise the real refresh pipeline without decoders."""
    metadata, provenance = tool["load_snapshot"]()
    raw = (ROOT / "packaging/interpreter/PYTHON.json").read_bytes()
    install = archive_bytes([(name, b"not executable", tarfile.REGTYPE)
                             for name in provenance["install_members"]])
    full = archive_bytes([("python/PYTHON.json", raw, tarfile.REGTYPE)] + [
        (notice["member"], path.encode(), tarfile.REGTYPE)
        for path, notice in provenance["notices"].items() if notice["archive"] == "full"
    ])
    source_notice = b"exact reviewed source bytes"
    source = archive_bytes([(tool["ZSTD_MEMBER"], source_notice, tarfile.REGTYPE)])
    argv = ["--root", str(tree), "refresh"]
    for name, contents in (("install", install), ("full", full), ("zstd", source)):
        path = tmp_path / f"{name}.tar.gz"
        path.write_bytes(contents)
        argv += [f"--{name}-archive", str(path), f"--{name}-sha256", tool["digest"](contents),
                 f"--{name}-size", str(len(contents))]
    fetcher = tree / "scripts/fetch-bundled-runtime.sh"
    fetcher.write_text(fetcher.read_text().replace(provenance["identity"]["sha256"], tool["digest"](install)))
    output = tree / "packaging/interpreter"
    argv += ["--metadata-sha256", tool["digest"](raw), "--metadata-size", str(len(raw)),
             "--zstd-license-sha256", tool["digest"](source_notice), "--release", "20260814",
             "--source-commit", provenance["source_commit"], "--output", str(output)]
    assert tool["main"](argv) == 0
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    assert before["PYTHON.json"] == raw
    inventory, _ = tool["verify_metadata"](tree)
    assert inventory == provenance["inventory"]
    assert tool["main"](argv) == 0
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
    argv[argv.index("--metadata-sha256") + 1] = "0" * 64
    assert tool["main"](argv) == 1
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


def test_notice_subset_checks_exact_bytes_and_unknown_components(tool, tree):
    metadata, provenance = tool["load_snapshot"]()
    notice = provenance["notices"][metadata["license_path"]]
    path = tree / notice["file"]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"substituted notice")
    with pytest.raises(tool["MetadataError"], match="source notice bytes disagree"):
        tool["verify_notice_sources"](tree, ["cpython"])
    with pytest.raises(tool["MetadataError"], match="unknown retained component"):
        tool["verify_notice_sources"](tree, ["setuptools"])


def test_openssl_notice_subset_uses_only_reviewed_build_selection(tool, tree):
    provenance_path = tree / "packaging/interpreter/PROVENANCE.json"
    provenance = json.loads(provenance_path.read_bytes())
    notice = provenance["notices"]["licenses/LICENSE.openssl-3.txt"]
    contents = b"reviewed selected notice fixture"
    path = tree / notice["file"]
    path.parent.mkdir(parents=True)
    path.write_bytes(contents)
    notice.update(sha256=tool["digest"](contents), size=len(contents))
    provenance_path.write_text(json.dumps(provenance))
    assert tool["verify_notice_sources"](tree, ["_ssl", "_hashlib"]) == 1
    provenance["source_commit"] = "0" * 40
    provenance["source_url"] = tool["SOURCE_URL"] + "/tree/" + "0" * 40
    provenance_path.write_text(json.dumps(provenance))
    with pytest.raises(tool["MetadataError"], match="OpenSSL notice selection"):
        tool["verify_metadata"](tree)


def test_fetcher_checks_metadata_before_curl_or_output_creation(package_tree, tmp_path):
    """Run only the isolated shell preflight, ending at a refusing curl sentinel."""
    tree = package_tree
    for relative in ("scripts/verify-interpreter-metadata.py", "src/idasen_companion/__init__.py",
                     "scripts/bundled-wheel-hashes.py", "packaging/bundled-wheel-hashes.json"):
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    commands = tmp_path / "commands"
    commands.mkdir()
    curl = commands / "curl"
    curl.write_text('#!/bin/sh\nprintf reached > "$CURL_CALLED"\nexit 73\n')
    curl.chmod(0o755)
    called = tmp_path / "curl-called"
    env = dict(os.environ, PYTHON=sys.executable, CURL_CALLED=str(called),
               PATH=str(commands) + os.pathsep + os.environ["PATH"], PYTHONDONTWRITEBYTECODE="1")
    fetcher = tree / "scripts/fetch-bundled-runtime.sh"
    valid = run_process(["bash", str(fetcher), str(tmp_path / "valid-output")],
                        capture_output=True, text=True, check=False, env=env, timeout=15)
    assert valid.returncode == 73, valid.stderr
    assert called.read_text() == "reached"
    called.unlink()
    text = fetcher.read_text()
    fetcher.write_text(text.replace('INTERPRETER_SHA256="cefba', 'INTERPRETER_SHA256="0efba'))
    stale_output = tmp_path / "stale-output"
    stale = run_process(["bash", str(fetcher), str(stale_output)],
                        capture_output=True, text=True, check=False, env=env, timeout=15)
    assert stale.returncode == 1, stale.stderr
    assert "fetcher identity disagrees" in stale.stderr
    assert not called.exists()
    assert not stale_output.exists()
    fetcher.write_text(text)
    (tree / "packaging/licenses/interpreter/LICENSE.sqlite.txt").write_bytes(b"wrong source text")
    stale = run_process(["bash", str(fetcher), str(stale_output)],
                        capture_output=True, text=True, check=False, env=env, timeout=15)
    assert stale.returncode == 1, stale.stderr
    assert "sqlite" in stale.stderr
    assert not called.exists()
    assert not stale_output.exists()


def test_source_manifest_carries_every_offline_verifier_input():
    manifest = (ROOT / "MANIFEST.in").read_text().splitlines()
    for relative in ("scripts/verify-interpreter-metadata.py", "packaging/interpreter/PYTHON.json",
                     "packaging/interpreter/PROVENANCE.json"):
        assert "include " + relative in manifest
    assert "recursive-include packaging/licenses/interpreter *.txt" in manifest
