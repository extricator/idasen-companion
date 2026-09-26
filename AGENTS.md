# Repository agent instructions

## Resuming unfinished work

Treat a brief continuation request, such as "keep working," "continue," "pick up where we left off," or "do the next phase," as a request to resume the most recently active unfinished task. Do not require an exact phrase. Read the current branch and git status, recent commits, and the relevant handoff or task document to find the next step. Carry forward the user's existing constraints and approvals. If several unfinished tasks are equally plausible, ask which one the user means after inspecting the available context. Verify completed work, commit when the task calls for it, update its handoff, and report the result before starting another phase.

## GitHub Actions CI redesign

While this redesign is active, use the open CI redesign PR description and `CONTRIBUTING.md` for its current state. A brief continuation request does not override the approval holds below.

Do not use GSD for this redesign. Preserve unrelated files and ignored build outputs. Do not install, stop, or launch the desktop application or daemon. Keep the repository private. Do not configure required reviews, branch protection, or required checks while the one-contributor approval policy is unresolved. Do not start a remote release dry run or publish a release without the user's explicit authorization.

Before changing GitHub Actions workflows, fetch current GitHub Actions documentation with the `ctx7` CLI: resolve `GitHub Actions` with `npx ctx7@latest library` before using `npx ctx7@latest docs` for the relevant topic.
