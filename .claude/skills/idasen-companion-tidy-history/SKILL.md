---
name: idasen-companion-tidy-history
description: Collapse the unpushed commits on main into the fewest coherent commits, each showing one change, behind a backup and a tree-hash proof that nothing was lost. Use when the user asks to tidy, clean up, squash or condense the git history, or when the release skill's Phase 0 offers it. Do not use to rewrite a commit already on origin/main, to reorder commits, to split one commit into several, or to reword a single message — those are different operations with different risks.
---

# Tidy the unpushed history

Development here lands as many small steps toward a change. That is the right
way to work and the wrong thing to publish: a reader of the history wants the
change, not the path to it. This skill collapses those steps into the fewest
commits that each still show one change on its own.

Read `CLAUDE.md` § "Renaming anything" and § "Commit atomically as you work"
before you start. This file states the mechanics.

## Scope is exactly the unpushed commits

```bash
git rev-list --count origin/main..HEAD
```

That range and no other. Rewriting a commit gives it a new id, so a commit the
remote already holds can only be reconciled by overwriting the remote's copy —
destructive today, and refused outright once the repository is public and
branch protection lands. Defining the scope this way makes that rule
self-enforcing rather than something to remember.

The range the user has in mind is usually "since the last release". On this
repository those normally coincide, because the Release workflow tags the
commit it publishes from. When they do not, the tidy covers only the unpushed
subset, and you say so plainly rather than quietly widening it.

---

## Refuse to start

Stop and tell the user when any of these is true:

- **The working tree is dirty.** `git status --porcelain` prints anything.
- **The branch is not `main`.**
- **The range is empty.** Nothing to do.
- **`origin/main` is not an ancestor of `HEAD`.** Run
  `git merge-base --is-ancestor origin/main HEAD`. A diverged branch means
  someone else has pushed, and this is no longer a private rewrite.
- **The range contains a merge.** Run
  `git rev-list --count --merges origin/main..HEAD`. Everything below assumes a
  linear range, and collapsing across a merge silently drops one side.

---

## Phase A — back up before touching anything

```bash
git branch backup/pre-tidy-YYYY-MM-DD HEAD
git tag backup-pre-tidy-YYYY-MM-DD HEAD
```

Both, deliberately: a branch is what the user reaches for, and a tag survives a
later `git branch -D` typed from memory. Never delete either in the same
session that created them, and never as part of "cleaning up" afterwards.

---

## Phase B — read the commits and propose a grouping

```bash
git log --reverse --format="%n@@ %h %s" --name-only origin/main..HEAD
```

Read all of it. The subjects alone are not enough — which files each commit
touches is what shows where one body of work ends and the next begins.

Group into **contiguous runs**. A run is a stretch of consecutive commits that
together deliver one change, and its boundary is where the touched files stop
overlapping and a new subject thread starts.

**Do not reorder to make a group purer.** A feature that landed in two batches
straddling another feature — as the appearance-portal reader once did around
the control-style work — folds into whichever neighbour it interleaves with,
and the message names it honestly. Reordering is a genuine rebase with merge
resolution at every step, which is a different operation carrying a different
risk, and it forfeits the tree-hash proof in Phase E.

Then **ask the user how coarse to go**, offering two or three granularities and
showing the resulting subject lines for each. This is a judgement call about
what counts as one change, and it is theirs. Two things to put in front of them:

- A coarser history is easier to read and harder to bisect. A commit of several
  thousand lines is where `git bisect` will stop being useful if a regression
  in it surfaces later.
- Bookkeeping commits — the `docs(todo)` entries that only churn `TODO.md` —
  dissolve into the change they belong to. That is the point, not a loss.

Never pick the granularity alone.

---

## Phase C — write the messages

One message per group, written to its own file under the scratchpad directory
and committed with `-F`. Multi-paragraph messages through `-m` and shell
quoting is how a stray backtick ends up executed.

Write an **actual commit message**, not a digest of what was folded in. State
what changed and why it had to; the reasoning is already there in the bodies of
the commits being collapsed, so read them rather than paraphrasing subjects.
Match the voice of the existing history.

Two rules that fail silently if broken:

- **Carry any `!` or `BREAKING CHANGE` marker onto the squashed message.** The
  release skill computes the version bump by classifying subject lines. A
  marker lost in a squash numbers a breaking release as a patch, and nothing
  downstream catches it — the version tests compare the manifests against
  `__version__`, never against what the commits said.
- **Never add a `Co-Authored-By: Claude` trailer.**

---

## Phase D — collapse

```bash
set -euo pipefail
LAST=(<sha of each group's last commit, in order>)
prev=$(git rev-parse origin/main)
for i in "${!LAST[@]}"; do
  L=${LAST[$i]}
  D=$(git show -s --format=%aI "$L")
  git reset --hard -q "$L"
  git reset --soft -q "$prev"
  GIT_AUTHOR_DATE="$D" GIT_COMMITTER_DATE="$D" git commit -q -F "$MSGDIR/$((i+1)).txt"
  prev=$(git rev-parse HEAD)
done
```

Each pass moves the branch to the group's last commit, moves it back to the
previous new commit while keeping that tree in the index, and commits. The new
commit's tree is therefore **literally the tree of a real commit from the old
history**, so no merge resolution happens anywhere and nothing can drift. Dates
come from the last commit of each group, which keeps the log in chronological
order.

Do not use `git rebase -i` for this. Interactive flags are unavailable in this
environment, and a rebase would replay every commit and resolve conflicts at
each step — more work, more risk, and it gives up the proof below.

A secret-scanning hook runs on every commit. Expect it to fire its canary and
then pass; that is the hook proving it works, not a finding.

---

## Phase E — verify

```bash
[ "$(git rev-parse HEAD^{tree})" = "$(git rev-parse backup/pre-tidy-YYYY-MM-DD^{tree})" ]
git status --porcelain
git merge-base --is-ancestor origin/main HEAD
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

**The tree comparison is the whole proof.** Identical tree hashes mean every
line of every collapsed commit is present, which no amount of reading diffs
would establish as firmly. If they differ, stop and restore from the backup —
do not try to patch the difference.

The suite is a check on the tip only. The collapsed commits in between have
never been built, and nothing here claims otherwise.

Gate on exit codes, never on log text. This project has a documented trap where
a coverage message prints a failure word and then exits 0.

---

## Phase F — report

Give the user the new log with per-commit diffstats, state that the tree hash
matches the backup, and name both backup refs with the command that restores
them:

```bash
git reset --hard backup/pre-tidy-YYYY-MM-DD
```

Do not push. Pushing is the release skill's job, or the user's.

---

## Traps

**Local tags go stale.** The Release workflow creates tags on GitHub and
nothing fetches them back, so `git describe --tags` can name a release older
than the newest one. Run `git fetch --tags origin` before you reason about
where the last release sits.

**Never `git add -f` anything under `.planning/`.** That directory and
`CLAUDE.md` are gitignored on purpose, and a whole phase existed to take them
out of tracked history.
