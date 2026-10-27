# Secret scanning: coverage, cost and input evidence

Assessed 2026-10-21 against the shared wrapper's pinned Gitleaks **8.30.1**.
**DESIGN JUDGMENT:** retain GitHub scanning and push protection, the staged
hook, CI history/worktree scans and the manual fresh-clone publication audit.
Their inputs and timing differ. The demonstrated improvement is to reject a
clean-looking result when the real scan reports unread or incomplete input.

Claim labels distinguish **DOCUMENTED** official contracts, **LOCALLY PROVED**
bounded experiments/current pinned source, **DESIGN JUDGMENT** the selected
tradeoff, and **UNRESOLVED** limits of the evidence.

| Layer / caller | Input and timing | Operational / maintenance cost | Limit and decision |
| --- | --- | --- | --- |
| GitHub secret scanning | Hosted Git history on all branches and documented GitHub content; detection after upload and rescans for new patterns. | Hosted operation; no local container startup. | Cannot inspect unpushed staged or machine-only ignored files. **Retain.** |
| GitHub push protection | Supported secret patterns during a push. | Hosted push-time check and handling of alerts/bypasses. | Supported-pattern, size and timeout limits; does not replace pre-commit detection. **Retain.** |
| `.githooks/pre-commit` → `staged` | Text added to the staged diff, including an unborn repository, before a local commit. | Each invocation pulls/checks the pinned image, starts a version container, a canary container and the real scanner. | Deliberately bypassable hook; binary-only/deletion/rename/empty input can yield zero bytes. **Retain.** |
| `.github/workflows/verify.yml` → `history` | History reachable from fetched local refs; CI explicitly fetches PR heads. | Same startup/canary cost plus history walk, Git counts/ref recording and remote PR-head query. | Absent refs remain outside the walk; missing remote PR heads fail the wrapper. **Retain.** |
| `.github/workflows/verify.yml` → `worktree` | Eligible files on the CI runner, including ignored/untracked files present there. | Same startup/canary cost plus directory traversal. | Cannot inspect developer-only files absent from the runner. **Retain.** |
| Contributor publication audit → `history` + `worktree` + human review | Fresh remote clone with fetched PR heads; separate personal-data, comments, logs and artifacts review. | Explicit operator effort and two wrapper invocations. | Development backup refs deliberately stay unpublished; credentials and personal data require different reviews. **Retain existing procedure.** |

