# GitHub Actions CI redesign

> **Temporary cross-conversation artifact.** This file exists only while the
> CI redesign is being reviewed and implemented. Remove it before merge, after
> moving any lasting operator guidance into maintained documentation.

Status: **design amended after the 1.2.0 release; implementation not approved or started**

Branch: `ci-workflow-rebuild`

Baseline: `eb829e2` (`main` when this phase began). `main` has since advanced
to `a20f559` (`v1.2.0`); synchronize it before implementation.

Last updated: 2026-09-25

## Goal and constraints

Replace the current seven-workflow layout with a smaller orchestration model
that gives every merge candidate one dependable `CI OK` conclusion, makes
expensive package work intentional, and still proves packaging changes before
merge.
The release path must continue to fully verify all five deliverables:
desktop and headless RPMs, desktop and headless Debian packages, and the
Flatpak bundle. A real release may publish the exact assets from a successful
dry run when their provenance and hashes are proved; otherwise it must build
and verify the complete set itself.

The repository is private and its current plan has no branch protection, so
the design must be useful as a visible maintainer signal today without
pretending it is an enforced merge policy. It must also be ready to enforce
approval plus both the fast `PR CI` check and approval-triggered `CI OK` check
when branch protection becomes available later.

## Audit baseline

### Current topology

`.github/workflows/ci.yml` calls four reusable workflow families:

- `test.yml`: four Python matrix jobs (3.11 through 3.14);
- `checks.yml`: six independent jobs (typing, distribution contents, naming,
  translations, AppStream metadata, and secret scanning);
- `rpm.yml`: build plus portability jobs;
- `deb.yml`: build plus systemd smoke jobs;
- `flatpak.yml`: one build job.

`release.yml` independently calls the three package workflows with `force:
true`, assembles and verifies exactly five assets, and publishes them. Today a
real release rebuilds at its ref even after a successful dry run. That is
trustworthy but duplicates the most expensive work and consumes another set
of temporary artifacts.

A full CI run can therefore expose sixteen job conclusions before counting
release-only work. Names explain individual operations, but the check list
does not communicate the intended groups particularly well.

### Current selection defect

RPM, Debian, and Flatpak each repeat the same checkout/base-selection/diff
shell block. On a pull request each block compares the PR base to the current
head, so once any package-relevant file has changed, every later update to
that PR rebuilds every affected package even when the new update is unrelated.
The duplicated regular expressions have already drifted in shape and make it
hard to state one policy for shared versus format-specific inputs.

### Existing workflow contracts enforced by tests

- `tests/test_workflow_pins.py` requires every external action reference in
  every workflow to be a full commit SHA and requires local reusable workflow
  references to remain local, unpinned paths.
- `tests/test_packaging.py` requires the Debian workflow to install Babel
  before dependency checking, the Flatpak workflow to install the manifest's
  BaseApp branch, and the RPM workflow to verify generated package metadata
  before uploading the artifact.
- The same packaging test module protects the semantics implemented by the
  package and portability verification scripts. Those are product/distribution
  tests, not merely workflow glue.
- Since `a20f559` on `main`, `tests/test_packaging.py` also protects the
  isolated Flatpak runtime setup in the five-asset verifier and requires
  one-day retention on all package/release artifact uploads. This branch has
  not yet incorporated that release fix.

Implementation must update these tests when job boundaries move while
preserving what they prove. Tests should assert behavior or ordering, not old
filenames that no longer own the behavior.

### Timing evidence

The earlier supplied full-run observation was approximately 14 minutes, with
RPM portability taking about 8m34s. `gh` access now works. The latest five
successful `main` push runs available on 2026-09-25 provide more evidence
(wall time from the run's start to its last update; job times from each job's
own start/end timestamps):

