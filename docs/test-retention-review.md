# Full-suite test-retention review

Reviewed 2026-10-19 against baseline `d5a9d1b`, applying the repository's
test-retention rule. The goal was distinct supported behavior with less redundant
maintenance; no removal quota was used.

## Scope and accounting

The authoritative inventory contains **92 files**: 88 test modules, two shared
Python support files and two vocabulary goldens. The three local review ledgers
contain exactly one specific decision for each of **1,193 baseline test
functions**, plus file-level helper/fixture and parameter-expansion review.
Combined file/function keys match the inventory exactly, without duplicates or
omissions. Current AST definitions match all **1,165 retain decisions** exactly.

| Group | Files | Baseline functions | Retained | Consolidated | Probes removed | Final collected cases | Cases removed |
|---|---:|---:|---:|---:|---:|---:|---:|
| A: core, daemon, transport | 38 | 565 | 560 | 4 | 1 | 739 | 6 |
| B: GUI interaction and style | 21 | 293 | 277 | 14 | 2 | 411 | 18 |
| C: presentation, localization, tooling, support | 33 | 335 | 328 | 6 | 1 | 507 | 11 |
| Total | 92 | 1,193 | 1,165 | 24 | 4 | 1,657 | 35 |

Consolidation deletes a duplicate function in favor of existing guards. Thus
**28 whole functions** were deleted: 24 consolidations and four probes. Those
functions accounted for 33 collected cases. Two reductions to retained parameter
tables removed another two cases. No test functions or parameter expansions were
added. Two duplicate assertion blocks and their explanatory comments were also
removed from retained token tests; unused local helpers/imports were removed
where their only consumers disappeared.

Group baseline case totals (745/429/518) are reconstructed from final collection
and classified deletions. They are not separate baseline reruns. The historical
full-suite result at `d5a9d1b` was **1,691 passed, one skipped, 12 warnings,
88.49% coverage**. This review used its saved coverage export for comparison.

## What changed and why

Every deleted function's recorded guard was checked against retained decisions,
the final AST, actual collection, and its surviving assertion/helper bodies.
All **52 reference occurrences, representing 45 distinct references**, resolve;
parameter-specific references match collected node IDs. No cross-group
last-guard conflict remains. Representative contracts are below; the complete
per-function ledger remains local evidence rather than tracked documentation.

| Cleanup | Rationale and surviving behavior |
|---|---|
| Portal cleanup, notification delay and schedule subsets (A, four functions) | Success/cancel/deadline tests in `test_background_portal.py` each assert disconnect cleanup. `test_the_delay_renders_english_under_the_system_catalog` retains exact 90/3900-second outputs. `test_inside_window` and `test_outside_window_same_day` retain all four Friday minute boundaries. |
| Unchecked typing probe (A, one function) | Calling an annotated nested no-op neither type-checks nor asserts anything. Adapter member/coroutine shape and actual mock failure reporting remain in `test_desk_port.py`. |
| Upstream Fusion diagnostics (B, two functions/three cases) | Standalone tests asserted that Qt still exhibits an upstream corner/icon difference, without requiring an application outcome. Application corner absence, positive single-pixel strokes, exact border tokens and enabled/disabled icon pixels remain in `test_control_style.py`. |
| Private classification and repeated control-border checks (B, four functions) | Seven-font `test_every_control_in_a_row_stands_at_one_height` detects the embedded-editor sizing regression through row geometry. Light/dark `test_resting_controls_in_a_card_carry_the_overlay_*` retains the same checkbox distance and exact spin-border assertions. |
| Picker, disconnected-height and tray subsets (B, ten functions) | Full ordered dropdown labels include `60 min`; exact `+ New preset` after link loss excludes stale heights. Exact SNI title and existing position/status signal integrations retain tray direction, duration, fallback, failure-menu and action assertions. |
| Duplicate token assertions (B, no whole function) | `test_a_resting_face_is_a_surface_and_not_a_panel` retains both surface bounds. `test_hover_and_keyboard_focus_are_told_apart` retains stronger rest/hover/focus separation and ordering through both edge routes. |
| Clock, English-output, AST-reachability and empty-reason subsets (C, six functions/ten cases) | Window/daemon clock tests independently pin the same three expected styles. Dedicated duration tests pin journal precision; the no-config AST boundary remains. Unchanged English vocabulary goldens and focused formatters pin all four English outputs. Transitive function/sibling-method tests assert both directly and indirectly reached names. The complete status branch table includes paused/unknown empty reasons. |
| Bare Qt locale probe (C, one function) | Constructing a bare `QDoubleSpinBox` measured Qt's default-locale behavior alone. Real `apply_language` binding, Settings spin suffixes and Overview unit-change integration remain. |

