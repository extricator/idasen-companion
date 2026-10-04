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
.venv/bin/pip install -e . pytest pytest-asyncio PySide6-Essentials
.venv/bin/python -m pytest
```

Run against a simulated desk — no Bluetooth, no hardware — with a throwaway
config so your real one is untouched:

```bash
.venv/bin/idasen-companiond --mock-desk --config /tmp/ic-test.toml
IDASEN_COMPANION_CONFIG=/tmp/ic-test.toml .venv/bin/idasen-companion
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
.venv/bin/python -m pytest
uvx pylint src/idasen_companion          # naming rules — see "Naming things"
```

Touching packaging (`MANIFEST.in`, `pyproject.toml`, `data/`, `packaging/`)
also wants:

```bash
PYTHON=.venv/bin/python bash scripts/build-dist.sh
```

It builds the sdist and wheel and fails if either contains a file nobody
meant to ship.

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

`docs/ARCHITECTURE.md` explains why the code is shaped the way it is; read it
before changing the shape of something rather than working within it.

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

One contextual gettext catalog owns every app message in the GUI, daemon and
CLI. Regenerate it with:

```bash
PATH="$PWD/.venv/bin:$PATH" bash scripts/build-translations.sh
```

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
