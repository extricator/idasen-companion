# Shared `idasen-companion` command

**Status:** Design agreed; implementation not started.
**Source task:** `TODO.md` → “Make `idasen-companion` the single user-facing command”.
**Scope:** Command routing, movement semantics, installed package entry points,
tests, and user documentation. This document is the handoff between work sessions.

## Decision

`idasen-companion` is the only user-facing command in the first published command
interface. There is no compatibility promise for the existing
`idasen-companion-cli` name or the old `--toggle` style flags: the repository is
private, and we are choosing the initial interface now. Remove the alias and do
not reintroduce the flags. Keep `idasen-companiond` as the daemon executable.

| Invocation | Full package | Headless package |
| --- | --- | --- |
| `idasen-companion` | Launch or activate the GUI | Clear usage error, exit 2 |
| `idasen-companion --window` | Launch or activate the GUI with the window shown | Clear usage error, exit 2 |
| `idasen-companion --help` / `--version` | Qt-free help / version, exit 0 | Same |
| `idasen-companion status`, `log`, `toggle`, `sit`, `stand`, `stop`, `preset NAME` | Qt-free CLI | Same CLI |
| Unknown or malformed arguments | Usage error, exit 2, without loading Qt | Same |

`--config PATH` remains an internal/test option for CLI commands; it must not
make a command without a subcommand open the GUI. The no-argument GUI behavior
preserves the desktop file and Flatpak default command. CLI commands must work
without a graphical session or a PySide6 installation.

`toggle`, `sit`, and `stand` are shortcut-friendly movement gestures. Send all
three through `Desk1.GestureMove`, so a repeated identical command during a move
uses the daemon's existing `[ui] tray_repeat_move` behavior (`stop`, `reverse`,
or `off`). A different movement command redirects to its target. `stop` sends
`Desk1.Stop`; `preset NAME` sends `Desk1.MoveToPreset`. The daemon remains the
authority for movement state; the command must not infer a repeat from a
possibly stale client-side `Moving` property. There is one public meaning per
movement command; the plain D-Bus `Toggle`/`Sit`/`Stand` methods may remain for
other clients, but the user-facing command does not use them.

The existing config key `tray_repeat_move` also governs keyboard gestures. Its
name is historical. Renaming the config schema is outside this command-routing
work; document the behavior accurately when updating the user guide.

## Current implementation

- `pyproject.toml` maps `idasen-companion` to `gui.main:main`, which imports
  PySide6 at module import time. It maps `idasen-companion-cli` to `cli:main`.
- `cli.py` already handles the seven subcommands without Qt, but its movement
  commands call the unconditional D-Bus methods.
- `gui/main.py` accepts only `--window` and `--version`; the old movement flags
  are gone. `daemon/service.py` already exposes `GestureMove`.
- The bundled RPM installs the GUI launcher only in the full flavor and a CLI
  launcher in both. Debian installs then deletes `idasen-companion` from the
  headless flavor. The Flatpak uses `idasen-companion` as its default command.
- `tests/test_cli.py`, `tests/test_cli_integration.py`,
  `tests/test_qt_free_imports.py`, and `tests/test_packaging.py` cover pieces of
  the current split and need to be updated as the new interface lands.

## Implementation design

Create a small Qt-free entry module for `idasen-companion`. It owns the
top-level decision: no arguments or `--window` load `gui.main` only when the
GUI package is present; every subcommand and top-level help/version/usage path
stays Qt-free. Import the GUI inside the GUI branch. Parse invalid input before
that import, so a mistyped shortcut cannot start the window. Reuse the CLI
parser/dispatch rather than copying its D-Bus logic or maintaining two lists of
commands. Keep argument errors at exit 2 and daemon/config errors at exit 1.

Route gesture commands by changing the CLI's movement dispatch to call
`GestureMove` with the action string. Keep the existing status/log formatting
and error contract. Adjust the parser's program name and help to show
`idasen-companion`, including the no-argument GUI behavior for full installs.
The headless no-argument error should say that a subcommand is required there.

Update every installed payload, not only `[project.scripts]`: bundled RPM
launcher and `%files` for both flavors, Debian install manifests and trim
assertions, and any Flatpak-facing examples. Remove the obsolete alias from
both flavors. The desktop file can retain `Exec=idasen-companion`.

## Work stages