The two retained-table reductions are specific: appearance value `999` repeated
an invalid positive interior outcome; `negative` (-1), `just-past` (3) and
`largest-uint32` remain. The flat palette's Window-to-Base assignment changed no
input; `light`, `dark`, `solarized` and `default` still exercise that mutation.
Other flat-palette relationship cases remain, including disabled-face collapse.

Meaningful structural and integration checks were retained: motion/persistence
failures, transport boundaries, independent restyle callbacks and lifetimes,
font/geometry/RTL cases, translation false-positive controls, headless process
boundaries, packaging provenance and executable workflow-routing behavior.

## Verification of the cleaned tree

Group checks after their final behavioral edits passed: **A 738 passed/one
skipped**, **B 411 passed**, **C 507 passed**. Affected-file checks were
79/210/107 passed respectively. Final independent collection found **1,657
cases**, exactly 35 fewer than the historical baseline's 1,692.

The integration executor's final full-suite command exited **0** with **1,656
passed, one skipped, 12 SQLite ResourceWarnings**, in 17.27 seconds:

```bash
COVERAGE_FILE=/tmp/idasen-phase22-final.coverage \
PYTHONPYCACHEPREFIX=/tmp/idasen-phase22-final-pycache \
.venv/bin/python -m pytest -q \
  -o cache_dir=/tmp/idasen-phase22-final-cache \
  --cov=idasen_companion --cov-fail-under=77 \
  --cov-report=term-missing \
  --cov-report=json:/tmp/idasen-phase22-final-coverage.json
```

The existing `test_cli_integration.py` smoke still skips unless supplied its
throwaway `/tmp` session bus. No skip was added. The 12-warning count matches
the historical count; warning emission locations can vary with collection.

Coverage is **6,735 of 7,611 statements, 88.49034292471423% (88.49%)**, above
the unchanged 77% floor. The baseline and final exports contain the same 62
production paths and **identical executed-line sets in every path**: zero lost
lines and zero gained lines. This compares actual line identities rather than
accepting an aggregate percentage. Local evidence includes the full log,
coverage JSON/data file, collection log, reconciliation JSON and empty
`/tmp/idasen-phase22-newly-uncovered.json`.

## Preservation and change boundary

SHA256 checks match all four immutable inventory entries:
`tests/conftest.py`, `tests/language_context.py`,
`tests/goldens/vocabulary_en.json` and `tests/goldens/vocabulary_es.json`.
Journal/subprocess blocking, forced offscreen collection, deferred widget
deletion, style/timezone/locale restoration and language cleanup remain intact.
Unused module-local helpers removed with duplicate tests are accounted for in
the review; shared support files and golden contents are byte-identical.

All **53 pending capture hashes** match their saved baseline, with 53 captures
still present. Root `TODO.md` is byte-identical to baseline and still has 53
unchecked items. No unrelated feature work was closed.

The three parent-owned commits are `2f1c54b` (A, five files), `f9aae52` (B,
seven files) and `64d596e` (C, four files). At reviewed head `64d596e`, the
tracked diff from `d5a9d1b` contains exactly those **16 inventoried test paths**
(nine insertions/462 deletions); this report is the only additional deliverable.
`git diff --check` passes. Production source, workflows, dependencies,
package/version metadata, GSD framework files and unrelated tracked files are
unchanged. No installation, desktop/daemon lifecycle, BLE, release or remote Git
operation was performed.

The parent independently reran the full suite: **1,656 passed, one skipped,
12 warnings**, with the same **88.49%** coverage and identical executed-line
sets across all 62 production files. The required prior-phase regression gate
passed **437 tests across 24 files**. GSD's independent code reviewer checked
all 28 deletions, both parameter reductions, both assertion-block removals and
surviving guards: **17 files reviewed, zero findings**. GSD's visual hook was
not applicable because product code and assets did not change. Canonical phase
verification and closure are recorded separately in the local Phase 22 artifacts.
