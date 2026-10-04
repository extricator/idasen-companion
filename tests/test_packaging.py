"""Packaging facts that are cheap to check and expensive to get wrong.

None of this needs rpmbuild; it reads the spec files as text. The point is the
class of error where the two specs, or a spec and the README, drift apart
silently — which is how the COPR spec ended up not installing the tray icon.
"""

import fnmatch
import importlib.util
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUNDLED = ROOT / "packaging" / "idasen-companion-bundled.spec"
SPLIT = ROOT / "packaging" / "idasen-companion.spec"
LAUNCHER = ROOT / "packaging" / "idasen-companion-launcher.sh"
SPECS = [BUNDLED, SPLIT]
BUILD_DIST = ROOT / "scripts" / "build-dist.sh"
DEBIAN_CONTROL = ROOT / "debian" / "control"
DEBIAN_RULES = ROOT / "debian" / "rules"
DEBIAN_CHANGELOG = ROOT / "debian" / "changelog"
FLATPAK_MANIFEST = (ROOT / "packaging" / "flatpak"
                    / "io.github.extricator.IdasenCompanion.yaml")
FLATPAK_DEPS = ROOT / "packaging" / "flatpak" / "python3-deps.json"
METAINFO = ROOT / "data" / "io.github.extricator.IdasenCompanion.metainfo.xml"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
MANIFEST = ROOT / "MANIFEST.in"
VENDORED_LICENCES = ROOT / "packaging" / "licenses"
RUNTIME_FETCHER = ROOT / "scripts" / "fetch-bundled-runtime.sh"
TRIMMER = ROOT / "scripts" / "trim-pyside6.py"
INTERPRETER_TRIMMER = ROOT / "scripts" / "trim-cpython.py"
ELF_VERIFIER = ROOT / "scripts" / "verify-bundled-elf.sh"
STRIP_PASS = ROOT / "scripts" / "strip-bundled-tree.sh"
BYTECODE_VERIFIER = ROOT / "scripts" / "verify-bundled-bytecode.sh"
METADATA_VERIFIER = ROOT / "scripts" / "verify-rpm-metadata.sh"
PORTABILITY_VERIFIER = ROOT / "scripts" / "verify-rpm-portability.sh"
RELEASE_BUILDER = ROOT / "scripts" / "build-release-variants.sh"
RELEASE_VERIFIER = ROOT / "scripts" / "verify-release-artifacts.sh"
PACKAGES_WORKFLOW = ROOT / ".github" / "workflows" / "packages.yml"
RPM_WORKFLOW = PACKAGES_WORKFLOW
DEB_WORKFLOW = PACKAGES_WORKFLOW
FLATPAK_WORKFLOW = PACKAGES_WORKFLOW
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
SRC = ROOT / "src" / "idasen_companion"
STATS = SRC / "daemon" / "stats.py"


def read(p: Path) -> str:
    return p.read_text()


def test_project_exposes_daemon_and_shared_command_entry_points():
    scripts = tomllib.loads(read(ROOT / "pyproject.toml"))["project"]["scripts"]
    assert scripts == {
        "idasen-companiond": "idasen_companion.daemon.main:main",
        "idasen-companion": "idasen_companion.command:main",
    }

    bundled = read(BUNDLED)
    install = spec_section(bundled, "install")
    files = spec_section(bundled, "files")
    assert "s/@ENTRY@/idasen_companion.command/" in install
    assert "s/@ENTRY@/idasen_companion.gui.main/" not in install
    assert "%{_bindir}/idasen-companion\n" in files
    assert "%{_bindir}/idasen-companiond\n" in files
    assert "idasen-companion-cli" not in install + files


def test_release_builder_and_verifier_define_the_five_asset_contract():
    builder = read(RELEASE_BUILDER)
    verifier = read(RELEASE_VERIFIER)
    for selector in ("--all", "--rpm", "--deb", "--flatpak", "--output"):
        assert selector in builder
    for stem in (
        "idasen-companion-[0-9]*.rpm",
        "idasen-companion-headless-*.rpm",
        "idasen-companion_[0-9]*.deb",
        "idasen-companion-headless_*.deb",
        "idasen-companion-[0-9]*.flatpak",
    ):
        assert stem in verifier


def test_release_verifier_installs_flatpak_runtime_in_its_isolated_home():
    verifier = read(RELEASE_VERIFIER)
    manifest = read(FLATPAK_MANIFEST)
    runtime = re.search(r"^runtime: (\S+)$", manifest, re.M)
    branch = re.search(r"^runtime-version: ['\"]?([^'\"\n]+)", manifest, re.M)
    assert runtime is not None
    assert branch is not None

    assert "flatpak_runtime=$(sed" in verifier
    assert "flatpak_runtime_version=$(sed" in verifier
    assert 'XDG_DATA_HOME="$flatpak_dir" flatpak --user remote-add' in verifier
    assert 'flathub "$flatpak_runtime//$flatpak_runtime_version"' in verifier


def test_workflow_package_artifacts_expire_after_one_day():
    if not RELEASE_WORKFLOW.exists():
        pytest.skip("workflow files are intentionally absent from the sdist")
    for workflow_path in (PACKAGES_WORKFLOW, RELEASE_WORKFLOW):
        workflow = read(workflow_path)
        assert workflow.count("retention-days: 1") == workflow.count(
            "actions/upload-artifact"
        )


def test_native_variants_are_standalone_and_mutually_exclusive():
    spec = read(BUNDLED)
    assert "%global package_name idasen-companion-headless" in spec
    assert "Conflicts:      idasen-companion-headless" in spec
    assert "Conflicts:      idasen-companion" in spec
    assert "release_flavor headless" in read(RELEASE_BUILDER)

    control = read(DEBIAN_CONTROL)
    assert "Package: idasen-companion\n" in control
    assert "Package: idasen-companion-headless\n" in control
    assert "Conflicts: idasen-companion-headless" in control
    assert "Conflicts: idasen-companion\n" in control


def test_headless_debian_payload_clones_common_tree_then_removes_gui():
    install = read(ROOT / "debian" / "idasen-companion.install")
    assert "usr/bin/idasen-companion\n" in install
    assert "idasen-companion-cli" not in install
    for full_only in (".desktop", "icons/", "metainfo"):
        assert full_only in install
    rules = read(DEBIAN_RULES)
    headless = read(ROOT / "debian" / "idasen-companion-headless.install")
    assert "usr/bin/idasen-companion\n" in headless
    assert "usr/bin/idasen-companiond" in headless
    assert "idasen-companion-cli" not in headless
    assert "export PYBUILD_DESTDIR=debian/tmp" in rules
    assert "idasen-companion-headless/usr/lib/python3*/dist-packages/idasen_companion/gui" in rules
    assert "test -x debian/idasen-companion-headless/usr/bin/idasen-companion" in rules
    assert "rm -f debian/idasen-companion-headless/usr/bin/idasen-companion" not in rules


def test_release_smoke_checks_the_shared_command_in_both_flavors():
    verifier = read(RELEASE_VERIFIER)
    assert "idasen-companion --help" in verifier
    assert "idasen-companion status" in verifier
    assert "subcommand is required" in verifier
    assert "--command=idasen-companion-cli" not in verifier
    assert "command: idasen-companion\n" in read(FLATPAK_MANIFEST)


def test_flatpak_docs_show_the_shared_command():
    flatpak_readme = ROOT / "packaging" / "flatpak" / "README.md"
    if not flatpak_readme.exists():
        pytest.skip("Flatpak documentation is intentionally absent from the sdist")
    assert "flatpak run io.github.extricator.IdasenCompanion status" in read(
        flatpak_readme
    )


def test_every_existing_artifact_path_carries_babel():
    """Babel is a base runtime dependency, not a GUI-only convenience."""
    pyproject = tomllib.loads(read(ROOT / "pyproject.toml"))
    assert any(requirement.startswith("Babel>=")
               for requirement in pyproject["project"]["dependencies"])

    split = read(SPLIT)
    assert "BuildRequires:  python3-babel" in split
    assert "Requires:       python3-babel" in split

    debian = read(DEBIAN_CONTROL)
    # One build dependency plus one runtime dependency in each standalone
    # Debian flavor.
    assert debian.count("python3-babel") == 3

    assert '"Babel==2.18.0"' in read(RUNTIME_FETCHER)
    assert "bundled(python3dist(babel)) = 2.18.0" in read(BUNDLED)
    assert "LICENSE.babel" in read(BUNDLED)

    flatpak = read(FLATPAK_DEPS)
    assert "babel==2.18.0" in flatpak
    assert "babel-2.18.0-py3-none-any.whl" in flatpak


def test_debian_ci_installs_babel_before_checking_build_dependencies():
    """The CI image installs a deliberate package list instead of build-dep."""
    if not DEB_WORKFLOW.exists():
        pytest.skip("workflow files are intentionally absent from the sdist")
    assert "python3-babel" in read(DEB_WORKFLOW)


def test_flatpak_ci_installs_the_manifest_base_app_branch():
    if not FLATPAK_WORKFLOW.exists():
        pytest.skip("workflow files are intentionally absent from the sdist")
    manifest = read(FLATPAK_MANIFEST)
    base = re.search(r"^base: (\S+)$", manifest, re.M)
    branch = re.search(r"^base-version: ['\"]?([^'\"\n]+)", manifest, re.M)
    assert base is not None
    assert branch is not None
    expected_ref = f"{base.group(1)}//{branch.group(1)}"

    workflow = read(FLATPAK_WORKFLOW)
    assert "flatpak install --noninteractive --assumeyes flathub" in workflow
    assert expected_ref in workflow
    assert "--disable-rofiles-fuse" in read(RELEASE_BUILDER)


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


def spec_section(spec_text: str, name: str) -> str:
    """The body of one %-section of a spec file.

    Sections end at the next one, and a section body's own macro references
    (`%{python3}`, `%{buildroot}`) are not section headers — a brace is not a
    letter, which is what tells the two apart.
    """
    _, _, body = spec_text.partition(f"\n%{name}\n")
    assert body, f"the spec has no %{name} section"
    # Conditionals such as %if/%else are part of a section, not new sections.
    # Stop only at RPM's actual top-level script/file/changelog sections.
    return re.split(
        r"\n%(?:prep|build|install|check|post|preun|postun|files|changelog)\b",
        body,
        maxsplit=1,
    )[0]


