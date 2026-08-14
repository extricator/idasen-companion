"""Packaging facts that are cheap to check and expensive to get wrong.

None of this needs rpmbuild; it reads the spec files as text. The point is the
class of error where the two specs, or a spec and the README, drift apart
silently — which is how the COPR spec ended up not installing the tray icon.
"""

import fnmatch
import re
import tomllib
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUNDLED = ROOT / "packaging" / "idasen-companion-bundled.spec"
SPLIT = ROOT / "packaging" / "idasen-companion.spec"
SPECS = [BUNDLED, SPLIT]
BUILD_DIST = ROOT / "scripts" / "build-dist.sh"
DEBIAN_CONTROL = ROOT / "debian" / "control"
DEBIAN_RULES = ROOT / "debian" / "rules"
DEBIAN_CHANGELOG = ROOT / "debian" / "changelog"
FLATPAK_MANIFEST = (ROOT / "packaging" / "flatpak"
                    / "io.github.extricator.IdasenCompanion.yaml")
METAINFO = ROOT / "data" / "io.github.extricator.IdasenCompanion.metainfo.xml"
CHANGELOG = ROOT / "CHANGELOG.md"
SRC = ROOT / "src" / "idasen_companion"


def read(p: Path) -> str:
    return p.read_text()


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_both_specs_install_the_symbolic_tray_icon(spec):
    """`gui/main.py` looks up APP_ID-symbolic *by name* through the icon
    theme. Without this file the panel silently falls back to the 64x64
    full-colour launcher icon — which is what the COPR spec shipped, on the
    build README advertises as the auto-updating path."""
    s = read(spec)
    icon = "io.github.extricator.IdasenCompanion-symbolic.svg"
    assert f"install -Dm644 data/icons/{icon}" in s, "not installed"
    assert f"hicolor/scalable/apps/{icon}" in s, "not in %files"


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_both_specs_install_the_appstream_metainfo(spec):
    """A software centre reads `/usr/share/metainfo/*.metainfo.xml` to show a
    name, summary, icon and screenshots for the package. Without this line
    the RPM installs and runs fine — nothing here fails a build — the package
    just has nothing to show in a listing, which is invisible from the
    build."""
    s = read(spec)
    metainfo = "io.github.extricator.IdasenCompanion.metainfo.xml"
    assert f"install -Dm644 data/{metainfo}" in s, "not installed"
    assert f"%{{_datadir}}/metainfo/{metainfo}" in s, "not in %files"


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_check_cannot_silently_skip_the_gui_tests(spec):
    """14 test modules `importorskip("PySide6")`. Without it as a
    BuildRequires they skip and %check still goes green, verifying 72% of the
    suite while the README presents a green build as having run it."""
    s = read(spec)
    assert "BuildRequires:  python3-pyside6" in s
    # ...and a guard, so removing the BuildRequires fails loudly rather than
    # quietly shrinking what %check covers.
    assert 'import PySide6' in s


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_the_licence_is_installed(spec):
    assert re.search(r"^%license ", read(spec), re.M)


# Names research disproved for the .deb's own dependency list: a bare
# PySide6 package that does not exist under this name on Debian or Ubuntu,
# the PyYAML name Fedora uses instead of Debian's own, and a dependency that
# reached the bundled RPM spec's Requires: by drift and is imported nowhere
# in src/.
WRONG_DEBIAN_DEPENDENCY_NAMES = (
    r"python3-pyside6[,\s]",
    r"python3-pyyaml",
    r"python3-voluptuous",
)
PYSIDE6_MODULES = ("qtcore", "qtgui", "qtwidgets", "qtdbus", "qtsvg")


def test_debian_control_depends_on_the_real_pyside6_modules_only():
    """PySide6 ships as ~63 per-module packages on Debian/Ubuntu, not one
    package named after the library. debian/control must name the five
    modules this app actually imports and none of the names research
    disproved: the single bare name doesn't exist, Fedora's PyYAML name
    differs from Debian's, and the third is stale drift the bundled RPM spec
    carries but nothing in src/ imports."""
    s = read(DEBIAN_CONTROL)
    missing = [m for m in PYSIDE6_MODULES if f"python3-pyside6.{m}" not in s]
    assert not missing, f"debian/control is missing PySide6 modules: {missing}"
    found = [p for p in WRONG_DEBIAN_DEPENDENCY_NAMES if re.search(p, s)]
    assert not found, f"debian/control still names a disproved dependency: {found}"


