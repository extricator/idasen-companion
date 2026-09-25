# Repository agent instructions

## Continuing the GitHub Actions CI redesign

When the user says **"keep working"** in this repository without naming another task, resume the next unfinished phase of the GitHub Actions CI redesign. Read the current git status and the latest handoff in `docs/github-actions-ci-redesign.md` first. Use the document and repository state to determine the next phase, complete the work that is authorized, verify it, make a logical commit, and leave a concise handoff. Report results and any design deviations before moving to another phase.

Do not use GSD for this redesign. Preserve unrelated files and ignored build outputs. Do not install, stop, or launch the desktop application or daemon. Keep the repository private. Do not configure required reviews, branch protection, or required `CI OK` while the one-contributor approval policy is unresolved. Do not start a remote release dry run or publish a release without the user's explicit authorization. "Keep working" alone does not grant those approvals.

Before changing GitHub Actions workflows, fetch current GitHub Actions documentation with the `ctx7` CLI: resolve `GitHub Actions` with `npx ctx7@latest library` before using `npx ctx7@latest docs` for the relevant topic.