def spec_commands(section: str) -> list[str]:
    """The commands a spec section runs, one per element.

    Comments go first, so a sentence reciting a command can never stand in for
    the command; continued lines are then joined, so a command that was
    wrapped for width is still one thing to look at.
    """
    uncommented = "\n".join(line for line in section.splitlines()
                            if not line.lstrip().startswith("#"))
    joined = re.sub(r"\\\n\s*", " ", uncommented)
    return [line.strip() for line in joined.splitlines() if line.strip()]


def test_the_split_spec_cannot_silently_skip_the_gui_tests():
    """14 test modules `importorskip("PySide6")`. Without it as a
    BuildRequires they skip and %check still goes green, verifying 72% of the
    suite while the README presents a green build as having run it."""
    s = read(SPLIT)
    assert "BuildRequires:  python3-pyside6" in s
    # ...and a guard, so removing the BuildRequires fails loudly rather than
    # quietly shrinking what %check covers.
    assert 'import PySide6' in s


def test_the_launcher_runs_the_entry_point_in_isolation():
    """Three directories would otherwise be searched for a module before the
    bundled copies: the process's working directory, which the interpreter puts
    at the very front when asked to run a module; the user's own
    `~/.local/lib/pythonX.Y/site-packages`; and whatever a `PYTHON*` variable
    in the environment names. The daemon's unit sets no working directory and
    therefore starts in the user's home, so a stray `tomlkit.py` or
    `logging.py` sitting there is enough. The switch asserted here takes all
    three off the search path at once, leaving the bundled interpreter's own
    directories and nothing else — which is what makes what ships be what runs.

    Anchored to the line that runs the entry point rather than to the file,
    since the same characters mean something else anywhere else in a shell
    script.
    """
    line = re.search(r"^exec .*-m @ENTRY@.*$", read(LAUNCHER), re.M)
    assert line, "the launcher no longer runs the entry point as a module"
    assert " -I " in line.group(0), (
        "the launcher runs the entry point without isolation, so the working "
        "directory, the user's own site directory and any Python search path "
        "in the environment all outrank the bundled copies")


def test_the_bundled_spec_cannot_silently_skip_the_gui_tests():
    """The same guarded failure as the split spec above, by a different
    mechanism: this package ships its own Qt, so there is no build dependency
    to name and nothing to assert about one. What has to hold instead is that
    %check imports Qt out of the tree that ships — with an empty or wrong
    path there, the GUI modules skip themselves and the build stays green
    having verified 72% of the suite.

    Both halves are read off the command that has to carry them rather than
    off the section. Two commands in there name the shipped tree, so asking
    whether the section mentions it anywhere is answered by either — and the
    one that matters is the suite, which is where dropping the path produces
    exactly the shrinking %check this describes while the import probe goes
    on satisfying the question.

    What names the tree is the interpreter out of the build root, run in
    isolation: that interpreter's own directories are the shipped libraries,
    and isolation is what keeps them there alone. Take either away and the
    modules resolve from the machine instead, which is the failure this
    describes.
    """
    commands = spec_commands(spec_section(read(BUNDLED), "check"))
    shipped = "%{buildroot}%{bundled_interpreter}"

    suites = [c for c in commands if "pytest" in c and shipped in c]
    suite = [c for c in suites if "QT_QPA_PLATFORM=offscreen" in c]
    assert len(suite) == 1, (
        f"%check runs the full GUI suite on the interpreter the package ships "
        f"{len(suite)} times; it runs it once, and not on the build host's")
    assert " -I " in suite[0], (
        "%check runs the suite without isolation, so the build host's own "
        "copy of a bundled library outranks the shipped one and the suite "
        "verifies the wrong tree")

    probe = [c for c in commands if "from PySide6 import" in c]
    assert len(probe) == 1, "%check has no single import probe for the bundled Qt"
    assert shipped in probe[0] and " -I " in probe[0], (
        "%check's Qt import probe reads the machine's own Qt, not the bundled "
        "one, so it passes on a package that ships no working Qt at all")
    imported = {name.strip()
                for name in re.search(r"from PySide6 import ([^\"']+)",
                                      probe[0]).group(1).split(",")}
    assert {"QtCore", "QtGui", "QtWidgets", "QtDBus"} <= imported


def test_nothing_in_the_check_runs_the_build_hosts_python_over_the_shipped_tree():
    """The failure this closes left a fingerprint in three shipped releases:
    105 bytecode caches tagged for the build host's CPython, in a package that
    carries a different one. Nothing installed them and nothing reads them.
    They were written by %check, which used to import the app and the bundled
    Qt on the host's interpreter with a search path pointed into the build
    root, and the build then packaged whatever it found.

    The dead weight is the small half. The host's own site directory carries a
    path configuration file that imports a module *by name* at every startup,
    and a search path pointed at the shipped tree outranks the host's copy of
    it — so the host interpreter reached into the package's private tree
    without being asked to, on a plain start. A build step that runs the host's
    Python over this tree is that mechanism, whatever it is nominally doing.

    Stated as the pair rather than as either half: the build host's
    interpreter is legitimate for the build's own tooling, and the build root
    is legitimate for the shipped interpreter. It is one naming the other that
    is the defect.
    """
    commands = spec_commands(spec_section(read(BUNDLED), "check"))
    reaching = [c for c in commands
                if "%{python3}" in c and "%{buildroot}" in c]
    assert not reaching, (
        f"%check runs the build host's interpreter against the tree the "
        f"package ships, which is what wrote bytecode for an interpreter the "
        f"package does not carry: {reaching}")


def test_the_check_examines_the_tree_that_ships_for_what_it_links():
    """Two facts hold this package together and neither is visible in a diff of
    it: nothing it carries references the interpreter's shared library, which
    is why that library is not in the package, and nothing it carries requires
    a symbol version newer than the oldest distribution line it reaches. A
    PySide6 or CPython release can end either one, and the build that noticed
    would be the one that stopped.

    What the argument names is the whole assertion. Two interpreters exist
    while a build runs and only one is packaged: the other is untrimmed, still
    carries the shared library this looks for, and runs pip. Pointed at that
    one, every check here would report on a tree no user ever receives — and in
    the direction that reads as a failure, which is how it would be noticed and
    then loosened.

    Read off the command rather than the section, so a comment naming the
    script neither satisfies this nor trips it.
    """
    commands = spec_commands(spec_section(read(BUNDLED), "check"))
    runs = [c for c in commands if ELF_VERIFIER.name in c]
    assert len(runs) == 1, (
        f"%check runs the linkage and symbol-version assertions {len(runs)} "
        f"times; it has to run them once, over the tree it is about to ship")
    assert "%{buildroot}%{appdir}" in runs[0], (
        "%check makes those assertions about something other than the tree "
        "the package is built from, so a regression in what ships passes them")


# The marker every file that decides about a strip has to be reading. It is
# the prefix BOLT gives the sections it leaves behind, and the whole exemption
# turns on it: the interpreter trim declines to strip a binary carrying it,
# the strip pass walks past one, and the verifier excuses one. Written with
# the dots optionally escaped, since two of the three match it as a pattern
# and the third as a shell glob.
BOLT_MARKER = re.compile(r"\\?\.bolt\\?\.org")

# The verifier's own status for a tree that stopped being stripped, read off
# the statement that returns it — the table of statuses in that file's header
# names the number too, and a check a comment can satisfy is measuring the
# wrong thing.
ELF_UNSTRIPPED_EXIT = re.compile(r"^\s*return 40\s*$", re.M)


def test_the_install_strips_what_ships_and_the_check_holds_it_to_that():
    """rpm's own build-root strip pass is switched off for this package and
    has to be — it walks the whole build root, and one binary in the tree is
    laid out by BOLT, which every strip tried against it corrupts. What that
    switch cannot do is spare only that binary: it spares every ELF file the
    package carries, which is Qt's libraries, PySide6's extension modules,
    ICU's tables and the standard library's own. Nothing about that fails.
    The package builds, installs and runs, carrying whatever each dependency's
    build host happened to leave on it — 2.2 MB of it at the time this was
    written, and no signal at all the day a new dependency brings more.

    So the pass is run by hand over the shipped tree, and the outcome is
    asserted separately from the step: a verifier that walks the finished tree
    is what turns "the pass no longer reaches these files" into a failed build
    rather than a bigger package.

    Read off parsed commands, so a comment describing either can neither
    satisfy this nor trip it.
    """
    install = spec_commands(spec_section(read(BUNDLED), "install"))
    passes = [c for c in install if STRIP_PASS.name in c]
    assert len(passes) == 1, (
        f"%install runs the strip pass {len(passes)} times; it runs it once, "
        f"over the tree the package is about to carry")
    assert "%{buildroot}%{appdir}" in passes[0], (
        "%install strips something other than the private directory the "
        "package installs, so what ships is stripped by nothing at all")

    assert ELF_UNSTRIPPED_EXIT.search(uncommented(read(ELF_VERIFIER))), (
        "the ELF assertions no longer refuse a tree carrying a symbol table, "
        "so the hand-run strip pass above could stop reaching a file and the "
        "build would go green on a package that ships it unstripped")


def test_everything_deciding_about_a_strip_reads_the_same_exemption():
    """Three files decide whether a binary may be stripped — the interpreter
    trim, the strip pass over everything else, and the verifier that refuses
    what neither of them stripped — and each of them answers it alone. They
    agree today by all reading BOLT's own section names, and that agreement is
    the whole design: an asset that stops being laid out that way gets its
    strip back in all three at once, with nothing to change anywhere.

    Drift here is silent in the worst direction. A trim that still declines
    and a verifier that no longer excuses is a build that cannot finish; a
    trim that strips and a pass that walks past is a corrupted interpreter in
    a package that builds.

    Read off each file's live text rather than its prose, since all three
    describe the marker in sentences as well.
    """
    deciding = (INTERPRETER_TRIMMER, STRIP_PASS, ELF_VERIFIER)
    blind = [p.name for p in deciding
             if not BOLT_MARKER.search(uncommented(read(p)))]
    assert not blind, (
        f"these decide whether something may be stripped without reading the "
        f"marker the other(s) exempt on, so the three no longer agree about "
        f"which binary is exempt: {blind}")


