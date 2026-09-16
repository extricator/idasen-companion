# Holistic i18n and distribution review of `refactor`

Review date: 2026-09-16. Subject: `refactor` at `30e59a1`, merge-base
`97fbdac`, 133 commits ahead of `main`, +13,124/−1,275 over 116 files.
This replaces the verdict and prescription in
`docs/presentation-rebuild-plan.md`; it does not alter that document.

`refactor:path:line` citations refer to the reviewed branch. `main:path:line`
means the current `main` branch. For readability, `core/`, `gui/` and `daemon/`
in citations abbreviate `src/idasen_companion/core/`,
`src/idasen_companion/gui/` and `src/idasen_companion/daemon/`. Findings and
decisions are kept separate.

## 1. Premise and trajectory

### Owner-established premise

- Languages are open-ended: this is open source, so the architecture must not
  assume a final count. RTL must therefore be supportable, not designed out.
- A standard dependency is welcome when it makes the product simpler or more
  correct. Solo-maintainer cost is not a review premise.
- Distribution means all existing release forms, not only the bundled RPM. The
  release workflow builds RPM, Debian and Flatpak artifacts
  (`refactor:.github/workflows/release.yml:97-128`) and assembles all three
  (`refactor:.github/workflows/release.yml:143-159`).

### My reading from the repository

The repository points in the same direction. The initial requirement explicitly
asked for translations that contributors could add without code changes and for
locale-aware numbers and time (`d87121f:TODO.md:21-28`). The catalog builder and
Spanish catalogs followed the next day (`612c21b:scripts/build-translations.sh:1-22`),
before the first 1.0 tag (`v1.0.0:src/idasen_companion/__init__.py:1-6`). That is
foundation work before release, not evidence of a two-language ceiling. Current
instructions still say a language is one code plus catalogs, with no Python
change (`refactor:docs/TRANSLATING.md:3-4,194-236`), and package data already
uses language wildcards (`refactor:pyproject.toml:55-61`).

The implementation is less ambitious than the intent: the language list is
still only `es` (`refactor:scripts/build-translations.sh:23-24`), and non-Latin
digits are explicitly deferred (`refactor:TODO.md:119-131`). The honest reading
is therefore **open-ended intent, two-language validation so far**. That squares
with the owner's answer; it invalidates the withdrawn review's two-language and
solo-maintainer premise.

## 2. Verdict (under 400 words)

**REBUILD — mixed at component level.** Do not merge `refactor` as-is, but do
not return to `main`'s presentation design either.

The branch correctly identifies the durable seams: language is not measurement
or clock preference (`refactor:core/units.py:116-138`,
`refactor:core/clock_format.py:158-191`); the daemon stays Qt-free; D-Bus carries
raw log parameters for reader-side translation
(`refactor:daemon/service.py:252-266`); whole messages replace translated
fragments (`refactor:CHANGELOG.md:21-37`); and real gettext plural selection is
used by notifications (`refactor:core/presentation/formatter.py:387-430`). Those
choices get more valuable, not less, as languages grow.

The central implementation nevertheless fails the established trajectory. Its
Qt-free formatter deliberately emits ASCII digits, `.` decimals, ISO dates and
English `AM`/`PM` in every language
(`refactor:core/presentation/plain_locale.py:58-102`), while the architecture
documents that mismatch as sanctioned (`refactor:docs/ARCHITECTURE.md:298-341`).
That is not internationalization for an open language ecosystem. The other
backend already has CLDR through Qt, so the branch institutionalizes two answers
to one locale question and adds 306 lines to catalogue the disagreement
(`refactor:tests/test_presentation_divergence_surface.py:1-20`).

The dual app catalogs are not inherent. A Qt-free daemon requires a non-Qt
runtime, but the GUI already binds and consumes gettext
(`refactor:gui/i18n.py:115-126`, `refactor:gui/context.py:84-87`). Only Qt's own
widget catalog must remain a `QTranslator` (`refactor:gui/i18n.py:100-110`). One
gettext app catalog with contexts removes the class-name, base-class and
non-literal-context traps rather than policing them forever.

Finally, goal (a) is not delivered: there are still only daemon and Qt GUI entry
points (`refactor:pyproject.toml:37-39`); the one-shot commands import Qt at
module load (`refactor:gui/main.py:14-17,32-58`); and every native package still
ships GUI dependencies (`refactor:packaging/idasen-companion.spec:22-34`,
`refactor:debian/control:26-40`). `feat/cli-frontend` contains only TODO changes,
as independently enumerated in the withdrawn review
(`docs/presentation-rebuild-plan.md:20-33`).

Rebuild the presentation series around one gettext message catalog and one
shared CLDR implementation, while salvaging the branch's policy separation,
domain vocabulary, plurals, whole-message rules and Qt-free gate. Here
**REBUILD describes the architecture, not the Git ancestry**: cut the
implementation branch from the reviewed `refactor` head rather than replaying
its accepted and unrelated work from `main`.

## 3. Findings before decisions

### Measured behavior

The complete suite passed: **2,038 passed in 15.17 s, exit 0**. The naming-span
gate also exited 0. In an isolated session bus, the mock daemon started at
0.6200 m, `idasen-companion --stand` moved it to 1.1000 m, `--stop` returned 0,
and the daemon shut down cleanly. These commands work, but through the GUI entry
point whose imports require PySide6 (`refactor:gui/main.py:14-17,146-154`).

A fresh isolated import loaded zero Qt modules for
`idasen_companion.daemon.main` and 20 PySide/shiboken modules for
`idasen_companion.gui.main`. This matches the placement rule: core is Qt-free
(`refactor:core/units.py:1-6`), while the GUI imports Qt at module scope
(`refactor:gui/main.py:14-17`). `main` already had the first property:
`main:daemon/i18n.py:1-8` explicitly describes the Qt-free daemon.

Locale experiment, fixed input `72.5 cm`, 2026-08-17 14:32, Spanish:

| Backend | Height | Day | 12-hour clock | Duration plurals |
|---|---|---|---|---|
| Qt | `72,5 cm` | `lun 17 ago 2026` | `2:32 p. m.` | `1 minuto`, `2 minutos` |
| Plain | `72.5 cm` | `2026-08-17` | `2:32 PM` | `1 minuto`, `2 minutos` |

The first three differences follow the implementations exactly
(`refactor:gui/locale_backend.py:40-60,79-136`;
`refactor:core/presentation/plain_locale.py:65-102`). The last result proves
that gettext plurals work: Spanish declares `n != 1`
(`refactor:po/es.po:4-20`) and the formatter calls the catalog's plural rule
(`refactor:core/presentation/formatter.py:418-430`).

An Arabic Qt experiment changed the application to RTL and rendered Arabic
digits. The branch has no RTL acceptance test, and several custom/physical
layouts bypass logical direction: fixed left borders
(`refactor:gui/widgets.py:389-410`), fixed right alignment
(`refactor:gui/pages/overview.py:257-265`), physical painter coordinates
(`refactor:gui/widgets.py:895-937,1009-1040`), and an unconditional RTL override
used merely to put an icon on the right
(`refactor:gui/pages/activity_log.py:154-166`). RTL is therefore an unverified
product gap, not a reason to reject Qt's automatic direction handling.

