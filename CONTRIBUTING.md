# Contributing

Thanks for looking. This is a small project; issues and patches are welcome.

## Reporting a bug

Please include:

- what the desk did, and what you expected it to do;
- your desktop (KDE / GNOME / other) and whether it is X11 or Wayland — idle
  and lock detection differ per desktop, and that is the most common source of
  "it moved while I was away";
- the relevant log lines:

  ```
  journalctl --user -t idasen-companion --since "1 hour ago"
  ```

  Filter on the **identifier** (`-t`), not the unit (`-u`) — the latter covers
  only the daemon's cgroup and omits lines the GUI writes itself.

Bluetooth problems specifically: the daemon logs a BlueZ snapshot whenever a
connect fails (adapter powered/scanning, device connected/paired/RSSI, other
daemons running). Please include it — it usually answers the question on its
own.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]' PySide6-Essentials
QT_QPA_PLATFORM=offscreen dbus-run-session -- .venv/bin/python -m pytest
```

The lightweight path installs the test extra and Qt Essentials without Addons.
For the CI-equivalent full-PySide6 environment, use the separate choice
`.venv/bin/python -m pip install -e '.[gui,test]'`. Python 3.11 or newer and
the host Qt libraries are required; `dbus-run-session` supplies the private
session bus for automated GUI/D-Bus checks, with Qt forced offscreen.

An optional visible walkthrough can use a simulated desk with a throwaway
config and its own session bus. Leave the installed app and daemon running;
the cleanup below targets only the test processes started in this shell:

```bash
dbus-run-session -- bash <<'SH'
set -eu
test_dir=$(mktemp -d)
daemon_pid=
gui_pid=
cleanup() {
    if [ -n "$gui_pid" ]; then
        kill "$gui_pid" 2>/dev/null || true
        wait "$gui_pid" 2>/dev/null || true
    fi
    if [ -n "$daemon_pid" ]; then
        kill "$daemon_pid" 2>/dev/null || true
        wait "$daemon_pid" 2>/dev/null || true
    fi
    rm -rf "$test_dir"
}
trap cleanup EXIT
.venv/bin/idasen-companiond --mock-desk --config "$test_dir/config.toml" &
daemon_pid=$!
IDASEN_COMPANION_CONFIG="$test_dir/config.toml" .venv/bin/idasen-companion &
gui_pid=$!
wait "$gui_pid"
gui_pid=
SH
```

`idasen-companion` also accepts Qt-free subcommands in both package flavors:
`status`, `log`, `toggle`, `sit`, `stand`, `stop`, and `preset NAME`. For example,
use `idasen-companion toggle` in a desktop keyboard shortcut. Repeating the
same movement gesture during a move follows `[ui] tray_repeat_move` (`stop`,
`reverse`, or `off`); `stop` and named presets are direct requests. In the
headless package, a bare command or `--window` exits with a usage error.

**Please default to `--mock-desk`.** The desk's controller accepts exactly one
BLE connection, and a client killed mid-connection leaves a half-open link that
the desk will not replace until the Bluetooth stack is reset. `docs/` has the
details.

Before opening a pull request, run:

```bash
.venv/bin/python -m pytest tests/test_machine_startup.py
.venv/bin/python -m pytest tests/test_machine_startup.py::test_start_classifies_current_height
QT_QPA_PLATFORM=offscreen dbus-run-session -- .venv/bin/python -m pytest -q --cov=idasen_companion --cov-fail-under=77
uvx mypy==2.3.0 --python-executable .venv/bin/python src/
uvx pylint==4.0.6 src/idasen_companion
```

The quality tools run separately through `uvx`; they are not project
dependencies. Use the full `.[gui,test]` environment above for the
CI-equivalent mypy target. Naming rules are described under "Naming things".

Touching packaging (`MANIFEST.in`, `pyproject.toml`, `data/`, `packaging/`)
also wants:

```bash
.venv/bin/python -m pip install build
PYTHON=.venv/bin/python bash scripts/build-dist.sh
```

`build` is a packaging-only Python prerequisite. The script builds the sdist
and wheel and audits their contents. It clears stale distribution metadata
and outputs, so use a disposable checkout to preserve existing local builds.

**Install the local secret-scanning hook once, with:**

```bash
git config core.hooksPath .githooks
```

Cloning installs nothing — the repository ships the hook, but git does not
use it until that line is run, and a contributor who assumes otherwise gets
no protection and no error. Once set, it scans whatever is staged with the
same pinned scanner CI runs, so the two cannot disagree about what counts as
a secret, and it needs docker or podman, failing closed with a message
rather than passing quietly if neither is present. `git commit --no-verify`
bypasses it, and that is deliberate — it is for a false positive in a hurry,
not an escape route, since the same scan runs in CI where nothing bypasses
it.

Shared scanner rules do not imply identical input coverage. See the
[coverage and cost assessment](docs/SECRET-SCANNING-ASSESSMENT.md) for the
distinct staged, history, worktree and hosted checks and their limits.

`docs/ARCHITECTURE.md` explains why the code is shaped the way it is; read it
before changing the shape of something rather than working within it.

## Editor conventions

EditorConfig-compatible editors read the root `.editorconfig` for the existing
text and indentation conventions. Markdown hard breaks, tabbed Debian recipes,
verbatim licenses, generated or upstream metadata, artwork, and binary assets
have deliberate exceptions. Properties set to `unset` remain controlled by
editor defaults; this does not lock file bytes. The configuration is contributor
guidance, not a formatter, linter, or request to reformat existing files in bulk.

## Building the packages

Released artifacts are built by CI. Build them by hand when you change
packaging, or when you package the app for a distribution.

The checked-in release builder creates an isolated RPM topdir. Install the
prerequisites first when running the RPM selector directly:

```bash
sudo dnf install rpm-build rpmdevtools python3-devel python3-build \
    systemd-rpm-macros desktop-file-utils \
    python3-pytest python3-pytest-asyncio \
    /usr/bin/strip /usr/bin/objdump /usr/bin/dbus-run-session \
    'libGL.so.1()(64bit)' 'libEGL.so.1()(64bit)' 'libxkbcommon.so.0()(64bit)' \
    'libfontconfig.so.1()(64bit)' 'libfreetype.so.6()(64bit)' \
    'libdbus-1.so.3()(64bit)'