| CI run | Overall | RPM build | RPM portability | Notes |
|---|---:|---:|---:|---|
| [36129311751](https://github.com/extricator/idasen-companion/actions/runs/36129311751) | 13m38s | 4m41s | 7m32s | 1.2.0 release-path fix |
| [36093456592](https://github.com/extricator/idasen-companion/actions/runs/36093456592) | 13m48s | 4m27s | 7m55s | 1.2.0 version bump |
| [36090895626](https://github.com/extricator/idasen-companion/actions/runs/36090895626) | 5m57s | 32s | skipped | Docs-only commit; package jobs skipped their expensive steps |
| [36090212371](https://github.com/extricator/idasen-companion/actions/runs/36090212371) | 11m52s | 4m31s | 5m52s | Distribution architecture change |
| [32441271276](https://github.com/extricator/idasen-companion/actions/runs/32441271276) | 7m44s | 2m45s | 3m28s | Earlier release-era baseline |

The release-path evidence is separate: successful 1.2.0 dry run
[36130614315](https://github.com/extricator/idasen-companion/actions/runs/36130614315)
took 17m04s, including 3m35s of five-asset assembly; the real release
[36132268056](https://github.com/extricator/idasen-companion/actions/runs/36132268056)
took 20m55s, including 3m05s of assembly and 14s of publication. Use these
observations to set initial timeouts with setup/network headroom; do not infer
a percentile or a performance promise from five heterogeneous runs.

The local `GH_TOKEN` issue that blocked the first audit no longer blocks
run listing, dispatch, or status queries. `gh run watch` still receives 403
when requesting check annotations with this token, so annotation access needs
separate diagnosis. Run status and job logs remain available.

### Lessons from the 1.2.0 release

The first 1.2.0 dry run
[36096469530](https://github.com/extricator/idasen-companion/actions/runs/36096469530)
built all five artifacts and passed RPM portability and Debian smoke, then
failed assembly because the verifier installed `org.kde.Platform//6.10` into
the runner's normal Flatpak home but installed the bundle into an isolated
home. Commit `a20f559` made runtime installation part of that isolated
verifier and passed full CI, the repeat dry run, and the real release. Keep
the five-asset verifier as an executable release contract, and preserve a dry
run that reaches assembly before creating a tag.

The repository's Actions storage warning reached 90% of the plan's 0.5 GB
allowance. An inventory found 79 retained workflow artifacts totaling
1,295,219,946 bytes; they were deleted by exact artifact ID, and the
repository artifact list then reported zero. This cleanup did not affect
published GitHub Release assets. Commit `a20f559` also set
`retention-days: 1` on the RPM, Debian, Flatpak, and assembled-release
uploads on `main`. Those changes must be retained when this branch is
synchronized. The original 3/7-day retention proposal is superseded.

## Proposed architecture

Use five workflow files:

1. `ci.yml` — the ordinary PR and `main` orchestrator, plus manual CI
   dispatch;
2. `full-ci.yml` — approval-triggered full PR verification, with a label
   fallback while branch protection is unavailable;
3. `verify.yml` — reusable Python tests and grouped quality checks;
4. `packages.yml` — reusable, input-driven package builds and package-level
   smoke/portability verification, with no changed-path logic;
5. `release.yml` — release gate, calls full verification and all packages,
   assembles exactly five assets, and publishes.

The two internal workflows must expose only `workflow_call`, not
`workflow_dispatch`. This removes them from the top-level Actions menu and
keeps manual policy in `ci.yml`. Names should read as a hierarchy in the UI:

- `Tests / Python 3.11` … `Tests / Python 3.14`;
- `Quality / Code`;
- `Quality / Distribution and supply chain`;
- `Packages / RPM`;
- `Packages / Debian`;
- `Packages / Flatpak`;
- `PR CI` for ordinary per-update verification;
- `CI OK`.

This keeps the useful four-version matrix visible, groups the current six
quality/static jobs into two coherent jobs, and combines each format's build
and downstream proof into one check. The RPM job builds in its Fedora
container and then runs portability from the host; the Debian job builds in
its Debian container and then runs the systemd smoke test from the host. Both
can be implemented with Docker/Podman from an Ubuntu runner, avoiding the
current job boundary without weakening the clean-environment tests. A full
run should expose ten named checks rather than sixteen.

The GitHub semantics used by this design were checked through Context7 on
2026-09-24 against the current official documentation for [workflow
triggers](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow),
[job conditions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-jobs-with-conditions),
[events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows),
[concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency),
[workflow syntax and token permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches),
and [ruleset check behavior](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/troubleshooting-rules).

### Central planner and changed paths

`ci.yml` gets one small `plan` job with a full checkout. It emits booleans for
`rpm`, `deb`, `flatpak`, and `rpm_portability`, plus a human-readable summary.
Do not add a path-filtering action or a new repository script: this logic is
specific to GitHub event payloads and has one caller, so a reviewed shell step
in the orchestrator is the simplest ownership boundary.

Diff ranges in ordinary `ci.yml` runs are event-aware:

- PR `synchronize`: compare `before..after`, meaning only the newly pushed
  update selects automatic package work;
- PR `opened`, `reopened`, or `ready_for_review`: compare PR base to head,
  because there is no prior checked head for this run;
- push to `main`: ignore paths and select every package proof;
- manual full run: ignore paths and select every package proof.

`full-ci.yml` does not classify paths. An approving review selects every
verification and package proof against that PR head. Applying the `full-ci`
label does the same as an interim or diagnostic fallback, but is not the
normal merge-gating path.

For force-pushes, try to fetch the event's `before` SHA. If it is unavailable
or is not an ancestor that yields a meaningful update diff, fall back to the
full base-to-head PR diff. The safe failure mode is extra verification, never
silently selecting nothing.

Path classes should be narrow and explained beside the classifier:

- shared package plumbing (package metadata, manifests, shared release-build
  code, or `packages.yml` itself) selects every affected format;
- RPM specs/runtime/trim/ELF/metadata files select RPM;
- Debian control/rules/install/unit files select Debian;
- Flatpak manifest/lock/build files select Flatpak;
- a change to the RPM portability verifier selects both RPM build and RPM
  portability, so the verifier is tested against a fresh package;
- ordinary tests, documentation, and unrelated scripts do not select a
  package merely because they live in a broad directory;
- ordinary `src/` changes receive the complete Python and quality gates but
  do not automatically rebuild three distribution formats. Approval launches
  the full package integration proof for the reviewed head.

The exact path table must be covered by focused unit tests. Put the classifier
data in a form the tests can read directly; avoid tests that merely duplicate
the same regex in Python.

### Event and job policy

| Event/state | Python 3.11–3.14 | Quality/static | RPM | Debian + smoke | Flatpak | RPM portability |
|---|---:|---:|---:|---:|---:|---:|
| Draft PR update | yes | yes | no | no | no | no |
| Ready PR, ordinary update | yes | yes | only if this update selects it | only if this update selects it | only if this update selects it | only if verifier changed |
| PR becomes ready | yes | yes | if full PR diff selects it | if full PR diff selects it | if full PR diff selects it | if verifier changed |
| Approving review | yes | yes | yes | yes | yes | yes |
| `full-ci` label fallback | yes | yes | yes | yes | yes | yes |
| Manual `core` | yes | yes | no | no | no | no |
| Manual `full` | yes | yes | yes | yes | yes | yes |
| Push to `main` | yes | yes | yes | yes | yes | yes |
| Release dry run | yes | yes | yes | yes | yes | yes |
| Real release using a verified dry run | reuse that run's successful verification | reuse | publish its verified RPMs | publish its verified Debian packages | publish its verified Flatpak | reuse its passed portability proof |
| Real release without a valid dry run, including a tag-push path | yes | yes | yes | yes | yes | yes |

Draft PRs still get useful, inexpensive feedback. Automatic package work is
suppressed until `ready_for_review`; that event evaluates the complete PR diff
so a packaging change made while draft is not lost.

Debian smoke remains coupled to every Debian build because it is the only
proof of the installed systemd user unit and archive PySide resolution. RPM
metadata checks remain coupled to every RPM build and must run before upload.
The roughly 8.5-minute RPM portability proof runs only when its own code
changes, after approval, when explicitly requested with the `full-ci` fallback,
on `main`, and during every release dry run or full-rebuild release. Promotion
reuses the successful proof for the exact published bytes.

### Expensive-job gate decision

| Gate | Strengths | Weaknesses | Decision |
|---|---|---|---|
| Changed paths | Automatic and format-specific | Cumulative PR diffs rerun forever unless event deltas are used; cannot express final confidence alone | Use update deltas for automatic package-definition validation |
| Draft state | Avoids spending on work explicitly marked unfinished | Not a readiness or trust signal by itself | Suppress package jobs while draft; re-evaluate full diff on ready |
| Review approval | Already part of the intended merge decision; can trigger full CI for the reviewed head; pairs directly with stale-approval protection | Requires another authorized reviewer; each new head must be approved again | Primary full-CI authorization and future merge gate |
| `full-ci` label | Visible, deliberate, and usable before branch protection is available | A second manual ceremony; a persistent label must not rebuild on later synchronize events | Interim and diagnostic fallback only; trigger only on the label event itself |
| Manual dispatch | Good recovery and targeted diagnostics | Easy to forget and not naturally represented as a PR-head policy | Provide `core`, `full`, and individual format modes as an escape hatch |
| Push to `main` | Tests the integrated tree and catches bypasses | Feedback is post-merge | Always run full verification |
| Release/tag | Protects published bytes | Too late to be the only package proof; rebuilding after a successful dry run repeats costly work | Publish a precisely identified, fully verified dry-run asset set when safe; otherwise run full verification and rebuild all five |

`full-ci.yml` starts from an approving `pull_request_review`. If multiple
approvals later become required, its gate must confirm that the PR's aggregate
review decision is approved before launching expensive jobs; the first of
several approvals must not spend a full run prematurely. A non-approval review
submission must never create a skipped-success `CI OK`: the gate and final
aggregate must make it impossible for comments or requested changes to produce
a false green check.

The label fallback must check the event action and the label applied, not
merely whether the PR currently contains the label. Otherwise the persistent
label recreates the current “every later commit rebuilds everything” defect.
The run and its checks are associated with the SHA that was actually tested.

### `PR CI`, `CI OK`, skips, and future merge protection

Do not put workflow-level `paths` filters on `ci.yml`. Current GitHub
documentation states that when a workflow is skipped by branch/path filtering,
its required check can remain pending. In contrast, a job skipped by an `if`
condition reports success and does not block merging.

`ci.yml` must therefore start on every relevant PR event and every `main`
push. The reusable package workflow is always called, receiving planner
booleans; its unselected format jobs skip normally. Selected jobs have no
second, independent path condition that could accidentally skip them. Its PR
aggregate is named `PR CI`, clearly distinguishing fast per-update evidence
from full merge readiness.

Only `full-ci.yml` publishes `CI OK` for a pull request. It calls complete
verification and every package proof, then uses `if: always()` to succeed only
when all required caller results are `success`. Failure, cancellation, an
unexpected skip, or an approval gate that did not pass must fail or withhold
the aggregate; none may become a green `CI OK`.

When branch protection or an equivalent ruleset becomes available, configure
`main` with all of the following:

- require pull requests and at least one approving review;
- dismiss stale approvals when new commits are pushed, or require approval of
  the most recent reviewable push;
- require the exact `PR CI` and `CI OK` status-check names, preferably from the
  GitHub Actions app;
- optionally require the branch to be current with `main` before merging;
- do not allow routine bypass of these rules.

That policy couples approval and full verification without a label. A new
commit makes the old approval stale and has no successful `CI OK` on its new
head. Reapproval triggers `full-ci.yml` again, and merge remains blocked until
that run proves the new head. Before protection is available the same checks
remain visible and trustworthy, but enforcement is necessarily social.

The 1.2.0 preparation commit went straight to `main` because this private
repository currently cannot protect that branch. Once protection is enabled,
cutting a release should use a normal release-preparation PR for the version,
changelog, package metadata, and any release-path fix. Review and `CI OK`
apply to that PR. After merge, run full `main` CI and a release dry run on
the **merged commit**; only then publish/tag that exact commit. A PR-head dry
run cannot be promoted if merging produced a different SHA. The release
operator must not need a routine protection bypass or direct push to `main`.

Configure `CI OK` as a required **status check**, not as an organization-level
required-workflow rule. GitHub's required-workflow mechanism supports
`pull_request`, `pull_request_target`, and `merge_group`, not
`pull_request_review`. If a merge queue becomes available later, add
`merge_group: checks_requested` and make full verification prove the queued
merge candidate as well as the approved PR head.

### Reliability, security, and cost controls

- **Concurrency:** give ordinary and full PR workflows distinct groups keyed
  by PR number, cancelling older runs within each tier. Do not let an ordinary
  update cancel an approval-triggered run through a shared group name; the new
  head instead makes the old result unusable. Do not cancel `main` runs. Give
  release runs a separate version/tag group with `cancel-in-progress: false`;
  never cancel a publishing run because another trigger arrived.
- **Timeouts:** add an explicit `timeout-minutes` to every job. Use the five
  measured `main` runs and the successful release/dry-run durations above,
  including the earlier 8m34s portability observation, with reasonable
  setup/network headroom. Recheck after the job topology changes.
- **Artifacts:** preserve the one-day upload retention now on `main`; do not
  regress to the original 90-day default or the superseded 3/7-day proposal.
  Delete ordinary-CI package artifacts after their last consumer finishes;
  in a release dry run, delete the three intermediate package artifacts after
  assembly produces the verified asset set. Keep a promotable dry-run
  `release-assets` artifact until it is
  published or expires; it cannot be deleted immediately after verification
  and still be reused. After publication and asset verification, delete that
  exact source artifact. A dry run not selected for publication should be
  cleaned when known obsolete, with one-day expiry as the fallback. Limit
  cleanup to artifact IDs from the current, verified run. Published GitHub
  Release assets remain attached to the release. Continue using
  `if-no-files-found: error`.
- **Permissions:** default to `contents: read`; grant `pull-requests: read`
  only where the approval gate queries review state. Cross-run artifact
  download requires `actions: read`; deleting an artifact through GitHub's
  REST API requires `actions: write`. Confine these to the promotion/cleanup
  jobs. Grant `contents: write` only to the final release publish job. No PR
  code or package-build job gets write access or repository secrets.
- **Forks:** use `pull_request`, never `pull_request_target`, and never execute
  untrusted PR code with write permission or repository secrets. The design
  works with the read-only fork token documented by GitHub.
- **Action pinning:** retain full commit SHA pins and the existing pin test.
  Local reusable workflows remain local paths. Review container image tags
  separately; action-SHA policy does not make mutable container tags immutable.
- **Caching:** retain `setup-python`'s pip download cache. Do not introduce
  broad build-output or package-manager caches in the first implementation;
  RPM/Flatpak artifacts and native package databases are high-churn and can
  obscure reproducibility. Measure the simplified runs before adding a
  narrowly keyed cache.
- **Release:** the dry run calls full verification and all package proofs,
  then assembles one checked set. A real release either promotes those exact
  bytes under the checks below or performs the same full build and proof when
  promotion is unavailable. Preserve unique filename checks, the five-asset
  verifier, checksums, and the publish-only write boundary.

### Promoting a verified dry run

Prefer a real release that names one successful, trusted dry-run **run ID**
and promotes its already-checked `release-assets` artifact. This removes the
second 17–21-minute build and avoids temporarily storing another set of large
RPMs. Cross-run download is supported by `actions/download-artifact` with
`run-id` and a token that has `actions: read`; GitHub's artifact API exposes
the source run ID, head SHA, size, and expiry. Current documentation also
provides a per-artifact delete endpoint requiring `actions: write`.

Promotion must fail closed unless all of the following hold:

- the named run belongs to this repository and the trusted release dry-run
  workflow, completed successfully on `main`, and its version equals the
  requested release version;
- the source run's head SHA equals the current `main` commit and the SHA the
  release will tag; no moving `latest successful run` lookup is sufficient;
- its single assembled artifact is unexpired, contains exactly the five
  expected package files, `SHA256SUMS`, and release notes, and its bytes match
  the checksums; the names, embedded versions, and release body are checked
  again before publication;
- the dry run included successful Python/quality checks, both native smoke
  proofs, RPM portability, and five-asset assembly; a skipped or failed
  required job disqualifies it;
- the published tag and GitHub Release assets are verified before the source
  artifact is deleted. If publication fails, keep the source for a controlled
  retry until its one-day expiry.

Do not promote PR artifacts or files from a caller-supplied repository. Keep
the tag-push path, if retained, on the full rebuild-and-verify route because
it lacks an explicitly selected dry run. Decide the exact workflow input and
cleanup job wiring in Phase 3, then dry-run both the promotion and fallback
paths before replacing the current proven publisher. The published release
must remain possible if a dry-run artifact expires: require another dry run
or an explicit full-rebuild release mode, never silently publish stale bytes.

Context7 and the current official [cross-run artifact example](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[artifact retention guidance](https://docs.github.com/en/actions/tutorials/store-and-share-data),
and [artifact REST API](https://docs.github.com/en/rest/actions/artifacts)
were checked on 2026-09-25 for this proposal.

## Script disposition

The initial impression is understandable because several scripts are long,
but most encode independently testable distribution invariants that would be
harder to review if pasted into YAML. The architecture change should remove
workflow glue, not hide product checks.

### Keep as durable verification/build interfaces

- `build-dist.sh`: guards sdist/wheel contents and is a documented local gate.
- `build-translations.sh`: canonical catalog regeneration used locally and in
  CI.
- `check_naming_span.py`: implements a project-specific rule and has its own
  test suite.
- `build-release-variants.sh`: one interface for the five artifacts; the
  format-specific paths are used by CI and documented for maintainers.
- `fetch-bundled-runtime.sh`, `strip-bundled-tree.sh`, `trim-cpython.py`, and
  `trim-pyside6.py`: RPM construction logic called by the spec.
- `verify-bundled-bytecode.sh`, `verify-bundled-elf.sh`,
  `verify-rpm-metadata.sh`, `verify-rpm-portability.sh`, and
  `verify-release-artifacts.sh`: executable distribution contracts, several
  directly protected by packaging tests.
- `extract-changelog.sh`: small, reusable release-note extraction with a
  documented local meaning.

### Simplify cautiously, not in the architecture phase

`scan-secrets.sh` is the strongest candidate for later simplification: at 469
lines it wraps Gitleaks with a canary, evidence capture, full-ref verification,
and three scan modes. Replacing it with a pinned action/container invocation
would delete substantial code, but only if the replacement proves the same
history coverage (including fetched PR refs), detects a planted canary, works
for local staged scans, and does not introduce a private-repository licensing
dependency. Treat that as an optional, separately reviewed phase rather than
quietly weakening the security check during workflow restructuring.

Do not create a new changed-path script. Delete the three duplicated inline
classifiers from the package workflows when the centralized planner lands.
During implementation, also remove any now-unused `force`/`relevant` outputs
and comments. After reference and test searches, delete a whole script only if
it has no remaining local, package-spec, documentation, or CI contract.

## Phased implementation plan

Each phase ends with focused verification, one logical commit, and an update
to this handoff.

### Phase 1 — design (this commit)

- Inventory workflows, workflow-sensitive tests, CI-facing scripts, branch,
  and available timing evidence.
- Verify current GitHub Actions skip/required-check, conditional job,
  reusable workflow, permission, concurrency, and fork behavior through
  current documentation.
- Record the proposed architecture and decisions; make no workflow changes.

Verification: review the document diff, confirm no workflow/source changes,
and run the existing workflow-pin and packaging contract tests.

### Phase 2 — planner and reusable topology

- Synchronize `ci-workflow-rebuild` with `main` at or after `a20f559` before
  changing workflows, preserving the release verifier fix and one-day
  artifact-retention contracts.
- Add the central planner and its path/event contract tests.
- Consolidate tests/quality into `verify.yml` and packages into
  input-driven `packages.yml`.
- Combine build and downstream proof per package format.
- Make `ci.yml` the ordinary PR/main/manual entry with stable `PR CI`.
- Add `full-ci.yml`, triggered by an approving review or the interim label
  fallback, with complete verification and the only PR `CI OK` aggregate.
- Add contract tests that prevent a non-approval or skipped job from producing
  a successful `CI OK`.
- Remove obsolete reusable workflow files and duplicated classifiers.

Verification: YAML parse/load, focused workflow tests, complete unit suite,
and manual inspection of computed plans for representative event fixtures.

### Phase 3 — release integration and controls

- Make release and dry-run paths call full verification plus all package
  proofs, preserving the five-asset assembly and publish boundary.
- Implement and test explicit promotion from a trusted successful dry run,
  including SHA/version/run-ID checks, exact asset/checksum revalidation,
  post-publication verification, scoped artifact cleanup, and an explicit
  full-rebuild fallback. Do not let the current tag-push path silently reuse
  a different run's bytes.
- Document the protected-`main` release-preparation PR path, with a post-merge
  dry run of the actual commit to be tagged.
- Add measured timeouts, explicit retention, final concurrency rules, and
  least-privilege permissions.
- Audit SHA pins and container-image policy.

Verification: focused release/packaging tests, complete unit suite, action
syntax validation, and a manual release dry run from the branch if the user
authorizes external execution.

### Phase 4 — live evidence and cleanup

- Observe PR runs for ordinary and packaging-specific updates, approval,
  reapproval after a new commit, the `full-ci` fallback, and superseded
  updates; observe one `main` or equivalent full run.
- Compare durations and check-list shape with the baseline; tune timeouts only
  from evidence.
- Confirm intermediate artifacts are removed after their consumers finish,
  dry-run promotion keeps only the verified set until publication, and
  published GitHub Release assets remain available. Investigate the local
  token's check-annotation 403 without making CI depend on that token.
- Decide the optional `scan-secrets.sh` simplification separately.
- Move lasting maintainer instructions to maintained documentation and delete
  this temporary file before merge.

Verification: recorded run URLs/timings, correct selected/skipped jobs, stable
`CI OK`, and a clean repository/reference search after temporary cleanup.

## Approval boundary and next-conversation handoff

No workflow implementation has begun. Approval is requested for these design
choices:

1. five-workflow topology with separate ordinary and approval-triggered PR
   entry points, two grouped quality jobs, and one job per package format;
2. event-delta automatic package selection, with full-diff fallback and
   full-diff evaluation when a draft becomes ready;
3. approving review as the primary full-CI authorization and future merge
   gate, with `full-ci` retained only as an interim/diagnostic fallback;
4. future branch protection requiring approval, stale-approval handling,
   `PR CI`, and approval-triggered `CI OK` on the current head;
5. RPM portability only for verifier changes, approval/full fallback, `main`,
   manual full, and release/dry-run;
6. full tests, checks, all five package builds, Debian smoke, and RPM
   portability on both `main` and release;
7. no whole-script deletion in the topology phase, with `scan-secrets.sh` as
   a separately proven simplification candidate;
8. one-day retention plus scoped deletion after the final consumer, with a
   verified dry-run asset set retained only until promotion or expiry;
9. explicit, provenance-checked promotion of a successful dry run's five
   artifacts as the preferred manual release path, with full rebuild when
   promotion is unavailable;
10. a normal release-preparation PR once `main` is protected, followed by
    full CI and a dry run of the merged commit before tagging.

On approval, resume at **Phase 2**. Re-read this file and the current branch
status first. Synchronize with `main` so the 1.2.0 release fixes are present;
then implement only the planner/topology phase, verify it, commit it logically,
and update this handoff before stopping. The local `gh` token's annotation 403
is a separate diagnostic and does not block run-status collection. No
workflow implementation is authorized by this design update.