### I18n correctness findings

1. **Plurals are half-fixed.** Gettext has three real plural pairs for
   hour/minute/second (`refactor:po/es.po:15-34`), but the Qt catalog has zero
   numerus forms and still ships `preajuste(s)` and
   `dispositivo(s) encontrado(s)` (`refactor:translations/idasen_companion_es.ts:355-356,583-584`).
2. **Spanish agreement was handled thoughtfully where inspected.** The catalog
   distinguishes feminine automation/status forms (`Automatización activa`,
   `Activa`), a feminine implicit position (`Personalizada`), and the masculine
   desk position (`Sentado`) (`refactor:po/es.po:71-73,119-125,257-258,312-318`).
   I found no defensible current gender defect. Flat source keys still need
   gettext contexts for future homographs.
3. **GUI heights are correct.** They route the number through injected `QLocale`
   and the whole unit message through gettext
   (`refactor:core/presentation/formatter.py:147-171`), yielding `72,5 cm` in
   Spanish. The daemon/future CLI backend is not (`plain_locale.py:65-96`).
4. **Two catalogs are a chosen design, not a process boundary.** The GUI already
   uses gettext for shared vocabulary (`refactor:gui/util.py:88-95,137-177`) and
   binds it beside Qt (`refactor:gui/i18n.py:115-126`). Qtbase translations are
   separate and should stay (`refactor:gui/i18n.py:100-105`); app-owned `.ts`
   messages need not.
5. **The branch still bypasses its number seam.** Statistics formats percentages
   with Python (`refactor:gui/pages/statistics.py:134-140`) and the custom chart
   paints another ASCII percentage (`refactor:gui/widgets.py:1035-1040`). This is
   invisible in Spanish for integer digits but wrong for non-Latin numbering
   systems and can place the percent sign incorrectly.

### CLI / Qt-free finding

There is a working Qt-free **daemon**, on both branches. There is no working
human-facing Qt-free **distribution**. PySide6 is optional in project metadata
(`refactor:pyproject.toml:28-29`), yet the only client entry point targets
`gui.main` (`refactor:pyproject.toml:37-39`) and imports Qt before command parsing
(`refactor:gui/main.py:14-17,47-64`). The Fedora spec unconditionally requires
PySide6 (`refactor:packaging/idasen-companion.spec:22-34`); Debian is one GUI
package (`refactor:debian/control:26-46`); the Flatpak intentionally uses the
PySide BaseApp (`refactor:packaging/flatpak/io.github.extricator.IdasenCompanion.yaml:5-16`).
The TODO itself correctly says the CLI is not first-class
(`refactor:TODO.md:148-172`). A green Qt-free import test proves a property, not
a deliverable.

## 4. New source components

Counts are physical lines. Production call-site counts were checked with `rg`
against `src/`, excluding each definition file.

| Component | Lines | Production use | Decision | Evidentiary reason |
|---|---:|---:|---|---|
| `core/presentation/__init__.py` | 31 | 0 exports | DROP | It explicitly exports nothing (`refactor:core/presentation/__init__.py:24-29`). |
| `daemon_errors.py` | 51 | 1 path | KEEP/FOLD | Reader-side localization is correct because the daemon detail may remain English (`refactor:core/presentation/daemon_errors.py:14-22,37-51`). |
| `dates.py` | 84 | 2 direct helpers; others via facade | DROP/FOLD | Four wrappers delegate six lines of behavior to locale/translator (`refactor:core/presentation/dates.py:47-81`). Keep behavior in the shared formatter. |
| `english.py` | 90 | 2 calls to one function | TRIM | It constructs a context and facade per log value (`refactor:core/presentation/english.py:54-90`); keep an English journal formatter but preserve compatibility. |
| `formatter.py` | 510 | 3 constructors | TRIM | Central domain formatting is right; 15 public methods have no external production caller, including `minutes_label`, `countdown`, day and verbose helpers (`refactor:core/presentation/formatter.py:189-219,300-387`). Target ~250 lines. |
| `gettext_translator.py` | 44 | 13 constructions | FOLD | Thin and heavily used, but it only delegates to `core.i18n` (`refactor:core/presentation/gettext_translator.py:31-44`). Fold into the presentation object. |
| `plain_locale.py` | 102 | 2 constructions | DROP/REPLACE | It is intentionally non-localized (`refactor:core/presentation/plain_locale.py:58-102`); replace with shared CLDR formatting. |
| `protocols.py` | 67 | annotations only | DROP | Useful vocabulary during migration, but one shared runtime formatter removes backend polymorphism; `runtime_checkable` exists for structural tests (`refactor:core/presentation/protocols.py:41-67`). |
| `register.py` | 412 | 4 importers, ~80 marks | TRIM | Central extraction marks scale; 300+ lines of decision prose do not. Add gettext contexts instead of maintaining a flat collision regime (`refactor:core/presentation/register.py:1-39`). Target ~120 lines. |
| `specs.py` | 124 | `NumberSpec` 1 real construction; `IntegerSpec` 8; `TimeStyle` shared | SPLIT/TRIM | `grouping=True` has no production call; keep clock/date enums if useful, pass ordinary Babel format options for numbers (`refactor:core/presentation/specs.py:44-124`). |
| `words.py` | 249 | 12 GUI forwarders plus facade | KEEP/TRIM | Central semantic vocabulary is appropriate at open-ended scale; remove duplicate facade/forwarder routes and the dead `minutes_label` (`refactor:core/presentation/words.py:87-176`). Target ~160 lines. |
| `core/clock_format.py` | 191 | 2 resolvers | KEEP/TRIM | Explicit preference is correct; a frozen 104-territory CLDR derivative is a data-maintenance liability (`refactor:core/clock_format.py:47-63,89-136`). Ask the shared locale data at runtime. Target ~70 lines. |
| `core/units.py` | 173 | 2 resolvers plus conversions | KEEP/TRIM | Separating setting from resolved unit and pure conversion is sound (`refactor:core/units.py:116-173`). Retain the product-specific US/LR default, cut repeated rationale. Target ~100 lines. |
| `gui/locale_backend.py` | 181 | `QtLocaleFormatter` 1; `QtTranslator` 0 | DROP app formatter | `QtTranslator` is never instantiated and even documents an unusable plural API (`refactor:gui/locale_backend.py:138-181`). Keep only QLocale/widget setup in `gui/i18n.py`. |

Abstractions consumed only by their own tests or migration scaffolding:
`QtTranslator`; `NumberSpec.grouping`; `IntegerSpec.grouping`; the runtime member
allowlists; and the facade methods named above. Deleting the first four changes
no shipped output. Deleting the unused facade methods changes no current output,
but some would otherwise serve the accepted CLI; add them with that consumer,
not in anticipation.

