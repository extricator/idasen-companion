# CI workflow redesign — temporary design and handoff

> **Temporary cross-conversation artifact.** This file exists only while the
> CI redesign is being reviewed and implemented. Remove it before merge, after
> moving any lasting operator guidance into maintained documentation.

Status: **design complete; implementation not approved or started**

Branch: `ci-workflow-rebuild`

Baseline: `eb829e2` (`main` when this phase began)

Last updated: 2026-09-24

## Goal and constraints

Replace the current seven-workflow layout with a smaller orchestration model
that gives every commit one dependable `CI OK` conclusion, makes expensive
package work intentional, and still proves packaging changes before merge.
The release path must continue to rebuild and verify all five deliverables:
desktop and headless RPMs, desktop and headless Debian packages, and the
Flatpak bundle.

The repository is private and its current plan has no branch protection, so
the design must be useful as a visible maintainer signal today without
pretending it is an enforced merge policy. It must also be safe to name only
`CI OK` as a required check if branch protection becomes available later.

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
true`, assembles and verifies exactly five assets, and publishes them. The
release design deliberately rebuilds at the release ref and is sound.

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

Implementation must update these tests when job boundaries move while
preserving what they prove. Tests should assert behavior or ordering, not old
filenames that no longer own the behavior.

### Timing evidence

The supplied latest full-run observation is approximately 14 minutes, with
RPM portability alone taking about 8m34s and therefore determining the
critical path. An attempt to retrieve recent runs and per-job durations with
`gh` could not authenticate: `GH_TOKEN` is invalid and there is no stored
GitHub CLI login. Because this is a private repository, no anonymous fallback
exists. Before choosing final timeout values in implementation, capture at
least the latest five representative successful CI runs once `gh` access is
available; do not infer percentiles from the single observation above.

## Proposed architecture

Use four workflow files:

1. `ci.yml` — the only PR and `main` orchestrator, plus manual CI dispatch;
2. `verify.yml` — reusable Python tests and grouped quality checks;
3. `packages.yml` — reusable, input-driven package builds and package-level
   smoke/portability verification, with no changed-path logic;
4. `release.yml` — release gate, calls full verification and all packages,
   assembles exactly five assets, and publishes.

The three internal workflows must expose only `workflow_call`, not
`workflow_dispatch`. This removes them from the top-level Actions menu and
keeps manual policy in `ci.yml`. Names should read as a hierarchy in the UI:

- `Tests / Python 3.11` … `Tests / Python 3.14`;
- `Quality / Code`;
- `Quality / Distribution and supply chain`;
- `Packages / RPM`;
- `Packages / Debian`;
- `Packages / Flatpak`;
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
and [workflow syntax and token permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

### Central planner and changed paths

`ci.yml` gets one small `plan` job with a full checkout. It emits booleans for
`rpm`, `deb`, `flatpak`, and `rpm_portability`, plus a human-readable summary.
Do not add a path-filtering action or a new repository script: this logic is
specific to GitHub event payloads and has one caller, so a reviewed shell step
in the orchestrator is the simplest ownership boundary.

Diff ranges are event-aware:

- PR `synchronize`: compare `before..after`, meaning only the newly pushed
  update selects automatic package work;
- PR `opened`, `reopened`, or `ready_for_review`: compare PR base to head,
  because there is no prior checked head for this run;
- PR `labeled` with `full-ci`: ignore paths and select every package proof;
- push to `main`: ignore paths and select every package proof;
- manual full run: ignore paths and select every package proof.

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
  do not automatically rebuild three distribution formats. Maintainers use
  `full-ci` on the final head when a source change needs package integration
  proof.

The exact path table must be covered by focused unit tests. Put the classifier
data in a form the tests can read directly; avoid tests that merely duplicate
the same regex in Python.

### Event and job policy

| Event/state | Python 3.11–3.14 | Quality/static | RPM | Debian + smoke | Flatpak | RPM portability |
|---|---:|---:|---:|---:|---:|---:|
| Draft PR update | yes | yes | no | no | no | no |
| Ready PR, ordinary update | yes | yes | only if this update selects it | only if this update selects it | only if this update selects it | only if verifier changed |
| PR becomes ready | yes | yes | if full PR diff selects it | if full PR diff selects it | if full PR diff selects it | if verifier changed |
| `full-ci` label applied | yes | yes | yes | yes | yes | yes |
| Manual `core` | yes | yes | no | no | no | no |
| Manual `full` | yes | yes | yes | yes | yes | yes |
| Push to `main` | yes | yes | yes | yes | yes | yes |
| Release/dry run | yes | yes | yes | yes | yes | yes |

Draft PRs still get useful, inexpensive feedback. Automatic package work is
suppressed until `ready_for_review`; that event evaluates the complete PR diff
so a packaging change made while draft is not lost.

Debian smoke remains coupled to every Debian build because it is the only
proof of the installed systemd user unit and archive PySide resolution. RPM
metadata checks remain coupled to every RPM build and must run before upload.
The roughly 8.5-minute RPM portability proof runs only when its own code
changes, when explicitly requested with `full-ci`, on `main`, and during every
release/dry run.

### Expensive-job gate decision

| Gate | Strengths | Weaknesses | Decision |
|---|---|---|---|
| Changed paths | Automatic and format-specific | Cumulative PR diffs rerun forever unless event deltas are used; cannot express final confidence alone | Use update deltas for automatic package-definition validation |
| Draft state | Avoids spending on work explicitly marked unfinished | Not a readiness or trust signal by itself | Suppress package jobs while draft; re-evaluate full diff on ready |
| Review approval | Semantically close to merge readiness | Separate event, approvals can become stale/dismissed, self-approval/team rules vary, and it is awkward without enforced protection | Do not use as an execution gate |
| `full-ci` label | Visible, deliberate, works without branch protection, attached to the PR head event | Persistent label must not cause every later synchronize event to rebuild; re-running needs remove/reapply | Preferred one-shot full PR gate; trigger only on the label event itself |
| Manual dispatch | Good recovery and targeted diagnostics | Easy to forget and not naturally represented as a PR-head policy | Provide `core`, `full`, and individual format modes as an escape hatch |
| Push to `main` | Tests the integrated tree and catches bypasses | Feedback is post-merge | Always run full verification |
| Release/tag | Protects published bytes | Too late to be the only package proof | Always run full verification and rebuild all five assets |

The `full-ci` condition must check the event action and the label applied, not
merely whether the PR currently contains the label. Otherwise the persistent
label recreates the current “every later commit rebuilds everything” defect.
After a new head commit, remove and reapply the label to certify that new head.
The run and its checks are associated with the SHA that was actually tested.

### `CI OK`, skips, and future required checks

Do not put workflow-level `paths` filters on `ci.yml`. Current GitHub
documentation states that when a workflow is skipped by branch/path filtering,
its required check can remain pending. In contrast, a job skipped by an `if`
condition reports success and does not block merging.

`ci.yml` must therefore start on every relevant PR event and every `main`
push. The reusable package workflow is always called, receiving planner
booleans; its unselected format jobs skip normally. Selected jobs have no
second, independent path condition that could accidentally skip them.

`CI OK` uses `if: always()` and depends on the planner, reusable verification,
and reusable packages call. It succeeds only when each required caller result
is `success`; failure, cancellation, or an unexpected skip fails the aggregate.
Expected skips exist only inside the successful package call. This preserves
one stable top-level signal without treating an intentionally unselected
package as a failure. If branch protection later becomes available, require
only the exact `CI OK` name.

### Reliability, security, and cost controls

- **Concurrency:** use `CI-${PR number or ref}` and cancel older PR runs, but
  not `main` runs. Give release runs a separate version/tag group with
  `cancel-in-progress: false`; never cancel a publishing run because another
  trigger arrived.
- **Timeouts:** add an explicit `timeout-minutes` to every job. Set initial
  values only after retrieving recent timings; use observed high-water marks
  plus reasonable setup/network headroom. The known 8m34s portability step
  should not inherit GitHub's multi-hour default.
- **Artifacts:** set explicit short retention for CI package artifacts (start
  with 3 days for PR runs and 7 days for `main`/manual/release diagnostics).
  Published release assets remain attached to the GitHub release. Continue
  using `if-no-files-found: error`.
- **Permissions:** default to `contents: read`; grant `contents: write` only
  on the final release publish job. No package or PR job needs repository
  write access or secrets.
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
- **Release:** both real releases and dry runs call full verification and the
  package workflow with all inputs true before assembly. The existing unique
  filename checks, five-asset verifier, checksums, and publish-only write
  permission remain intact.

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

- Add the central planner and its path/event contract tests.
- Consolidate tests/quality into `verify.yml` and packages into
  input-driven `packages.yml`.
- Combine build and downstream proof per package format.
- Make `ci.yml` the only PR/main/manual CI entry and add stable `CI OK`.
- Remove obsolete reusable workflow files and duplicated classifiers.

Verification: YAML parse/load, focused workflow tests, complete unit suite,
and manual inspection of computed plans for representative event fixtures.

### Phase 3 — release integration and controls

- Make release and dry-run paths call full verification plus all package
  proofs, preserving the five-asset assembly and publish boundary.
- Add measured timeouts, explicit retention, final concurrency rules, and
  least-privilege permissions.
- Audit SHA pins and container-image policy.

Verification: focused release/packaging tests, complete unit suite, action
syntax validation, and a manual release dry run from the branch if the user
authorizes external execution.

### Phase 4 — live evidence and cleanup

- Observe PR runs for ordinary, packaging-specific, `full-ci`, and superseded
  updates; observe one `main` or equivalent full run.
- Compare durations and check-list shape with the baseline; tune timeouts only
  from evidence.
- Decide the optional `scan-secrets.sh` simplification separately.
- Move lasting maintainer instructions to maintained documentation and delete
  this temporary file before merge.

Verification: recorded run URLs/timings, correct selected/skipped jobs, stable
`CI OK`, and a clean repository/reference search after temporary cleanup.

## Approval boundary and next-conversation handoff

No workflow implementation has begun. Approval is requested for these design
choices:

1. four-workflow topology with two grouped quality jobs and one job per package
   format;
2. event-delta automatic package selection, with full-diff fallback and
   full-diff evaluation when a draft becomes ready;
3. one-shot `full-ci` label as the preferred expensive PR gate;
4. RPM portability only for verifier changes, `full-ci`, `main`, manual full,
   and release/dry-run;
5. full tests, checks, all five package builds, Debian smoke, and RPM
   portability on both `main` and release;
6. no whole-script deletion in the topology phase, with `scan-secrets.sh` as
   a separately proven simplification candidate.

On approval, resume at **Phase 2**. Re-read this file and the current branch
status first, then implement only the planner/topology phase, verify it, commit
it logically, and update this handoff before stopping.