```

Six of those names are library sonames and three are program paths, and
neither kind is a package name: `dnf` resolves each to whatever package
provides it here. The spec asks for them that way on purpose — it is how a
build dependency gets stated without naming any one distribution's package for
it — so the command that installs them says the same thing. The sonames are
what the bundled Qt links against while the suite runs, and without them the
GUI tests fail at collection rather than skipping. Two of the programs are what
the build's trimmers shell out to, one to take the symbol table off the bundled
interpreter and one to walk Qt's dependency graph; the third is the session bus
the build starts the daemon on, to prove the tree it is about to package
actually runs rather than merely imports.

Neither `pip` nor `setuptools` is asked for by name any more: every install
`rpmbuild` performs is run by the interpreter the package will carry, out of
the extraction the spec unpacks, and that extraction brings its own of both.
The sdist step below still assembles an isolated environment of its own, for
which `python3-build` pulls in what it needs.

The release ships two standalone self-contained RPMs from the same spec. Both
carry the app's Python runtime and common dependencies; the full flavor also
carries Qt, while the headless flavor contains only the CLI and daemon. Both
install `idasen-companion` for CLI subcommands; only full opens the GUI:

```bash
bash scripts/build-release-variants.sh --rpm --output dist-release
```

The builder regenerates the sdist, fetches the pinned runtime input, then runs
both spec flavors offline against those shared sources.

The result is architecture-specific — it contains Qt — so it appears under
`rpmbuild/RPMS/x86_64/`.

The spec's `%check` runs the test suite against the tree that ships, bundled
Qt included, so a failing test fails the build. It runs it **on the interpreter
the package carries**, not on the machine's — so a test that passes in your
venv and fails in `%check` is most likely a test that depends on a Python newer
than the bundled minor, which is the one the package's users get. The test
framework itself is still the build host's, appended to the search path behind
the bundled directories; that is the one thing in `%check` the package cannot
supply, since nothing in the payload is a test dependency and the build runs
offline.

### Refreshing bundled interpreter metadata

The fetcher checks the reviewed metadata before downloading or creating outputs.
Run that same check offline with the existing Python environment:

```bash
.venv/bin/python scripts/verify-interpreter-metadata.py verify
```

For a runtime bump, review the upstream release and source commit, update the
three interpreter pins, and obtain complete local copies of the install-only
asset, its matching optimized `pgo+lto` full archive, and the checksum-pinned
Zstandard source archive. Install-only archives omit `PYTHON.json`. Review the
complete archive hashes and sizes, metadata member hash and size, and source
LICENSE hash independently before passing them to refresh:

```bash
.venv/bin/python scripts/verify-interpreter-metadata.py refresh \
    --install-archive "$INSTALL_ARCHIVE" \
    --install-sha256 "$INSTALL_SHA256" --install-size "$INSTALL_SIZE" \
    --full-archive "$FULL_ARCHIVE" \
    --full-sha256 "$FULL_SHA256" --full-size "$FULL_SIZE" \
    --zstd-archive "$ZSTD_ARCHIVE" \
    --zstd-sha256 "$ZSTD_SHA256" --zstd-size "$ZSTD_SIZE" \
    --metadata-sha256 "$METADATA_SHA256" --metadata-size "$METADATA_SIZE" \
    --zstd-license-sha256 "$ZSTD_LICENSE_SHA256" \
    --release "$RELEASE" --source-commit "$SOURCE_COMMIT" \
    --output packaging/interpreter