## 5. New test surface

Classification: **A** pins user-visible behavior, **B** pins a pre-existing rule,
**C** pins a rule/shape invented by this branch, **I** is supporting data or
infrastructure. At file granularity: A 3,732 lines, B 179, C 3,422, I 447 = 7,780.
Some C files contain useful assertions; the decision column preserves those.

| File | Lines | Class | Decision | Reason |
|---|---:|:---:|---|---|
| `goldens/vocabulary_en.json` | 100 | A/I | TRIM | Semantic outputs are useful; do not require a full hand-maintained file per language (`refactor:tests/test_baseline_vocabulary.py:1-20`). |
| `goldens/vocabulary_es.json` | 100 | A/I | TRIM | Same. |
| `goldens/window_en.json` | 222 | C/I | DROP | Widget ordinals record structure, not behavior (`refactor:tests/test_baseline_window.py:1-17`). |
| `goldens/window_es.json` | 222 | C/I | DROP | Same. |
| `language_context.py` | 94 | I | KEEP/TRIM | Dynamic shipped-language setup is useful (`refactor:tests/language_context.py:37-64`); one catalog simplifies it. |
| `presentation_fakes.py` | 138 | I | DROP/TRIM | Exists largely to satisfy the protocol/golden matrix. Keep only fakes used by behavioral tests. |
| `presentation_samples.py` | 215 | I | DROP/TRIM | Every public method needs sample metadata only because the golden contract requires it (`refactor:tests/test_golden_presentation_contract.py:698-710`). |
| `test_app_context_formatter.py` | 120 | A | KEEP | Proves settings reach the formatter (`refactor:tests/test_app_context_formatter.py:79-117`). |
| `test_baseline_vocabulary.py` | 418 | A | DROP after migration | It calls itself a temporary before-picture (`refactor:tests/test_baseline_vocabulary.py:1-20`). Replace with focused semantic tests. |
| `test_baseline_window.py` | 527 | C | DROP | It explicitly says it is not a behavior test (`refactor:tests/test_baseline_window.py:12-17`). |
| `test_catalog_concept_overlap.py` | 308 | C | DROP | Polices a boundary removed by one app catalog (`refactor:docs/TRANSLATING.md:151-171`). |
| `test_clock_format.py` | 180 | A | KEEP/REPOINT | Pins explicit/system preference; replace the frozen territory set with CLDR-backed expectations (`refactor:tests/test_clock_format.py:43-180`). |
| `test_clock_format_wiring.py` | 165 | A | KEEP/TRIM | Cross-process preference wiring is real (`refactor:tests/test_clock_format_wiring.py:84-121`). |
| `test_daemon_error_import_guard.py` | 126 | C | FOLD | Valid Qt-free boundary, duplicate mechanism; fold into the subprocess import gate (`refactor:tests/test_daemon_error_import_guard.py:30-47`). |
| `test_dates.py` | 123 | A | KEEP/REPOINT | Pins locale requests and whole day+clock composition (`refactor:tests/test_dates.py:38-123`). |
| `test_english_translator.py` | 77 | A/C | TRIM | English journal stability matters; protocol conformance does not (`refactor:tests/test_english_translator.py:35-77`). |
| `test_extraction_scope.py` | 179 | B | KEEP | Prevents literals being outside the extractor's real scope (`refactor:tests/test_extraction_scope.py:142-179`). |
| `test_formatter_durations.py` | 158 | A | KEEP | Direct output assertions cover thresholds/plurals (`refactor:tests/test_formatter_durations.py:45-158`). |
| `test_formatter_heights.py` | 73 | A | KEEP | Pins conversion and rendered heights (`refactor:tests/test_formatter_heights.py:38-73`). |
| `test_gettext_translator.py` | 57 | A/C | FOLD | Retain catalog/plural behavior in `core/i18n` tests; drop protocol ceremony. |
| `test_golden_presentation_contract.py` | 730 | A/C | TRIM to ~200 | Hand-written representative cross-surface cases are good; completeness by public-method inventory and per-language rows is refactor tax (`refactor:tests/test_golden_presentation_contract.py:698-730`). |
| `test_gui_language_binding.py` | 84 | A | KEEP | Proves the chosen language binds app text (`refactor:tests/test_gui_language_binding.py:50-58`). |
| `test_locale_backend.py` | 481 | A/C | REPLACE | It pins Qt backend compatibility, including a dead `QtTranslator` (`refactor:tests/test_locale_backend.py:1-18`). Replace with shared CLDR tests. |
| `test_notification_delay.py` | 93 | A | KEEP | Real localized notification delay output (`refactor:tests/test_notification_delay.py:60-93`). |
| `test_notification_sentences.py` | 174 | A | KEEP | Real whole notification sentences in both languages (`refactor:tests/test_notification_sentences.py:85-174`). |
| `test_picker_shape.py` | 363 | A | KEEP/TRIM | Pins five user-visible surfaces separately (`refactor:tests/test_picker_shape.py:1-22`); keep outputs, reduce setup. |
| `test_plain_locale.py` | 297 | A/C | DROP/REPLACE | Its structural gate proves intentional locale independence (`refactor:tests/test_plain_locale.py:1-19`), the opposite of the product requirement. |
| `test_presentation_divergence_surface.py` | 306 | C | DROP | A matrix recording deliberate wrong-language divergence (`refactor:tests/test_presentation_divergence_surface.py:1-20`). |
| `test_presentation_no_globals.py` | 239 | C | DROP | AST policy and exemption-list maintenance; explicit per-process presentation construction can be tested behaviorally (`refactor:tests/test_presentation_no_globals.py:183-239`). |
| `test_presentation_policy.py` | 185 | C | DROP | Mostly proves fakes conform to branch protocols. Static typing already covers actual implementations. |
| `test_presentation_protocols.py` | 79 | C | DROP | Locks protocol member sets to allowlists (`refactor:tests/test_presentation_protocols.py:1-12,61-79`). |
| `test_presentation_seam.py` | 118 | C | DROP | Pins enum literals and dataclass shape rather than output (`refactor:tests/test_presentation_seam.py:43-118`). |
| `test_qt_free_imports.py` | 202 | C/A | KEEP ~60 | Fresh-process import proof is the right test (`refactor:tests/test_qt_free_imports.py:1-23`); retain daemon/core/CLI checks, remove matrix scaffolding. |
| `test_sidebar_width.py` | 214 | A | KEEP | Real layout fit across dynamically discovered languages (`refactor:tests/test_sidebar_width.py:152-170`). |
| `test_translation_collisions.py` | 158 | C | DROP | Source-key collision registry disappears with `pgettext` contexts (`refactor:tests/test_translation_collisions.py:37-44,109-158`). |
| `test_units.py` | 139 | A | KEEP | Pins setting resolution and exact conversions (`refactor:tests/test_units.py:36-139`). |
| `test_words.py` | 316 | A | KEEP/TRIM | Semantic vocabulary outputs matter; stop asserting register topology. |

