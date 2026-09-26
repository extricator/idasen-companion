---
name: idasen-companion-release
description: Cut a release of Idasen Companion end to end — pick the version, write the release notes, update the version files on a preparation branch, merge its verified PR, and dispatch the Release workflow on the merged main commit. Use when the user asks to cut, publish or ship a release, or names a version to release (for example "release 1.0.1"). Do not use to change the version for any other reason, to rebuild a package at the current version, or to re-point an existing tag.
---

# Cut a release

This skill performs the procedure in `CONTRIBUTING.md` § "Cutting a release".
Read that section before you start. This file states the mechanics. That
section states the reasoning, and it wins if the two ever disagree.

## Refuse to start

Fetch tags before you check anything else:

```bash
git fetch --tags origin
```

The Release workflow creates the tag on GitHub, so a clone that has not fetched
since the last release does not hold it. `git describe` then names an older
release, and Phase A1 goes on to classify commits that already shipped —
re-announcing them in the notes and computing the bump over a superset. The
existing-tag check below reads the remote for the same reason.

Stop and tell the user when any of these is true:

- A new release starts with a dirty working tree. Run `git status --porcelain`.
  If resuming an existing preparation branch, inspect its changes and continue
  safely instead of discarding them.
- The current branch is neither `main` for a new release nor the matching
  `release/vX.Y.Z` branch for an in-progress preparation PR. On the latter,
  inspect the existing PR and resume its actual phase; do not create another
  branch or repeat completed release actions.
- The tag for the target version already exists. Run
  `git ls-remote --tags origin`.

For a new release, fetch `origin` and fast-forward local `main` before
classifying commits. If local `main` is ahead of or diverged from
`origin/main`, stop and resolve that history separately; do not push it
directly to `main` as part of a release.

```bash
git fetch origin
git merge --ff-only origin/main
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
```

A released version is spent. Never move an existing tag. A defect found after
a release ships as the next patch version.

---

## Phase 0 — review the history

```bash
LAST=$(git describe --tags --abbrev=0)
git log --oneline "$LAST..HEAD"
git rev-list --count "$LAST..HEAD"
```

Report how many commits stand between the last release and `origin/main`, and
whether they represent finished changes. Do not rewrite commits already on
`origin/main`. If the history raises a release-scope question, resolve it before
choosing the version. The separate history-tidying skill applies only to
unpushed local history and is not part of this PR-based release path.

---

## Phase A — decide the version and write the notes

### A1. Read the commits

```bash
LAST=$(git describe --tags --abbrev=0)
git log --format='%n@@ %h%n%B' "$LAST..HEAD"
```

The `@@` line separates commits. Classify each complete message by its
conventional-commit type and breaking-change markers.

| Types present | Bump |
|---|---|
| any `!` after the type/scope, or a `BREAKING CHANGE` footer | major |
| any `feat` | minor |
| any `fix` or `perf` | patch |
| only `docs`, `chore`, `test`, `ci`, `refactor`, `style` | none |

If another type or an unconventional message appears, inspect its compatibility
and user-visible impact. Do not silently treat it as no release; ask the user
when its intended bump is ambiguous.

### A2. Propose the version

State the computed bump and the commits behind it. Then ask the user to
confirm or override.

When the table gives **none**, say so plainly. Do not invent a `fix:` to
force a bump. A documentation release is a legitimate override. Record the
reason in the changelog section.

After the user confirms the target, check that exact tag again:

```bash
git ls-remote --tags origin "refs/tags/vX.Y.Z"
git rev-parse --verify --quiet "refs/tags/vX.Y.Z"
```

Any output from the first command or a successful second command means the
version is already spent. Stop; never move or rebuild that tag.

### A3. Draft three pieces of prose

Write all three before you edit anything. Show them to the user together.
Match the voice of the existing entries. Do not concatenate commit subjects.

1. **The `CHANGELOG.md` section.** Reconcile the existing `[Unreleased]`
   content with every commit since the last tag; do not duplicate or omit
   already-drafted entries. This becomes the release body verbatim —
   `scripts/extract-changelog.sh` extracts exactly it. Follow Keep a Changelog:
   `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Security`.
   Documentation work goes under `### Changed`.
2. **The metainfo description.** One or two short `<p>` blocks. GNOME
   Software and KDE Discover show this text to end users, so write for a
   reader who has never seen the repository.
3. **The package changelog summary.** Terse bullet lines. Both `%changelog`
   entries and the Debian stanza share this text.

Wait for the user to approve or rewrite the draft. Do not proceed on silence.