def test_debian_rules_guards_against_silently_skipped_gui_tests():
    """14 test modules importorskip("PySide6"). Without a build-time guard
    they skip and the pybuild test step still goes green, verifying 72% of
    the suite while the build reports it ran in full — the same trap
    test_check_cannot_silently_skip_the_gui_tests guards against for the RPM."""
    s = read(DEBIAN_RULES)
    assert "override_dh_auto_test" in s
    assert "PySide6.QtWidgets" in s


def test_the_user_unit_ships_under_the_filename_the_helper_resolves():
    """dh_installsystemduser resolves the unit from a
    debian/<pkg>.user.service filename. The debian/<pkg>.service spelling is
    the *system*-unit convention and would silently install no unit at all —
    a failure invisible to a build that still exits 0.

    Skipped when the full packaging tree isn't on disk: the Python sdist
    intentionally ships only the three debian/ files pyproject-based checks
    need, not this one, since dpkg-buildpackage reads the git checkout
    directly rather than through the sdist. debian/install never ships
    there either, so its presence is what this test uses to tell the two
    situations apart.
    """
    if not (ROOT / "debian" / "install").exists():
        pytest.skip("full debian/ tree not present (running from the sdist)")
    user_unit = ROOT / "debian" / "idasen-companion.user.service"
    system_unit_misspelling = ROOT / "debian" / "idasen-companion.service"
    assert user_unit.exists(), "debian/idasen-companion.user.service is missing"
    assert not system_unit_misspelling.exists(), (
        "debian/idasen-companion.service exists — dh_installsystemduser "
        "does not look for this filename and would install nothing"
    )
    assert user_unit.read_text() == (ROOT / "data" / "idasen-companion.service").read_text()


def test_the_contributor_guide_lists_every_build_requirement():
    """The documented `dnf install` line is the first thing a packager or
    contributor runs, and rpmbuild hard-fails on an unmet BuildRequires.

    The block lives in the contributor guide rather than the README: the
    README addresses someone installing a released artifact, who never runs
    this command. Moving it did not weaken the check, which follows the text.
    """
    required = set(re.findall(r"^BuildRequires:\s+(\S+)", read(BUNDLED), re.M))
    guide = (ROOT / "CONTRIBUTING.md").read_text()
    block = guide.split("sudo dnf install rpm-build")[1].split("```")[0]
    missing = sorted(p for p in required if p not in block)
    assert not missing, f"CONTRIBUTING build prerequisites omit: {missing}"


def test_no_shipped_file_carries_a_developer_home_path():
    """A `/home/<someone>` in a shipped file publishes an account name and is
    inert everywhere but that machine. The legacy
    idasen-desk-auto-sit-stand.service hardcoded one; it was the only such
    path in the repo, and the file was dead — shipped in neither the RPM nor
    the sdist. It is gone now, and the test below keeps it gone; this one
    stops an equivalent path reappearing anywhere else."""
    offenders = []
    for d in ("src", "data", "packaging", "scripts"):
        for f in sorted((ROOT / d).rglob("*")):
            if not f.is_file() or f.suffix in {".qm", ".mo", ".svg"}:
                continue
            try:
                text = f.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if re.search(r"/home/[a-z]", line):
                    offenders.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not offenders, offenders


def test_the_dead_legacy_unit_is_gone():
    assert not (ROOT / "idasen-desk-auto-sit-stand.service").exists()


# Vendor-namespaced D-Bus name literals, rooted at the four prefixes this
# project talks over. Discovered fresh from the source on every run rather
# than hardcoded — the same reasoning that makes the pylint suppression audit
# enumerate from pylint's own output rather than a list of "known" names.
_BUS_NAME_RE = re.compile(
    r"org\.(?:freedesktop|gnome|kde|bluez)\.[A-Za-z0-9_.]*[A-Za-z0-9_]")

# A finish-args list item granting a well-known name, anchored on the option
# itself so a comment that merely mentions a name can never satisfy this —
# only an actual grant line can.
_GRANT_RE = re.compile(r"^[ \t]*-[ \t]*--(?:system-)?talk-name=(\S+)[ \t]*$",
                       re.M)

# Names a straightforward source-grep can't settle either way, each with its
# own reason. Matched by plain prefix, not the dot-boundary rule the
# coverage relation below uses, because the exemption is deliberately
# broader than any single name:
EXEMPT_BUS_NAME_PREFIXES = frozenset({
    # Always available on both the session and system bus; nothing in this
    # project is ever granted access to it, and nothing needs to be.
    "org.freedesktop.DBus",
    # The tray icon exports this name on its own connection rather than
    # talking to a service by it, so the source never needs a grant for it —
    # and the well-known name it does talk to, the watcher, is negotiated
    # entirely inside Qt's own C++ tray implementation, so it never appears
    # as a literal in this project's own source either. One prefix accounts
    # for both halves of that pair.
    "org.kde.StatusNotifier",
    # Granted to every sandbox regardless of finish-args — that's the whole
    # point of a portal — so a talk-name grant here would be a no-op at
    # best. Plan 07 introduces the first reference under this namespace;
    # this exemption is written ahead of that so it never has to widen this
    # test under time pressure.
    "org.freedesktop.portal",
})