**Maintenance tax.** The files classified C plus the two window goldens are
3,866 lines; subtracting the valuable Qt-free and mixed golden assertions still
leaves roughly 3,000 lines that a backend/catalog refactor rewrites without a
user-visible change. The overlap is concrete: the same Qt-free property is
enforced by a subprocess import gate (`test_qt_free_imports.py:1-23`), an AST
policy (`test_presentation_no_globals.py:183-239`) and a daemon name/import walk
(`test_daemon_error_import_guard.py:30-47`). Keep one strong mechanism.

## 6. Every new normative documentation rule

Line counts are the cited normative span, not the surrounding explanation.

| # | Rule | Lines | Decision | Reason |
|---:|---|---:|---|---|
| 1 | Backend renders atomic values, not product policy | 5 | KEEP | Sound separation (`refactor:docs/ARCHITECTURE.md:287-292`). |
| 2 | No locale-database fields on the seam | 3 | KEEP/GENERALIZE | Consumers ask Babel-backed operations for output rather than rebuilding formatting from exposed CLDR data (`refactor:docs/ARCHITECTURE.md:292-294`). |
| 3 | Ask for operations, never read fields | 3 | KEEP/GENERALIZE | Keep the rule at the `LocaleProfile` boundary; the interchangeable-backend seam itself is removed (`refactor:docs/ARCHITECTURE.md:294-296`). |
| 4 | Any atomic operation may diverge by backend | 6 | DROP | Correctness should not depend on which executable renders (`refactor:docs/ARCHITECTURE.md:298-303`). |
| 5 | Qt-free dates are always ISO | 3 | DROP | Not localized (`refactor:docs/ARCHITECTURE.md:321-323`). |
| 6 | Qt-free 12-hour meridiem is fixed English | 7 | DROP | Not localized (`refactor:docs/ARCHITECTURE.md:328-338`). |
| 7 | Never obtain meridiem from catalog/data | 3 | DROP | CLDR should own it (`refactor:docs/ARCHITECTURE.md:339-341`). |
| 8 | Resolve clock preference once | 4 | KEEP | Product policy belongs above rendering (`refactor:docs/ARCHITECTURE.md:328-331`). |
| 9 | Do not derive the choice independently in each backend | 10 | KEEP | One resolver, implemented with shared locale data (`refactor:docs/ARCHITECTURE.md:354-363`). |
| 10 | Theme colours stay in GUI | 3 | KEEP | Qt/UI concern (`refactor:docs/ARCHITECTURE.md:380-382`). |
| 11 | Daemon error reader translation has no facade method | 1 | KEEP | Preserves reader-side language (`refactor:docs/ARCHITECTURE.md:383`). |
| 12 | Spin suffix helpers retain leading space | 1 | KEEP | Required by widget API (`refactor:docs/ARCHITECTURE.md:384`). |
| 13 | Every moved formatter keeps a thin unchanged GUI forwarder | 5 | DROP | Permanent duplicate routes add hops (`refactor:docs/ARCHITECTURE.md:373-377`). |
| 14 | Qt-free import gate | 2 | KEEP | Directly supports distribution goal (`refactor:docs/ARCHITECTURE.md:386-388`). |
| 15 | Cross-backend goldens are hand-typed | 3 | TRIM | Hand-type representative behavior, not every method/language (`refactor:docs/ARCHITECTURE.md:388-390`). |
| 16 | Every seam cell needs a divergence verdict | 5 | DROP | No intentional app-format divergence in target design (`refactor:docs/ARCHITECTURE.md:391-395`). |
| 17 | AST-ban locale access across presentation | 13 | DROP | Replace with CLDR output tests (`refactor:docs/ARCHITECTURE.md:397-409`). |
| 18 | Status note adds one fact absent from head | 3 | KEEP | Useful copy guidance (`refactor:docs/TRANSLATING.md:63-65`). |
| 19 | Repetition/reassurance/explanation becomes empty | 4 | KEEP | Deliberate UX rule (`refactor:docs/TRANSLATING.md:66-69`). |
| 20 | At most one non-range dash | 3 | KEEP | Review guidance, not a gate (`refactor:docs/TRANSLATING.md:70-72,101-106`). |
| 21 | Fit status notes at 760 px in shipped languages | 5 | KEEP/GENERALIZE | Test every shipped language plus a forced RTL structural locale (`refactor:docs/TRANSLATING.md:73-77`). |
| 22 | Resolve source-key collisions case by case | 4 | KEEP | Judgment remains, though contexts prevent most collisions (`refactor:docs/TRANSLATING.md:126-132`). |
| 23 | Collision decision must be its own commit | 2 | DROP | Commit topology is not an i18n invariant (`refactor:docs/TRANSLATING.md:133-134`). |
| 24 | Shared collision needs a registry entry | 5 | DROP | `msgctxt` replaces the registry (`refactor:docs/TRANSLATING.md:135-139`). |
| 25 | One English source maps to one Spanish value globally | 3 | DROP | False for homographs; use semantic context (`refactor:docs/TRANSLATING.md:112-114`). |
| 26 | One catalog owns a concept | 5 | KEEP | Becomes naturally true with one app catalog (`refactor:docs/TRANSLATING.md:151-159`). |
| 27 | Rewrite duplicates; do not exempt genuine duplicates | 10 | KEEP/TRIM | Keep intent, delete dual-catalog checker bureaucracy (`refactor:docs/TRANSLATING.md:167-176`). |
| 28 | Daemon uses gettext `_`/`ngettext` | 2 | KEEP/GENERALIZE | All app-owned strings use gettext (`refactor:docs/TRANSLATING.md:267-268`). |
| 29 | Core constants use `N_`/`NP_` markers | 4 | TRIM | Keep lazy/context-aware markers only where import-time constants require them (`refactor:docs/TRANSLATING.md:269-272`). |
| 30 | Shared markers take no context | 4 | DROP | Add `pgettext`/`npgettext` contexts (`refactor:docs/TRANSLATING.md:273-276`). |
| 31 | Extraction scope must contain every marker | 5 | KEEP | Real silent-failure prevention (`refactor:docs/TRANSLATING.md:277-281`). |
| 32 | Heights go through presentation formatter | 4 | KEEP | Prevents decimal/unit drift (`refactor:docs/TRANSLATING.md:289-292`). |
| 33 | Spin suffixes use the three widget helpers | 5 | KEEP | Necessary widget exception (`refactor:docs/TRANSLATING.md:293-297`). |
| 34 | Reuse established duration terms/patterns | 7 | KEEP | Avoids vocabulary drift (`refactor:docs/TRANSLATING.md:282-288`). |

Three documentation defects ship in the branch: `daemon/i18n.py` is described
as retaining `human_delay` after the file was deleted
(`refactor:docs/ARCHITECTURE.md:272-276`); the collision log says no formatter
has moved while the architecture says sixteen moved
(`refactor:docs/TRANSLATING.md:141-145` versus
`refactor:docs/ARCHITECTURE.md:373-377`); and a contributor document cites a
gitignored `.planning` file (`refactor:docs/TRANSLATING.md:116-124`).