```

Refresh reads named regular members without extracting or executing archive
contents. It uses standard-library Zstandard support when available, otherwise
`zstd -dc`; ordinary verification needs neither. For the current build, the
full archive lacks the referenced Zstandard notice, so its exact source
`LICENSE` is the recorded fallback. The missing zlib-ng alternate path does
not describe a shipping component: the Unix build uses ordinary zlib.

Review the regenerated raw `PYTHON.json`, deterministic `PROVENANCE.json`, and
the corresponding exact source notice bytes together. Retained extensions,
explicit public-domain status, actual trim exclusions, and build-only
setuptools are separate from wheel terms. Source associations establish
provenance; they do not establish legal substitutability or complete compliance.
After copying the reviewed exact notice bytes into `packaging/licenses/interpreter`
and reconciling the full/headless declarations and staging, run the complete check:

```bash
.venv/bin/python scripts/verify-interpreter-metadata.py verify
```

Confirm expanded full/headless declarations separately with actual `rpmspec`
outputs and the verifier's explicit `verify-expanded` command.

### Other package builds

`packaging/` also holds a three-package split (`idasen-companion.spec` plus
`python-bleak.spec` and `python-idasen.spec`) for a repository that carries the
two libraries separately. This is not what ships, and nothing in CI builds
`idasen-companion.spec` — it shipped with a broken `%install` line, unbuilt
and undetected, until this phase's research built it by hand and found the
break; a follow-up commit removed the stray line, but the spec still has no
build gate, so it can go stale again the same way. It is unverified between
releases. The two self-contained release RPMs are the supported path. If you build
the split anyway, build the two library packages and install them before you
build the app package.

The Debian selector produces the full and headless packages from one pybuild
staging tree:

```bash
bash scripts/build-release-variants.sh --deb --output dist-release
```

For the Flatpak bundle, read `packaging/flatpak/README.md`. To reproduce all
five release artifacts in their Fedora and Debian container environments and
then smoke-test them:

```bash
bash scripts/build-release-variants.sh --all --output dist-release
bash scripts/verify-release-artifacts.sh dist-release
```

## Translations

`docs/TRANSLATING.md` is written for translators and is the place to start.

One contextual GNU gettext catalog owns every app message in the GUI, daemon
and CLI. Install the external gettext tools `xgettext`, `msgmerge` and `msgfmt`
with your operating system's package manager (`msginit` is also used when
initializing a language). They are not pip dependencies. Regenerate with:

```bash
bash scripts/build-translations.sh
git diff --exit-code -- po/ src/idasen_companion/locale
```

The script extracts `po/idasen_companion.pot`, merges `po/<language>.po`, then
compiles `src/idasen_companion/locale/<language>/LC_MESSAGES/idasen_companion.mo`.
For a string change, review the diff, fill new translations in the PO files,
rerun the script and commit the POT, PO and MO changes. With no string change,
the diff check must pass. Qt's standard buttons use its separate prebuilt
`qtbase` catalog; there is no app-owned TS/QM generation step.

A change that adds or alters a user-facing string must regenerate it and fill
in every shipped language before it lands. Leaving a string untranslated
is quiet: the build succeeds, the catalog ships, and the string is simply
never translated.

`docs/TRANSLATING.md`'s Glossary section covers *terminology* consistency --
one English concept, one word per language, enforced by a test rather than
left to memory.

## Patches

- One coherent change per commit, with a message explaining *why* where it
  isn't obvious. Conventional Commits style (`fix(daemon): …`).
- Keep refactors separate from behaviour changes.
- New behaviour wants a test. The suite runs in a few seconds and needs no
  hardware, so there is rarely a good reason not to.
- Renaming anything, the D-Bus wire format, and how config gets written are
  covered in `docs/ARCHITECTURE.md` § "Renaming anything" — read it before a
  rename or before touching config or the D-Bus service, since each of those
  three has a way to go wrong that a green build and a passing test suite
  won't catch.

## Cutting a release

Building and attaching the artifacts is automated; the *order* is not, and
getting it wrong costs a version number. Follow this top to bottom.

Ordinary PR merges to `main` always build and test the packages. While the
source still names an already tagged version, CI removes those temporary
packages after testing; it creates no release candidate or GitHub Release.
The first merge that carries a new, unreleased version and its release notes
also assembles a one-day candidate from that same `main` CI run. Publishing
always remains a separate, explicitly authorized action.

**Every release.**

1. **Move the version.** It lives in `src/idasen_companion/__init__.py`, and
   every packaging manifest mirrors it, so they all move together in one
   commit: both specs under `packaging/` (`Version:`, plus a new `%changelog`
   entry each), `debian/changelog` (a new stanza), the Flatpak manifest's
   pinned sdist filename, and
   `data/io.github.extricator.IdasenCompanion.metainfo.xml` (a new `<release>`
   block). `Release:` in the specs stays at `1` — only the version moves. The
   test suite compares each of those files against the source of truth, so one
   you missed is a red run rather than a shipped mismatch.
2. **Write the notes.** Add a `## [X.Y.Z] - YYYY-MM-DD` section at the top of
   `CHANGELOG.md`. That section *is* the release body — the workflow extracts
   exactly it — and the suite fails if it is missing or empty. The metainfo
   `<release>` prose from step 1 is a second, shorter piece of writing aimed at
   software centres; it is not generated from the changelog.