def test_the_check_holds_the_shipped_bytecode_to_the_interpreter_that_ships():
    """A cache tagged for another interpreter is what a build step running the
    machine's own Python out of this tree leaves behind, and 105 of them went
    out in three releases before anyone looked. The steps that wrote them are
    gone; this is what says they have not come back — after a distribution
    bump moves the build host's Python, or after somebody adds one more probe
    to %check.

    Three properties, and the third is the one a reader skips. It has to be
    the last thing in the section, because everything above it runs *out of*
    the tree it examines: moved up by one step, it reports on the tree as it
    was before whatever follows wrote to it, which is exactly the state it
    exists to disbelieve.

    The tag it compares against has to come from the interpreter in the build
    root rather than from a constant beside the minor version. Two constants
    agree with each other after a version has been moved in one place only,
    which is the moment this should be failing.
    """
    commands = spec_commands(spec_section(read(BUNDLED), "check"))
    runs = [c for c in commands if BYTECODE_VERIFIER.name in c]
    assert len(runs) == 1, (
        f"%check makes the bytecode assertions {len(runs)} times; it makes "
        f"them once, over the tree it is about to ship")
    assert "%{buildroot}%{appdir}" in runs[0], (
        "%check makes those assertions about something other than the private "
        "directory the package installs, so bytecode for the wrong "
        "interpreter passes them")

    derivations = [c for c in commands if "cache_tag" in c]
    assert len(derivations) == 1, (
        f"%check asks for the interpreter's cache tag {len(derivations)} "
        f"times; asking once is what keeps the tag and the interpreter one "
        f"fact")
    assert "%{buildroot}%{bundled_interpreter}" in derivations[0], (
        "%check takes the cache tag from something other than the interpreter "
        "the package ships, so the assertions are made against a tag no file "
        "in the package was written under")
    named = re.match(r"^(\w+)=\$\(", derivations[0])
    assert named, "the cache tag is no longer read into anything"
    assert f'"${named.group(1)}"' in runs[0], (
        "the bytecode assertions are made against something other than the "
        "tag %check just asked the shipped interpreter for")

    after = commands[commands.index(runs[0]) + 1:]
    reaching = [c for c in after if "%{buildroot}" in c]
    assert not reaching, (
        f"%check touches the build root after asserting what its bytecode is, "
        f"so anything those steps write ships unexamined: {reaching}")


# A path to one of this repository's own programs, as a command in the spec
# names it. Anchored to the two suffixes it uses rather than to any characters
# at all, so a directory or a partial word is not read as one.
SPEC_SCRIPT = re.compile(r"\bscripts/[\w.-]+\.(?:sh|py)\b")


def test_every_script_the_bundled_build_runs_ships_in_the_sdist():
    """MANIFEST.in reads the filesystem, and the RPM builds from an unpacked
    tarball. So a script this build runs but nobody named is sitting right
    there during every local build and absent from the one that matters, where
    rpmbuild stops partway through a section. It has shipped that way once
    already, and the sdist audit cannot catch it: that asserts what ships is
    tracked, not that what is needed ships.

    Read off parsed commands in both directions — a comment naming a script
    neither adds one to the list nor answers for one.
    """
    spec = read(BUNDLED)
    invoked = set()
    for section in ("prep", "install", "check"):
        for command in spec_commands(spec_section(spec, section)):
            invoked.update(SPEC_SCRIPT.findall(command))
    assert invoked, "the bundled build runs none of this repository's programs"

    manifest = read(MANIFEST)
    missing = sorted(name for name in invoked
                     if not re.search(rf"^include {re.escape(name)}$",
                                      manifest, re.M))
    assert not missing, (
        f"the bundled build runs these and the sdist does not carry them, so "
        f"the package build dies partway through while every local build "
        f"passes: {missing}")


def test_the_check_runs_the_daemon_the_way_the_package_will():
    """Two properties make this a proof about the package rather than about
    whatever happened to be installed on the build host. It has to be the
    interpreter out of the build root — a run on the host's own Python would
    pass on a package whose bundled tree cannot start at all, which is exactly
    the failure this exists to catch, since the two experiments the design rests
    on were run against trees that each lacked half of what ships. And it has to
    be a simulated desk — a build that reached a real one over Bluetooth would
    be moving somebody's furniture, and would report on their desk's
    availability rather than on this package.
    """
    commands = spec_commands(spec_section(read(BUNDLED), "check"))
    starts = [c for c in commands
              if "-m idasen_companion.daemon.main" in c]
    assert len(starts) == 1, (
        f"%check starts the daemon {len(starts)} times; it starts it once, "
        f"out of the tree the build is about to package")
    assert "%{buildroot}%{bundled_interpreter}" in starts[0], (
        "%check starts the daemon on something other than the interpreter in "
        "the build root, so it proves nothing about the tree that ships")
    assert "--mock-desk" in starts[0], (
        "%check starts the daemon against a real desk over Bluetooth, from a "
        "package build")


#: The two places that start the smoke daemon behind ``dbus-run-session``.
#: Both had the same defect and both carry the same fix, so both are checked
#: by one test rather than by one test each that could drift apart.
SMOKE_DAEMON_STARTERS = (
    ("packaging/idasen-companion-bundled.spec", "%check"),
    ("scripts/verify-rpm-portability.sh", None),
)

#: A kill aimed at a process *group* — the minus before the id is the whole
#: point, so the pattern insists on it. ``kill "$daemon"`` and
#: ``kill -- -"$daemon"`` differ by two characters and by whether a machine
#: is left with an orphaned daemon on it.
GROUP_KILL = re.compile(r'kill\s+--\s+-"?\$\{?\w+')


def shell_commands(text: str) -> list[str]:
    """A shell script's commands, comments dropped and continuations joined.

    The same shape as :func:`spec_commands`, and for the same reason: this
    module's checks must never be satisfiable by a sentence that happens to
    recite the thing being checked for.
    """
    uncommented = "\n".join(line for line in text.splitlines()
                            if not line.lstrip().startswith("#"))
    joined = re.sub(r"\\\n\s*", " ", uncommented)
    return [line.strip() for line in joined.splitlines() if line.strip()]


@pytest.mark.parametrize(
    "relative_path,section", SMOKE_DAEMON_STARTERS,
    ids=lambda value: value.split("/")[-1] if isinstance(value, str) else "")
def test_the_smoke_daemon_is_started_and_killed_as_a_process_group(
        relative_path, section):
    """A daemon started behind ``dbus-run-session`` outlives a kill aimed at
    ``$!``, because ``$!`` is the wrapper and the daemon is its child.

    This is not hypothetical and it is not a style point. Both of these files
    shipped with the naive form, so every package build orphaned exactly one
    mock daemon; three were found alive on one workstation, the oldest three
    days old, each holding memory and a name on the session bus. The fix is
    ``setsid`` at the start — which makes the wrapper a process-group leader,
    so its pid doubles as the group id — and a negative kill at the end, which
    reaches the daemon and the bus with it.

    Both halves are asserted, because either one alone is inert: ``setsid``
    without the group kill still orphans, and a group kill without ``setsid``
    aims at the *build's own* process group, which is worse than the bug.
    """
    text = read(ROOT / relative_path)
    commands = (spec_commands(spec_section(text, section.lstrip("%")))
                if section else shell_commands(text))

    starts = [c for c in commands
              if "dbus-run-session" in c and "daemon.main" in c
              or "dbus-run-session" in c and "idasen-companiond" in c]
    assert len(starts) == 1, (
        f"{relative_path} starts the smoke daemon {len(starts)} times; it "
        f"starts it once")
    assert "setsid" in starts[0], (
        f"{relative_path} starts the smoke daemon without setsid, so the "
        f"wrapper is not a process-group leader and the kill below cannot "
        f"reach the daemon it spawns — every run leaks one")

    group_kills = [c for c in commands if GROUP_KILL.search(c)]
    assert group_kills, (
        f"{relative_path} never kills the smoke daemon's process group, so "
        f"the daemon behind dbus-run-session survives the run")


# The enterprise 9 line's glibc, and so the oldest one this package reaches.
# Restated here to give the ceiling a second reader: the script says which
# symbol versions to accept, this says which line that was chosen for, and
# moving one without the other stops rather than ships.
ENTERPRISE_GLIBC = "2.34"

# The ceiling as the script assigns it, never as the file mentions it — the
# constant carries a paragraph of prose that says the number too, and a check
# a nearby sentence can satisfy is measuring the wrong thing.
ELF_GLIBC_CEILING = re.compile(r"^GLIBC_CEILING=(\S+)\s*$", re.M)


def test_the_glibc_ceiling_is_the_oldest_line_the_package_reaches():
    """Raising this is not a build fix, it is dropping a distribution line —
    the enterprise 9 generation ships exactly this glibc, so a package
    requiring anything newer will not load there. The symbol comes from Qt
    rather than from the bundled interpreter, whose own floor is lower, which
    means a Qt bump is what moves it and a green build is what would carry it.
    """
    stated = ELF_GLIBC_CEILING.search(read(ELF_VERIFIER))
    assert stated, "the ELF assertions no longer state a glibc ceiling at all"
    assert stated.group(1) == ENTERPRISE_GLIBC, (
        f"the glibc ceiling is {stated.group(1)}, not {ENTERPRISE_GLIBC} — "
        f"which is the enterprise 9 line's own glibc and the oldest this "
        f"package reaches, so moving it decides who can install the package")


# The program the portability script hands to the installed interpreter in
# every container, as the shell hands it over. Only the delimiters can produce
# it, so no sentence about the probe can stand in for the probe.
STATS_PROBE = re.compile(
    r"<<'STATS_ROUND_TRIP'[^\n]*\n(.*?)\nSTATS_ROUND_TRIP\n", re.S)

# What the shell does with a probe that failed, and what the host calls that.
STATS_PROBE_RUNNER = re.compile(r"^.*<<'STATS_ROUND_TRIP'.*$", re.M)
PROBE_FAILURE_EXIT = re.compile(r"\|\|\s*exit\s+(\d+)")


def uncommented(text: str) -> str:
    """The lines of a script that do something, in either language it is
    written in — both spell a comment the same way."""
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("#"))