def _is_exempt_bus_name(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in EXEMPT_BUS_NAME_PREFIXES)


def _is_dot_boundary_prefix(prefix: str, name: str) -> bool:
    """True if `prefix` is `name` itself, or a prefix of it ending on a dot.

    This is what lets one bluez grant cover both the device and adapter
    interfaces, and one login1 grant cover its manager interface, without
    also letting an unrelated name that merely starts with the same
    characters count as covered.
    """
    return name == prefix or name.startswith(prefix + ".")


def _discovered_bus_names() -> set[str]:
    names: set[str] = set()
    for path in SRC.rglob("*.py"):
        names.update(_BUS_NAME_RE.findall(read(path)))
    return names


def _granted_bus_names() -> set[str]:
    return set(_GRANT_RE.findall(read(FLATPAK_MANIFEST)))


def test_finish_args_grant_every_bus_name_the_source_talks_to():
    """A bus name added to daemon/idle.py, daemon/notify.py, daemon/bluez.py
    or gui/sni.py without a matching finish-args line doesn't fail this
    build — it fails silently inside the sandbox instead, the first time a
    user hits that code path. This is what closes that gap for good."""
    discovered = _discovered_bus_names()
    granted = _granted_bus_names()
    missing = sorted(
        name for name in discovered
        if not _is_exempt_bus_name(name)
        and not any(_is_dot_boundary_prefix(g, name) for g in granted)
    )
    assert not missing, (
        f"finish-args grants no --talk-name/--system-talk-name covering: "
        f"{missing}")


def test_finish_args_grant_nothing_the_source_no_longer_talks_to():
    """The forward test above catches a missing grant; this is its mirror —
    a grant that outlived the code that needed it is a sandbox hole nobody
    uses, which is exactly the over-broad-permission failure mode this
    finish-args audit exists to prevent."""
    discovered = _discovered_bus_names()
    granted = _granted_bus_names()
    unused = sorted(
        grant for grant in granted
        if not _is_exempt_bus_name(grant)
        and not any(_is_dot_boundary_prefix(grant, name)
                   for name in discovered)
    )
    assert not unused, f"finish-args grants an unused bus name: {unused}"


def _strip_debian_revision(version: str) -> str:
    """Drop everything from the last hyphen onward.

    A Debian version string is `<upstream>-<revision>`, and the revision
    itself is free-form — an Ubuntu-style one can carry its own hyphen — so
    only the *last* hyphen marks the real boundary; a fixed-width slice would
    cut the wrong string for a longer revision.
    """
    return version.rsplit("-", 1)[0]


class VersionManifest(NamedTuple):
    """One packaging file that restates the package version, and how to
    read it back out."""

    path: Path
    pattern: re.Pattern[str]
    normalize: object = None


# Every manifest this project ships that states the package's own version,
# each paired with the regex that finds it and, where the surrounding syntax
# adds something beyond the bare version, the normalisation that strips it
# back down to a bare version string. `pyproject.toml` is deliberately not
# here: it declares its version dynamic and reads `__version__` directly, so
# there is nothing in it to drift.
VERSION_MANIFESTS = [
    VersionManifest(BUNDLED, re.compile(r"^Version:\s+(\S+)", re.M)),
    VersionManifest(SPLIT, re.compile(r"^Version:\s+(\S+)", re.M)),
    VersionManifest(DEBIAN_CHANGELOG,
                     re.compile(r"^idasen-companion \(([^)]+)\)"),
                     _strip_debian_revision),
    VersionManifest(FLATPAK_MANIFEST,
                     re.compile(r"idasen_companion-([\d.]+)\.tar\.gz")),
    VersionManifest(METAINFO, re.compile(r'<release version="([\d.]+)"')),
    # Anchored to the start of a line so it finds the topmost version heading
    # and stops there; a heading whose name is not a version number is left
    # alone, since the capture only accepts digits and dots.
    VersionManifest(CHANGELOG, re.compile(r"^## \[([\d.]+)\]", re.M)),
]