3. **Land the preparation PR on `main`** and wait for its full `main` CI run to
   pass. On a ready PR, changing the source version against the PR base
   automatically selects Python and quality checks, RPM with portability,
   Debian with smoke, Flatpak, and five-asset assembly on the exact PR head.
   The single `PR CI` aggregate requires all selected proofs to pass. A new
   PR commit gets a new run; inspect the checks for that exact head. The
   protection policy requires `PR CI`, an up-to-date branch, and resolved
   review conversations. Zero approving reviews are required while the
   repository has one maintainer. Start the preparation from
   current `main` on a dedicated release branch, make the version and notes
   commit there, and merge the PR only after its exact head has passed the
   complete automatic PR run. If `main` moves before merge, refresh the PR
   and repeat its checks. Do not push the preparation commit directly to
   `main`. The resulting `main` push runs all package proofs; inspect the
   complete run on the merge SHA.
4. **Use the merged commit's release candidate.** The full `main` CI run
   builds and tests all five packages on the merge commit. For an unreleased
   version, it also verifies the complete set, writes checksums, release notes,
   and provenance, and retains one `release-assets` bundle for one day. It
   removes the three intermediate package artifacts after assembly. Save the
   successful `main` CI run ID and confirm it names the current `main` SHA.
   A release dry run remains available to test release-workflow changes, but
   is not required for an ordinary release.
