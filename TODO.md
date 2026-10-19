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

- [ ] **Add a clear statistics / history button** — Add daemon storage and Stats1 operations
      plus a confirmed GUI action.
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
- [ ] **Show observed time in desk position** — Track observed position timing separately,
      expose knownness/timestamps and age the display locally.
- [ ] **Show ambient tray feedback for warning moving and failed states** — Define
      warning/moving/failure feedback, priorities and clearing.
- [ ] **Decide Activity Log history-range and paging improvements** — Decide useful ranges and
      retrieval/display limits before adding controls or paging.
- [ ] **Add a schedule option for outside-hours statistics** — Define the config key/polarity,
      effect on durations versus transitions and spent-time treatment across
      schedule/config/pending-credit boundaries.

## Interaction and behavior

- [ ] **Investigate off-centre setup wizard placement** — Reproduce on the current build and fix
      confirmed parent/window-manager placement behavior.
- [ ] **Prevent unintended wheel edits while scrolling settings** — Preserve values in unfocused
      spin/combo/time controls while scrolling the page; keep intentional focused editing.
- [ ] **Restyle existing activity log rows on theme changes** — Restyle populated rows on
      palette changes while preserving reader position, bounded batching and the
      unchanged-output shortcut.
- [ ] **Refresh tray tooltip on configuration changes** — Refresh relevant tray text on the
      actual configuration-change/Apply trigger.
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
- [ ] **Refresh presence eligibility before automated movement** — Recheck eligibility after
      intervening waits through an interface that keeps platform monitors out of core.
- [ ] **Extend idle detection to other Wayland compositors** — Evaluate other-Wayland support,
      revalidating protocol/bindings and bundled-runtime packaging.
- [ ] **Report remaining active time after a brief interruption** — Carry actual remaining
      active time through relevant idle/session/seat return messages using translated templates
      and shared renderers.
- [ ] **Investigate orphaned BlueZ links on recurrence** — On recurrence, correlate
      daemon/BlueZ/Bleak lifecycles and lock ownership using preserved traces.

## Refactoring and design

- [ ] **Assess distinct internal height and duration types** — Assess concrete benefits of
      distinct height/duration/timestamp types before broad conversion.
- [ ] **Use DeskState and Status enums at GUI boundaries** — Adopt useful typed state boundaries
      and consumer annotations, accounting for Signal(str).
- [ ] **Define shared decoded D-Bus data contracts** — Define shared decoded structures and
      parsing boundaries without changing transport.
- [ ] **Improve Python type coverage for D-Bus service declarations** — Revalidate
      typed-signature support and supported source/package versions.
- [ ] **Decide the next CLI extensions** — Choose the next CLI scope among config operations,
      JSON status, reconnecting watch, man/completion and terminal-output rules.
- [ ] **Reassess stable translation IDs against contextual gettext** — Measure real rewording
      churn against stable-ID migration/maintenance costs.
- [ ] **Remove unused GUI clock forwarder** — Remove the forwarder and update actual
      test/docstring references while preserving formatting assertions.

## Tests

- [ ] **Split state-machine tests and share helpers** — Split cohesive behavior groups and share
      suitable helpers, coordinating with harness consolidation.
- [ ] **Consolidate shared daemon and GUI test harnesses** — Share genuinely common builders
      with deterministic defaults.
- [ ] **Cover the setup wizard's missing behavior** — Test current ScanPage cached/empty
      discovery, stale hints, selection and verified success/failure, including relevant
      usage/autostart outcomes.
- [ ] **Gate Spanish Activity Log message rendering** — Exercise the compiled Spanish catalog
      and matching formatter across substitutions, plurals, cycle and fallback branches.
- [ ] **Resolve translator receivers in concatenation guard** — Resolve receivers or use another
      independent identification method.
- [ ] **Clarify translated-return marker semantics** — Define the marker contract and retain
      bad-sentence detection.
- [ ] **Pin outside-schedule statistics accounting with a regression test** — Add a real
      state-machine/accounting regression case showing daily credit while OUT_OF_SCHEDULE.

## Repository maintenance

- [ ] **Add EditorConfig formatting conventions** — Encode existing file-type conventions and
      deliberate whitespace exceptions, including Markdown.
- [ ] **Define Git attributes for repository files** — Inventory current formats and define
      deliberate attributes, including artwork and compiled catalogs.
- [ ] **Add per-file SPDX license headers** — Inventory scope and add consistent identifiers
      while preserving shebangs/encoding declarations.
- [ ] **Provide an example configuration file** — Add a commented minimal or comprehensive
      example matching the schema, with harmless values and a documentation link.
- [ ] **Decide whether to add a task runner** — Assess whether a thin runner helps repeated
      work.
- [ ] **Refresh development setup and verification instructions** — Align setup and verification
      instructions with current extras, scripts and CI while preserving deliberate GUI
      dependency choices.

## Supply chain and packaging

- [ ] **Review secret scanner coverage and simplification** — Compare callers and simplify only
      with concrete benefit.
- [ ] **Monitor bundled runtime and build dependencies** — Define component inventory,
      review/triage and coordinated pin/metadata updates, including embedded interpreter
      libraries.
- [ ] **Verify interpreter component and licence metadata** — Define a repeatable runtime-bump
      check against exact asset/build metadata and package variants.
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