def test_the_metainfo_is_well_formed_xml():
    """Every other check on this file reads it as text, with a regex, so a
    broken document sails past all of them and the suite goes green.

    Only `appstreamcli` in CI notices, which makes a two-character mistake a
    push-and-wait to find. A comment carrying a double hyphen does it, which
    XML forbids inside one: the regex checks stay satisfied, every test
    passes, and the file will not parse.
    """
    import xml.etree.ElementTree as ET

    ET.parse(METAINFO)


# The metainfo states the version a second time, in the tag each screenshot
# URL is pinned to, and the table above cannot reach it -- that pattern reads
# the newest release element and stops. Nothing else looked at these, and they
# drifted the first time they were touched: the screenshots were replaced with
# a new set and the URLs left naming the previous tag, which does not carry
# the new files. A software centre renders that as a listing with no
# screenshots at all, and no build step notices, because the images are
# fetched by the centre rather than shipped in the package.
SCREENSHOT_URL = re.compile(
    r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/v([\d.]+)/([^<\s]+)")


def test_every_screenshot_url_names_this_version_and_the_file_is_present():
    """Both halves are needed, and neither alone is worth much.

    The URL naming the current version is what makes it resolve *after* the
    release tags this commit. The file sitting in the tree is what makes the
    tag carry it. A URL that names the right tag but points at a file nobody
    added is exactly the state this test was written for.

    The count is checked too. A malformed URL simply fails to match the
    pattern, and without this the test would pass by looking at nothing.

    The second half runs only from a checkout. The images are deliberately
    not in the sdist -- a software centre fetches them from the forge and
    nothing installs them, and at 639 kB they would take the tarball straight
    through its size ceiling. The metainfo itself does ship, so the version
    half still runs inside the RPM's %check, where this whole test failed
    once for asserting a checkout-only fact.
    """
    from idasen_companion import __version__

    text = read(METAINFO)
    urls = SCREENSHOT_URL.findall(text)
    # Match the element, not the container that wraps them: the opening tag
    # is followed by an attribute or by its own close, never by a letter.
    declared = len(re.findall(r"<screenshot[ >]", text))
    assert len(urls) == declared, (
        f"{declared} screenshot elements but {len(urls)} usable URLs — "
        f"one is malformed and would be skipped rather than checked")

    from_a_checkout = (ROOT / "data" / "screenshots").is_dir()
    for version, path in urls:
        assert version == __version__, (
            f"{path} is pinned to v{version}, package says {__version__}")
        if from_a_checkout:
            assert (ROOT / path).is_file(), (
                f"{path} is named by a screenshot URL but is not in the "
                f"tree, so the tag will not carry it either")


@pytest.mark.parametrize(
    "manifest", VERSION_MANIFESTS,
    ids=lambda m: m.path.relative_to(ROOT).as_posix())
def test_every_manifest_agrees_with_the_package_version(manifest):
    """The version is restated all over the place — pyproject.toml,
    __init__.py, both app specs, `debian/changelog`, the Flatpak manifest's
    sdist source path, the AppStream metainfo's newest release and the
    release notes' newest heading — with nothing checking they all matched.
    pyproject now derives it from `__version__`; none of the other six can,
    so they are pinned here.

    It matters because `__version__` is what the daemon reports over
    `--version` and writes into its startup log line, so a drift shows up in
    bug reports as a version that was never released. Phase 4's bump to
    1.0.0 is the first thing that will exercise every row in this table.
    """
    from idasen_companion import __version__

    text = read(manifest.path)
    found = manifest.pattern.search(text)
    assert found, f"{manifest.path.relative_to(ROOT)}: no version found"
    version = found.group(1)
    if manifest.normalize is not None:
        version = manifest.normalize(version)
    assert version == __version__, (
        f"{manifest.path.relative_to(ROOT)} says {version}, "
        f"package says {__version__}")


def test_the_current_version_has_release_notes_with_something_in_them():
    """The table above only proves the topmost heading *names* the current
    version. A heading with nothing under it passes that check and then
    becomes the release body — an empty release page, discovered after the
    tag has been pushed and spent, which is the one point in the process
    that cannot be repeated.

    Checks content rather than the heading, so the pair of them cover both
    halves of what `CONTRIBUTING.md` promises: that the section is neither
    missing nor empty.
    """
    from idasen_companion import __version__

    text = read(CHANGELOG)
    heading = f"## [{__version__}]"
    start = text.find(heading)
    assert start != -1, (
        f"CHANGELOG.md has no {heading} section — the release body is "
        f"extracted from it, so there would be nothing to publish")

    after = text[start + len(heading):]
    end = after.find("\n## ")
    body = (after if end == -1 else after[:end])
    # Drop the remainder of the heading line itself (the date), leaving only
    # what a reader would actually see under it.
    _, _, body = body.partition("\n")
    assert body.strip(), (
        f"CHANGELOG.md's {heading} section is empty. It is used verbatim as "
        f"the release body, and a tag is spent by the time the release "
        f"workflow would notice")


def test_debian_revision_stripping_keeps_only_the_last_hyphen_boundary():
    """A revision can itself contain a hyphen — cutting at the first one
    instead of the last would leave part of the revision behind."""
    assert _strip_debian_revision("0.2.0-1") == "0.2.0"
    assert _strip_debian_revision("0.2.0-0ubuntu1-1") == "0.2.0-0ubuntu1"


# Specs in packaging/ that state some *other* project's version — vendored
# libraries this app bundles, not the app itself — and so must never be
# compared against __version__.
UNRELATED_LIBRARY_SPECS = frozenset({
    ROOT / "packaging" / "python-bleak.spec",
    ROOT / "packaging" / "python-idasen.spec",
})


def _discovered_manifest_shaped_files() -> set[Path]:
    discovered = set(ROOT.glob("packaging/*.spec"))
    discovered.update(ROOT.glob("packaging/flatpak/*.yaml"))
    discovered.add(DEBIAN_CHANGELOG)
    discovered.update(ROOT.glob("data/*.metainfo.xml"))
    # The globs above reach into packaging directories only; the release
    # notes sit at the repository root, so nothing discovers them by shape
    # and they have to be named.
    discovered.add(CHANGELOG)
    return discovered - UNRELATED_LIBRARY_SPECS


def test_every_manifest_shaped_file_is_in_the_version_table():
    """A packaging manifest that exists on disk but is missing from
    VERSION_MANIFESTS above is one nobody is comparing to __version__ —
    exactly the drift this whole check exists to close. A table row naming a
    file that no longer exists is the opposite failure: a stale entry left
    behind after a manifest was removed. This test goes red either way.

    Only files present on disk are compared. Inside an unpacked sdist,
    several of the table's paths are deliberately absent (see MANIFEST.in);
    an unconditional set comparison would fail there for a reason unrelated
    to what this test exists to catch, so both sides are first restricted to
    what actually exists in the environment the suite is running in.
    """
    discovered = {p for p in _discovered_manifest_shaped_files() if p.exists()}
    tabled = {m.path for m in VERSION_MANIFESTS if m.path.exists()}
    assert discovered == tabled


def test_pyproject_does_not_restate_the_version():
    text = (ROOT / "pyproject.toml").read_text()
    assert 'dynamic = ["version"]' in text
    assert re.search(r'^version = "', text, re.M) is None


def test_build_dist_refuses_untracked_files_before_building():
    """The untracked-file guard exists to fail before any artifact is
    produced, which only holds if it actually runs first."""
    s = read(BUILD_DIST)
    untracked_offset = s.index("git ls-files --others")
    build_offset = s.index("-m build")
    assert untracked_offset < build_offset


def test_build_dist_allowlist_is_exactly_three_patterns():
    """A fourth pattern appearing here means someone widened the allowlist
    instead of fixing the leak it exists to catch."""
    s = read(BUILD_DIST)
    allow_exact = re.search(r"allow_exact = \{([^}]*)\}", s)
    assert allow_exact, "no allow_exact set found in build-dist.sh"
    egg_info_pattern = re.search(r'egg_info_pattern = "([^"]+)"', s)
    assert egg_info_pattern, "no egg_info_pattern found in build-dist.sh"

    patterns = set(re.findall(r'"([^"]+)"', allow_exact.group(1)))
    patterns.add(egg_info_pattern.group(1))
    assert patterns == {"PKG-INFO", "setup.cfg", "src/*.egg-info/*"}


def test_build_dist_wheel_check_matches_package_data():
    """The wheel check's asserted catalog paths and pyproject's
    package-data patterns must describe the same two files, or one could
    silently drift from the other."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package_data = pyproject["tool"]["setuptools"]["package-data"]["idasen_companion"]

    s = read(BUILD_DIST)
    required_qm = re.search(r'required_qm = "([^"]+)"', s)
    mo_pattern = re.search(r'mo_pattern = "([^"]+)"', s)
    assert required_qm, "no required_qm found in build-dist.sh"
    assert mo_pattern, "no mo_pattern found in build-dist.sh"

    for asserted in (required_qm.group(1), mo_pattern.group(1)):
        rel = asserted.removeprefix("idasen_companion/")
        assert any(fnmatch.fnmatch(rel, pattern) for pattern in package_data), (
            f"{asserted} matches none of pyproject.toml's package-data patterns"
        )