def test_the_portability_probe_reads_the_statistics_it_wrote_back_out():
    """The statistics store degrades instead of raising, deliberately and for
    good reasons: it sits on the user's disk, it is written on every tick, and
    an exception there would stop the desk moving. The cost is that calling it
    proves nothing at all. On a machine whose standard library arrives split —
    which is the machine this package carries an interpreter for — the module
    the store is built on is simply absent, every call becomes a no-op, and a
    check that writes a number and looks at nothing reports that as a pass.

    So the probe has to read back. Asserted as a relation rather than as a
    vocabulary: the value handed to the write is the value some line compares
    against something a read returned. A probe that only writes satisfies a
    list of method names and would be invisible in a green run.
    """
    found = STATS_PROBE.search(read(PORTABILITY_VERIFIER))
    assert found, ("the portability script no longer runs the statistics "
                   "anywhere in its containers")
    probe = uncommented(found.group(1))

    assert re.search(r"\bavailable\b", probe), (
        "the probe never asks whether the store opened, so it passes on a "
        "machine where every one of its calls is a no-op")

    write = re.search(r"add_active_time\(\s*[^,]+,\s*([^,)]+)", probe)
    assert write, "the probe credits no desk time, so it reads back nothing"
    credited = write.group(1).strip()

    for reader in ("daily_totals", "recent_transitions"):
        binding = re.search(rf"(\w+)\s*=\s*[^=\n]*?{reader}\(", probe)
        assert binding, (
            f"the probe never reads {reader} back into anything, so what it "
            f"wrote is never looked at")
        compared = [line for line in probe.splitlines()
                    if binding.group(1) in line
                    and ("!=" in line or "==" in line)]
        assert compared, (
            f"the probe reads {reader} and compares it with nothing, which is "
            f"the same evidence as not reading it at all")
        if reader == "daily_totals":
            assert any(credited in line for line in compared), (
                f"the probe compares what {reader} returned against something "
                f"other than the {credited} it wrote")

    assert re.search(r"sys\.exit\([1-9]", probe), (
        "the probe cannot tell the shell it found anything wrong")

    script = uncommented(read(PORTABILITY_VERIFIER))
    runner = STATS_PROBE_RUNNER.search(script)
    assert runner, "nothing in the portability script runs the probe"
    failed = PROBE_FAILURE_EXIT.search(runner.group(0))
    assert failed, (
        "a probe that fails is not reported at all, so statistics that do "
        "nothing reach the summary as a package that runs")
    assert re.search(rf"^\s*{failed.group(1)}\)\s*echo ", script, re.M), (
        f"the host has no name for exit {failed.group(1)}, so dead statistics "
        f"are filed as a crash rather than as themselves")


def test_the_workflow_asks_the_package_its_questions_before_publishing_it():
    """The requires, the provides and the package format are all generated by
    rpmbuild rather than written in the spec, so nothing that reads a file can
    stand in for asking the finished package — which means the check has a
    position as well as a subject. Run after the upload it would be a report on
    an artifact people already have; ordering is the whole point of it.

    Comments come out first, so a sentence naming the script cannot stand in
    for the step that runs it. Skipped away from a git checkout: the CI
    configuration is deliberately not part of the source distribution, so this
    cannot run from the RPM's own unpacked-sdist %check.
    """
    if not RPM_WORKFLOW.exists():
        pytest.skip("CI configuration is deliberately not part of the source "
                    "distribution, so this check only runs from a git checkout")
    workflow = "\n".join(line for line in read(RPM_WORKFLOW).splitlines()
                         if not line.lstrip().startswith("#"))
    gate = workflow.find(METADATA_VERIFIER.name)
    assert gate != -1, (
        "the RPM workflow no longer asks the built package what it requires, "
        "offers and is written as")
    built = re.search(rf"^.*{re.escape(METADATA_VERIFIER.name)}.*$",
                      workflow, re.M).group(0)
    assert "dist-rpm/" in built and ".rpm" in built, (
        f"the workflow runs those checks against something other than the "
        f"package this job built: {built.strip()!r}")
    upload = workflow.find("actions/upload-artifact")
    assert upload != -1, "the RPM workflow no longer publishes the package"
    assert gate < upload, (
        "the workflow publishes the package before asking it anything, so a "
        "package that fails is downloadable by the time anyone finds out")


# Constructs that would tie the self-contained package back to the machine
# that built it, each with what it actually does. Read as text on purpose:
# the property is only visible in a built package, an rpmbuild run is far
# more than the suite can ask for, and that gap is precisely why nothing was
# watching this until a release shipped an artifact named for one distro
# release and installable on it alone.
BUILD_HOST_LEAKS = {
    r"%pyproject_install":
        "installs the app into the build host's own interpreter path, which "
        "writes that interpreter's version into every shipped path",
    r"%pyproject_files":
        "lists files by the same path, so the two drift back together",
    r"^BuildArch:":
        "declares the package architecture-independent, which it stopped "
        "being when it started carrying Qt",
    r"%\{\?dist\}":
        "stamps the build host's distribution onto an artifact built once "
        "and installed anywhere",
    r"^Requires:\s+python3-":
        "names a distribution's package for a library this package bundles",
    r"^Requires:\s+python":
        "asks the machine for a Python, when the package carries its own — "
        "and the one capability that resolves across families is announced by "
        "a package that need not hold the whole standard library",
}


def test_the_bundled_spec_carries_nothing_of_the_machine_that_built_it():
    """Each of these is silent: the build stays green, the package installs
    on the machine it was built on, and the constraint only shows up as an
    unmet dependency on someone else's."""
    s = read(BUNDLED)
    found = sorted(p for p in BUILD_HOST_LEAKS if re.search(p, s, re.M))
    assert not found, "the bundled spec is build-host-specific again: " + "; ".join(
        f"{p} — {BUILD_HOST_LEAKS[p]}" for p in found)


# Anything in %install that takes files away, however it spells it.
SPEC_REMOVAL = re.compile(r"(?:^|\s)rm\s|(?:^|\s)-delete(?:\s|$)")

# The private tree, in each of the ways a command can name it, and the
# directory inside it that the app and its bundled libraries occupy. A removal
# naming one of the first without the second is one whose reach is the whole
# interpreter.
SPEC_PRIVATE_TREE = ("%{buildroot}", "%{appdir}", "%{bundled_runtime}")
SPEC_BUNDLED_LIBRARIES = "%{bundled_libraries}"


def test_no_delete_in_the_install_reaches_past_the_bundled_libraries():
    """The interpreter and the libraries now share one tree, and two of
    %install's deletes were written when they did not. Scoped to the tree
    rather than to the libraries inside it, the console-script removal takes
    the interpreter's own `bin/` — every entry point in the package then points
    at nothing — and the purge of version-tagged extension modules takes
    `_dbm` out of the standard library, which this package is required to
    keep. Neither fails a build.

    Read as commands rather than as text, so a comment describing a delete can
    neither satisfy this nor trip it.
    """
    commands = spec_commands(spec_section(read(BUNDLED), "install"))
    removals = [c for c in commands if SPEC_REMOVAL.search(c)]
    assert removals, "%install takes nothing away at all any more"
    too_wide = [c for c in removals
                if any(named in c for named in SPEC_PRIVATE_TREE)
                and SPEC_BUNDLED_LIBRARIES not in c]
    assert not too_wide, (
        "a delete in %install names the private tree without naming the "
        "libraries directory inside it, so it reaches the interpreter's own "
        f"files: {too_wide}")


def test_no_wheel_in_the_install_is_installed_by_the_build_hosts_interpreter():
    """This is a build that dies rather than a package that ships something
    subtly wrong, which is worth stating because the opposite assumption is
    what makes a reader skip the test. The wheel set is resolved by the
    interpreter the package carries, so the two wheels that are built for one
    CPython minor rather than for the stable ABI arrive tagged for that minor —
    and a pip one minor away refuses them outright, one error line, exit 1.
    Every build on a host whose Python is not exactly this one stops in
    %install.

    Three installs, not two: the wheel set, the build backend the untrimmed
    install driver needs to build the app's own wheel without isolation, and
    the app itself.

    What makes the difference is which program runs pip, so that is what is
    asserted: the untrimmed extraction %prep leaves behind, never the build
    host's own interpreter. Reading parsed commands rather than file text is
    what makes this immune to a comment, in both directions.
    """
    commands = spec_commands(spec_section(read(BUNDLED), "install"))
    installs = [c for c in commands if "-m pip install" in c]
    assert len(installs) == 3, (
        f"%install installs with pip {len(installs)} times; it installs the "
        f"wheel set, the build backend and the app, and all three have to be "
        f"accounted for here")
    host = [c for c in installs if "%{python3}" in c]
    assert not host, (
        f"%install installs with the build host's interpreter, which refuses "
        f"the wheels this package carries: {host}")
    strayed = [c for c in installs if "%{install_driver}" not in c]
    assert not strayed, (
        f"%install installs with something other than the interpreter %prep "
        f"unpacked for the purpose: {strayed}")


def test_the_build_backend_installs_before_the_apps_own_wheel_is_built():
    """The app's own wheel is built with `--no-build-isolation`, which
    imports whatever the install driver's site-packages already holds at that
    moment — nothing installed afterwards. A backend installed after that
    build is not a backend; it is dead weight that happened to also get
    installed. Read by position among the parsed %install commands, the same
    argument test_the_bundled_interpreter_is_checked_before_anything_uses_it
    makes about the checksum.
    """
    commands = spec_commands(spec_section(read(BUNDLED), "install"))
    installs = [c for c in commands if "-m pip install" in c]
    backend = [c for c in installs if "find-links build-backend" in c]
    assert len(backend) == 1, (
        f"%install installs the build backend {len(backend)} times; it needs "
        f"installing exactly once, ahead of the app's own wheel")
    app = [c for c in installs if "--no-build-isolation" in c]
    assert len(app) == 1, (
        f"%install builds the app's own wheel {len(app)} times; it is built "
        f"exactly once")
    assert commands.index(backend[0]) < commands.index(app[0]), (
        "%install installs the build backend after building the app's own "
        "wheel, which needed it before that point")


def build_backend_pins() -> dict[str, str]:
    """What the untrimmed install driver gets that the package never carries.

    Read from the fetcher the way bundled_pins() reads PINS, so this
    describes exactly what the second, never-shipped array names.
    """
    block = read(RUNTIME_FETCHER).split("BUILD_BACKEND=(")[1].split("\n)")[0]
    pins = re.findall(r'^\s*"([A-Za-z0-9_.-]+)==(\S+?)"\s*$', block, re.M)
    assert pins, "the build-backend pin list no longer reads as one"
    return {re.sub(r"[-_.]+", "-", name).lower(): version for name, version in pins}


