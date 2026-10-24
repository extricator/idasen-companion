# Idasen Companion — TODO

Remaining work only. Delete completed or rejected entries; git history records
past work. Each entry below is one task; detailed scope and completion criteria
are maintained in its corresponding local GSD capture.

Manual verification requires actual observations recorded in
`docs/MANUAL-TESTING.md`; source review and container CI do not establish desktop
or hardware results. Follow `AGENTS.md` and `CONTRIBUTING.md` when selecting work.

## Manual verification

- [ ] **Verify Flatpak portal login autostart** — Verify enable, disable, denial and
      logout/login with a published artifact and an identified desktop/portal backend.
- [ ] **Verify Debian packages on a real desktop** — Check a published .deb on a supported
      Debian/Ubuntu desktop with distro PySide6; record tray, launcher, AppStream and desk
      operation.
- [ ] **Verify RPM and Flatpak presentation and automation** — Verify software-centre
      presentation and a full scheduled cycle for published RPM and Flatpak artifacts.
- [ ] **Verify remaining desktop hardware and policy paths** — Work through selected
      GNOME/KDE-session, pairing, unavailable-desk and policy checks in docs/MANUAL-TESTING.md.

## Features and preferences

- [ ] **In-app Light / Dark / System theme control** — Add a validated setting and Settings
      control that apply the selected scheme and restore desktop following for System.
- [ ] **Add a date-format preference** — Decide supported date choices, then resolve them once
      through the shared renderer for GUI/CLI.
- [ ] **Support native digit glyphs** — Define native-digit behavior for the target locale
      across numbers, countdowns, units, dates and times.
- [ ] **Add proactive BLE warm-up** — Compare a longer linger setting with daemon-owned warm-up
      triggers.
- [ ] **Make non-default presets first-class citizens** — Define named-preset cycle order,
      timing, schedule/statistics semantics and daemon-reported next targets before extending
      config, D-Bus and GUI.
- [ ] **Show ambient tray feedback for warning moving and failed states** — Define
      warning/moving/failure feedback, priorities and clearing.
- [ ] **Decide Activity Log history-range and paging improvements** — Decide useful ranges and
      retrieval/display limits before adding controls or paging.

## Interaction and behavior

- [ ] **Investigate off-centre setup wizard placement** — Reproduce on the current build and fix
      confirmed parent/window-manager placement behavior.
- [ ] **Prevent unintended wheel edits while scrolling settings** — Preserve values in unfocused
      spin/combo/time controls while scrolling the page; keep intentional focused editing.
- [ ] **Define and implement the app's high-contrast response** — Define affected controls/text
      and measurable criteria, then implement live preference handling through shared
      theme/restyling.
- [ ] **Improve the scrollbar appearance** — Reconfirm the current issue before selecting a
      scoped appearance improvement.
- [ ] **Improve pre-move warning timing** — Define a measurable tolerance and
      scheduling/cancellation behavior.
- [ ] **Preserve cycle progress across short service restarts** — Restore validated recent
      progress and its original target only for applicable boot/session, desk, configuration and
      position.
- [ ] **Extend idle detection to other Wayland compositors** — Evaluate other-Wayland support,
      revalidating protocol/bindings and bundled-runtime packaging.
- [ ] **Report remaining active time after a brief interruption** — Carry actual remaining
      active time through relevant idle/session/seat return messages using translated templates
      and shared renderers.
- [ ] **Investigate orphaned BlueZ links on recurrence** — On recurrence, correlate
      daemon/BlueZ/Bleak lifecycles and lock ownership using preserved traces.

## Refactoring and design

- [ ] **Decide the next CLI extensions** — Choose the next CLI scope among config operations,
      JSON status, reconnecting watch, man/completion and terminal-output rules.
- [x] **Reassess stable translation IDs against contextual gettext** — Measure real rewording
      churn against stable-ID migration/maintenance costs.

## Tests

- [ ] **Gate Spanish Activity Log message rendering** — Exercise the compiled Spanish catalog
      and matching formatter across substitutions, plurals, cycle and fallback branches.
- [ ] **Clarify translated-return marker semantics** — Define the marker contract and retain
      bad-sentence detection.

## Repository maintenance

- [ ] **Add EditorConfig formatting conventions** — Encode existing file-type conventions and
      deliberate whitespace exceptions, including Markdown.
- [ ] **Define Git attributes for repository files** — Inventory current formats and define
      deliberate attributes, including artwork and compiled catalogs.
- [ ] **Decide whether to add a task runner** — Assess whether a thin runner helps repeated
      work.

## Supply chain and packaging

- [ ] **Monitor bundled runtime and build dependencies** — Define component inventory,
      review/triage and coordinated pin/metadata updates, including embedded interpreter
      libraries.
- [ ] **Pin hashes for downloaded runtime and build wheels** — Record and enforce hashes for
      intended wheel sets.
- [ ] **Make bundled wheel archives reproducible** — Normalize archive creation while preserving
      member layout and runtime/build-backend contents.
- [ ] **Add aarch64 RPM build and release support** — Verify matching aarch64
      runtime/build-wheel assets and hashes, then add native/emulated execution, variants,
      portability checks, artifact names and release-set support.
- [ ] **Decide scheduled dependency auditing and triage** — Compare actual environments and
      alert coverage, then decide audit scope and finding ownership/triage.
- [ ] **Decide release artifact attestations or signatures** — Define downloader verification
      goals and choose an identity/key model and mechanism.