Rules that can fail silently with a green build: Qt context/class renames and
base-class `tr()` (`refactor:docs/TRANSLATING.md:188-192` and
`CLAUDE.md:251-270`); non-literal extraction contexts
(`CLAUDE.md:260-265`); status guidance (explicitly review-only at
`refactor:docs/TRANSLATING.md:101-106`); hardcoded Spanish-only collision and
terminology checks (`refactor:tests/test_translation_collisions.py:37-44`);
hardcoded baseline language tables; and the wheel check that requires Spanish
`.qm` specifically while checking `.mo` by wildcard
(`refactor:scripts/build-dist.sh:106-127`).

## 7. Defects and regressions, ranked by user impact

### P1 — mixed daemon/GUI versions corrupt one Activity Log message

Input: old daemon emits `automation.snoozed` with `{"minutes": 10}`; new GUI
expects `duration`. Measured output: **`Snoozed for N/A.`** New daemon plus old
GUI yields **`Snoozed for ? minutes.`** The branch renamed both the parameter and
type (`main:core/logmsg.py:418-421` versus
`refactor:core/logmsg.py:418-421`). Parameters cross D-Bus as JSON
(`refactor:daemon/service.py:252-266`, `refactor:daemon/main.py:631-635`), and a
normal RPM upgrade restarts the daemon beneath an existing GUI
(`refactor:packaging/idasen-companion.spec:83-90`). Add a compatibility alias or
version the payload; never change a stable message parameter in place.

### P1 — two shipped Spanish messages have no plural grammar

Input: first-run import count 1, or scan count 1/2. Output contains literal
`preajuste(s)` or gender/number-neutralized `dispositivo(s) encontrado(s)`
(`refactor:translations/idasen_companion_es.ts:355-356,583-584`). The catalog has
zero `<numerusform>` entries. Convert both events to real plural selection now;
the shared gettext catalog makes that one implementation.

### P1 for the stated trajectory — RTL and non-Latin rendering are not release-ready

Input: force an Arabic locale. Qt flips the application direction, but custom
painting remains physically left/right and two percentages remain ASCII
(`refactor:gui/widgets.py:389-410,895-937,1009-1040`); integer formatting is
explicitly ASCII (`refactor:gui/locale_backend.py:62-78`), already recorded as
unfinished (`refactor:TODO.md:119-131`). This is not a defect Spanish users see;
Decision E treats it as structural remediation now, before any RTL catalog is
added; linguistic and manual visual acceptance still wait for that catalog.

### P2 — downgrade after Apply prevents the old daemon from starting

Input: run branch, click Apply, downgrade to 1.1.1. The new writer always stores
`clock_format` (`refactor:core/config.py:448-451`); the old loader rejects unknown
keys (`main:core/config.py:190-210`), and the daemon exits 1 on `ConfigError`
(`main:daemon/main.py:1823-1829`). Correction to the prior review: the old GUI
does **not** brick; it catches the error and launches defaults
(`main:gui/main.py:162-177`). Automation remains unavailable until the file is
edited. Decision D resolves this: unknown keys warn, are preserved and do not
abort startup; recognized keys remain strictly validated.

### P2 — journal duration compatibility changed without migration value

Input: a 90-second duration. `main` emitted `1.5 minutes`; branch emits `1m`.
Input 45.6 seconds: `46 seconds` becomes `45s`. The old behavior is explicit
(`main:core/durations.py:47-53`); the new code intentionally aligns journal and
Activity Log shapes (`refactor:core/presentation/english.py:54-90`). This loses
precision and breaks grep/consumer expectations. Keep the Activity Log compact,
but retain the stable journal formatter or make the log format change explicit
in release notes.

### P2 — package goal (a) remains unimplemented

Input: install base project without the `gui` extra and run any desk command.
There is no CLI entry point (`refactor:pyproject.toml:37-39`); the existing client
imports PySide6 (`refactor:gui/main.py:14-17`). Native packages also remain
monolithic (`refactor:packaging/idasen-companion.spec:28-34`,
`refactor:debian/control:26-40`). The Qt-free core is enabling work, not delivery.

### P3 — locale-sensitive percentages bypass presentation

Input: Arabic stats. The footer and chart use Python ASCII formatting
(`refactor:gui/pages/statistics.py:134-140`,
`refactor:gui/widgets.py:1035-1040`), producing Western digits and a hardcoded
percent placement. Route both through the shared number/percent formatter.

### Verified prior claims that are not defects

- The deleted Overview explanations were intentional UX work, not a silent
  regression. The new rule says reassurance and implementation explanation
  should be empty (`refactor:docs/TRANSLATING.md:56-77`), and the code follows it
  (`refactor:gui/pages/overview.py:461-503`). Whether to restore copy is a product
  decision, not an engineering defect.
- Unit/language decoupling is correct. Clock output can change for an explicit
  language plus `LC_TIME=C`, but the branch explicitly treats `LC_TIME` as the
  user's time-format statement (`refactor:core/clock_format.py:23-45`). Ship a
  release note; do not call the separation a bug.
- The D-Bus interface signatures did not change; the break is inside the JSON
  message payload. The reader already has arity compatibility logic
  (`refactor:gui/dbus_client.py:171-197`).
- No packaging omission was found for the four committed golden JSON files;
  they are explicitly in `MANIFEST.in` (`refactor:MANIFEST.in:77-87`).

## 8. Maintenance cost

### Indirection

On `main`, Overview height rendering is page → `fmt_height` →
`fmt_height_value`/`fmt_number` → `QLocale`, then one Qt translation
(`main:gui/pages/overview.py:374`, `main:gui/util.py:90-102,185-214`): two source
modules and roughly nine meaningful calls/lookups. On `refactor`, it is page →
`AppContext.fmt` → `Formatter.height` → unit policy → `height_value` → conversion
→ `NumberSpec` → `QtLocaleFormatter.number` → `GettextTranslator.message` →
process-global gettext (`refactor:gui/pages/overview.py:382-409`,
`refactor:core/presentation/formatter.py:113-171`,
`refactor:gui/locale_backend.py:37-60`,
`refactor:core/presentation/gettext_translator.py:34-44`): about fifteen hops
across six modules. Explicit dependencies are good; duplicate facade, spec and
adapter layers are not free.

### Files touched

Today a new GUI sentence normally touches its Python call site, `.ts` and `.qm`;
a shared/core concept can additionally touch `register.py`, formatter/words,
`.pot`, `.po`, `.mo`, collision/overlap tests and goldens
(`refactor:docs/TRANSLATING.md:254-310`). A daemon notification touches call
site/formatter, register, `.pot`, `.po`, `.mo`, sentence tests and often both
catalog bindings. One gettext app catalog reduces both to call site + `.po` +
compiled `.mo`, with focused tests where behavior warrants them.