5. **Publish that verified set.** After explicit publication authorization,
   open **Actions → Release → Run workflow** on `main`, enter the version
   without a leading `v` (for example `1.2.0`), and enter the successful
   `main` CI run ID in **promotion run ID**. Leave **dry run** and **full
   rebuild** unticked. The workflow checks the source run, exact current
   `main` commit, version, required job results, five file names, release
   notes, and checksums before publishing those bytes. It verifies the
   published tag and assets before deleting the source bundle.

   If the candidate expired or cannot be promoted, select **full rebuild**
   with authorization. Full rebuild reruns every verification and package
   proof. Select exactly one real-release mode: a promotion run ID or full
   rebuild. A push of a `v*` tag also uses full rebuild. The workflow
   refuses a dispatch from a side branch or a version that disagrees with
   `__version__` on `main`.

   The release carries full/headless RPMs, full/headless `.deb` packages, the
   versioned full `.flatpak` bundle, and `SHA256SUMS`. Its body is the matching
   `CHANGELOG.md` section. Its title is `vX.Y.Z`.
6. **Check what shipped.** Confirm the GitHub Release title is
   `vX.Y.Z`. Download the assets and, in that directory:

   ```bash
   sha256sum --ignore-missing -c SHA256SUMS
   ```

   A released version is spent. A defect found afterwards ships as the next
   patch version, never as a moved tag: the release publishes a checksum over
   the exact bytes it carried, so re-pointing a tag leaves anyone who already
   downloaded holding a file that no longer matches what the tag now claims —
   and a checksum that can mean two different things is worth nothing.

## Repository protections and publication

The applied settings are recorded in [`.github/repository-policy.json`](.github/repository-policy.json).
Treat this as an audited snapshot; verify current settings through GitHub when
changing protections or investigating a blocked merge.

The repository uses the following policy for a single maintainer:

- `main` requires a pull request, the `PR CI` check from GitHub Actions,
  an up-to-date branch, and resolved review conversations.
- Zero approving reviews are required. The maintainer cannot approve their
  own PR; CI and the PR merge route remain mandatory.
- Force pushes and deletion of `main` are blocked, with no routine bypass.
- Merge commits and squash merges are supported. Release preparation uses
  a merge commit to retain its approved source commit.
- Existing tags matching `v*` cannot be updated or deleted. Tag creation is
  allowed so the release publisher can create the next version.
- Immutable releases protect the assets and tags of future published
  releases. Enabling this setting does not make existing releases immutable.

`PR CI` runs on every PR update and requires every selected proof to pass.
Package selection uses the complete diff against the PR base, including after
synchronize events: a documentation-only push cannot hide an earlier package
failure. Ready PRs that change the version also require complete release
preparation proof. Draft PRs defer packaging until they are marked ready.

The Actions token defaults to read access, with write permissions limited to
publication and artifact cleanup jobs. External fork contributors require
maintainer approval before their workflows run. Review workflow changes before
approving a run, keep fork jobs without write tokens or repository secrets,
and use GitHub-hosted runners. Allowed actions are maintained in the repository
settings and must be pinned to full commit SHAs.

Secret scanning, repository push protection, private vulnerability reporting,
Dependabot alerts and security updates, and Python CodeQL scanning are enabled
through GitHub settings. CodeQL starts as an advisory check until its baseline
has been reviewed. `.github/dependabot.yml` groups weekly Python and Actions
updates. Bundled dependencies pinned in RPM specs and Flatpak manifests also
need review during release preparation; Dependabot does not cover every
bundled runtime or library.

### Weekly bundled Python advisory audit

The maintainer owns the separate **Bundled dependency audit** workflow in
`.github/workflows/dependency-audit.yml`. It runs Mondays at 09:17 UTC and can
be started manually through Actions. It has read-only repository access and
reports in the job summary and logs. Findings fail that run for attention;
operational errors or incomplete package coverage also fail, with a distinct
error report. This advisory workflow is independent of required PR checks.
GitHub notifications depend on each maintainer's account and repository
notification settings; email delivery is not guaranteed. Scheduled runs use
the default branch and may be delayed or disabled under GitHub's scheduling
rules, so check the Actions history when reviewing dependency health.

