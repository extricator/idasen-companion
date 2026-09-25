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

**Please default to `--mock-desk`.** The desk's controller accepts exactly one
BLE connection, and a client killed mid-connection leaves a half-open link that
the desk will not replace until the Bluetooth stack is reset. `docs/` has the
details.

Before opening a pull request, run:

```bash
.venv/bin/python -m pytest
uvx pylint src/idasen_companion          # naming rule, tier 3 — see "Naming things"
python scripts/check_naming_span.py src  # naming rule, tier 2 — see "Naming things"
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
carries Qt, while the headless flavor contains only the CLI and daemon:

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
   pass. The PR's `PR CI` is ordinary per-update verification. Applying the
   `full-ci` label starts complete PR verification and reports `CI OK` for that
   head. An approving review can start the same full run when another reviewer
   is available. The repository currently has one contributor, so no review,
   `CI OK`, or branch-protection requirement is enforced yet. A new PR commit
   needs a new full run before its result can describe the current head.
4. **Dry-run the merged commit.** Open **Actions → Release → Run workflow** on
   `main`, enter the version without a leading `v` (for example `1.2.0`), and
   tick **dry run**. It runs Python, quality, all package builds, Debian smoke,
   RPM portability, and five-asset assembly without creating a tag or release.
   Save the successful run ID. A branch dry run can exercise release changes,
   but only a successful dry run on the current `main` commit can be promoted.
5. **Publish that verified set.** Run **Actions → Release → Run workflow** again
   on `main` with the same version and the successful dry run's ID in
   **promotion run ID**. Leave **dry run** and **full rebuild** unticked. The
   workflow checks the source run, exact `main` commit, version, required job
   results, five file names, release notes, and checksums before publishing
   those bytes. It verifies the published tag and assets before deleting the
   source artifact. Dry-run artifacts expire after one day.

   If the dry run expired or cannot be promoted, run a new dry run or select
   **full rebuild** for a real release. Full rebuild reruns every verification
   and package proof. Select exactly one real-release mode: a promotion run ID
   or full rebuild. A push of a `v*` tag also uses full rebuild. The workflow
   refuses a dispatch from a side branch or a version that disagrees with
   `__version__` on `main`.

   The release carries full/headless RPMs, full/headless `.deb` packages, the
   versioned full `.flatpak` bundle, and `SHA256SUMS`. Its body is the matching
   `CHANGELOG.md` section.
6. **Check what shipped.** Download the assets and, in that directory:

   ```bash
   sha256sum --ignore-missing -c SHA256SUMS
   ```

   A released version is spent. A defect found afterwards ships as the next
   patch version, never as a moved tag: the release publishes a checksum over
   the exact bytes it carried, so re-pointing a tag leaves anyone who already
   downloaded holding a file that no longer matches what the tag now claims —
   and a checksum that can mean two different things is worth nothing.

**One time, for the 1.0 release only.** These steps happen once. They are
written down because getting their order wrong is expensive.

*Before making the repository public*, re-scan both the whole history and the
working tree for committed secrets — they answer different questions (a
history scan cannot see a file that was never committed, by construction),
and this phase exists precisely because a working-tree-only gap once hid a
real credential from a history-only scan:

```bash
git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'
bash scripts/scan-secrets.sh history <evidence-directory>/history
bash scripts/scan-secrets.sh worktree <evidence-directory>/worktree
```

The fetch is not optional and not a convenience. A clone holds branches and
tags; the forge additionally keeps a permanent ref for every proposed change,
carrying each of its intermediate commits — including the ones a squash-merge
collapsed, whose content therefore never reached `main` and which a scan of
the branches cannot reach either. A secret added in such a commit and tidied
up before the merge lives on that ref, invisible to every check here, and
becomes fetchable by anyone the moment the repository is public. The history
scan compares what the remote publishes against what this clone can reach and
refuses to report clean when the two disagree, so a forgotten fetch fails the
scan rather than quietly narrowing it.

Each plants a secret in a throwaway repository and checks the scanner finds it
before it will believe a clean result on the real target — a scan that walked
nothing looks exactly like a scan that found nothing. A zero exit from a run
means both halves passed for that mode; both commands above must exit zero.
It covers credential-shaped strings only: personal data (MAC addresses, home
directory paths, email addresses, authorship trailers) still needs a person
to judge each distinct value, and the safe window for finding any of it
closes the moment anonymous readers can fetch the history.

*Every push to this remote, and above all the ones around the flip*: push
branches by name. Never `git push --all`, never `git push --mirror`. This
clone carries far more history than the remote does, and the gap is now almost
total — `git rev-list --count HEAD` reports 1 revision on `main` against the
555 that `git rev-list --all --count` reports across every ref. The difference
lives on `backup/main-pre-squash` and five other refs
(`feat/flatpak-release`, `feat/logging-policy`, `feat/settings-apply-model`,
`review-main`, `simplify`) deliberately left behind by the rewrites, plus the
pull-request refs of the repository that preceded this one. What they hold is
exactly what the rewrites removed: the real desk MAC, retired home-directory
paths and stale authorship trailers. Once one of those objects is pushed, it is fetchable by
sha whether or not the branch that carried it still exists — deleting the
branch afterwards does not retract it. Neither flag is something anyone reaches
for deliberately; both get typed as a shortcut for "push everything I have",
which is precisely the thing not to do here.

*Flip the repository public — after the release is published*, so the
repository and the release become visible together:

```bash
gh repo edit --visibility public --accept-visibility-change-consequences
```

Both flags are needed. Passing the visibility on its own is an error rather
than a default.

*Enable secret scanning and push protection — the first thing done once the
repository is public*, since neither setting exists on it before that:

```bash
gh api \
  --method PATCH \
  repos/extricator/idasen-companion \
  --field security_and_analysis[secret_scanning][status]=enabled \
  --field security_and_analysis[secret_scanning_push_protection][status]=enabled