Before changing the version files, record the base commit and create a fresh
preparation branch. If the branch name already exists locally or remotely,
inspect it rather than overwriting it. Keep `main` at the fetched remote SHA.

```bash
BASE_SHA=$(git rev-parse origin/main)
git switch -c "release/vX.Y.Z"
```

---

## Phase B — edit seven files

Nine sites. Miss one and `pytest` goes red in Phase C, so the cost of an
error is a red run rather than a bad release. Edit all nine anyway.

### B1. `src/idasen_companion/__init__.py`

```python
__version__ = "X.Y.Z"
```

This is the source of truth. `pyproject.toml` reads it and needs no edit.

### B2 and B3. `packaging/idasen-companion-bundled.spec`

Move `Version:`. **Leave `Release:` at `1`.** Only the version moves.

```
Version:        X.Y.Z
Release:        1%{?dist}
```

Add a new entry at the top of `%changelog`, above the existing newest one:

```
* Www Mmm DD YYYY name <email> - X.Y.Z-1
- First summary line, wrapped at roughly 75 columns.
- Second summary line.
```

Copy the name and email from the newest existing entry rather than inventing
them. Use the RPM date format shown above, for example `* Sun Aug 09 2026`.

**Escape a literal percent sign as `%%`.** An unescaped `%` in a spec file is
a macro. The existing entries contain `%%check` for this reason.

### B4 and B5. `packaging/idasen-companion.spec`

The same two edits. This is the unshipped three-package COPR variant, and it
carries its own `%changelog`. Keep the two entries identical in content.

### B6. `debian/changelog`

Add a new stanza at the very top:

```
idasen-companion (X.Y.Z-1) unstable; urgency=medium

  * First summary line.
  * Second summary line.

 -- name <email>  Www, DD Mmm YYYY 00:00:00 +0000
```

The spacing is exact and `dpkg-buildpackage` fails on a malformed stanza.
One space before `--`. Two spaces before the date. Two spaces before each
`*` bullet. Copy the identity and the trailing `+0000` from the stanza below.

### B7. `packaging/flatpak/io.github.extricator.IdasenCompanion.yaml`

```yaml
        path: ../../dist/idasen_companion-X.Y.Z.tar.gz
```

The underscore is correct. setuptools normalises the sdist name per PEP 625.

### B8. `data/io.github.extricator.IdasenCompanion.metainfo.xml`

Add a new `<release>` element at the top of `<releases>`, above the current
newest one. Keep the older elements. Software centres show release history.

```xml
    <release version="X.Y.Z" date="YYYY-MM-DD">
      <description>
        <p>
          The prose from A3.
        </p>
      </description>
    </release>
```

### B9. `CHANGELOG.md`

Keep `## [Unreleased]` directly under the introductory paragraph. Move its
release-ready content into the section approved in A3, reconcile that content
with the commits being released, and put the new version directly below the
now-clean `[Unreleased]` heading:

```markdown
## [X.Y.Z] - YYYY-MM-DD
```

The section must have content. An empty section passes the version check and
then becomes an empty release page. Do not leave released entries under
`[Unreleased]`, and do not duplicate them in both sections.

---

## Phase C — verify locally

```bash
.venv/bin/python -m pytest -q
PYTHON=.venv/bin/python bash scripts/build-dist.sh
```

`pytest` is the proof that you missed no file. `test_every_manifest_agrees_with_the_package_version`
compares all seven against `__version__`, and
`test_the_current_version_has_release_notes_with_something_in_them` proves
the release body is not empty.

`build-dist.sh` proves the sdist builds under the new filename.

Do not run mypy, pylint, the naming check or the translation build. A version
bump cannot affect them, and CI runs them regardless.

**Gate on the exit code, never on the log text.** This project has a
documented trap where a coverage message prints `FAIL` and then exits 0.

Fix any failure and re-run before you continue.

---

## Phase D — verify and land the preparation PR

Commit the release preparation on its branch as one commit. Stage the seven
specified files, including both specs, instead of adding unrelated files:

```bash
git add -- src/idasen_companion/__init__.py \
  packaging/idasen-companion-bundled.spec packaging/idasen-companion.spec \
  debian/changelog packaging/flatpak/io.github.extricator.IdasenCompanion.yaml \
  data/io.github.extricator.IdasenCompanion.metainfo.xml CHANGELOG.md
git commit -m "chore(release): X.Y.Z"
PREP_SHA=$(git rev-parse HEAD)
git push -u origin HEAD
```

Never add a `Co-Authored-By: Claude` trailer.

Never `git add -f` anything under `.planning/`. That directory and
`CLAUDE.md` are gitignored on purpose.