Each stage can be completed in a separate conversation. Before starting a
stage, read this document, inspect `git status` and recent commits, and check
the handoff below. Mark a stage complete only after its exit criteria pass;
record the commit and any remaining risk in the handoff.

### 1. Route one command

**Status:** Pending.

- Add the Qt-free top-level entry module and point `[project.scripts]` at it.
- Keep the GUI's no-argument and `--window` behavior, including single-instance
  activation, while avoiding any GUI import for CLI/help/error paths.
- Make `toggle`, `sit`, and `stand` call `GestureMove`. Keep the existing alias
  temporarily in packaging until Stage 2 removes it from every payload in one
  coherent change. Do not add legacy movement flags.
- Add focused parser, routing, D-Bus-method, and isolated-import tests. Test a
  real command-shaped shortcut invocation with a fake D-Bus service or client;
  never move the physical desk as part of automated verification.

**Exit:** Command routing and movement tests pass; a fresh CLI subprocess
reports no PySide6 import; repeated gesture behavior is exercised through the
daemon's existing fake-based tests; no-argument GUI routing is tested without
launching the installed desktop application.

### 2. Align full and headless packages

**Status:** Pending. **Depends on:** Stage 1.

- Install `idasen-companion` in both RPM and Debian flavors and remove
  `idasen-companion-cli` from `[project.scripts]` and both package flavors.
  Keep GUI and Qt absent from headless.
- Update package tests so they check installed payloads and actual entry
  targets, including full no-argument routing and headless CLI/help behavior.
- Check the Flatpak command path and its documentation; its default still
  launches the GUI.

**Exit:** Local package/build checks prove that the full flavor has GUI plus
CLI, the headless flavor has CLI without Qt, and both expose the same command
name. No package is installed and no release workflow is started.

### 3. Document and verify the first interface

**Status:** Pending. **Depends on:** Stages 1–2.

- Update `README.md`, `CONTRIBUTING.md`, Flatpak notes, and
  `docs/MANUAL-TESTING.md` to use the single command and explain repeat
  gestures, headless no-argument behavior, and shortcut examples.
- Remove or close the source TODO item when implementation and verification are
  complete. Remove stale `idasen-companion-cli` guidance from active docs.
- Run the local checks required by `CONTRIBUTING.md`: pytest, pylint, naming
  span, and `scripts/build-dist.sh` for packaging changes. Run the isolated
  D-Bus CLI integration test and focused package tests. Record actual commands
  and results below; do not claim an unrun package flavor was verified.
- Commit coherent changes atomically, leave a clean working tree, and prepare
  a PR summary. Do not start a release or release dry run.

**Exit:** Documentation matches the shipped command, all relevant local
checks pass (or a concrete limitation is recorded), commits are reviewable,
and the source TODO is closed.

## Handoff for the next conversation

**Current stage:** 1 — Route one command. Nothing in this plan has been
implemented yet.

**Working branch:** `ft/shared-command`. Keep this work and its stage commits
on that branch; local `main` tracks `origin/main` and should remain untouched.

**Next action:** Inspect the current entry points and tests, then implement
Stage 1. Keep the GUI import behind the no-argument/`--window` branch. Use
`GestureMove` for all three movement gestures.

**Completed work:** Design and stage boundaries recorded here. No code or
package behavior changed.

**Verification evidence:** None yet; this is a planning-only change.

**Constraints:** Do not launch, stop, or install the desktop application or
daemon. Use fakes and throwaway D-Bus sessions. Do not start a release. Preserve
unrelated files and ignored build outputs. GSD's `.planning/` files are not the
tracking source for this work.

**Update after every stage:** Record the stage status, commit SHA, exact check
commands with pass/fail results, open decisions, and the next concrete action
here before ending the conversation. If a stage changes the design, update the
decision and later stages in the same commit as that change.

**Give the maintainer a continuation prompt:** At the end of every work part,
include a copy-ready message they can paste into a new conversation. It must
name the working branch, this document, the current stage or next unfinished
task, and tell the next agent to read the handoff, git status, and recent
commits before acting.
Write the prompt from the handoff as it stands *after* the part; do not point
back to a stage that was just completed. For this initial planning-only part,
the prompt is:

> Continue the shared-command work on `ft/shared-command` from
> `docs/plans/shared-command.md`. Read its handoff, `git status`, and recent
> commits, then complete Stage 1. Update the document with results and give me
> the prompt for the next conversation.