To reproduce from the repository root, use a disposable environment (only audit
tooling is installed; the packages being audited are neither installed nor
resolved):

```bash
audit_tmp=$(mktemp -d)
python3 -m venv "$audit_tmp/venv"
"$audit_tmp/venv/bin/python" -m pip install --disable-pip-version-check pip-audit==2.10.1
"$audit_tmp/venv/bin/python" scripts/audit-bundled-dependencies.py
```

The entrypoint reads the authoritative `PINS` and `BUILD_BACKEND` arrays in
`scripts/fetch-bundled-runtime.sh` as data, validates their reviewed wheel
catalog coverage, and reads the install pins in
`packaging/flatpak/python3-deps.json`. It reports RPM shipped packages (the full
set includes the headless subset), the RPM build backend, and Flatpak installed
packages separately. It sends only exact name/version requirements to
`pip-audit --no-deps --disable-pip`; it never sources the fetch script, changes
pins, downloads audited wheels, or automatically fixes findings. Exit codes
are 0 for complete clean results, 1 for findings, and 2 for an audit or input
error, including skipped or missing packages. Review audit-tool pin updates
through normal PRs independently of application pins.

For each finding, the maintainer should:

1. Confirm the advisory's affected versions, the inventory that ships the
   package (or uses it only during the build), and the application's exposure.
   Treat an audit error as an investigation task, not a clean result.
2. Check existing Dependabot alerts, PRs, and tracked work before opening
   duplicate remediation. If alerts are inaccessible, record that limitation;
   do not assume there are no alerts. The dependency graph is not proof of
   these exact bundled inventories.
3. Use a normal PR to update affected pins, validate the change, and rebuild
   and release affected packages. If deferring, record the advisory, affected
   inventory, owner, exposure rationale, and a concrete expiry/review date in
   tracked work. An exception is time-bounded and does not suppress the audit.

This is a PyPI package advisory lookup for declared pins, not an inspection of
shipped bytes or a guarantee of no vulnerabilities. It excludes CPython and
its embedded libraries, complete Qt/native-code coverage, distro packages,
and the Flatpak platform and BaseApp. Bundled-runtime monitoring remains
separate work; wheel content is checked by the build boundary below.

### Reviewed bundled-wheel hashes

`PINS` and `BUILD_BACKEND` in `scripts/fetch-bundled-runtime.sh` remain the
version authority. `packaging/bundled-wheel-hashes.json` binds intended wheel
basenames to reviewed SHA256 digests, separately for shipped runtime and the
build-only backend. The fetcher validates both groups before downloading,
generates temporary requirements for pip's `--require-hashes` mode, and checks
exact filenames, bytes, and one wheel per pin before publishing either output.
The bundled interpreter still selects compatible wheels through the configured
pip index or mirror; a mirror must serve the approved bytes. Downloads remain
binary-only and dependency resolution stays disabled. The RPM installs from
those separate verified wheel directories offline.

Refresh this catalog explicitly when changing pins or intended artifacts:

1. Choose the intended release and exact compatible filenames. Keep the fetcher
   pins, spec declarations and other existing version consumers synchronized;
   do not add a second editable version list. Review both current CPython 3.14
   x86_64 `dbus-fast` alternatives (the older-glibc and `manylinux_2_41` wheels).
   Both are approved, but exactly one may enter a runtime archive.
2. Fetch the primary PyPI release metadata at
   `https://pypi.org/pypi/<project>/<version>/json`. Check each intended filename,
   release identity, wheel type, yanked status, size and `digests.sha256`.
3. Download each exact intended artifact into disposable storage, independently
   compute its SHA256 (for example, `sha256sum <downloaded-wheel>`), and require
   agreement with that primary metadata and its size. Review every catalog
   entry, including the alternative wheel that this host's pip did not select.
   Never approve hashes from a pip error suggestion, URL fragment, cache
   listing, or arriving build directory alone.