Open a PR from `release/vX.Y.Z` into `main` with the version, approved notes,
and exact verification commands in its body. Use a body file with `gh pr create
--base main --head "release/vX.Y.Z" --title "chore(release): X.Y.Z"
--body-file <path>`. Record its number and URL. Wait for ordinary PR CI on
`PREP_SHA`:

```bash
gh run list --workflow=ci.yml --commit="$PREP_SHA" --limit 20 \
  --json databaseId,headSha,status,conclusion,url
gh run watch <database-id> --exit-status
```

Select the PR run for the exact preparation SHA. If it is not registered yet,
wait and query again. Never substitute a merely latest CI run. The automatic
version-change plan must select RPM with portability, Debian with smoke, and
Flatpak. Require Python 3.11–3.14, both quality groups, all three package
jobs, exact-head five-asset assembly, and the `PR CI` aggregate to succeed in
that single run. A failed, cancelled, or skipped required proof is a stop.

Before merging, fetch `origin` and require both the PR head and `origin/main`
to match `PREP_SHA` and `BASE_SHA` respectively. If either changed, update the
preparation branch, rerun local verification as needed, and obtain fresh
automatic release-preparation `PR CI` on the new exact head. If a future review policy blocks the
PR, wait for an authorized reviewer; do not bypass it. Merge the verified PR
through GitHub, then fetch `origin/main` and record its new SHA:

```bash
gh pr merge <pr-number> --merge
git fetch origin main
git switch main
git merge --ff-only origin/main
RELEASE_SHA=$(git rev-parse HEAD)
```

Confirm the PR is merged, `RELEASE_SHA` is the current `origin/main`, and its
version files and notes match the chosen version. A merge commit may differ
from `PREP_SHA`; all following checks and release dispatches use `RELEASE_SHA`.
Wait for the full `main` `ci.yml` run associated with that exact SHA to pass.
Check the plan, Python/quality, all three package formats, RPM portability,
release candidate assembly, and artifact cleanup. Record its run ID and
verify that it retains exactly one unexpired `release-assets` artifact, with
the five packages, release notes, checksums, and matching provenance. The
three intermediate package artifacts should be gone. The `PR CI` aggregate
applies to pull requests; inspect each required proof on the merged SHA.
Stop on any red or missing required proof.

Stop here if CI is red. Report what failed.

---

## Phase E — publish the verified main CI candidate

Confirm `origin/main` still equals `RELEASE_SHA` before dispatch. A later
merge changes the release target and requires a new full `main` CI candidate.

**Ask the user before publication every time.** Show the version, approved
notes, merged SHA, successful `main` CI URL and run ID, and exact promotion
choice. Publishing creates a remote tag and GitHub Release. After explicit
approval, record the existing release-workflow dispatch IDs for this commit:

```bash
BEFORE_RUN_IDS=$(gh run list --workflow=release.yml --commit="$RELEASE_SHA" \
  --event workflow_dispatch --limit 100 --json databaseId \
  --jq '.[].databaseId')
gh workflow run release.yml --ref main -f version=X.Y.Z \
  -f promotion_run_id=<successful-main-ci-run-id>
```

Poll for a new workflow-dispatch run on the exact `RELEASE_SHA`, absent from
`BEFORE_RUN_IDS`, and watch that exact ID. The promotion validator accepts
only a successful `main` CI release candidate or successful `main` release
dry run from the same current SHA. It rechecks all proof jobs, asset names,
release notes, provenance, and checksums. The workflow then publishes and
verifies the tag, release body, and six downloadable files before retiring
the source artifact. Independently inspect the release URL and asset list.

If the candidate artifact has expired or promotion fails closed, stop and
explain why. With user authorization, choose the explicit full-rebuild path;
never silently switch modes:

```bash
gh workflow run release.yml --ref main -f version=X.Y.Z \
  -f full_rebuild=true
```

A remote release dry run is optional for testing workflow changes, requires
separate explicit authorization, and creates no tag or publication. It builds
the five assets and retains a promotable bundle for one day. The routine
release path uses the already verified `main` CI candidate without rebuilding.
The workflow refuses an existing tag and a version that differs from source.

Report the release URL:

```bash
gh release view "vX.Y.Z" --json url --jq .url
```

---

## Known limits

The repository currently has one contributor and no enforced review or
required-check policy. Use the preparation PR and its exact-head automatic proof anyway;
if a future policy adds a reviewer, honor it before merge. Never bypass the
policy or push a release preparation commit directly to `main`.

**The Actions form remains the documented route.** `CONTRIBUTING.md` § "Cutting
a release" describes the manual procedure for a maintainer without Claude
Code. Keep that section correct when this skill changes.