def test_the_build_backend_acquires_no_provides_or_licence_arm():
    """The metadata-side half of "it must not escape": a distribution that
    reached the shipped tree would pick up a Provides line and a licence
    obligation for free, from mechanisms scoped to %{bundled_libraries} and
    its own *.dist-info directories. Neither mechanism should have anything to
    say about a distribution that only ever lives in the install driver's own,
    never-packaged site-packages.
    """
    names = set(build_backend_pins())
    assert names, "the build-backend pin list is empty"

    declared = set(re.findall(
        r"^Provides:\s+bundled\(python3dist\(([^)]+)\)\)", read(BUNDLED), re.M))
    assert not (names & declared), (
        f"the build backend acquired a Provides line meant for what ships: "
        f"{sorted(names & declared)}")

    vendored = {path.stem.lower() for path in VENDORED_LICENCES.iterdir()
                if path.is_file()}
    licensed = {name for name in names
                if any(name in text for text in vendored)}
    assert not licensed, (
        f"the build backend acquired a vendored licence arm meant for what "
        f"ships: {sorted(licensed)}")


def test_the_install_compiles_the_private_tree_with_the_interpreter_that_reads_it():
    """Three things about one command, each of which fails silently.

    Which interpreter: a cache the shipped one does not recognise is not a
    cache, it is a file the package carries and nothing reads. Nothing on a
    user's machine reports that; the app merely compiles the source again.

    When: the tree has to be finished. Run before the libraries are installed
    this compiles the standard library and nothing else, which is the state
    the package was already in — most of its source shipped with no cache,
    recompiled at every start into a directory root owns and thrown away.

    What the cache is checked against: the default is the source's
    modification time, which makes what this package ships depend on the
    timestamps its build saw and stops being believed the moment an unpack or
    a copy moves one. Checked against the source itself, neither is true.

    Ordering is read as position rather than as text, the way
    test_the_bundled_interpreter_is_checked_before_anything_uses_it is: it is
    the property, and it is invisible to any check that only asks whether each
    line is present.
    """
    commands = spec_commands(spec_section(read(BUNDLED), "install"))
    compiles = [c for c in commands if "-m compileall" in c]
    assert len(compiles) == 1, (
        f"%install compiles the private tree {len(compiles)} times; it does "
        f"it once, after the tree stops changing")
    assert "%{buildroot}%{bundled_interpreter}" in compiles[0], (
        "%install compiles the private tree with something other than the "
        "interpreter that ships, so the package carries caches nothing it "
        "installs can read")
    assert "checked-hash" in compiles[0], (
        "%install writes caches the interpreter validates against a "
        "modification time, so what the package ships depends on the "
        "timestamps this build happened to see")
    last_trim = max(index for index, command in enumerate(commands)
                    if "trim-" in command)
    assert commands.index(compiles[0]) > last_trim, (
        "%install compiles the private tree before it has finished building "
        "it, so what ships is bytecode for a tree that no longer exists and "
        "no bytecode for most of the one that does")


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_the_licence_is_installed(spec):
    assert re.search(r"^%license ", read(spec), re.M)


# The interpreter the package carries, restated here so the pin has a second
# reader. The fetcher says which bytes to accept; this says which bytes were
# reviewed, and a bump that moves one without the other stops rather than
# ships.
BUNDLED_INTERPRETER_SHA256 = (
    "cefba034445d2875408d1fd4d5700ae6731563aeb54dcb39fd8164ab5c457533")

# A checksum literal anywhere in the fetcher: 64 hex digits with no hex digit
# on either side, so a longer run of them is not read as one.
SHA256_LITERAL = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")

# The assignment that pins it, as opposed to the same digits appearing
# anywhere: what the download is held to is a value the script reads, and a
# hash recited in a comment is not one.
PINNED_SHA256 = re.compile(r'^\w*SHA256\w*="([0-9a-f]{64})"\s*$', re.M)

# The command that resolves the wheel set, and the variable naming the program
# that runs it.
WHEEL_RESOLVER = re.compile(r'^\s*"\$\{(\w+)\[[0-9]+\]\}"\s+-m pip download\b',
                            re.M)

# Where that variable gets its value: the directory searched for the program.
RESOLVER_SOURCE = re.compile(
    r'^mapfile\s+-t\s+(\w+)\s*<\s*<\(\s*find\s+"([^"]+)"', re.M)


def test_the_bundled_interpreter_is_pinned_to_exactly_one_checksum():
    """The fetcher downloads an interpreter and the build then executes it,
    so this hash is the whole of what separates the reviewed asset from
    anything else served under its name — upstream signs no individual asset,
    and its checksum list travels with the assets it describes.

    One literal, not at least one. Two is what a half-finished bump leaves
    behind, with the old hash still sitting beside the new one, and from
    outside that is indistinguishable from the pinned build it has stopped
    being: whichever the script reads, the file reads as though both were
    checked.
    """
    s = read(RUNTIME_FETCHER)
    literals = SHA256_LITERAL.findall(s)
    assert len(literals) == 1, (
        f"the fetcher carries {len(literals)} checksum literals; a bump left "
        f"one behind and the wrong one may be what the download answers to")
    pinned = PINNED_SHA256.search(s)
    assert pinned, "the fetcher no longer assigns the interpreter's checksum"
    assert pinned.group(1) == BUNDLED_INTERPRETER_SHA256


def test_the_bundled_interpreter_is_checked_before_anything_uses_it():
    """A checksum is a gate only where it sits. Moved below the unpacking, it
    reports on a tarball already written to disk; moved below the wheel
    resolution, it reports on an interpreter that has already run as this
    build's own tool. Either way the check passes, the build goes green, and
    what it proves is that the bytes which were executed are the ones that
    were executed.

    Read by position in the file for the same reason
    test_build_dist_refuses_untracked_files_before_building is: order is the
    property, and it is invisible to any check that only asks whether each
    line is present.
    """
    s = read(RUNTIME_FETCHER)
    checked = s.index("sha256sum -c")
    unpacked = s.index("tar xzf")
    resolved = s.index("-m pip download")
    assert checked < unpacked, (
        "the fetcher unpacks the interpreter before checking it")
    assert checked < resolved, (
        "the fetcher runs the interpreter before checking it")


# The interpreter asset, named on each side of the build: the source the spec
# unpacks, and the file the fetcher writes for it to find.
SPEC_INTERPRETER_SOURCE = re.compile(r"^Source2:\s+(\S+)\s*$", re.M)
FETCHER_INTERPRETER_ASSET = re.compile(r'^INTERPRETER_ASSET="(\S+)"\s*$', re.M)

# The minor version the spec builds its own paths from, and the same number as
# the asset's filename states it.
SPEC_INTERPRETER_MINOR = re.compile(r"^%global bundled_minor (\S+)\s*$", re.M)
ASSET_INTERPRETER_MINOR = re.compile(r"^cpython-([0-9]+\.[0-9]+)\.")


def test_the_spec_unpacks_the_interpreter_the_fetcher_writes():
    """Two independent chances to bump the interpreter halfway. Name a
    different asset in the spec than the fetcher writes and the build cannot
    start, which is loud. Move the asset and leave the minor version behind and
    the build starts, installs everything into a directory beside the one the
    shipped interpreter reads, and produces a package that imports nothing —
    which the build asserts against too, but only after unpacking around a
    hundred megabytes and running two trims. Here it costs nothing.
    """
    spec = read(BUNDLED)
    source = SPEC_INTERPRETER_SOURCE.search(spec)
    assert source, "the bundled spec no longer names an interpreter source"
    asset = FETCHER_INTERPRETER_ASSET.search(read(RUNTIME_FETCHER))
    assert asset, "the fetcher no longer names the asset it writes"
    assert source.group(1) == asset.group(1), (
        f"the spec unpacks {source.group(1)} and the fetcher writes "
        f"{asset.group(1)}")

    stated = SPEC_INTERPRETER_MINOR.search(spec)
    assert stated, "the bundled spec no longer states the interpreter's minor"
    inside = ASSET_INTERPRETER_MINOR.match(asset.group(1))
    assert inside, (
        f"the asset {asset.group(1)} no longer states its own version where "
        f"this can read it")
    assert stated.group(1) == inside.group(1), (
        f"the spec builds its paths from Python {stated.group(1)} and the "
        f"interpreter it unpacks is {inside.group(1)}")


def test_the_wheels_are_resolved_by_the_interpreter_that_will_run_them():
    """Two of the pinned distributions publish a separate wheel per
    interpreter version, and pip selects for the interpreter it is. Asked on
    a build host ahead of the one the package carries, it answers with a set
    the shipped interpreter cannot import — and nothing in the build notices,
    because every one of those files is a valid wheel for somebody.

    The half-fix is the thing to keep out: a flag naming the target version
    corrects which wheel is chosen and leaves marker evaluation reading the
    host, which is how a requirement conditioned on an older interpreter goes
    missing from a package that accepts one. Only the interpreter genuinely
    being 3.14 answers both, so what this asserts is that the program running
    pip is the one that was just unpacked.
    """
    s = read(RUNTIME_FETCHER)
    resolver = WHEEL_RESOLVER.search(s)
    assert resolver, (
        "nothing in the fetcher resolves the wheel set with a named "
        "interpreter")
    source = RESOLVER_SOURCE.search(s)
    assert source, "the fetcher no longer searches for an interpreter to use"
    assert source.group(1) == resolver.group(1), (
        f"the wheel set is resolved by {resolver.group(1)}, which is not the "
        f"interpreter the fetcher unpacked into {source.group(1)}")

    directory = source.group(2)
    assert directory.startswith("$WORK") and directory.endswith("/bin"), (
        f"the fetcher takes its resolver from {directory}, not from the "
        f"interpreter it unpacked into its own scratch directory")
    assert "--python-version" not in s, (
        "the fetcher names a target version for pip, which fixes wheel "
        "selection and leaves marker evaluation reading whichever "
        "interpreter runs it")


def bundled_pins() -> dict[str, str]:
    """What the self-contained package carries, and at which version.

    Read from the fetcher rather than restated, so this describes the wheels
    that actually go into the tarball. Names come back spelled the way an rpm
    provides spells them, which is also the way the index does.
    """
    block = read(RUNTIME_FETCHER).split("PINS=(")[1].split("\n)")[0]
    pins = re.findall(r'^\s*"([A-Za-z0-9_.-]+)==(\S+?)"\s*$', block, re.M)
    assert pins, "the wheel fetcher's pin list no longer reads as one"
    return {re.sub(r"[-_.]+", "-", name).lower(): version for name, version in pins}


# The two bundled wheels that ship no licence text of their own. The spec
# copies theirs out of this repository and names it separately, which is why
# they cannot be looked for under a name derived from theirs.
BUNDLED_WITHOUT_OWN_LICENCE = frozenset({"pyside6-essentials", "shiboken6"})