```

Both are free on a public repository, regardless of account plan, and neither
is available on a private personal-account repository — which is why this step
cannot precede the flip and is not a step that got forgotten.

These are a third layer, not a duplicate of what this project already runs.
The local hook is advisory and absent for anyone who never installed it; CI
catches a pull request but has nothing to say about a push to a branch with no
pull request open; push protection is server-side and needs no cooperation
from the contributor at all — it sees every push, by construction. What that
actually binds, because the field names mislead: the two settings are
independent. Secret scanning finds a credential already committed; push
protection refuses a new one on the way in. Enabling only the first leaves the
door open on the way a credential most often lands in a public repository —
a push, not a merge.

Once this is on, a push carrying a credential-shaped string is rejected by
GitHub itself, and that rejection is the feature working, not a broken remote.

Confirm it took:

```bash
gh api repos/extricator/idasen-companion \
  --jq '.security_and_analysis.secret_scanning.status,
        .security_and_analysis.secret_scanning_push_protection.status'
```

Both lines should read `enabled`.

*Decide the `main` approval policy before adding protection.* This private
repository has one contributor, who cannot approve their own PR. Do not make
an approving review or `CI OK` required until that contributor policy is
settled and live PR runs confirm the exact check names and head-SHA association.
`PR CI` reports ordinary updates; `CI OK` comes only from a full run triggered
by approval or by applying `full-ci`. Neither check is enforced today. Keep
force-push and deletion prevention in the eventual protection decision, and
check the rules available to the account at that time. The old command with a
required `CI OK` check and zero required reviews must not be reused: it could
block the sole contributor's PRs because ordinary pushes do not create `CI OK`.

*Enable private vulnerability reporting* the moment the repository is public.
`SECURITY.md` already tells reporters to use it, and it is unavailable on a
private personal-account repository:

```bash
gh api -X PUT repos/extricator/idasen-companion/private-vulnerability-reporting
```

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

Two of the three tiers are enforced by a command, both blocking, both run
before opening a pull request:

```bash
uvx pylint src/idasen_companion          # tier 3 — glossary
python scripts/check_naming_span.py src  # tier 2 — scope span
```

The scope-span band: a 1-character name may live 5 lines between its
declaration and its last use, 2 characters 8 lines, 3 characters 12 lines;
4+ characters is unlimited. `scripts/check_naming_span.py` explains why the
band stops at 3.

**Tier 1 (accuracy) is not machine-checkable and stays a review norm,
permanently.** Both commands exiting clean means tiers 2 and 3 are
satisfied — it does not mean the naming rule as a whole is satisfied.