The hosted rows are **DOCUMENTED** by [GitHub secret scanning](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning),
[push protection](https://docs.github.com/en/code-security/concepts/secret-security/push-protection),
[detection scope](https://docs.github.com/en/code-security/reference/secret-security/secret-scanning-scope)
and [supported patterns](https://docs.github.com/en/code-security/reference/secret-security/supported-secret-scanning-patterns).
The caller rows are **LOCALLY PROVED** from the unchanged hook, reusable
verification workflow, shared wrapper and [publication procedure](../CONTRIBUTING.md#repository-protections-and-publication).
Ordinary CI and non-promotion release verification use the reusable workflow;
promotion reuses previously verified artifacts. No caller or policy changed.

**LOCALLY PROVED, read-only observation on 2026-10-21:** this repository is public;
GitHub secret scanning and repository push protection are enabled; non-provider
patterns and validity checks are disabled. This records observed settings and
does not recommend changing them. Hosted configuration is time-dependent.
Using the same local pinned rules across callers establishes neither identical
input scope nor equivalence with GitHub's hosted rules.

## Measured benefit and cost

**LOCALLY PROVED:** cached-image micro-fixture scanner calls took approximately
**0.13–0.48 seconds**; four original exact-wrapper fixture runs took
**1.37–2.04 seconds**, including cached pull/version/canary/evidence work.
These are small synthetic fixtures, not repository throughput or CI latency.
History additionally performs the recorded Git/ref/network checks. No measured
benefit justified removing Docker/Podman fallback, ANSI normalization, canaries
or evidence output. A replacement scanner or ruleset change was unnecessary.

| Pinned synthetic fixture | Observed scanner behavior | Wrapper decision |
| --- | --- | --- |
| Staged clean text addition | Positive bytes, zero findings, exit zero. | Accept valid receipt/report/status. |
| Empty staged index, deletion-only, pure rename, empty-file or binary-only change | Legitimate zero bytes, zero findings, exit zero. | Accept a valid zero receipt after independent Git metadata establishes no text additions. |
| Staged failing text converter | Error diagnostics, zero bytes, empty report, exit zero; original wrapper passed. | Reject real-run diagnostics, independently of other evidence. |
| Partial history after two of three commits | Positive bytes and two commits, errors, empty report, exit zero; original wrapper passed its count heuristic. | Reject errors even when counts look plausible. |
| Unreadable worktree file | Permission warning, empty report, exit zero. | Reject unread-input warning even if other project files produce positive bytes. |
| Removed synthetic credential | History detects it; current worktree does not. | Preserve history's distinct scope. |
| Ignored synthetic credential | Directory scan detects it; staged scan does not. | Preserve worktree's distinct scope. |

All credential-shaped values were derived at runtime in disposable repositories.
Raw logs/reports remain private temporary evidence; only redacted counts,
statuses, timings and hashes enter the assessment/provenance. No real credential,
development `--all` backup history, live ignored user data or GitHub push was
tested. Research evidence lives under `/tmp/idasen-phase37-evidence`; fresh
cleaned-tree receipts live under `/tmp/idasen-phase37-final-evidence` locally.

## Narrow implementation decision

**LOCALLY PROVED:** pinned source [Git input](https://github.com/gitleaks/gitleaks/blob/v8.30.1/sources/git.go)
and [file input](https://github.com/gitleaks/gitleaks/blob/v8.30.1/sources/files.go)
can log errors or permission skips without a failing process status. The
[summary source](https://github.com/gitleaks/gitleaks/blob/v8.30.1/cmd/root.go)
prints a decimal `scanned ~N bytes` counter followed by humanized units;
zero's parenthesized value is unitless. A canary proves detection in its own
fixture, not successful reading of the actual requested input.

The shared wrapper now checks normalized real-run error/unread/partial-scan
diagnostics, one structurally valid pinned byte receipt, a JSON-array report,
findings and process status. Ordinary warning summaries remain valid.
For staged input, a separately successful
`git diff --staged --numstat -z --no-ext-diff --no-textconv -- .` supplies
strict decimal/binary counts and complete NUL-delimited ordinary/rename/copy
path records. Command or metadata failure is never treated as an empty diff.
[Git documents the NUL record format](https://git-scm.com/docs/git-diff).
Positive text additions require positive scanned bytes; the legitimate
zero-text categories above do not. Approximate scanner bytes are never
compared with exact file sizes.

Worktree mode uses a bounded **project invariant**: the scanned repository
contains its own regular, nonempty `scripts/scan-secrets.sh`, which the pinned
defaults do not exclude. It therefore requires positive bytes. This is not a
general empty-directory policy or proof that every eligible file was read.
History retains its count/ref/remote-PR safeguards and adds the same real-run
diagnostic/receipt checks. Runtime pin, fallback, isolated mode canaries,
reports, raw logs, cleanup and caller-facing exit behavior remain intact.

## Limits and re-evaluation

**LOCALLY PROVED limitation:** the unchanged history factor-of-two check can
conservatively false-fail a legitimate history dominated by empty or deletion
commits. A five-revision fixture yielded one scanned fragment-producing commit.
Scanner commit counts are not exact Git revision counts. Keep the current
safeguard until a separately justified replacement exists.

### Measured history-count follow-up

**LOCALLY PROVED, 2026-10-21:** four fresh synthetic histories scanned directly
with pinned Gitleaks 8.30.1 produced the following counts. Ratio decisions
evaluate the current factor-of-two arithmetic; these were not new full-wrapper
runs. Each scanner run exited zero with positive bytes, no error diagnostics
and an empty findings array.

| Synthetic history | Git revisions | Scanner commits | Positive raw numstat file records | Current ratio |
| --- | ---: | ---: | ---: | --- |
| One addition, file deletion, three empty commits | 5 | 1 | 1 | Rejects |
| Initial text, two line deletions in a surviving file | 3 | 3 | 1 | Accepts |
| Three raw revisions collapsed by textconv | 3 | 1 | 4 across three commits | Rejects |
| Three ordinary additions | 3 | 3 | 3 | Accepts |

**DOCUMENTED:** Git's [textconv/patch behavior](https://git-scm.com/docs/gitattributes#_performing_text_diffs_of_binary_files)
can lose raw-file information, and [merge-log behavior](https://git-scm.com/docs/git-log#_diff_formatting)
normally omits merge patches unless a merge-diff mode is selected, with a
first-parent exception. **LOCALLY PROVED:** pinned [sources/git.go](https://github.com/gitleaks/gitleaks/blob/v8.30.1/sources/git.go)
yields eligible patch/archive fragments; [detect/detect.go](https://github.com/gitleaks/gitleaks/blob/v8.30.1/detect/detect.go)
records commit identities when fragments reach the detector. Total revisions,
non-merge revisions and positive raw-addition records therefore do not identify
that fragment-producing commit set. Deletion hunks can count without additions;
textconv can remove hunks despite raw additions. File records are not commits.

**DESIGN JUDGMENT:** retain the current history guard and all diagnostic,
byte-receipt, report, findings, exit-status, ref and remote-scope checks. The
bounded evidence establishes no reliable small counter replacement. An exact
replacement would require scanner-aligned patch/fragment semantics, controlled
input semantics, or an upstream verifiable completion receipt, with additional
implementation and validation cost. No current operational need beyond the
demonstrated synthetic conservative failure justifies that redesign. Revisit
after an actual operational false failure, an upstream verifiable completion
receipt, or an approved scanning-contract redesign. **UNRESOLVED:** stronger
designs remain possible; aggregate counts alone do not prove complete input
consumption.

**UNRESOLVED:** positive byte/count receipts demonstrate some processing, not
per-file completeness. Pinned exclusions still apply, including eligible
binary/archive/symlink and allowlisted-path behavior. No local/hosted ruleset
equivalence, real-repository performance benchmark or credential validity check
was established. Reassess when the scanner pin, rules, callers, hosted settings
or required coverage changes. Final isolated focused/full tests, actual pinned
reproductions, Python 3.11 compilation, copied-tree distribution checks and
test-retention receipts precede independent review/security/canonical closure.
