---
name: idasen-companion-release
description: Cut a release of Idasen Companion end to end — pick the version, write the release notes, update the seven files that carry the version, land the bump on main, and dispatch the Release workflow. Use when the user asks to cut, publish or ship a release, or names a version to release (for example "release 1.0.1"). Do not use to change the version for any other reason, to rebuild a package at the current version, or to re-point an existing tag.
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

- The working tree is dirty. Run `git status --porcelain`.
- The current branch is not `main`.
- The tag for the target version already exists. Run
  `git ls-remote --tags origin`.

A released version is spent. Never move an existing tag. A defect found after
a release ships as the next patch version.

---

## Phase 0 — offer to tidy the history

```bash
LAST=$(git describe --tags --abbrev=0)
git log --oneline "$LAST..HEAD"
git rev-list --count "$LAST..HEAD"
git rev-list --count origin/main..HEAD
```

Report three things: how many commits stand between the last release and
`HEAD`, how many of those are unpushed, and whether they read as finished
changes or as steps toward one. Then ask the user to choose.

- **Release as it stands.** Go straight to A1. A long history is not a defect
  and this needs no justification. Take this as the answer to silence only if
  the user has already said so in this session; otherwise ask.
- **Tidy first.** Stop here and hand over to the `idasen-companion-tidy-history`
  skill, which carries its own backup and its own verification. The user
  re-enters this skill when that is done.

Never tidy anything yourself inside this skill, and never refuse a release over
an untidy history.

Whoever does the tidying — this session or a later one — is bound by two rules:

- **Never rewrite a commit already on `origin/main`.** Rewriting changes a
  commit's id, so the remote's copy can only be reconciled by overwriting it.
  Phase D pushes with a plain `git push`, and branch protection will forbid the
  alternative outright once the repository is public.
- **Carry any `!` or `BREAKING CHANGE` marker onto the squashed message.** A1
  computes the bump from subject lines, so a marker dropped in a squash turns a
  major release into a patch. Nothing downstream catches it: the version tests
  compare the seven manifests against `__version__`, never against what the
  commits said.

Either way the tidying happens before A1, because A1 reads the subject lines it
would rewrite.

---

## Phase A — decide the version and write the notes

### A1. Read the commits

```bash
LAST=$(git describe --tags --abbrev=0)
git log --format='%h %s' "$LAST..HEAD"
```

Classify each subject by its conventional-commit type.

| Types present | Bump |
|---|---|
| any `!` or `BREAKING CHANGE` | major |
| any `feat` | minor |
| any `fix` | patch |
| only `docs`, `chore`, `test`, `ci`, `refactor`, `style` | none |

### A2. Propose the version

State the computed bump and the commits behind it. Then ask the user to
confirm or override.

When the table gives **none**, say so plainly. Do not invent a `fix:` to
force a bump. A documentation release is a legitimate override. Record the
reason in the changelog section.

### A3. Draft three pieces of prose

Write all three before you edit anything. Show them to the user together.
Match the voice of the existing entries. Do not concatenate commit subjects.

1. **The `CHANGELOG.md` section.** This becomes the release body verbatim —
   `scripts/extract-changelog.sh` extracts exactly it. Follow Keep a
   Changelog: `### Added`, `### Changed`, `### Fixed`, `### Removed`,
   `### Security`. Documentation work goes under `### Changed`.
2. **The metainfo description.** One or two short `<p>` blocks. GNOME
   Software and KDE Discover show this text to end users, so write for a
   reader who has never seen the repository.
3. **The package changelog summary.** Terse bullet lines. Both `%changelog`
   entries and the Debian stanza share this text.

Wait for the user to approve or rewrite the draft. Do not proceed on silence.

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

Add the section from A3 directly under the introductory paragraph, above the
current newest heading:

```markdown
## [X.Y.Z] - YYYY-MM-DD
```

The section must have content. An empty section passes the version check and
then becomes an empty release page.

---

## Phase C — verify locally

```bash
.venv/bin/python -m pytest -q
bash scripts/build-dist.sh
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

## Phase D — land the bump

Commit everything from Phase B as one commit:

```bash
git add -A
git commit -m "chore(release): X.Y.Z"
git push origin main
```

Never add a `Co-Authored-By: Claude` trailer.

Never `git add -f` anything under `.planning/`. That directory and
`CLAUDE.md` are gitignored on purpose.

Then wait for the aggregate check to go green:

```bash
gh run list --workflow=ci.yml --commit="$(git rev-parse HEAD)" --limit 1
gh run watch <run-id> --exit-status
```

The aggregate check is named `CI OK`, verbatim. It fails when any job is
`failure`, `cancelled` **or `skipped`**.

Stop here if CI is red. Report what failed.

---

## Phase E — publish

**Ask the user before this phase. Every time.**

This is the only irreversible step. It creates a public tag and a public
release. Show the user the version and the release notes, then wait for an
explicit go-ahead.

Offer a dry run first when the release machinery itself changed. A dry run
builds all five release artifacts and writes their checksums, and creates no
tag and no release:

```bash
gh workflow run release.yml -f version=X.Y.Z -f dry_run=true
```

The real release:

```bash
gh workflow run release.yml -f version=X.Y.Z
gh run list --workflow=release.yml --limit 1
gh run watch <run-id> --exit-status
```

The workflow re-checks the version against `__version__`, refuses a tag that
already exists, builds the full and headless RPMs, the full and headless
`.deb` packages, and the Flatpak bundle, writes `SHA256SUMS` over all five,
creates the `vX.Y.Z` tag pointing at the commit the artifacts came from, and
publishes.

Report the release URL:

```bash
gh release view "vX.Y.Z" --json url --jq .url
```

---

## Known limits

**Direct push to `main` works today only because the repository is private
on a free plan.** Branch protection is unavailable there. When the repository
goes public and protection lands, Phase D must open a pull request instead.

**The Actions form remains the documented route.** `CONTRIBUTING.md` § "Cutting
a release" describes the manual procedure for a maintainer without Claude
Code. Keep that section correct when this skill changes.