Adding a language currently requires the `LANGS` edit plus `.ts`, `.qm`, `.po`
and `.mo` (`refactor:docs/TRANSLATING.md:194-236`): five project files. The
golden contract then requires hand-entered rows per shipped language
(`refactor:tests/test_golden_presentation_contract.py:698-710`), while the
baseline/collision/terminology tests hardcode Spanish and silently omit the new
language. The target is one code + `.po` + `.mo`, dynamic completeness checks,
and a small representative locale matrix rather than duplicating all expected
strings per language.

### Contributor concepts

The branch asks a contributor to understand two catalogs, two extractors, two
translation marker families, two value backends, two translator backends,
`PresentationContext`, `Formatter`, three spec types, two setting/resolved enum
pairs, a register, words/dates wrappers, sanctioned divergence, a collision log,
a collision registry, catalog-overlap rules, semantic and window goldens, fake
backends and sample inventories. Most are individually reasoned; together they
make a string change an architectural task. One catalog and one locale engine
remove the largest mental branches.

There is also a contributor-distribution defect outside the branch's core
design: `CLAUDE.md` is gitignored (`refactor:.gitignore:26-29`) while fourteen
tracked files cite it, including shipped source. Move load-bearing rules into
tracked `CONTRIBUTING.md`/docs and stop citing a file a clone does not receive.

## 9. Resolved design decisions and surveyed candidates

### Decision A — shared locale data for both processes

**Requirement:** numbers, percent, dates, clock designators, units and plural
categories must work from the same locale data in GUI, daemon and CLI; the
daemon/CLI must remain Qt-free.

**Accepted 2026-09-16:** Babel becomes the single application-value formatter
and a base runtime dependency for every installation. GUI, daemon and CLI use
it for application-rendered numbers, percentages, dates, times and units.
`QLocale` remains only for native Qt widget behavior, locale selection/layout
direction and Qtbase translations; it is not a second formatter for application
labels. Acceptance includes explicit Arabic/non-Latin-numbering tests and parity
tests between Babel-rendered labels and adjacent Qt-native controls. Package
footprint is accepted in exchange for one correct locale engine.

