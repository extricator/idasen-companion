# Script and release workflow simplification plan

Branch: `plan/script-simplification`

Baseline: `b02e30d` (`main`, 2026-09-30)

## Goal

Reduce maintenance work without hiding it in another file. The proposed change
removes one custom style-checking script and makes release assembly use one
existing implementation. It also corrects the distribution audit's catalog
check. Package formats, release routes, and publication controls stay intact.

The expected script count is **17 instead of 18**. The deleted script is
`scripts/check_naming_span.py`; moving its implementation elsewhere would not
meet this goal.

## Current contract to preserve

- A ready version-change PR proves its exact head with Python and quality
  checks, all five packages, RPM portability, and five-asset assembly. Ordinary
  `main` CI proves the merged SHA and retains a one-day candidate only for an
  unreleased version. These are the contracts documented in `CONTRIBUTING.md`
  and the merged CI redesign PR #2.
- A release dry run builds and assembles without publishing. Promotion checks
  the successful source run, exact SHA, version, artifact provenance, names,
  notes, and checksums. Rebuild and tag-push routes still build their own
  assets. Publishing still needs separate authorization.
- The RPM's build-root checks and the complete five-package smoke test remain.
  The package jobs alone do not currently smoke-test the Flatpak or headless
  Debian package to the same depth as `verify-release-artifacts.sh`.
- Keep the repository private. Do not configure reviews, required checks,
  rulesets, or branch protection as part of this work. Do not run a remote
  release dry run or publish a release as part of implementation or validation.
  Do not install, stop, or launch the desktop app or daemon locally.

## Implementation sequence

### 1. Retire the numerical naming-span gate

Remove `scripts/check_naming_span.py`, its dedicated tests, its `MANIFEST.in`
entry, and the CI invocation. Update `CONTRIBUTING.md` and the comments in
`pyproject.toml` so naming guidance describes accuracy, clear scope, and the
existing Pylint rules without claiming that line-count bands are enforced.
Search the repository for remaining references before finishing. Keep Pylint
and human review; neither should be described as equivalent to the removed
algorithm.

**Why:** the 192-line AST checker and its tests enforce a subjective
project-specific line-span policy. This is the one current check whose removal
reduces ongoing code and CI maintenance without changing a package or release
guarantee. The explicit tradeoff is that the 5/8/12-line thresholds will no
longer block a PR.

Commit this policy change separately from the release workflow change.

### 2. Use one release assembly path

In `.github/workflows/release.yml`, replace the rebuild/dry-run assembly
steps that independently select five filenames, smoke-test the files, write
`SHA256SUMS`, construct release notes, and write `provenance.json` with a call
to `python3 scripts/release-assets.py assemble . "$VERSION" "$GITHUB_SHA" "$GITHUB_RUN_ID"`.
Keep the host-tool installation required by that command,
the existing `release-assets` upload, the job name used by promotion's source
proof, and all publication-side verification. Retain
`scripts/verify-release-artifacts.sh` and `scripts/extract-changelog.sh` as
independent, useful commands called by the assembler.

Check that the dry-run, rebuild, tag-push, and promotion routes still select
the intended SHA and artifact source. Add or adjust workflow topology tests
so both ordinary CI and Release assembly must call the same command and the
Release job no longer has a second implementation of checksum, notes, or
provenance generation. Keep tests that verify exact names and provenance in
`tests/test_release_assets.py`.

Before editing a GitHub Actions workflow, use `ctx7` as required by
`AGENTS.md`: resolve `GitHub Actions` with `npx ctx7@latest library`, then
fetch documentation for reusable job dependencies, expressions, and artifact
handling relevant to the edit. Run those requests outside the default
sandbox.

Commit the workflow change separately. No remote dry run is part of this plan;
local tests and the eventual PR's normal checks provide its review evidence.

### 3. Correct the wheel catalog assertion

`scripts/build-dist.sh` currently claims to require both compiled catalogs,
but only `po/es.po` is tracked today and its check passes if it finds any one
`.mo` file. Derive the expected language set
from tracked `po/*.po` files and require each corresponding wheel member.
Fail if the expected set is empty. Add a small test that removes one catalog
from a fixture wheel and proves the check fails, then run the distribution
build audit. Commit this as a separate bug fix.

### 4. Decide portability cadence from evidence

Keep `scripts/verify-rpm-portability.sh` in this branch. Measure its share of
recent CI time and check whether ordinary main-branch runs catch defects that
the release-preparation PR would otherwise miss. Change the trigger only if
the measured saving is material and every release candidate still has a
successful cross-distribution proof on its exact SHA. Record the decision in
the PR description. This step has no predetermined code change or script
deletion.

## Verification and completion criteria

1. Confirm the sole deleted script is the naming-span checker and no source,
   test, manifest, documentation, or workflow reference to it remains.
2. Run focused tests for release assets, workflow topology, packaging, and
   distribution content locally. Let the normal PR run execute the full test
   suite. Run `actionlint`, shell syntax checks, and `git diff --check` where
   available. Do not start the desktop app or daemon locally.
3. Build the sdist and wheel with `scripts/build-dist.sh`; confirm every
   tracked translation source has a compiled catalog and the archive remains under
   its size ceiling. Do not build or launch the desktop app or daemon.
4. Review the diff against the release routes and holds above. Open a normal
   PR from the implementation branch when implementation is complete; inspect
   its exact-head CI result before considering merge. Do not start a remote
   release dry run or publish a release without separate explicit permission.

## Implementation outcome

- The naming-span gate and its dedicated tests were removed in `9209c87`.
- Release rebuild and dry-run assembly now use `release-assets.py assemble`,
  with topology coverage in `4cb2ef5`.
- The wheel audit now requires a compiled catalog for each tracked `po/*.po`
  source, with a missing-catalog regression test in `6aa0dbc`. At this
  baseline the only tracked source is `po/es.po`, so exactly one app catalog
  is expected. The former "both catalogs" wording was incorrect.
- RPM portability stays on main CI. In successful main run `36370468843`,
  its step took 7m19s within an 11m55s RPM job. The potential saving is
  material, but removing it would leave the merged main SHA without a
  cross-distribution proof before it becomes a releasable candidate.
- Local focused verification: 125 tests passed; shell syntax and diff checks
  passed. The distribution audit built the sdist and wheel, found 211 tracked
  sdist members at 726,886 bytes, and found the expected compiled catalog.

Keep this file as the review record; it is not included in the source archive
by `MANIFEST.in`.
