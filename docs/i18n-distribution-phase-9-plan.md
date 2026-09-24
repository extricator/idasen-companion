# Phase 9 — close human-acceptance UX findings

Plan date: 2026-09-24. Status: **Complete**. This phase follows the completed
human-acceptance pass recorded in
[`i18n-distribution-implementation-plan.md`](i18n-distribution-implementation-plan.md#13-phase-8--human-acceptance-without-installation).
It fixes the two current-scope UX findings discovered there without reopening
the completed localization/distribution architecture.

## 1. Outcome

After this phase:

1. The Activity Log's channel and severity filters remain fully readable at
   the minimum and default window widths in every shipped language.
2. Unknown configuration data produces one consolidated warning per distinct
   warning set in a GUI session, rather than one modal per preloaded page plus
   another on navigation.
3. Unknown keys, sections, comments, values and ordering continue to survive a
   known-setting edit exactly as they do now.

This is a focused polish phase. It does not add Arabic, change the stable
English/metres journal policy, alter config validity rules, or redesign the
settings pages.

## 2. Finding A — layout-driven Activity Log minimum width

### Observed failure

At the default window width, Spanish's longer severity labels—especially
`Depuración` and `Información`—can be clipped in the Activity Log filter row.
Widening the window makes them visible. The current row places the Show label,
channel segmented control, four severity segments, trailing “and above” label
and stretch in one non-wrapping `QHBoxLayout`.

### Required design

- Preserve the present single-row toolbar, including the Show label,
  Activity/All audience segments, four minimum-severity segments and trailing
  “and above” label. Do not turn it into two permanent rows or replace either
  segmented control with a different interaction.
- Stop the top-level window's explicit 760 px minimum width from overriding
  Qt's layout-derived minimum. The effective minimum must be the larger of:
  - the existing 760×600 usability floor; and
  - the complete window layout's current `minimumSizeHint()`, calculated from
    the active translations, font, style and sidebar width.
- Express that rule through Qt's size-hint/layout machinery. Do not maintain a
  table of pixel widths by language and do not guess a new global width such as
  800 or 820 px.
- Keep the 860×660 initial window size when it is no smaller than the effective
  minimum; if the layout genuinely requires more, the initial window must honor
  that minimum rather than open with clipped controls.
- Preserve the current filtering behavior and selected defaults.
- Let Qt mirror the row naturally in RTL; do not hand-code left/right order.
- Keep every segment's full translated text. Do not solve clipping by shortening
  Spanish, eliding labels, shrinking the font or reducing control padding.
- Preserve keyboard navigation, accessible names/descriptions and the visible
  relationship between the labels and segmented controls.

### Tests

- Construct the real main window under English and Spanish and obtain its
  effective minimum through the same layout/size-hint path used in production.
- Assert the English window retains at least the 760×600 usability floor and
  that each language can raise either dimension when its real layout requires
  more space.
- Resize each window to its effective minimum and to the 860×660 default when
  permitted by that minimum.
- Assert every filter button's content rectangle can contain its full text in
  normal and selected/DemiBold states.
- Run the same geometry assertions in LTR and RTL directions so the repair does
  not regress Phase 6.
- Retain the existing filter-behavior tests; add a focused test proving both
  controls still drive `_visible()` correctly.

## 3. Finding B — deduplicate unknown-config dialogs

### Observed failure

With one unknown key and one unknown section, startup displayed three modal
warnings: one from the preloaded Automation page, one from the preloaded
Settings page and one from `gui.main`'s aggregate. Opening Settings displayed
the same warnings a fourth time. Preservation itself passed.

### Required design

- Give warning presentation one GUI-level owner. Settings-form pages may load
  and display config values, but must not independently show unknown-data
  modals.
- At startup, show exactly one aggregate dialog containing every warning in
  source order.
- Track warning fingerprints for the lifetime of the GUI process. Reloading or
  navigating with the same set must not show another dialog.
- If a later reload introduces a genuinely new warning, show one aggregate
  containing the newly introduced warnings. Removing and re-adding the same
  warning in one process must not create a modal loop.
- Keep malformed recognized values on the existing `ConfigError` path; those
  errors are not deduplicated as forward-compatibility warnings.
- Do not suppress daemon journal/Activity Log warning records. This change is
  only about duplicate GUI modals.

### Tests

- Launch the real GUI startup path with multiple warnings and assert one modal
  whose body contains each warning once.
- Construct/preload both settings-class pages and navigate between them; assert
  no additional modal for the same warning fingerprints.
- Add a new unknown key after startup and reload; assert exactly one new
  aggregate, then no repeat on another unchanged reload.
- Retain and extend the round-trip test proving a known edit preserves unknown
  keys, sections, comments, ordering and values.
- Cover English and Spanish warning text.

## 4. Explicit non-solutions and deferred RTL gate

Do not fix either finding by guessing a larger fixed minimum window width,
deleting translations, hiding warnings, weakening config validation, or
avoiding config reloads.

The Arabic fallback observation from Phase 8 is not implementation scope here:
no RTL catalog ships. Before the first RTL language is released, its own phase
must translate and test spin-box suffixes, bidirectional isolation, native Qt
input digits versus Babel-rendered digits, control widths and minimum/default
window geometry. The present structural RTL tests remain mandatory in this
phase.

## 5. Implementation order

1. Add failing geometry tests for the Spanish Activity Log at minimum/default
   widths and both layout directions.
2. Replace the explicit top-level minimum-width override with the approved
   layout-derived minimum plus the existing usability floor. Make the geometry
   tests pass without changing the one-row toolbar.
3. Add failing startup/navigation/reload tests for duplicate warning modals.
4. Centralize warning presentation and fingerprinting at GUI scope; remove
   page-owned unknown-data dialogs.
5. Run the focused suites, then every repository quality gate.
6. Repeat the relevant Phase 8 human checks at the default window size with a
   temporary config and mock desk. The installed version must again be stopped
   and restored around that check so only one responsive tray icon exists.

## 6. Verification gates

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_activity_log_presentation.py tests/test_settings_form.py \
  tests/test_first_run.py tests/test_config.py tests/test_rtl_layout.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_naming_span.py src
uvx mypy --python-executable .venv/bin/python src/
uvx pylint==4.0.6 src/idasen_companion
bash scripts/build-translations.sh
git diff --check
```

Post-implementation human acceptance:

- English and Spanish at each layout-derived effective minimum: every Activity
  Log filter label is visible on the unchanged single toolbar row.
- The initial window remains 860×660 where that satisfies the effective minimum;
  a platform whose translated font/style needs more opens at the larger
  layout-derived size rather than clipping.
- English and Spanish filtering still behaves correctly.
- One startup dialog lists multiple unknown items once; opening Settings and
  revisiting it produces no duplicate.
- A known setting can be saved and the unknown-data canaries remain intact.
- RTL geometry still mirrors correctly; no claim of Arabic-language readiness
  is made.

## 7. Completion record

- State: Complete
- Starting checkpoint: `11c22ff`
- Regression-test commit: `83a2c81`
- Implementation commit: `488466c`
- Human-verification record: this completion record
- Automated verification:
  - focused Phase 9 suite: 152 passed;
  - full suite: 1566 passed, 1 skipped;
  - naming-span check: passed;
  - mypy: no issues in 57 source files;
  - pylint 4.0.6: 10.00/10;
  - translation build and `git diff --check`: passed.
- Human acceptance:
  - temporary root: `/tmp/idasen-companion-phase9-1vbCrQ`;
  - the installed GUI and daemon were stopped before the branch session;
    process checks proved one branch GUI and one mock daemon, never two tray
    instances;
  - the real-xcb window used the desktop's font and style. Spanish's complete
    layout required a 950×600 minimum, so the production default correctly
    opened at 950×660. The unchanged single Activity Log row showed
    `Depuración`, `Información`, `Aviso`, `Error` and `y superior` in full;
  - both Activity Log controls still filtered correctly;
  - startup produced one aggregate for two warnings. Preloading and navigating
    between both settings-class pages produced no duplicate; one later unknown
    section produced one new aggregate, and an unchanged reload produced none;
  - applying a known clock-format edit preserved the unknown option, unknown
    sections, values, canary comment and source ordering;
  - the branch GUI and mock daemon were stopped afterward. Final process proof:
    installed service active, one installed GUI process, no branch process.
- Remaining Phase 9 findings: none. The first-shipped-RTL-language gate in
  section 4 remains deliberately deferred and unchanged.