def test_the_spec_declares_every_bundled_pin_at_the_pinned_version():
    """Both files tell the reader to move their lines together, and nothing
    made them. A distribution that arrives without a line here ships with
    nothing naming it — and the version in these lines is the field a security
    scanner reads, so one left behind reports a library the package does not
    carry as though it did.
    """
    declared = dict(re.findall(
        r"^Provides:\s+bundled\(python3dist\(([^)]+)\)\)\s*=\s*(\S+)",
        read(BUNDLED), re.M))
    assert declared == bundled_pins()


def test_the_spec_installs_a_licence_for_every_bundled_pin():
    """Bundling obliges the package to carry the bundled code's terms, and the
    README says every one of them installs with it. A wheel added to the pins
    without a line here makes that untrue silently: nothing fails, the licence
    simply is not there."""
    installed: set[str] = set()
    for line in re.findall(r"^%license (.+)$", read(BUNDLED), re.M):
        installed.update(line.split())
    missing = sorted(
        pin for pin in bundled_pins()
        if pin not in BUNDLED_WITHOUT_OWN_LICENCE
        and f"LICENSE.{pin.replace('-', '_')}" not in installed)
    assert not missing, f"the bundled spec installs no licence text for: {missing}"


def installed_licence_files() -> set[str]:
    """Every text the bundled spec installs as a licence, one per element."""
    installed: set[str] = set()
    for line in re.findall(r"^%license (.+)$", read(BUNDLED), re.M):
        installed.update(line.split())
    return installed


# The expression as the spec states it. Anchored to the field, so the prose
# above it can neither satisfy this nor add a term to it.
SPEC_LICENCE_EXPRESSION = re.compile(r"^License:\s+(.+?)\s*$", re.M)


def licence_terms() -> list[str]:
    """The identifiers the licence expression names, in the order it names
    them. The grouping is not the subject here — which terms are claimed is —
    so the parentheses come out and the operators are what the split runs on.
    """
    stated = SPEC_LICENCE_EXPRESSION.search(read(BUNDLED))
    assert stated, "the bundled spec no longer states a licence expression"
    flattened = stated.group(1).replace("(", " ").replace(")", " ")
    return [term for term in re.split(r"\s+(?:AND|OR)\s+", flattened.strip())
            if term]


# Which installed text answers each identifier the expression claims. Written
# out rather than derived from the name, because the two do not line up and
# pretending they do is what would let this pass by looking at nothing: half
# these terms are answered by a file named after the *distribution* that
# carries them, and three of the four remaining are answered by one file each
# for a term named after neither.
LICENCE_TEXT_FOR_TERM = {
    "GPL-3.0-or-later": "LICENSE",
    "MIT": "LICENSE.bleak",
    "BSD-3-Clause": "LICENSE.voluptuous",
    "PSF-2.0": "LICENSE.typing_extensions",
    "Python-2.0": "LICENSE.cpython",
    "CNRI-Python": "LICENSE.cpython",
    "Apache-2.0": "LICENSE.Apache-2.0.txt",
    "OpenSSL": "LICENSE.OpenSSL.txt",
    "X11": "LICENSE.X11.txt",
    "Sleepycat": "LICENSE.Sleepycat.txt",
    "BSD-2-Clause": "LICENSE.BSD-2-Clause.txt",
    "0BSD": "LICENSE.0BSD.txt",
    "Zlib": "LICENSE.Zlib.txt",
    "bzip2-1.0.6": "LICENSE.bzip2-1.0.6.txt",
    "LGPL-3.0-only": "LICENSE.LGPL-3.0.txt",
    "GPL-2.0-only": "LICENSE.LGPL-3.0.txt",
    "GPL-3.0-only": "LICENSE.LGPL-3.0.txt",
}


def test_every_term_in_the_licence_expression_has_its_text_in_the_package():
    """The field and the texts are two statements about the same contents,
    written in two places, and nothing held them together until the package
    started carrying a whole interpreter — at which point the field gained
    eight terms in one change. A term added without its text is a claim the
    package cannot back; the build stays green, because a licence expression
    is a string as far as rpm is concerned.
    """
    terms = licence_terms()
    unmapped = sorted(t for t in terms if t not in LICENCE_TEXT_FOR_TERM)
    assert not unmapped, (
        f"the licence expression claims {unmapped}, and nothing here says "
        f"which shipped text answers those terms")
    missing = sorted({LICENCE_TEXT_FOR_TERM[t] for t in terms}
                     - installed_licence_files())
    assert not missing, (
        f"the licence expression claims a term whose text the package does "
        f"not install: {missing}")


def test_every_licence_text_in_the_package_answers_a_term_it_claims():
    """The other direction, and the one a bump breaks. A component dropped
    from the interpreter build, or a bundled library replaced, leaves a text
    behind that no longer covers anything — which reads as diligence while
    being the opposite: a package shipping terms for something it does not
    contain tells a redistributor to comply with a licence that is not there.

    The per-distribution texts are excluded because the pin list decides those
    rather than the expression, and the test above this holds them to it.
    """
    covered = {LICENCE_TEXT_FOR_TERM[term] for term in licence_terms()
               if term in LICENCE_TEXT_FOR_TERM}
    per_distribution = {f"LICENSE.{pin.replace('-', '_')}"
                        for pin in bundled_pins()}
    orphaned = sorted(installed_licence_files() - covered - per_distribution)
    assert not orphaned, (
        f"the package installs a licence text answering no term the licence "
        f"expression claims: {orphaned}")


# A vendored text as MANIFEST.in has to name it for one to survive into an
# sdist. Anchored at the start of a line, so the paragraph explaining the
# directory cannot stand in for an entry in it.
MANIFEST_VENDORED_LICENCE = re.compile(
    r"^include packaging/licenses/(\S+)\s*$", re.M)


def test_every_vendored_licence_text_ships_and_installs():
    """Three ways one of these goes missing, each of them quiet. Left out of
    MANIFEST.in it is absent from the sdist the RPM builds from, so %install
    copies nothing and the build fails somewhere that reads as unrelated,
    while every local build passes because the file is sitting right there in
    the working tree. Left out of %files it is simply not in the package.
    Emptied, it is in the package and says nothing.
    """
    vendored = {path.name for path in VENDORED_LICENCES.iterdir()
                if path.is_file()}
    assert vendored, "no licence text is vendored in this repository any more"

    named = set(MANIFEST_VENDORED_LICENCE.findall(read(MANIFEST)))
    assert vendored == named, (
        f"the vendored licence texts and the ones the source distribution "
        f"carries have drifted apart: on disk only {sorted(vendored - named)}, "
        f"named only {sorted(named - vendored)}")

    missing = sorted(vendored - installed_licence_files())
    assert not missing, (
        f"a licence text is vendored here and installed by nothing: {missing}")

    empty = sorted(path.name for path in VENDORED_LICENCES.iterdir()
                   if path.is_file() and not path.read_text().strip())
    assert not empty, f"a vendored licence text carries no text: {empty}"


# The interpreter as the spec declares it to a scanner, and as the pinned
# asset's own filename states it.
SPEC_BUNDLED_INTERPRETER = re.compile(
    r"^Provides:\s+bundled\(python3\)\s*=\s*(\S+)\s*$", re.M)
ASSET_INTERPRETER_VERSION = re.compile(r"^cpython-([0-9]+(?:\.[0-9]+)+)\+")


def test_the_spec_declares_the_interpreter_at_the_version_it_bundles():
    """The largest bundled component in the package, and the one whose age a
    scanner most wants to know: it links its own OpenSSL, so the distribution's
    updates do not reach it. A version left behind at a bump reports a runtime
    the package does not carry, which is worse than declaring nothing —
    the same single-source-of-truth check the nine wheels already get, for the
    one bundled component that has no dist-info to be read out of.
    """
    declared = SPEC_BUNDLED_INTERPRETER.search(read(BUNDLED))
    assert declared, (
        "the bundled spec no longer declares the interpreter it carries, so "
        "the package's largest bundled component is invisible to a scanner")
    asset = FETCHER_INTERPRETER_ASSET.search(read(RUNTIME_FETCHER))
    assert asset, "the fetcher no longer names the asset it writes"
    inside = ASSET_INTERPRETER_VERSION.match(asset.group(1))
    assert inside, (
        f"the asset {asset.group(1)} no longer states its own version where "
        f"this can read it")
    assert declared.group(1) == inside.group(1), (
        f"the spec declares a bundled interpreter of {declared.group(1)} and "
        f"the fetcher writes {inside.group(1)}")


def test_the_interpreters_own_licence_is_taken_from_the_untrimmed_source():
    """The one text the interpreter tarball does ship, and the one whose
    install can stop happening without a build noticing. Both extractions of
    the same tarball are on disk while %install runs, and the copy in the build
    root is the one the trim rewrites — take the licence from there and its
    presence becomes a property of a delete list, which is exactly the coupling
    that decays silently.

    Read off the command rather than the section, so a comment describing the
    copy neither satisfies this nor trips it.
    """
    commands = spec_commands(spec_section(read(BUNDLED), "install"))
    copies = [c for c in commands if c.endswith("LICENSE.cpython")]
    assert len(copies) == 1, (
        f"%install writes the interpreter's own licence text {len(copies)} "
        f"times; it writes it once, out of the extraction %prep left")
    assert "%{buildroot}" not in copies[0], (
        f"%install takes the interpreter's licence text out of the tree the "
        f"trim rewrites, so a widened removal takes the licence with it: "
        f"{copies[0]}")


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



def test_debian_svg_icon_plugin_is_present_for_build_and_gui_runtime():
    """QtSvg bindings alone cannot load SVGs through QIcon on Debian."""
    source, full, headless = read(DEBIAN_CONTROL).split("\nPackage:")
    assert "qt6-svg-plugins" in source
    assert "qt6-svg-plugins" in full
    assert "qt6-svg-plugins" not in headless
    for relative in ("scripts/build-release-variants.sh", ".github/workflows/packages.yml"):
        assert "qt6-svg-plugins" in (ROOT / relative).read_text()


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
    if not (ROOT / "debian" / "idasen-companion.install").exists():
        pytest.skip("full debian/ tree not present (running from the sdist)")
    user_unit = ROOT / "debian" / "idasen-companion.user.service"
    headless_unit = (ROOT / "debian"
                     / "idasen-companion-headless.idasen-companion.user.service")
    system_unit_misspelling = ROOT / "debian" / "idasen-companion.service"
    assert user_unit.exists(), "debian/idasen-companion.user.service is missing"
    assert not system_unit_misspelling.exists(), (
        "debian/idasen-companion.service exists — dh_installsystemduser "
        "does not look for this filename and would install nothing"
    )
    assert user_unit.read_text() == (ROOT / "data" / "idasen-companion.service").read_text()
    assert headless_unit.read_text() == user_unit.read_text()


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


