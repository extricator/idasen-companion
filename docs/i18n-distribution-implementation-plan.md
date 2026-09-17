# i18n and distribution rebuild implementation plan

Plan date: 2026-09-16. Design authority:
[`i18n-distribution-holistic-review.md`](i18n-distribution-holistic-review.md),
especially its accepted Decisions A-E and target design. This plan lives on
`i18n-distribution-rebuild`, which was created directly from `refactor` at
`30e59a1`. The accepted review was then carried onto the branch without the
withdrawn `presentation-rebuild-plan` prescription.

The implementation is seven sequential, independently testable phases. Each
phase produces one implementation commit and one small handoff commit. A later
phase may not hide a failing earlier phase, rewrite its implementation commit,
or defer a known regression without recording it here.

## 1. Outcome and boundaries

The completed branch must deliver all of the following together:

- Babel is the only formatter for app-owned numbers, percentages, dates,
  times and units in GUI, daemon and CLI code. Qt retains responsibility only
  for native widget behavior, layout direction and Qtbase translations.
- One contextual gettext catalog owns every app message. It supports
  `pgettext`, `npgettext`, real plurals and reader-side Activity Log rendering.
- Language, measurement units and hour cycle remain independent settings.
  Unknown config sections and keys warn, survive rewrites and do not stop the
  daemon, GUI or CLI; malformed recognized values still fail validation.
- `idasen-companion-cli` is a useful Qt-free front end with `status`, `sit`,
  `stand`, `toggle`, `stop`, `preset` and `log` commands.
- GitHub Releases contain standalone full and headless RPM and Debian
  artifacts. Full and headless native variants conflict and cannot be
  installed together. Flatpak stays full-only.
- The GUI has no known physical-LTR assumptions at the accepted review's
  enumerated boundaries. This is structural RTL readiness, not a claim that
  an Arabic or Hebrew translation ships.
- The temporary dual-backend, dual-catalog and migration machinery is gone.
  The final architecture matches the compact target in review section 10.

This plan does not add live language switching, a new public package channel,
install-time RPM/DEB subpackage graphs, `--json`, `--watch`, an RTL catalog or
a schema-version system. Journald remains stable English. Partial gettext
catalogs continue to fall back to English.

## 2. Execution and handoff protocol

Each phase is intentionally sized for a separate conversation. Start every
phase with this sequence:

1. Switch to `i18n-distribution-rebuild` and confirm a clean tracked worktree.
   Do not remove or absorb unrelated untracked files.
2. Read this plan, the accepted review, the current phase's execution record,
   and the immediately preceding phase's handoff.
3. Run `git log -5 --oneline` and verify that the preceding handoff commit is
   at `HEAD`. For Phase 1, verify that the plan commit is at `HEAD`.
4. Run the phase's preflight tests before editing. If the baseline is red,
   record the exact failure and stop instead of building on an unknown state.
5. Change only the current phase's scope. Preserve compatibility shims and
   obsolete files until Phase 7 unless the plan explicitly says otherwise.
6. Run targeted tests, then the phase gate. Update the execution record below
   with commands and results before committing.
7. Create the named implementation commit. It must contain the phase's code,
   tests, generated artifacts and user-facing documentation together.
8. Update the ledger and handoff with the implementation commit hash, remaining
   risks and the exact starting conditions for the next phase. Commit only
   that documentation as `docs(plan): hand off phase N to phase N+1`.

Never claim a phase complete from targeted tests alone. If a test is skipped
because its tool or build environment is unavailable, leave the phase
`Blocked` or `In progress`, list the missing verification, and do not create
the handoff commit.

### Status ledger

| Phase | State | Implementation commit | Handoff commit | Required proof |
|---:|---|---|---|---|
| 1. Babel formatting | Complete | `6dd6d30` | this commit | Babel locale matrix, formatter/GUI parity, full tests |
| 2. Contextual gettext | Complete | `912f1eb` | this commit | extraction freshness, catalog audit, mixed-version log tests, full tests |
| 3. Config compatibility | Complete | `f9860da` | this commit | unknown-key round trips, visible warnings, strict known-key tests, full tests |
| 4. CLI | In progress | pending | — | Qt-free import, command contract, isolated D-Bus smoke, full tests |
| 5. Artifact variants | Pending | — | — | full/headless RPM and DEB builds and smoke tests, Flatpak gate |
| 6. RTL readiness | Pending | — | — | offscreen LTR/RTL geometry and Arabic formatting tests, full tests |
| 7. Obsolete removal | Pending | — | — | no obsolete imports/files, complete quality and artifact gates |

Allowed states are `Pending`, `In progress`, `Blocked` and `Complete`. A phase
becomes `Complete` only in its handoff commit.

### Common quality gates

Use the repository virtual environment for deterministic local commands:

```text
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_naming_span.py src
uvx mypy --python-executable .venv/bin/python src/
uvx pylint==4.0.6 src/idasen_companion
```

The full pytest suite and naming-span check are required in every phase. Run
mypy and pylint in every phase that changes Python. The phase record must show
their exit status. Phase-specific build commands appear below. A command is a
gate only when it exits zero; printed words such as “PASS” do not override a
non-zero exit.

The Context7 catalog did not expose the official Python Babel project during
planning: searches for Babel and python-babel returned Quart-Babel, and a
direct `/python-babel/babel` lookup reported that the library was not found.
The intended project is **Babel** at
<https://github.com/python-babel/babel>. Before implementing Phase 1, consult
Babel's official documentation for the version selected in `pyproject.toml`,
and record the URL/version in the Phase 1 execution record. Do not infer
numbering-system or hour-cycle behavior from a similarly named framework
extension.

## 3. Cross-phase invariants

These are gates for every implementation commit, not cleanup wishes for the
last phase:

1. `idasen_companion.daemon.main`, the shared presentation path and, after
   Phase 4, `idasen_companion.cli` import and run with no `PySide6` or
   `shiboken6` module loaded.
2. D-Bus interface names, signatures, message ids, JSON parameter names and
   units remain compatible. The `automation.snoozed` reader accepts both
   `minutes` and `duration` until an explicit versioned wire migration exists.
3. Journald duration text retains the released English precision and shape.
   Compact localized duration text belongs to Activity Log, notifications and
   CLI output, not journal compatibility output.
4. Every user-visible quantity passes through the shared Babel-backed locale
   object. Python f-strings may not render a localized number or percent.
5. App message lookup always uses the selected app language. Unit and
   12/24-hour fallback resolution always uses the separately defined system
   measurement and time locale inputs.
6. Translatable sentences are whole messages. Semantic contexts are literal
   at extraction sites; plurals use catalog plural APIs; placeholder names and
   types match between source and translation.
7. English fallback works with no compiled catalog. A partial catalog never
   prevents startup or a command from completing.
8. Full artifacts contain GUI, CLI and daemon. Headless artifacts contain CLI
   and daemon, contain no GUI entry point or desktop assets, and require or
   vendor no Qt/PySide/shiboken payload.
9. Generated catalogs and packaging lock data are committed in the same phase
   as the source change that generated them.
10. Existing unrelated behavior from `refactor` remains in place unless the
    accepted review explicitly replaces it.

## 4. Phase dependency map

| Phase | Depends on | Why it must precede the next phase |
|---:|---|---|
| 1 | accepted review | Gives every process one locale-value engine before messages and CLI move |
| 2 | 1 | Gives GUI/daemon/CLI one message system and fixes stable payload rendering |
| 3 | 2 | Makes the selected language/preferences safe to read and preserve across versions |
| 4 | 1-3 | CLI needs Babel, contextual gettext and forward-compatible config semantics |
| 5 | 4 | Headless artifacts are not useful until the CLI exists and passes the Qt-free gate |
| 6 | 1-2 | RTL geometry depends on the selected locale and on localized Babel output |
| 7 | 1-6 | Old paths are removable only after all consumers and artifacts use replacements |

## 5. Phase 1 — Babel formatting

**Goal:** Make Babel the single engine for app-owned locale values while
preserving the existing message catalogs and public presentation call sites.

**Implementation commit:**
`refactor(i18n): use Babel for application value formatting`

### Read first

- Review Decisions A and D and section 10's target modules.
- `pyproject.toml`, `MANIFEST.in`, `core/clock_format.py`, `core/units.py` and
  every file under `core/presentation/`.
- `gui/locale_backend.py`, `gui/i18n.py`, `gui/context.py`, `gui/util.py`,
  `gui/pages/statistics.py` and the custom painters in `gui/widgets.py`.
- Existing dependency pins and license handling in
  `scripts/fetch-bundled-runtime.sh`, both RPM specs, `debian/control` and
  `packaging/flatpak/`.
- The locale, clock, unit, date, height, duration and divergence tests named
  in review section 5.

### Work

1. Add Babel as a base project dependency and to every existing full-artifact
   build path. Pin its bundled wheel, include its license, add Fedora/Debian
   build/runtime requirements, regenerate Flatpak Python sources, and extend
   packaging tests so omitting Babel cannot silently pass.
2. Add `core/locale_profile.py`. `LocaleProfile` is immutable and constructed
   from an explicit app locale. It owns number, integer, percent, date, time
   and unit operations. It must not mutate Python's process locale or inspect
   Qt. Specify rounding, grouping, significant/fraction digits and hour cycle
   at the call boundary instead of exposing CLDR fields to consumers.
3. Keep `UnitSetting`/`HeightUnit` and `ClockSetting`/resolved hour-cycle
   concepts, but move their locale-data questions behind Babel. Preserve the
   product-specific system-unit rule (`US` and `LR` default to inches; other
   territories, including `GB`, default to centimetres). Replace the frozen
   12-hour territory table with a runtime query derived from the system time
   locale. An explicit `12` or `24` setting always wins.
4. Repoint `PresentationContext` and `Formatter` at `LocaleProfile`. Preserve
   existing facade method signatures during this phase. Compatibility classes
   in `plain_locale.py` and `gui/locale_backend.py` may delegate to
   `LocaleProfile`, but may no longer produce independent answers.
5. Route the Statistics footer, daily-bar painter and every other percentage
   or localized integer through the shared percent/integer operations. Preserve
   height conversion precision and whole-message unit placement.
6. Restrict `QLocale` to widget locale behavior. Set it from the selected app
   locale so adjacent Qt-native controls use the same separators and direction,
   but do not call it to render app labels.
7. Add focused `en_US`, `es_ES` and representative Arabic-locale cases for
   decimals, integers, percentages, dates, 12/24-hour times, meridiem text,
   units and plural categories. Record the actual Babel numbering-system
   behavior in assertions instead of assuming native digits. Add GUI parity
   cases comparing Babel labels with adjacent Qt-native controls where the
   accepted decision requires them to agree.
8. Rewrite architecture/configuration documentation to describe one value
   engine and the exact language/unit/clock inputs. Add a release note for the
   independent preference semantics. Do not rewrite catalog documentation yet.

### Do not do in this phase

- Do not migrate GUI messages from Qt `.ts`/`.qm`.
- Do not delete locale protocols, specs, compatibility adapters, divergence
  tests or frozen catalogs. Repoint or mark them transitional.
- Do not claim that all Arabic locales render native digits. Test and document
  what the selected Babel version actually emits.

### Verification