Scores: 5 best. Fedora availability was checked with `dnf list --available` and
`dnf repoquery`; Debian with its package index. Babel is
[`python3-babel` on Fedora](https://packages.fedoraproject.org/pkgs/babel/python3-babel/)
and [Debian](https://packages.debian.org/stable/python/python3-babel), and PyPI
publishes a [pure `py3-none-any` wheel](https://pypi.org/project/Babel/). PyICU
is [`python3-pyicu` on Fedora](https://packages.fedoraproject.org/pkgs/python-pyicu/python3-pyicu/)
and [`python3-icu` on Debian](https://packages.debian.org/stable/python/python3-icu);
upstream describes it as a C++ extension wrapping ICU
([PyICU](https://gitlab.pyicu.org/main/pyicu)). The bundled RPM pins every
carried wheel explicitly
(`refactor:scripts/fetch-bundled-runtime.sh:36-60`), Flatpak names each wheel
explicitly (`refactor:packaging/flatpak/gen-python-deps.py:24-48`), and Debian
names runtime packages explicitly (`refactor:debian/control:26-40`), so no option
is a one-file metadata change.

| Candidate | Fedora / Debian | Pure Python | Both processes | Bundle size/shape | Maintenance | Score |
|---|---|---:|---:|---|---|---:|
| **Babel** | packaged / packaged | yes | yes | ~10.2 MiB wheel; ~30 MiB Fedora installed data | CLDR maintained upstream; straightforward APIs | **24/25** |
| PyICU | packaged / packaged | no | yes | small binding plus system ICU; no portable CPython wheel assumption | ABI/toolchain/ICU lifecycle | 15/25 |
| stdlib `locale` | built in | yes | yes | zero | process-global, not thread-safe, depends on generated host locales, awkward explicit app locale ([Python docs](https://docs.python.org/3/library/locale.html)) | 12/25 |
| Qt `QLocale` | already GUI-packaged | no | **no** | enormous in the bundled/headless path | excellent GUI data, violates goal (a) | 11/25 |
| PyGObject/GLib | packaged / packaged | compiled binding | yes | pulls GNOME stack into non-GNOME paths | process-locale oriented; second native ecosystem | 10/25 |
| Generated CLDR subset | project-owned | yes | yes | smallest selectable subset | project owns generation, updates and edge cases | 13/25 |

**Decision: Babel.** It earns the dependency by deleting the
hand-frozen territory table, both custom locale backends, the divergence matrix,
ASCII/English fallback policy and future per-language formatting tables. Its
official APIs cover number, percent, date/time, unit formatting and plural rules
([Babel API](https://babel.pocoo.org/en/latest/api/)). The accepted cost is real:
add the
wheel/pin/license to the bundled RPM, add it to Flatpak's generated wheel list,
and add distro requirements. That is still far smaller and more portable than
Qt or ICU in the headless package. Verify default/non-Latin numbering behavior
with Arabic tests rather than assuming every script is substituted automatically.

### Decision B — app message catalog

**Requirement:** app-owned GUI, daemon, Activity Log and CLI messages need one
translation workflow that supports semantic disambiguation and real plurals
without making the Qt-free processes import Qt. The existing GUI already binds
gettext, proving that process boundaries do not require two app catalogs
(`refactor:gui/i18n.py:100-126`, `refactor:gui/context.py:84-87`).

**Accepted 2026-09-16:** every app-owned message moves to one contextual
gettext catalog per language, keyed by English source text plus a literal
semantic context; opaque message ids are not used. The catalog covers GUI,
daemon notifications, Activity Log, CLI and shared vocabulary. Qt
`QTranslator` remains in the GUI only to load Qt's own prebuilt `qtbase`
catalog for standard widget/dialog text; the project no longer owns `.ts` or
`.qm` files. Migration must preserve translator comments, placeholders,
plurals and context, and must pass source-message counts, placeholder parity,
Spanish-output and extraction-freshness checks before the old Qt app catalog is
removed.

| Candidate | Strength | Cost |
|---|---|---|
| Keep Qt `.ts` + gettext `.po` | Native Qt tooling and existing translations | Permanent drift, collision machinery, two translator workflows, class-context traps |
| **One gettext app catalog with `pgettext`/`npgettext`** | Works in both processes; real plurals/contexts; deletes three silent Qt extraction hazards | One-time `.ts`→`.po` migration; Qt Linguist no longer edits app strings |
| Fluent | Excellent selectors and translator-facing syntax | New runtime/toolchain plus migration; locale value formatting still needs Babel/ICU |
| Stable opaque IDs + custom store | Rename-safe | Project owns tools and fallback semantics; weak ecosystem |

**Decision:** one gettext app catalog with semantic contexts. Keep a
`QTranslator` only for Qtbase (`refactor:gui/i18n.py:100-105`). Python 3.11's
stdlib gettext provides context and plural APIs; the runtime dependency remains
stdlib. Preserve translator comments and verify conversion counts/placeholders.

### Decision C — package/product split

**Requirement:** a useful Qt-free installation, not merely an importable daemon.

**Accepted 2026-09-16:** extend the existing GitHub Release pipeline with two
standalone artifact flavors, not install-time subpackages. The full bundled RPM
contains daemon + CLI + GUI + Qt; the full `.deb` contains daemon + CLI + GUI
and depends on the distribution's Qt bindings. A headless bundled RPM and
headless `.deb` each contain daemon + CLI and require no Qt. The Flatpak remains
the full GUI artifact and may expose the CLI inside its sandbox where practical.
The project adds no PyPI or other public distribution channel. Full and
headless native variants own overlapping files, declare a package conflict and
cannot be installed together. Keep separate executables:
`idasen-companion` (GUI), `idasen-companion-cli` (CLI) and
`idasen-companiond` (daemon). Shared packaging inputs generate both variants so
dependency pins, catalogs, service metadata and versions cannot drift.

| Candidate | Trade-off |
|---|---|
| Daemon-only base | Smallest, but a human has only `busctl`; does not prove the presentation layer |
| Move existing action flags only | Cheap and Qt-free, but still write-only (`refactor:TODO.md:52-65`) |
| **Standalone full and headless flavors** | Both include daemon + first-class CLI; only full includes GUI/Qt; duplicates artifacts but avoids install-time package graphs |
| Keep monolithic native packages | No packaging work; fails stated goal |

**Decision:** publish independent full and headless RPM/`.deb` downloads through
GitHub Releases. Do not create core/GUI subpackages, compatibility metapackages
or a new release ecosystem. The headless smoke test proves PySide6/Qt is absent;
the full smoke test exercises both GUI and CLI. Flatpak stays intentionally
full-only.

### Decision D — clock/unit migration and config compatibility

**Requirement:** language, measurement units and hour cycle must remain
independently selectable, with deterministic system fallbacks, while a config
written by a newer build remains usable and round-trippable by the product.
The branch already separates the settings but rejects every unknown key
(`refactor:core/units.py:116-138`, `refactor:core/clock_format.py:158-191`,
`refactor:core/config.py:219-222,391-415`).

| Candidate | Trade-off |
|---|---|
| Selected language controls text, units and hour cycle | One locale input, but changing UI language silently changes physical and time preferences |
| System locale controls all conventions | Matches the desktop, but selected-language dates and number symbols can remain in another language |
| Independent language/units/clock preferences with strict unknown-key rejection | Preserves user intent, but an additive config key can stop another version's daemon |
| **Independent preferences plus preserve-and-warn unknown keys** | Keeps each setting's meaning and forward-compatible round trips; requires warning plumbing and lossless edits through the existing `tomlkit` dependency (`refactor:pyproject.toml:20-26`) |

**Accepted 2026-09-16:** keep language, measurement units and hour cycle as
independent preferences, resolved once and formatted through Babel. `[ui]
language` controls translated text, number symbols, date language/month names
and localized meridiem text. Explicit `[ui] units` and `[ui] clock_format`
values answer for themselves; `units = "system"` follows the system measurement
locale and `clock_format = "system"` follows the system time locale, never the
selected app language. Thus selecting Spanish on a US system changes language
and symbols without silently changing inches or the 12-hour preference.

Unknown config sections and keys produce a visible warning, survive `tomlkit`
rewrites and do not stop the daemon or GUI. Recognized keys retain strict type
and value validation. A renamed key requires an explicit migration and must not
silently fall into the unknown-key path. Do not add a schema-version mechanism
until a concrete migration needs one. This replaces the strict rejection that
makes every added key a downgrade outage
(`refactor:core/config.py:219-222,391-415`). Document the resolved semantics in
the user configuration reference; there is no installed-user migration program
to add for this unreleased rebuild.

### Decision E — RTL acceptance

**Requirement:** an open-ended language architecture must not bake physical LTR
assumptions into the GUI, but structural readiness must not be represented as a
translated language. The reviewed branch contains known physical CSS and custom
painting despite Qt's automatic direction handling
(`refactor:gui/main_window.py:239-243`,
`refactor:gui/widgets.py:389-411,881-938,995-1059`).

| Candidate | Trade-off |
|---|---|
| Defer RTL work until the first RTL catalog | No current remediation cost, but knowingly hands the first translator broken geometry |
| **Remove known RTL-hostile geometry now** | Bounded GUI/test work and honest structural readiness; native-speaker acceptance still happens with a real catalog |
| Add and claim an Arabic or Hebrew translation now | Exercises the complete path, but requires translation ownership and linguistic review that are not currently available |

**Accepted 2026-09-16:** make the remediation structurally RTL-ready now,
without adding an Arabic/Hebrew catalog or claiming linguistic support for
either language. Set the application's layout direction explicitly from the
selected locale rather than relying on installation of a Qt translation to do so
(`refactor:gui/i18n.py:75-112`). Keep Qt's automatic mirroring for ordinary
layouts; replace the known physical assumptions at the application boundary:
the sidebar divider (`refactor:gui/main_window.py:239-243`), the Move direction
icon and caption alignment (`refactor:gui/pages/overview.py:126-145,257-265`),
the journal chip's unconditional RTL override
(`refactor:gui/pages/activity_log.py:154-166`), preset padding
(`refactor:gui/pages/presets.py:134-143`), joined-segment borders and radii
(`refactor:gui/widgets.py:389-411`), and the custom-painted height rail and
daily bars (`refactor:gui/widgets.py:881-938,995-1059`). Preserve the existing
direction-aware button icon/text layout, which already maps logical rectangles
through `QStyle.visualRect` (`refactor:gui/widgets.py:569-608`).

Add focused offscreen LTR/RTL tests for application direction and those known
asymmetric controls, plus Babel number/percent cases for representative Arabic
locales. Record the observed numbering system rather than assuming native
digits. The acceptance boundary is removal of known RTL-hostile geometry and
protection against its return; native-speaker review and a manual visual pass
remain release criteria for the first actual RTL catalog.

## 10. Target design

Approximate steady-state production surface:

| Module | Purpose | Approx. lines |
|---|---|---:|
| `core/i18n.py` | bind gettext domain; `_`, `pgettext`, `ngettext`, `npgettext`; catalog discovery | 100 |
| `core/locale_profile.py` | Babel locale resolution and number/percent/date/time/unit operations | 150 |
| `core/presentation.py` | one `Presentation` object: domain vocabulary, height/duration/date/status formatting | 300 |
| `core/display_prefs.py` | unit and 12/24 settings/resolution; conversions | 120 |
| `core/logmsg.py` | existing stable ids/raw params; render through English or selected translations without GUI twin | current −100 |
| `gui/i18n.py` | bind app gettext; install Qtbase translator; set QLocale/layout direction for widgets | 90 |
| `cli.py` | `status`, `sit`, `stand`, `toggle`, `stop`, `preset`, `log` over `dbus-fast` | 250 |
| packaging changes | full/headless RPM and `.deb` flavors, Flatpak/Babel pin, licenses | ~140 metadata lines |

Expected presentation/i18n production code is roughly 750–900 lines plus the
CLI, rather than the branch's 2,309 new source lines. This is not a line-count
target; it follows from removing two app catalogs, two competing locale engines,
the general backend protocol/spec matrix and GUI forwarders.

### Migration commits

Create the implementation branch from the reviewed `refactor` head, not from
`main`. `REBUILD` describes replacement of the presentation architecture; it
does not mean discarding the branch's accepted policy separation, raw D-Bus
parameters, whole-message conversions, plural work or unrelated improvements
(`refactor:core/units.py:116-138`, `refactor:daemon/service.py:252-266`,
`refactor:CHANGELOG.md:21-37`). The documentation-only
`presentation-rebuild-plan` branch remains the review and decision record. Each
implementation commit builds and tests independently.

1. **Fix compatibility defects on `refactor`:** accept both snooze parameter
   spellings; restore journal output compatibility; fix the two Spanish plurals.
2. **Add Babel as shared locale data:** project metadata plus pins/licenses for
   bundled RPM, Debian and Flatpak; add Arabic/Spanish/English formatter tests.
3. **Introduce `LocaleProfile` and repoint `Formatter`:** keep current public
   behavior except documented fixes; remove `PlainLocaleFormatter`, frozen clock
   table and Qt app-value backend.
4. **Make configuration forward-compatible:** preserve unknown sections and
   keys through `tomlkit`, warn visibly without aborting either executable, keep
   recognized values strict, and document the independent language, unit and
   clock fallback rules.
5. **Add contextual gettext APIs and convert `.ts` app messages to `.po`:**
   automated scope-aware rewrite, placeholder/count audit, no `sed`. Keep old
   `.qm` active for one intermediate commit if needed.
6. **Switch GUI app strings to gettext; retain Qtbase only:** delete app `.ts`,
   `.qm`, `QtTranslator`, collision/overlap/divergence machinery and stale docs.
7. **Collapse Activity Log catalog twin:** render the shared `Message` definition
   with the reader's translator; preserve unknown-id English fallback and raw
   JSON wire (`refactor:daemon/service.py:252-266`).
8. **Add first-class Qt-free CLI and import smoke.** Move existing action parsing
   from `gui/main.py`; add read commands from existing D-Bus properties described
   in `refactor:TODO.md:52-64`.
9. **Build standalone full/headless RPM and `.deb` flavors; update Flatpak
   intentionally.** Do not add a release channel or install-time subpackage
   graph. Run the existing independent CI workflows
   (`refactor:.github/workflows/ci.yml:22-41`).
10. **RTL-ready structural pass:** set direction from locale, fix known physical
   layout and custom-paint assumptions, and add Arabic-locale offscreen and
   number/percent assertions. Defer a catalog and linguistic acceptance to the
   first actual RTL translation.
11. **Delete migration goldens/meta-tests and publish tracked contributor rules.**

### Deliberately given up

- No interchangeable locale backend protocol: Babel is the one application
  value engine; Qt remains only for widget behavior and Qtbase strings.
- No sanctioned cross-backend divergence matrix, because there is one app
  backend.
- No full-window ordinal snapshots or one golden row per method per language.
- No live language switching; relaunch remains acceptable
  (`refactor:docs/TRANSLATING.md:31-37`).
- Journald stays stable English; Activity Log/notifications/CLI are localized.
- Partial catalogs continue to fall back to English, as documented
  (`refactor:docs/TRANSLATING.md:31-35`).

## 11. Verification and corrections to prior measurements

| Prior measurement/claim | Result |
|---|---|
| 2,038 tests passed | Verified: 2,038 passed, 15.17 s, exit 0. |
| `main` ~16,092 src / 21,270 test LOC | Verified exactly for Python files. |
| `refactor` ~18,500 / 29,240 | Verified exactly for Python files; including four new JSON goldens gives 29,884 test/data lines. |
| +13,124/−1,275, 116 files | Verified. |
| 2,309 new source lines | Verified across the 14 modules in §4. |
| 7,780 new test lines | Verified including helpers and JSON goldens. |
| Meta tests 4→21 | Verified under the prior review's structural/meta definition; because that definition is subjective, §5 reports every new file instead. |
| Qt catalog 389 messages | **Wrong at reviewed head:** 322 messages in 18 contexts. The build-script comment still says 391 survived an earlier operation (`refactor:scripts/build-translations.sh:43-55`), explaining likely stale provenance. |
| gettext ~80 msgids | Close: 75 non-header singular msgids plus 3 plural entries at reviewed head. |
| zero Qt numerus forms | Verified. |
| no Qt import outside `gui/` on `main` | Verified; `main` daemon fresh import loaded zero Qt modules. |
| prior D2 status deletion is a defect | Withdrawn: documented intentional UX decision (`refactor:docs/TRANSLATING.md:56-77`). |
| prior D4 `LC_TIME=C` behavior is simply wrong | Withdrawn as stated: it is explicit policy (`refactor:core/clock_format.py:23-45`); migration disclosure is still needed. |
| prior D5 bricks both executables | Corrected: old daemon exits; old GUI catches the config error and opens with defaults (`main:gui/main.py:162-177`). |

CI gates not run: build-dist and translation regeneration write non-Markdown
artifacts; mypy/pylint via `uvx` would install tools; the review constraints
forbade both. `scripts/scan-secrets.sh` was explicitly not run. The full suite,
naming gate, fresh-process imports, mock D-Bus session, locale/RTL experiments,
catalog parses and package queries were run.

## 12. Holistic conclusions beyond the branch

1. **Distribution architecture and application architecture are currently out of
   sync.** Metadata already makes PySide optional (`refactor:pyproject.toml:28-29`),
   but no released native artifact is headless. Publish standalone full and
   headless flavors from shared packaging inputs.
2. **The real scale risk is translator workflow, not runtime dispatch.** Requiring
   two source catalogs, two tools and per-language hand goldens compounds with
   every language. A single contextual gettext catalog matters more than saving
   a facade class.
3. **The branch prevents several real English-shaped bugs.** Whole-message
   substitution, raw D-Bus params, unit/language separation and catalog plurals
   deserve preservation even though the implementation is rebuilt
   (`refactor:CHANGELOG.md:21-37`, `refactor:daemon/service.py:252-266`).
4. **Release gates need a language dimension.** Current package CI is strong and
   format-specific, but the first RTL language needs an explicit visual/manual
   gate alongside the existing published-artifact checks
   (`refactor:TODO.md:8-50`).
5. **Treat message payloads as API.** D-Bus signatures alone are insufficient;
   stable ids, JSON keys, units and types require compatibility tests across
   N/N−1 producer-reader pairs. D1 is the proof.

The owner was right to reject the earlier RPM-only, two-language framing. The
evidence does not support keeping the branch as-is, but it also does not support
throwing away its core ideas or ancestry. The appropriate action is a robust
architectural rebuild on a branch from `refactor`, aimed at the actual
open-source language and multi-package trajectory.