# One artifact's install instructions: a line that is bold and nothing else,
# then the command and the prose beneath it, up to the next such line. The
# heading is the anchor — without it, a passing remark anywhere in the file
# could stand in for the claim the section is supposed to make.
ARTIFACT_INSTALL_HEADING = re.compile(r"^\*\*.+\*\*$", re.M)

# Picks the RPM's section out of the three.
RPM_INSTALL_COMMAND = "dnf install ./idasen-companion-"

# The package asks the system for bluez and for sonames, and carries
# everything else itself. A name from this list in its install section would
# draw a support boundary the package does not have, and would need
# re-checking every time one of these released.
DISTRIBUTION_NAMES = (
    "fedora", "rhel", "red hat", "centos", "almalinux", "rocky",
    "opensuse", "suse", "mageia", "openmandriva",
)


def _rpm_install_section() -> tuple[str, str]:
    """The RPM's install heading, and the whole section under it."""
    text = read(README)
    headings = list(ARTIFACT_INSTALL_HEADING.finditer(text))
    assert headings, "the README's per-artifact install headings have moved"
    for n, heading in enumerate(headings):
        end = (headings[n + 1].start() if n + 1 < len(headings)
               else len(text))
        section = text[heading.start():end]
        if RPM_INSTALL_COMMAND in section:
            return heading.group(0), section
    raise AssertionError("no README section carries the RPM install command")


# An interpreter stated as a requirement: the capability an rpm would ask for,
# or a version of Python written out. "its own Python" is the section's whole
# point and says nothing about the machine, so only a *version* counts here.
INTERPRETER_REQUIREMENT = re.compile(r"python\(abi\)|python\s*3\.[0-9]", re.I)


def test_the_rpm_install_docs_promise_no_interpreter_and_no_distribution():
    """The package requires neither, and a reader deciding whether to download
    it is owed exactly that. Both halves of the claim age the same silent way:
    a named distribution's release moves and nobody rechecks it, and an
    interpreter version outlives the moment the package stopped asking for one.
    This file's install section has now been wrong in both directions — it
    named one distribution while the package was built for a single release,
    and it went on naming an interpreter floor after the package started
    carrying its own.

    A test enforcing a claim that has become false is worse than no test, which
    is why this replaced its predecessor rather than being relaxed to accept
    either wording.
    """
    heading, section = _rpm_install_section()
    named = sorted(d for d in DISTRIBUTION_NAMES if d in section.lower())
    assert not named, (
        f"the RPM's install section names {named}, which the package does not "
        f"require and cannot promise")
    stated = INTERPRETER_REQUIREMENT.search(section)
    assert not stated, (
        f"the RPM's install section (headed {heading!r}) states an interpreter "
        f"requirement, {stated.group(0)!r} — the package carries its own and "
        f"asks the machine for none, so this is a condition a reader would "
        f"check against their machine for nothing")


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
    # Not a bus name at all — it's the Settings-namespace argument
    # gui/appearance_portal.py passes to ReadOne, which happens to match the
    # dotted "org.freedesktop.*" shape this regex looks for. The bus name it
    # actually talks to is org.freedesktop.portal.Desktop, already covered
    # by the exemption above.
    "org.freedesktop.appearance",
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


