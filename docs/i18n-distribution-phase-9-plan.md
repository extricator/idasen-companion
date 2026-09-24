# Phase 9 — close human-acceptance UX findings

Plan date: 2026-09-24. Status: **Planned**. This phase follows the completed
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

## 2. Finding A — responsive Activity Log filters

### Observed failure

At the default window width, Spanish's longer severity labels—especially
`Depuración` and `Información`—can be clipped in the Activity Log filter row.
Widening the window makes them visible. The current row places the Show label,
channel segmented control, four severity segments, trailing “and above” label
and stretch in one non-wrapping `QHBoxLayout`.

### Required design

- Replace the single crowded toolbar with two stable logical rows:
  - audience: Show + Activity/All;
  - severity: Level + Debug/Info/Warn/Error + “and above”.
- Preserve the current filtering behavior and selected defaults.
- Let Qt mirror both rows naturally in RTL; do not hand-code left/right order.
- Keep every segment's full translated text. Do not solve clipping by shortening
  Spanish, eliding labels, shrinking the font, or increasing the application's
  global minimum width.
- Preserve keyboard navigation, accessible names/descriptions and the visible
  relationship between each label and its segmented control.

### Tests

- Construct the real Activity Log page under English and Spanish at the window
  minimum (760×600) and default (860×660) sizes.
- Assert every filter button's content rectangle can contain its full text in
  normal and selected/DemiBold states.
- Run the same geometry assertions in LTR and RTL directions so the repair does
  not regress Phase 6.
- Retain the existing filter-behavior tests; add a focused test proving both
  rows still drive `_visible()` correctly.

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

Do not fix either finding by raising the minimum window size, deleting
translations, hiding warnings, weakening config validation, or avoiding config
reloads.

The Arabic fallback observation from Phase 8 is not implementation scope here:
no RTL catalog ships. Before the first RTL language is released, its own phase
must translate and test spin-box suffixes, bidirectional isolation, native Qt
input digits versus Babel-rendered digits, control widths and minimum/default
window geometry. The present structural RTL tests remain mandatory in this
phase.

## 5. Implementation order

1. Add failing geometry tests for the Spanish Activity Log at minimum/default
   widths and both layout directions.
2. Recompose the filter toolbar into the two logical rows and make those tests
   pass without changing the global window minimum.
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

- Spanish at 760×600 and 860×660: every Activity Log filter label is visible
  without resizing.
- English and Spanish filtering still behaves correctly.
- One startup dialog lists multiple unknown items once; opening Settings and
  revisiting it produces no duplicate.
- A known setting can be saved and the unknown-data canaries remain intact.
- RTL geometry still mirrors correctly; no claim of Arabic-language readiness
  is made.

## 7. Completion record

- State: Planned
- Starting commit: `8fe1da6`
- Implementation commit: —
- Human-verification commit: —
- Quality-gate results: —
- Remaining findings: —