```text
.venv/bin/python -m pytest -q tests/test_locale_backend.py tests/test_plain_locale.py tests/test_clock_format.py tests/test_units.py tests/test_dates.py tests/test_formatter_heights.py tests/test_formatter_durations.py tests/test_locale_formatting.py tests/test_qt_free_imports.py tests/test_packaging.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_naming_span.py src
uvx mypy --python-executable .venv/bin/python src/
uvx pylint==4.0.6 src/idasen_companion
```

Also regenerate Flatpak dependency data and the bundled-runtime input, then
run their existing deterministic tests/checks. The execution record must name
the official Babel docs and selected version used to settle any API details.

### Phase 1 execution record

- State: Complete
- Starting commit: `85255cc`
- Babel version and official docs: Babel 2.18.0. Context7 searches for both
  `Babel` and `python-babel` returned only the unrelated Quart-Babel project,
  as anticipated above, so API behavior was checked against Babel's official
  [number](https://babel.pocoo.org/en/latest/api/numbers.html),
  [date/time](https://babel.pocoo.org/en/latest/api/dates.html) and
  [unit](https://babel.pocoo.org/en/latest/api/units.html) references; the
  selected release and wheel were verified on
  [PyPI](https://pypi.org/project/Babel/2.18.0/).
- Implementation commit: `6dd6d30`
- Commands/results: preflight `.venv/bin/python -m pytest -q` — 2,038 passed;
  preflight naming — exit 0; preflight mypy — no issues in 66 files; preflight
  pylint — 10.00/10. Post-change targeted formatter/packaging suite — 288
  passed; full pytest — 2,002 passed; naming — exit 0; mypy — no issues in 67
  files; pylint — 10.00/10. `packaging/flatpak/gen-python-deps.py` regenerated
  the six-wheel offline lock including Babel 2.18.0; translation regeneration
  completed with 322 finished Qt entries and refreshed gettext artifacts;
  `scripts/build-dist.sh` built and audited a 229-member, 773,118-byte sdist
  plus the wheel, including both compiled catalogs and `locale_profile.py`.
  After the implementation commit, translation regeneration again found and
  finished all 322 Qt entries, refreshed gettext, and left
  `git diff --exit-code` clean.
- Deviations from plan: Context7 had no official Python Babel entry, so the
  official project documentation was consulted directly. The transitional
  `PlainLocaleFormatter` and `QtLocaleFormatter` names remain as delegating
  adapters, as permitted; both now use `LocaleProfile` and no longer produce
  independent value-formatting answers.
- Known risks carried forward: complete native artifact/container builds
  remain Phase 5 gates. Babel 2.18.0's `ar_EG` data supplies Arabic separators,
  units, date text and day periods but retains Latin digit glyphs; tests pin
  that observed behavior rather than claiming native digits.
- Handoff to Phase 2: GUI `AppContext` and daemon construction instantiate
  `LocaleProfile` directly. The stable-English journal formatter is the only
  production importer of transitional `PlainLocaleFormatter`; no production
  caller imports `QtLocaleFormatter`, although both adapters remain exercised
  by compatibility tests until Phase 7. The migration baseline is 322 finished
  Qt TS/QM source messages and 79 translated gettext POT/PO/MO source messages,
  including three plural entries and three already-contextual entries. Phase 2
  must preserve their user-visible coverage while consolidating them.

## 6. Phase 2 — contextual gettext migration

**Goal:** Move every app-owned message to one contextual gettext catalog while
preserving translations, stable wire behavior, plurals and English fallback.

**Implementation commit:**
`refactor(i18n): migrate app messages to contextual gettext`

### Read first

- Phase 1 handoff and review Decisions B and A.
- `core/i18n.py`, `core/logmsg.py`, `core/presentation/register.py`,
  `core/presentation/words.py`, `gui/i18n.py`, `gui/log_catalog.py` and all GUI
  Python files containing `tr(`, `translate(` or app `QTranslator` calls.
- `scripts/build-translations.sh`, `translations/*.ts`, `po/*.po`, compiled
  catalog paths, `docs/TRANSLATING.md` and catalog-related tests.
- Notification, Activity Log, daemon-error and whole-message tests.

### Work

1. Extend `core/i18n.py` with stable `_`, `pgettext`, `ngettext` and
   `npgettext` functions that delegate to the currently bound stdlib gettext
   catalog. Keep language rebinding visible to existing importers.
2. Change extraction to one Python source scope covering GUI, daemon and core.
   Configure context/plural extraction for literal calls, including
   `pgettext:1c,2` and `npgettext:1c,2,3`. Preserve deterministic POT dates and
   filename-only locations. Discover shipped languages from `.mo`/`.po`
   catalog presence rather than a Spanish-specific test table.
3. Create a repeatable, scope-aware migration tool for this one-time move. It
   must parse the Qt TS XML, preserve translator comments, plural forms and
   placeholders, assign literal semantic contexts, and refuse ambiguous or
   dynamic call sites. Source rewriting must use Python syntax/token locations,
   not `sed` or blind text replacement. Keep the tool through Phase 6 for
   audit/replay; Phase 7 removes it after proving the migration is stable.
4. Convert GUI app calls to contextual gettext. Contexts describe the semantic
   role (`settings.unit-label`, `overview.automation-status`, and similar), not
   incidental Python class names. Preserve whole messages and named
   placeholders. Use `npgettext` for the two Spanish plural defects and every
   other count-dependent sentence.
5. Make `gui/i18n.py` bind gettext and install only Qt's prebuilt `qtbase`
   translator. The app-owned `.qm` remains committed but frozen and inactive
   until Phase 7 so rollback/audit is possible. `available_languages()` must
   follow the gettext catalog, not `gui/translations/`.
6. Collapse the Activity Log's parallel GUI sentence catalog onto the shared
   `Message` definitions and the reader's translator. Preserve the raw JSON
   wire and unknown-id English `text` fallback. Accept both `minutes` and
   `duration` for `automation.snoozed`, and add N/N-1 producer-reader tests.
7. Restore released journald duration precision/shape in the stable English
   journal formatter. Do not force Activity Log's compact localized style onto
   journald.
8. Audit pre/post migration counts, contexts, translator comments,
   placeholders, plural entries and Spanish rendered outputs. A count change
   must be explained as an intentional merge, split or obsolete message; no
   message may disappear only because extraction missed it.
9. Update `docs/TRANSLATING.md` for one app catalog and contextual APIs. Keep
   Qtbase clearly separate. Document literal contexts, plural practice,
   extraction scope, fallback and translator-comment conventions.

### Do not do in this phase

- Do not delete `.ts`, `.qm`, the migration tool or the structural tests that
  still provide migration evidence. Phase 7 owns deletion.
- Do not change D-Bus signatures or replace the raw-parameter Activity Log
  protocol with pre-rendered localized text.
- Do not use opaque message ids as the gettext source key.

### Verification

```text
bash scripts/build-translations.sh
git diff --check
.venv/bin/python -m pytest -q tests/test_catalog_contexts.py tests/test_extraction_scope.py tests/test_gui_language_binding.py tests/test_notification_delay.py tests/test_notification_sentences.py tests/test_log_catalog.py tests/test_log_messages.py tests/test_whole_message_rendering.py tests/test_translation_markers.py tests/test_terminology.py tests/test_qt_free_imports.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_naming_span.py src
uvx mypy --python-executable .venv/bin/python src/
uvx pylint==4.0.6 src/idasen_companion
```

After the implementation commit, rerun `scripts/build-translations.sh` and
require `git diff --exit-code` before writing the handoff commit.

### Phase 2 execution record

- State: Complete
- Starting commit: `0f7e5bb`
- Pre-migration TS/POT/PO message counts: 322 finished Qt TS messages and 79
  translated gettext source messages, including three plural entries, as
  recorded by the Phase 1 handoff.
- Post-migration contextual/plural counts: 402 non-header POT/PO entries, all
  with `msgctxt`, including five plural entries and no empty Spanish
  translations. The apparent net `+1` over 322 + 79 is intentional: the one
  positional `%s · %s` tray key previously covered two distinct roles and was
  split into named `position/status` and `status/countdown` messages. The two
  defective `(s)` Activity Log messages became real singular/plural pairs
  without changing entry count.
- Implementation commit: `912f1eb`
- Commands/results: preflight full pytest — 2,002 passed; preflight naming —
  exit 0; preflight mypy — no issues in 67 files; preflight pylint — 10.00/10.
  Post-change targeted Phase 2 suite — 210 passed; full pytest — 2,000 passed;
  naming — exit 0; mypy — no issues in 67 files; pylint — 10.00/10.
  `scripts/build-translations.sh` extracted, merged and compiled all 402
  contextual entries and was byte-for-byte deterministic on a second run.
  The AST rewrite audit reported zero pending GUI/shared/log rewrites; replay
  from the frozen 322-entry TS plus the pre-migration PO migrated all 402
  translations, and bidirectional `msgcmp` passed. `msgfmt --check`,
  `git diff --check`, placeholder parity, mixed-version snooze payloads,
  Spanish 1/2-device plurals and unknown-id English fallback all passed.
- Deviations from plan: the frozen `.ts`/`.qm` remain committed and inactive
  as required. The transitional `QtTranslator` compatibility class also
  remains until Phase 7, but delegates app lookup to contextual gettext; the
  GUI installs only Qtbase. The legacy collision test was repointed to audit
  the frozen 322-message baseline, universal semantic contexts and placeholder
  parity because cross-catalog collision registration no longer describes the
  runtime architecture.
- Known risks carried forward: the inactive Qt migration artifacts and
  compatibility adapter remain removal work for Phase 7. Native artifact
  inspection remains Phase 5. Phase 3 must surface forward-compatibility
  warnings through GUI, daemon/Activity Log and the future CLI-facing API.
- Handoff to Phase 3: runtime app-message lookup is gettext-only. Direct GUI
  calls use literal `pgettext`; deferred/shared keys use `P_`/`NP_` and
  `GettextTranslator`; Activity Log reader rendering uses the canonical
  `core/logmsg.py` `Message`; `gui/i18n.py` installs only Qtbase. The
  transitional `QtTranslator` name remains solely as a gettext-delegating
  compatibility adapter. Frozen migration artifacts retained for Phase 7 are
  `translations/idasen_companion_es.ts`,
  `src/idasen_companion/gui/translations/idasen_companion_es.qm`, their
  package-data rules, `scripts/migrate-contextual-gettext.py` and the frozen
  baseline audits. Phase 3 starts at this handoff commit with a clean tracked
  worktree. It must surface one deduplicated unknown-config warning through
  daemon journald plus Activity Log and GUI startup/settings feedback, and
  expose the same Qt-free warning result for Phase 4 to print on CLI stderr.

## 7. Phase 3 — config compatibility

**Goal:** Preserve and warn on unknown config data while retaining strict
validation for keys this version understands.

**Implementation commit:**
`fix(config): preserve unknown options across versions`

### Read first

- Phase 2 handoff and review Decision D.
- `core/config.py`, its migrations and every `load_config`/`save_config` caller
  in daemon, GUI and tests.
- Settings apply/reload paths, startup error handling, Activity Log diagnostics
  and `docs/ARCHITECTURE.md`/configuration documentation.

### Work

1. Introduce a typed warning result carried with `AppConfig` (or a small
   loaded-config result that updates all callers atomically). A warning names
   the exact unknown section/key and source path. Warning metadata does not
   participate in config equality or serialization.
2. In known sections, skip and record unknown keys instead of raising. Preserve
   unknown top-level sections likewise. Continue to reject the wrong type or
   invalid value for every recognized key, malformed TOML, invalid schedule
   days and invalid preset heights.
3. Preserve unknown tables, keys, values, comments and ordering when
   `save_config` uses `tomlkit`. Continue explicit migrations for renamed or
   deleted keys; a known rename may not silently become an “unknown” warning.
4. Surface warnings visibly in the front ends that exist in this phase:
   daemon journal/Activity Log and GUI startup/settings feedback. Provide a
   Qt-free warning API that Phase 4 can print on CLI stderr. Deduplicate within
   one load so a single unknown key does not flood repeated reload output.
5. Add tests for unknown known-section keys, nested unknown tables, unknown
   top-level sections, comments and ordering; load → edit a known key → save →
   reload must preserve all unknown material byte-semantically where tomlkit
   permits. Add downgrade-shaped fixtures containing future keys. Assert that
   recognized invalid values still raise `ConfigError` and are never preserved
   as harmless unknowns.
6. Document independent preference fallback and the preserve-and-warn policy.
   State explicitly that there is no schema-version key until an actual
   one-way migration requires it.

### Verification

```text
.venv/bin/python -m pytest -q tests/test_config.py tests/test_config_reload.py tests/test_app_context_formatter.py tests/test_clock_format_wiring.py tests/test_command_errors.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_naming_span.py src
uvx mypy --python-executable .venv/bin/python src/
uvx pylint==4.0.6 src/idasen_companion
```

### Phase 3 execution record

- State: Complete
- Starting commit: `f0f31ff`
- Warning API chosen: immutable `ConfigWarning(source, section, key)` values
  travel on `AppConfig.warnings`, whose dataclass field is excluded from
  equality and serialization. `str(warning)` is the Qt-free stable-English
  diagnostic form for journald and future CLI stderr;
  `format_config_warning()` renders the same structured result through the
  selected gettext catalog for user interfaces. Known-section unknown keys,
  nested future tables, unknown top-level sections and unknown top-level keys
  all use this result. Explicit removed/renamed-key migrations remain separate
  and silent.
- Implementation commit: `f9860da`
- Commands/results: preflight full pytest — 2,000 passed; preflight naming —
  exit 0; preflight mypy — no issues in 67 files; preflight pylint — 10.00/10.
  Post-change phase-targeted suite — 110 passed; expanded config/warning,
  GUI, daemon, catalog and extraction suite — 323 passed; full pytest — 2,011
  passed; naming — exit 0; mypy — no issues in 67 files; pylint — 10.00/10;
  `msgfmt --check` and `git diff --check` — exit 0. Translation regeneration
  extracted, merged and compiled the warning messages successfully.
- Deviations from plan: none. The existing in-place `tomlkit` save path already
  owned lossless syntax preservation, so no parallel parsed-document field was
  added to `AppConfig`; tests prove unknown values, nested tables, comments and
  ordering survive load → known edit → save → reload.
- Known risks carried forward: Phase 4 must print `AppConfig.warnings` on CLI
  stderr after binding the selected language and must keep the core config API
  Qt-free. Native artifact inspection remains Phase 5 work. The inactive Qt
  migration artifacts and compatibility adapter remain Phase 7 removal work.
- Handoff to Phase 4: Phase 3 ends at this handoff commit with a clean tracked
  worktree; translation regeneration after `f9860da` was byte-for-byte clean.
  CLI code must call `load_config()` and use the returned `AppConfig` directly,
  then call `set_language(config.ui.language)` before rendering messages or
  `format_config_warning()` results. Print every `config.warnings` result on
  stderr before command output. Build its Qt-free `Formatter` exactly like
  `Daemon._build_formatter`: `LocaleProfile(resolve_app_locale(...))`,
  `UnitSetting`/`resolve_height_unit`, `ClockSetting`/`resolve_clock_style`,
  and `GettextTranslator`. Do not import `gui.context`, `gui.i18n` or any
  PySide6-backed module. The next preflight baseline is 2,011 tests, 67 mypy
  source files, naming exit 0 and pylint 10.00/10. Phase 4 retains all frozen
  Qt migration artifacts for Phase 7 and does not change packaging variants,
  which remain Phase 5 scope.

## 8. Phase 4 — first-class Qt-free CLI

**Goal:** Ship a read/write terminal front end that proves the shared
presentation stack is useful without Qt.

**Implementation commit:**
`feat(cli): add the Qt-free command-line frontend`

### Read first

- Phase 3 handoff and review Decision C/target CLI.
- Existing one-shot parsing/calls in `gui/main.py`, daemon interfaces in
  `daemon/service.py`, the Qt D-Bus client and D-Bus contract tests.
- `core/logmsg.py`, shared presentation APIs, config loading and daemon-error
  reader translation.
- The accepted status shape in `TODO.md`: Desk / Automation / Today using the
  tray-tooltip wording.

### Work

1. Add `src/idasen_companion/cli.py` and the console script
   `idasen-companion-cli`. It uses `argparse`, `asyncio` and the existing
   `dbus-fast` base dependency. Importing it must not import GUI modules,
   PySide6 or shiboken.
2. Implement subcommands:
   `status`, `sit`, `stand`, `toggle`, `stop`, `preset NAME` and
   `log [--limit N]`. Map them only to existing D-Bus methods/properties:
   Desk1, Automation1, Presets1, Stats1 and Log1. Do not widen the D-Bus API
   merely to make client code shorter.
3. `status` prints labelled `Desk`, `Automation` and `Today` sections. It uses
   shared localized height, position/status, elapsed/remaining duration and
   date/time vocabulary. User-entered preset names remain verbatim.
4. `log` reads `Log1.GetRecent`, applies the optional client-side limit, and
   renders recognized ids through the reader's selected-language catalog with
   the wire's English `text` fallback. It never asks the daemon to translate
   existing entries.
5. Print the Phase 3 config warnings on CLI stderr before command output or
   D-Bus dispatch. Add a CLI acceptance test proving an unknown future key is
   non-fatal, visible and preserved when a known setting is later saved.
6. Define and test exit semantics: `0` success, argparse's `2` for usage, and
   `1` for daemon absence, D-Bus errors, malformed replies or config errors.
   Normal output goes to stdout; localized actionable errors and config
   warnings go to stderr. No traceback is part of the normal error contract.
7. Keep the legacy `idasen-companion --sit`-style GUI flags working during
   this phase, implemented through shared Qt-free command helpers where
   practical. Mark them deprecated in help/docs; Phase 7 removes the duplicate
   parser after release notes and tests prove the standalone replacement.
8. Add unit tests with a fake D-Bus adapter and a fresh-process import gate.
   Add an isolated session-bus smoke test using the mock daemon that exercises
   one read (`status`), one move, `stop`, `log`, clean daemon shutdown and the
   documented error when no owner exists.
9. Update README/manual testing for the new executable and examples. Do not
   advertise headless downloads until Phase 5 builds them.

### Verification

```text
.venv/bin/python -m pytest -q tests/test_qt_free_imports.py tests/test_dbus_contract.py tests/test_command_errors.py tests/test_log_messages.py tests/test_packaging.py tests/test_cli.py
dbus-run-session -- .venv/bin/python -m pytest -q tests/test_cli_integration.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_naming_span.py src
uvx mypy --python-executable .venv/bin/python src/
uvx pylint==4.0.6 src/idasen_companion
```

`tests/test_cli.py` and `tests/test_cli_integration.py` are planned new files;
their absence before this phase is not a preflight failure.

### Phase 4 execution record

- State: In progress
- Starting commit: `8bf2543`
- Final command/exit-code contract: `idasen-companion-cli` requires one of
  `status`, `sit`, `stand`, `toggle`, `stop`, `preset NAME` or
  `log [--limit N]`. Success is 0, argparse usage is 2, and configuration,
  session-bus, daemon, D-Bus reply and malformed-payload failures are 1.
  Command output is stdout; localized config warnings and actionable errors
  are stderr; expected failures include no traceback.
- Implementation commit: pending
- Commands/results, including session-bus smoke: preflight full pytest — 2,011
  passed; preflight naming — exit 0; preflight mypy — no issues in 67 source
  files; preflight pylint — 10.00/10. Post-change targeted Phase 4 suite — 141
  passed; isolated `dbus-run-session` smoke — 1 passed, covering status, sit,
  stop, log, service shutdown and missing owner; full pytest — 2,028 passed,
  1 isolated-bus test skipped by design outside `dbus-run-session`; naming —
  exit 0; mypy — no issues in 69 source files; pylint — 10.00/10. Translation
  extraction/merge/compile completed deterministically with contextual English
  and Spanish CLI entries.
- Deviations from plan: reader-side structured Activity Log rendering moved
  from the Qt-free-in-practice `gui/log_catalog.py` implementation into
  `core/activity_log.py`; the GUI now delegates to it, so the CLI does not
  import a `gui` module or duplicate the catalog. A hidden `--config` path is
  available for isolated testing and development, matching the daemon's test
  setup without expanding the documented command surface.
- Known risks carried forward: Phase 5 must generate and inspect both native
  variants; this phase adds the CLI launcher to the existing full bundled RPM
  but does not yet define headless file/dependency lists or release assets.
- Handoff to Phase 5: List the exact Python modules, scripts, data files,
  service metadata and catalogs required by a headless installation, and prove
  that list contains no GUI/Qt path.

## 9. Phase 5 — standalone full and headless artifact variants

**Goal:** Publish useful full and headless native artifacts from shared inputs,
with Flatpak intentionally remaining full-only.

**Implementation commit:**
`feat(packaging): build full and headless native artifacts`

### Read first

- Phase 4 handoff and review Decision C.
- Both RPM specs and every RPM verification script.
- `debian/control`, `debian/rules`, `debian/install`, service metadata and the
  Debian workflow.
- Flatpak manifest/dependency generator and release/RPM/DEB/Flatpak workflows.
- `scripts/build-dist.sh`, package-data rules and packaging tests.

### Work

1. Define two native product names: `idasen-companion` (full) and
   `idasen-companion-headless` (headless). Each owns its complete standalone
   installation. Both declare a mutual conflict because daemon, CLI, catalogs,
   service metadata and Python modules overlap. Do not create a metapackage or
   install-time core/GUI subpackage graph.
2. Generate both variants from shared version, dependency, catalog, service and
   file-list inputs. A change to Babel/gettext pins or common files must have
   one source of truth. Variant-only lists control GUI entry points, PySide/Qt,
   desktop files, icons and AppStream metadata.
3. Add checked-in `scripts/build-release-variants.sh` and
   `scripts/verify-release-artifacts.sh`. The build script accepts
   `--all --output DIR`, constructs both RPMs and both DEBs in their existing
   Fedora/Debian container environments, builds the Flatpak bundle, and places
   exactly five named artifacts under `DIR`. The verify script installs or
   inspects each flavor in a clean container, runs the full/headless smoke
   contracts below, verifies mutual conflicts and rejects missing, duplicate or
   ambiguous release assets. These scripts are the local commands the CI
   workflows call; workflow YAML must not maintain a second command sequence.
4. Full bundled RPM: daemon + CLI + GUI + bundled Qt. Headless bundled RPM:
   daemon + CLI, no PySide6/shiboken/Qt libraries or GUI assets. Retain the
   distro-integrated full RPM spec used outside the release artifact if its
   existing channel requires it, but do not present it as the headless flavor.
5. Full Debian package: daemon + CLI + GUI with distro PySide dependencies.
   Headless Debian package: daemon + CLI with no PySide dependencies. Both
   install the shared gettext catalog and Babel dependency.
6. Flatpak stays one full GUI artifact. Expose
   `idasen-companion-cli` inside the sandbox when the manifest can do so
   without pretending it is a host-level headless install; document the
   sandbox limitation.
7. Extend CI/release matrices to invoke the checked-in build/verify scripts and
   upload full/headless RPM and
   DEB artifacts plus the existing Flatpak. Release assembly must fail when a
   required flavor is absent or ambiguously named.
8. Add artifact inspection/smoke gates. Headless installation must run daemon
   and CLI import/help/status smoke, assert no GUI console script, and prove no
   PySide6/shiboken/Qt payload or dependency. Full installation must run both
   CLI and GUI import/launch smoke. Both must verify catalogs, service metadata,
   version and declared conflict.
9. Update README installation tables and release documentation only after the
   smoke tests describe artifacts users can actually download.

### Verification

```text
.venv/bin/python -m pytest -q tests/test_packaging.py tests/test_workflow_pins.py tests/test_qt_free_imports.py
bash scripts/build-dist.sh
bash scripts/build-release-variants.sh --all --output dist-release
bash scripts/verify-release-artifacts.sh dist-release
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_naming_span.py src
uvx mypy --python-executable .venv/bin/python src/
uvx pylint==4.0.6 src/idasen_companion
```

The two checked-in scripts are the exact RPM, Debian, Flatpak, release-assembly
and smoke gates; their non-zero exit blocks completion. Record all five artifact
filenames, sizes, dependency inspection and smoke-test output in the execution
record. A green source suite without both RPMs, both DEBs and the Flatpak bundle
is not phase completion.

### Phase 5 execution record

- State: Pending
- Starting commit: —
- Shared variant input/generator: —
- Artifact names and sizes: —
- Implementation commit: —
- Build/inspection/smoke results: —
- Deviations from plan: —
- Known risks carried forward: —
- Handoff to Phase 6: Confirm packaging is green before UI geometry changes,
  and list the full artifact/test command used for offscreen GUI verification.

## 10. Phase 6 — structural RTL readiness

**Goal:** Remove the known physical-LTR assumptions without adding or claiming
an RTL translation.

**Implementation commit:**
`fix(gui): make asymmetric layouts direction-aware`

### Read first

- Phase 5 handoff and review Decision E.
- `gui/i18n.py`, `gui/main_window.py`, `gui/pages/overview.py`,
  `gui/pages/activity_log.py`, `gui/pages/presets.py`, `gui/widgets.py`, theme
  helpers and existing offscreen layout tests.
- Phase 1 Arabic number/percent assertions and Qt-native parity tests.

### Work

1. Set application layout direction explicitly from the selected locale before
   constructing widgets. This must not depend on whether a Qtbase translation
   happened to load.
2. Replace the sidebar divider's physical side with logical leading/trailing
   behavior. Mirror the Move direction icon/caption alignment and preset
   padding through layout direction rather than hardcoded left/right values.
3. Remove the Activity Log chip's unconditional RTL override used only to move
   an icon. Express icon placement logically so true RTL can mirror it.
4. Make joined-segment borders/radii direction-aware. Preserve the existing
   button implementation that maps rectangles with `QStyle.visualRect`.
5. Mirror the custom-painted height rail and daily bars using logical or
   visual-mapped coordinates. Hit targets, labels, fills and markers must use
   the same transform; a picture that mirrors while interaction does not is a
   failure.
6. Add focused offscreen LTR/RTL tests for application direction and every
   enumerated asymmetric control. Test geometry/ordering and painter inputs,
   not fragile full-window pixel snapshots. Retain representative Arabic
   Babel number/percent assertions beside the layout tests.
7. Add the first-real-RTL-catalog release gate to translation/manual-testing
   docs: native-speaker linguistic review and a manual visual pass remain
   required when such a catalog is introduced.

### Do not do in this phase

- Do not add an Arabic/Hebrew catalog, translated language picker entry or
  support claim.
- Do not create a second RTL-only layout implementation.
- Do not restore full-window ordinal snapshots.

### Verification

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_sidebar_width.py tests/test_overview_control_row.py tests/test_picker_shape.py tests/test_locale_formatting.py tests/test_rtl_layout.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python scripts/check_naming_span.py src
uvx mypy --python-executable .venv/bin/python src/
uvx pylint==4.0.6 src/idasen_companion
```

`tests/test_rtl_layout.py` is a planned new file. The execution record must
also name the controls manually inspected offscreen or in a local GUI run.

### Phase 6 execution record

- State: Pending
- Starting commit: —
- Controls covered automatically/manually: —
- Implementation commit: —
- Commands/results: —
- Deviations from plan: —
- Known risks carried forward: —
- Handoff to Phase 7: Enumerate every transitional file, import, test and doc
  rule now safe to remove. Include `rg` commands that prove each replacement
  has a live consumer before deletion.

## 11. Phase 7 — remove obsolete machinery and close the rebuild

**Goal:** Delete the migration scaffolding and converge on the accepted compact
architecture without changing user-visible behavior.

**Implementation commit:**
`refactor(i18n): remove superseded presentation machinery`

### Read first

- Every preceding handoff, especially Phase 6's removal inventory.
- Review sections 4-6 and 10: component/test/doc fate tables and target design.
- Current import graph (`rg`), package data, translation tooling, build scripts
  and all docs that cite `core/presentation`, `.ts`, `.qm`, `QLocale` value
  formatting, divergence or collision registries.

### Work

1. Move the surviving facade/domain behavior into the final modules:
   `core/i18n.py`, `core/locale_profile.py`, `core/presentation.py` and
   `core/display_prefs.py`. Preserve stable public behavior, then update every
   caller in one commit so no compatibility shim remains accidentally live.
2. Delete the superseded presentation package pieces identified by the review:
   empty package export, protocol matrix, number/integer spec ceremony,
   `plain_locale`, `gettext_translator`, wrapper-only `dates`, unused facade
   methods, register prose/collision registry, dead `QtTranslator`, Qt app-value
   backend and the frozen clock territory table. Fold the small daemon-error
   behavior and stable English journal formatter into their final owners.
3. Delete the inactive app `.ts`/`.qm`, GUI app-translation directory/package
   data, Qt extraction branch and the one-time migration tool. Retain Qtbase
   loading. Make `scripts/build-translations.sh` gettext-only and dynamic over
   shipped languages.
4. Remove the duplicate one-shot command parser from `gui/main.py` after
   confirming release notes and CLI docs point users to
   `idasen-companion-cli`. `idasen-companion` becomes GUI-only; the daemon and
   CLI stay independently importable without Qt.
5. Delete or replace the structural/meta test tax named in review section 5:
   dual-catalog overlap/collision checks, divergence surface, protocol/member
   allowlists, AST global-locale policy, full-window ordinal goldens and the
   per-public-method sample inventory. Keep focused output tests, extraction
   freshness, contextual/plural audits, Qt-free fresh-process checks,
   config/CLI/package behavior and RTL geometry tests.
6. Trim semantic goldens to a representative matrix rather than every method
   times every language. Remove temporary baseline files only after direct
   behavior tests cover the accepted English and Spanish outputs they guarded.
7. Rewrite tracked contributor/architecture/translation docs to the final
   topology. Remove citations to gitignored `CLAUDE.md`/`.planning` artifacts
   and stale rules for dual catalogs, backend divergence, unchanged GUI
   forwarders or collision registries. Update TODO/CHANGELOG to close delivered
   items without erasing deferred date-format or first-RTL-language work.
8. Run an unused-code/import sweep and package-content inspection. No deleted
   symbol, `.ts`/`.qm` path, app Qt translator, legacy CLI flag or obsolete
   test helper may remain in source, tests, docs, manifests or workflows.

### Required absence checks

The exact patterns may be refined for legitimate mentions in historical
review documents, which remain as decision records. Outside those records,
the following searches must be empty or contain only the documented Qtbase
exception:

```text
rg -n 'PlainLocaleFormatter|QtLocaleFormatter|QtTranslator|LocaleFormatter|NumberSpec|IntegerSpec|TWELVE_HOUR_TERRITORIES' src tests scripts docs --glob '!docs/i18n-distribution-holistic-review.md' --glob '!docs/i18n-distribution-implementation-plan.md'
rg -n 'idasen_companion_.*\.qm|translations/.*\.ts|lupdate|lrelease' pyproject.toml MANIFEST.in src scripts packaging debian .github docs --glob '!docs/i18n-distribution-holistic-review.md' --glob '!docs/i18n-distribution-implementation-plan.md'
rg -n 'presentation_fakes|presentation_samples|window_(en|es)\.json|catalog_concept_overlap|presentation_divergence_surface|translation_collisions' tests pyproject.toml MANIFEST.in
```

### Final verification

```text
bash scripts/build-translations.sh
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_naming_span.py src
uvx mypy --python-executable .venv/bin/python src/
uvx pylint==4.0.6 src/idasen_companion
bash scripts/build-dist.sh
bash scripts/scan-secrets.sh worktree
```

Also run all four native artifact builds and smoke tests from Phase 5, the
Flatpak build gate, the isolated mock-D-Bus CLI flow, the fresh-process Qt-free
imports, and the offscreen LTR/RTL suite. Inspect the final wheel/sdist and each
native artifact for the intended catalog, entry points and absence/presence of
Qt by flavor.

After creating the Phase 7 implementation commit, rerun
`scripts/build-translations.sh` and require `git diff --exit-code` before
writing the final handoff commit. This post-commit check proves catalog
freshness without treating the phase's intentional pre-commit edits as dirt.

### Phase 7 execution record

- State: Pending
- Starting commit: —
- Removed files/symbols/tests: —
- Replacement behavior tests retained: —
- Implementation commit: —
- Complete quality/build/artifact results: —
- Deviations from accepted design: —
- Remaining release/manual gates: —
- Final handoff: State whether the branch is ready for review, list any
  intentionally deferred work, and give the exact compare range from
  `refactor` to the final handoff commit.

## 12. Final acceptance checklist

The rebuild is ready for review only when every box can be answered with a
test, artifact inspection or explicit manual record:

- [ ] All seven ledger rows are `Complete` with implementation and handoff
      commit hashes.
- [ ] Full pytest, naming, mypy and pylint gates are green at final `HEAD`.
- [ ] Translation regeneration is deterministic and produces only contextual
      gettext POT/PO/MO artifacts.
- [ ] English and Spanish behavior is covered; representative Arabic locale
      value and RTL-geometry tests are green without an Arabic catalog.
- [ ] D-Bus N/N-1 payload compatibility and stable journal output are covered.
- [ ] Unknown config data warns and survives a known-key edit/save/reload;
      recognized invalid data still fails.
- [ ] CLI read/write/log behavior passes both fake-bus and isolated live-bus
      tests and imports with no Qt.
- [ ] Full/headless RPM and DEB variants build, conflict correctly and pass
      content/dependency smoke tests; Flatpak remains intentionally full-only.
- [ ] No app-owned Qt catalog, competing locale backend, divergence matrix,
      collision registry, legacy GUI command parser or superseded structural
      test remains outside the historical review.
- [ ] Architecture, translation, configuration, CLI, installation and release
      documentation describe what the artifacts actually ship.