# A screenshot URL names the default branch, so replacing an image is a plain
# overwrite. What remains breakable is the path: rename or delete a file and
# every install already out there loses that picture, since a software centre
# fetches this URL directly rather than reading anything shipped in the
# package. Nothing else looks at these -- the version table above reads the
# newest release element and stops, and appstreamcli runs with networking off.
SCREENSHOT_URL = re.compile(
    r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/[^/]+/([^<\s]+)")


def test_every_screenshot_url_points_at_a_file_that_exists():
    """The count is checked as well as the paths. A malformed URL simply
    fails to match the pattern, and without the count this would pass by
    looking at nothing.

    The path half runs only from a checkout. `data/screenshots/` is
    deliberately absent from the sdist -- a software centre fetches those
    images from the forge and nothing installs them, and at 639 kB they would
    take the tarball straight past its size ceiling. This test failed inside
    the RPM's %check once for asserting a checkout-only fact, so the guard is
    the whole reason it is here.
    """
    text = read(METAINFO)
    paths = SCREENSHOT_URL.findall(text)
    # Match the element, not the container that wraps them: the opening tag
    # is followed by an attribute or by its own close, never by a letter.
    declared = len(re.findall(r"<screenshot[ >]", text))
    assert len(paths) == declared, (
        f"{declared} screenshot elements but {len(paths)} usable URLs — "
        f"one is malformed and would be skipped rather than checked")

    if not (ROOT / "data" / "screenshots").is_dir():
        pytest.skip("no data/screenshots/ — running from an sdist, not a "
                    "checkout")

    for path in paths:
        assert (ROOT / path).is_file(), (
            f"a screenshot URL names {path}, which is not in the tree — "
            f"the link is dead for every install already out there")


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
    """The wheel check and package-data must name the same app catalog."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package_data = pyproject["tool"]["setuptools"]["package-data"]["idasen_companion"]

    s = read(BUILD_DIST)
    mo_pattern = re.search(r'mo_pattern = "([^"]+)"', s)
    assert mo_pattern, "no mo_pattern found in build-dist.sh"

    asserted = mo_pattern.group(1)
    rel = asserted.removeprefix("idasen_companion/")
    assert any(fnmatch.fnmatch(rel, pattern) for pattern in package_data), (
        f"{asserted} matches none of pyproject.toml's package-data patterns")


def test_build_dist_rejects_wheel_missing_one_tracked_catalog(tmp_path, monkeypatch, capsys):
    """One surviving catalog must not make a partly translated wheel pass."""
    script = read(BUILD_DIST)
    check = script.split('"$PYTHON" - "$WHEEL" <<\'PYEOF\'\n', 1)[1].split("\nPYEOF", 1)[0]
    wheel = tmp_path / "fixture.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "idasen_companion/locale/en/LC_MESSAGES/idasen_companion.mo", b"catalog")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(stdout="po/en.po\npo/es.po\n"))
    monkeypatch.setattr("sys.argv", ["wheel-check", str(wheel)])

    with pytest.raises(SystemExit) as failure:
        exec(compile(check, str(BUILD_DIST), "exec"), {"__name__": "__main__"})
    assert failure.value.code == 1
    assert "locale/es/LC_MESSAGES/idasen_companion.mo" in capsys.readouterr().err


def load_trimmer():
    """The Qt trimmer, imported by path — its filename is not an identifier."""
    spec = importlib.util.spec_from_file_location("trim_pyside6", TRIMMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plant_qt_plugins(base: Path, seeds: dict, extra_kinds=()) -> Path:
    """A Qt plugin directory carrying the named plugins and nothing else."""
    plugins = base / "PySide6" / "Qt" / "plugins"
    for kind, names in seeds.items():
        (plugins / kind).mkdir(parents=True, exist_ok=True)
        for name in names:
            (plugins / kind / name).touch()
    for kind in extra_kinds:
        (plugins / kind).mkdir(parents=True, exist_ok=True)
    return plugins


def test_the_trimmed_qt_keeps_an_input_method_plugin():
    """Qt has no input context of its own under X11: without a plugin from
    this directory a compose sequence and a dead key produce nothing, and an
    IBus user cannot type into the app at all. The app ships a Spanish
    catalog and has free-text fields, and every automated check runs on the
    offscreen platform, which loads none of this — so the day it goes missing
    again, this is what says so."""
    seeds = load_trimmer().SEED_PLUGINS
    assert "libcomposeplatforminputcontextplugin.so" in \
        seeds.get("platforminputcontexts", ())


def test_the_trim_stops_on_a_plugin_it_can_no_longer_find(tmp_path):
    """A seeded name that no longer resolves is a Qt rename or a typo, and
    skipping it ships a package missing a plugin the app needs — with a green
    build, since nothing automated ever loads one."""
    trimmer = load_trimmer()
    seeds = dict(trimmer.SEED_PLUGINS)
    seeds["iconengines"] = ()
    plugins = plant_qt_plugins(tmp_path, seeds)

    with pytest.raises(SystemExit):
        trimmer.plugin_seed_paths(str(plugins))


def test_the_trim_stops_on_a_kind_of_plugin_it_has_no_decision_about(tmp_path):
    """The one failure a keep-list cannot see by itself: Qt starts shipping a
    new kind of plugin, and the package silently goes out without it. Every
    directory has to be named, kept or dropped, so a Qt bump that adds one
    fails the build until somebody decides."""
    trimmer = load_trimmer()
    plugins = plant_qt_plugins(
        tmp_path, trimmer.SEED_PLUGINS,
        extra_kinds=("a-kind-of-plugin-qt-did-not-used-to-ship",))

    with pytest.raises(SystemExit):
        trimmer.plugin_seed_paths(str(plugins))


def test_the_trim_takes_every_plugin_it_names_from_a_real_tree(tmp_path):
    """The two checks above are only worth their failure if the arrangement
    they pass on is the one the package is actually built from."""
    trimmer = load_trimmer()
    plugins = plant_qt_plugins(tmp_path, trimmer.SEED_PLUGINS)

    kept = trimmer.plugin_seed_paths(str(plugins))
    assert len(kept) == sum(len(names)
                            for names in trimmer.SEED_PLUGINS.values())


def test_the_trim_decides_about_a_kind_of_plugin_exactly_once():
    """Keeping and dropping the same directory reads as a decision while
    being none, and the completeness check above would accept it."""
    trimmer = load_trimmer()
    assert not set(trimmer.SEED_PLUGINS) & set(trimmer.DROPPED_PLUGINS)


# The placeholder the spec fills in with the installed interpreter's absolute
# path, and the variable it is assigned to.
LAUNCHER_INTERPRETER = re.compile(r"^(\w+)=@PYTHON@\s*$", re.M)


def test_the_launcher_execs_the_interpreter_the_spec_substitutes():
    """Its predecessor asked whether a candidate interpreter could import
    `sqlite3`, because the machine's own interpreters were what the launcher
    had to choose between and the one a split standard library leaves behind
    cannot open the daemon's statistics. There is no candidate now: the package
    carries the interpreter, and the only path the launcher may exec is the one
    the spec writes into it.

    So what is worth asserting has moved with the subject — that the program on
    the exec line is that substituted path, and that nothing of the old search
    survives beside it. Either of those coming back would be a launcher that
    runs an interpreter chosen somewhere other than in the package, which under
    isolation would find none of the bundled libraries at all.
    """
    text = read(LAUNCHER)
    substituted = LAUNCHER_INTERPRETER.search(text)
    assert substituted, (
        "the launcher no longer takes an interpreter path from the spec")
    line = re.search(r"^exec (\S+) ", text, re.M)
    assert line, "the launcher no longer execs anything"
    assert line.group(1) == f'"${substituted.group(1)}"', (
        f"the launcher execs {line.group(1)}, not the interpreter path the "
        f"spec substitutes into {substituted.group(1)}")
    assert "PYTHONPATH" not in text, (
        "the launcher sets a Python search path, which the isolation switch on "
        "the exec line makes the interpreter ignore")
    assert not re.search(r"/usr/bin/python3\.", text), (
        "the launcher searches the machine for an interpreter again")


def load_interpreter_trimmer():
    """The CPython trimmer, imported by path, as the Qt one above is."""
    spec = importlib.util.spec_from_file_location("trim_cpython",
                                                  INTERPRETER_TRIMMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# What the pinned interpreter tarball actually unpacks to, in the parts the
# trim decides about: everything the removals are meant to reach, listed as the
# real asset spells it rather than as the patterns spell it. The tests below
# are worth their failure only against this — a tree planted from the patterns
# themselves would agree with any pattern, including a wrong one.
REMOVABLE_IN_THE_REAL_ASSET = (
    "lib/libpython3.14.so.1.0", "lib/libpython3.14.so", "lib/libpython3.so",
    "lib/libtcl9.0.so", "lib/libtcl9tk9.0.so",
    "lib/tcl9", "lib/tcl9.0", "lib/tk9.0", "lib/itcl4.3.8", "lib/thread3.0.6",
    "lib/python3.14/tkinter",
    "lib/python3.14/lib-dynload/_tkinter.cpython-314-x86_64-linux-gnu.so",
    "lib/python3.14/site-packages/pip",
    "lib/python3.14/site-packages/pip-26.2.1.dist-info",
    "lib/python3.14/ensurepip", "lib/python3.14/idlelib",
    "lib/python3.14/pydoc_data",
    "lib/python3.14/turtledemo",
    "include", "share",
    "bin/pip", "bin/pip3", "bin/pip3.14", "bin/idle3", "bin/idle3.14",
    "bin/pydoc3", "bin/pydoc3.14",
    "lib/pkgconfig", "bin/python3.14-config", "bin/python3-config",
    "lib/python3.14/config-3.14-x86_64-linux-gnu", "lib/python3.14/venv",
)

# Files from the same directory that have to come through untouched. The
# extension module is the one a purge scoped one directory too wide takes,
# and no test in this project imports it.
KEPT_IN_THE_REAL_ASSET = (
    "bin/python3.14",
    "lib/python3.14/os.py", "lib/python3.14/dbm/ndbm.py",
    "lib/python3.14/lib-dynload/_dbm.cpython-314-x86_64-linux-gnu.so",
)


def plant_interpreter_tree(base: Path, paths=REMOVABLE_IN_THE_REAL_ASSET,
                           kept=KEPT_IN_THE_REAL_ASSET) -> Path:
    """An interpreter tree shaped like the pinned asset and holding nothing."""
    root = base / "python"
    for relative in tuple(paths) + tuple(kept):
        planted = root / relative
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.touch()
    return root


def test_the_interpreter_trim_stops_on_a_removal_it_can_no_longer_find(
        tmp_path):
    """A pattern that resolves to nothing is CPython having moved or renamed
    something, and carrying on regardless ships several megabytes nobody asked
    for with a green build — the one failure a delete cannot report itself,
    since a tree missing only what it was going to lose still runs."""
    trimmer = load_interpreter_trimmer()
    thinned = [path for path in REMOVABLE_IN_THE_REAL_ASSET
               if path != "lib/itcl4.3.8"]
    root = plant_interpreter_tree(tmp_path, thinned)

    with pytest.raises(SystemExit):
        trimmer.removal_targets(str(root))


def test_the_interpreter_trim_takes_every_removal_it_names_from_a_real_tree(
        tmp_path):
    """The check above is worth its failure only if the arrangement it passes
    on is the one the package is built from — and this is also what says a
    removal has not been quietly dropped from the list, or widened until it
    reaches a file the standard library needs."""
    trimmer = load_interpreter_trimmer()
    root = plant_interpreter_tree(tmp_path)

    taken = {str(Path(path).relative_to(root))
             for path in trimmer.removal_targets(str(root))}
    assert taken == set(REMOVABLE_IN_THE_REAL_ASSET)


def test_the_interpreter_trim_keeps_the_extensions_a_wide_purge_would_eat(
        tmp_path):
    """`_dbm` sits in the directory the Tcl binding is removed from, and
    nothing automated here imports it. So its survival is asserted against
    the filesystem, and a trim that took it stops before the package is
    assembled around it."""
    trimmer = load_interpreter_trimmer()
    root = plant_interpreter_tree(tmp_path)
    assert len(trimmer.surviving_extensions(str(root))) == 1

    (root / "lib/python3.14/lib-dynload"
     / "_dbm.cpython-314-x86_64-linux-gnu.so").unlink()
    with pytest.raises(SystemExit):
        trimmer.surviving_extensions(str(root))


def test_the_interpreter_trim_proves_the_module_the_statistics_need():
    """The whole reason this package carries its own interpreter: where a
    distribution splits the standard library, `sqlite3` lands in the half no
    dependency of this package names. So the trimmed interpreter is made to
    import it and complete a round trip — and the probe set must keep naming
    it, rather than being narrowed to whatever still passes."""
    modules = load_interpreter_trimmer().REQUIRED_MODULES
    assert "import sqlite3" in read(STATS), (
        "the statistics no longer open their database with sqlite3, so the "
        "probe set is being held to the wrong module")
    assert "sqlite3" in modules


# A literal excerpt of `objdump -h`'s own output shape, section names only --
# real enough for the classifier to read, with none of an actual ELF file's
# other machinery. The second carries no BOLT markers at all.
BOLTED_SECTION_HEADERS = """
Sections:
Idx Name          Size      VMA               LMA               File off  Algn
 30 .bolt.org.text 00abcdef  0000000000401000  0000000000401000  00001000  2**4
                  CONTENTS, ALLOC, LOAD, READONLY, CODE
 31 .bolt.org.rodata 00001234  0000000000501000  0000000000501000  00002000  2**4
                  CONTENTS, ALLOC, LOAD, READONLY, DATA
 32 .note.bolt_info 00000020  0000000000601000  0000000000601000  00003000  2**2
                  CONTENTS, ALLOC, LOAD, READONLY, DATA
"""

PLAIN_SECTION_HEADERS = """
Sections:
Idx Name          Size      VMA               LMA               File off  Algn
  8 .text         00a41020  00000000001e0000  00000000001e0000  001e0000  2**12
                  CONTENTS, ALLOC, LOAD, READONLY, CODE
 10 .rodata       00341168  0000000000c22000  0000000000c22000  00c22000  2**12
                  CONTENTS, ALLOC, LOAD, READONLY, DATA
"""


def test_the_bolt_classifier_finds_and_misses_its_own_markers():
    """What decides whether a strip is safe to run is the presence of BOLT's
    own section names, and a pure text read is the seam this can exercise
    with two literal `objdump -h` excerpts — no ELF file, no real
    BOLT-optimized binary to hand."""
    trimmer = load_interpreter_trimmer()
    assert trimmer.bolt_sections(BOLTED_SECTION_HEADERS), (
        "the classifier missed BOLT's own section names in a listing that "
        "carries them")
    assert not trimmer.bolt_sections(PLAIN_SECTION_HEADERS), (
        "the classifier found BOLT markers in a listing that carries none")


def test_the_interpreter_trim_reports_an_unreadable_binary_in_its_own_voice(
        monkeypatch):
    """Everything else in that script names itself when it stops — a missing
    removal, a lost extension module, a strip that left the file no smaller,
    an interpreter that cannot import what the application needs. The reader
    the classification is built on was the one step that could instead raise
    through, and a package build is where that lands: a truncated download or
    an `objdump` that does not understand the asset's layout would have
    arrived as a traceback in the middle of a build log, with no line in it
    saying which program was unhappy about what.

    What the reader said has to survive into the message, too — the exit
    status alone names no cause, and the run stops before anything else can
    ask the binary a second question.
    """
    trimmer = load_interpreter_trimmer()
    complaint = "objdump: 'python3.14': File format not recognized"
    monkeypatch.setattr(
        trimmer.subprocess, "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args[0], 1, "", complaint + "\n"))

    with pytest.raises(SystemExit) as stopped:
        trimmer.section_headers("python3.14")
    message = str(stopped.value)
    assert message.startswith("trim-cpython: "), (
        f"an unreadable binary stopped the run without naming the program "
        f"that could not read it: {message!r}")
    assert complaint in message, (
        f"the stop names no cause, so a build log carries an exit status and "
        f"nothing to act on: {message!r}")


def test_a_bolt_rewritten_interpreter_declines_strip_visibly(tmp_path,
                                                              monkeypatch):
    """The build log must carry a sentence naming the skip and its reason,
    and a skipped strip must not read as one that ran: `main()`'s own
    summary line is derived from exactly the value this asserts. Driven with
    the classifier's own subprocess seam forced to report markers, against a
    throwaway file standing in for the interpreter binary: a `strip` that ran
    anyway changes the file, and a skip that returns what a successful strip
    would have returned is indistinguishable from one — the failure this
    exists to catch."""
    trimmer = load_interpreter_trimmer()
    root = tmp_path / "python"
    binary = root / "bin" / "python3.11"
    binary.parent.mkdir(parents=True)
    original = b"not an ELF file, just bytes strip must never touch"
    binary.write_bytes(original)

    monkeypatch.setattr(trimmer, "section_headers",
                        lambda _binary: BOLTED_SECTION_HEADERS)

    before, after, skipped = trimmer.strip_interpreter(str(root))
    assert skipped is True, (
        "a BOLT-marked binary was stripped instead of being skipped")
    assert before == after, (
        "a skipped strip reports different before/after sizes, which is "
        "what a real strip leaves behind")
    assert binary.read_bytes() == original, "a skipped strip touched the file"