4. Edit the catalog and review the filename, group, digest and pin diff together.
   Run the focused offline checks:

   ```bash
   .venv/bin/python -m pytest -q tests/test_bundled_wheel_hashes.py tests/test_dependency_audit.py tests/test_packaging.py
   ```

   In disposable storage, use the fetcher with its verified bundled interpreter
   to check actual selection, both groups' complete closure and separate
   `--no-index --no-deps` installation. Build and check the source package in a
   disposable committed checkout so local build outputs stay intact. Submit
   the reviewed catalog and matching pin changes through a normal PR.

The initial review trusts the chosen upstream metadata and downloaded bytes;
agreement cannot prove that upstream was uncompromised at that moment. Once
reviewed and committed, the catalog rejects later substitutions from an index,
mirror or cache. Ordinary builds only consume approval: the helper provides
`prepare` and `verify`, with no refresh or auto-accept operation. Keep the catalog
diff and metadata/actual-byte review evidence with the maintenance review.

Before the initial public visibility change, audit a fresh remote clone rather
than the development clone, which also holds deliberately unpublished backup
history:

```bash
git clone https://github.com/extricator/idasen-companion.git /tmp/idasen-public-audit
git -C /tmp/idasen-public-audit fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'
cd /tmp/idasen-public-audit
bash scripts/scan-secrets.sh history /tmp/idasen-public-history-scan
bash scripts/scan-secrets.sh worktree /tmp/idasen-public-worktree-scan
```

Both scanner modes must pass their canary and real scan. Review personal data,
PR descriptions and comments, retained Actions logs, and build artifacts too.
Making the repository public exposes its history and Actions logs; subsequent
forks can remain public even if visibility is later changed back to private.

Push branches explicitly by name. Never push all refs or mirror this development
clone: local backup refs hold removed personal data, and archived icon artwork
is intentionally excluded from the published project.

After the audit and CI preparation PR pass, change visibility and immediately
apply the branch and tag rulesets, fork approval policy, and security settings.
Check the effective rules and use a small PR to verify the required check and
normal maintainer merge route. An administrator can edit the ruleset for
recovery, but must not bypass it for an ordinary merge.

*Nothing to do for the AppStream screenshot URLs.* They name the default
branch, so replacing a picture is a plain overwrite of the file in
`data/screenshots/` and nothing else moves with it. They 404 for anonymous
readers only while the repository stays private, and they resolve the moment
it is public.

Do not repoint them at a release tag. That was tried, and it needs the URL to
name a tag that does not exist yet at the moment it is written; one release
replaced the images while the URLs still named the previous tag, leaving five
dead links. `tests/test_packaging.py` checks only what stays breakable: that
every path a URL names is a file in the tree, so a rename or a deletion is
caught before it reaches anyone.

## Naming things

Name a thing for the role it plays, and keep one name per concept. The test
that matters: the name still has to mean something *quoted away from its
file* — in a commit message, a bug report, a review comment. Three tiers, in
priority order:

1. **Accuracy.** The name states the role, and means one thing project-wide.
   `sane` for "elapsed time isn't a suspend-sized gap" in one module and `ok`
   meaning two different things in two different modules both fail this. Not
   machine-checkable — it's on review, permanently.
2. **Scope span.** The further a name's declaration is from its last use, the
   more descriptive it needs to be. Short names are fine near their
   assignment.
3. **Glossary.** Don't coin a second abbreviation for something that already
   has a name (`cfg` vs `config`).

Explicitly *not* the rule: "longer is better". A long, misleading name is
worth no more than a single letter — extra length only earns its keep when it
carries an extra concept. Renames are their own commits, never mixed with
behaviour changes; see `docs/ARCHITECTURE.md` § "Renaming anything" for two
ways a rename can look fine and still break something silently.

Pylint enforces the configured glossary and naming patterns. Run it before
opening a pull request:

```bash
uvx pylint src/idasen_companion
```

Accuracy and scope span remain review norms. A clean Pylint run does not
establish that every name communicates its role clearly at its actual scope.
