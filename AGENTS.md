# Repository agent instructions

## Resuming unfinished work

Treat a brief continuation request, such as "keep working," "continue," "pick up where we left off," or "do the next phase," as a request to resume the most recently active unfinished task. Do not require an exact phrase. Read the current branch and git status, recent commits, and the relevant handoff or task document to find the next step. Carry forward the user's existing constraints and approvals. If several unfinished tasks are equally plausible, ask which one the user means after inspecting the available context. Verify completed work, commit when the task calls for it, update its handoff, and report the result before starting another phase.

## Review test additions before completing work

After each implementation, refactor, or GSD phase, review every new test and every expansion of existing test parameters before reporting completion. Do this automatically without waiting for the user to request cleanup.

- Retain tests that protect distinct supported behavior, boundaries, failures, or regressions. Use the smallest set of cases that covers those risks; parameterization is appropriate when each case protects a distinct behavior.
- Remove temporary research matrices, framework/API probes, duplicate assertions, and tests that only mirror implementation details. Do not retain a Cartesian product of delivery modes, inputs, or environments merely because it helped investigate the change. Keep focused integration coverage when the application depends on that interaction.
- Keep exploratory scripts and one-off type-check proofs under `/tmp` or ignored local evidence, unless they serve a justified ongoing regression check. Record the finding without turning the experiment into permanent suite maintenance.
- Run the appropriate checks after cleanup, update local evidence and handoff documents, and report what was retained or removed with test counts. Distinguish historical verification from checks of the final cleaned tree. Apply this repository rule to GSD work without modifying GSD framework files.

## GitHub Actions CI redesign

While this redesign is active, use the open CI redesign PR description and `CONTRIBUTING.md` for its current state. A brief continuation request does not override the approval holds below.

Do not use GSD for this redesign. Preserve unrelated files and ignored build outputs. Do not install, stop, or launch the desktop application or daemon. Do not start a remote release dry run or publish a release without the user's explicit authorization.

## Public repository policy

The user approved public visibility and the protection policy in `CONTRIBUTING.md`. Use pull requests for changes to `main`, require the GitHub Actions `PR CI` check against current `main`, resolve review conversations, and require zero approving reviews while the repository has one maintainer. Never bypass protections to merge a failing PR. Keep force-push and deletion prevention on `main`, and update/deletion prevention on release tags. Push branches explicitly by name; local backup refs and archived icon versions must not be published.

Before changing GitHub Actions workflows, fetch current GitHub Actions documentation with the `ctx7` CLI: resolve `GitHub Actions` with `npx ctx7@latest library` before using `npx ctx7@latest docs` for the relevant topic.
