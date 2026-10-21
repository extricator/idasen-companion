# Translation keys: retain contextual English sources

**Decision, 2026-10-21:** Retain the current contextual English source keys.
True stable IDs can preserve Spanish through an English-only reword, as the
bounded fixture below demonstrates. The available post-migration history shows
additions rather than recurrent editorial remapping, so it does not currently
justify migration and the additional default-register and review contracts.
Phase 35 authorizes no migration; [current translation policy](TRANSLATING.md)
remains in effect. This is an assessment, not an estimate of translator effort.

## Current lookup and maintenance seams

GUI, daemon, Activity Log reader and CLI use one app gettext catalog:
`po/idasen_companion.pot`, `po/es.po`, and the compiled
`src/idasen_companion/locale/es/LC_MESSAGES/idasen_companion.mo`.
Qt's standard-widget translator is separate from app-owned text.

Literal `pgettext` / `npgettext` calls and deferred `P_` / `NP_` markers carry
semantic contexts such as `overview` and `activity-log.entry`. A `MessageKey`
is a source string carrying context. `GettextTranslator` resolves it late,
using the current catalog, then substitutes values. Thus language rebinding
remains visible even for keys stored at import time. Missing catalogs or
messages yield readable English source text; plurals use the catalog rule.
Whole-message rendering and named placeholder names/conversion types remain
contracts, alongside the existing positional unit plurals.

[`scripts/build-translations.sh`](../scripts/build-translations.sh) runs
`xgettext` with `pgettext:1c,2`, `npgettext:1c,2,3`, `P_:1c,2`, and `NP_:1c,2,3`,
then `msgmerge`, then `msgfmt`. Literal arguments make extraction discoverable.
Filename-only locations (`--add-location=file`) and the pinned
`POT-Creation-Date: 2000-01-01 00:00+0000` suppress avoidable metadata churn.
Normal compilation excludes fuzzy/untranslated entries; a successful build
alone does not establish completeness. Contributor policy requires filling
every shipped language after a string change. Existing marker, extraction,
terminology, vocabulary, completeness and rendered-message checks protect
different parts of this contract.

Activity Log **wire IDs are distinct from translation lookup keys**.
[`core/logmsg.py`](../src/idasen_companion/core/logmsg.py) sends stable activity
identity, raw parameters and English fallback. The reader maps recognized IDs
to its own contextual text; an unknown ID uses the daemon fallback. Stable wire
identity therefore does not stabilize the English `msgid` used by gettext.
See [architecture](ARCHITECTURE.md), [translation policy](TRANSLATING.md),
[`core/i18n.py`](../src/idasen_companion/core/i18n.py) and
[contributor policy](../CONTRIBUTING.md).

## Measurement window and definitions

Observed on **2026-10-21**, at research/execution baseline
`8382394e0268f359aec79d616f14982fcc05bd83` (author timestamp
2026-10-20T22:40:22-04:00). The reachable root is
`d8d6a28bd5f2f1a0bd2689b0697188b2ef71a970`, authored
2026-08-13T00:30:01-04:00. The checkout is non-shallow. This window includes
reachable committed snapshots only; it does not expose pre-root history,
squash-internal edits, uncommitted work or intermediate fuzzy states. Other
refs' counterparts are not counted as additional mainline events.

The measurement unit is a decoded active **`(msgctxt, msgid, msgid_plural)`**
identity, excluding the header and obsolete entries. Translation form tuples
are compared separately. This tuple notices plural-source edits; Python's
actual plural lookup uses the singular ID and count. Decoded internal
whitespace affects exact identity; PO line wrapping does not.

The following categories must remain distinct:

| Category | What it measures or requires |
|---|---|
| English lexical rewrite/shortening | Reviewed surviving-message wording changes; not inferred from removed/added key pairs. |
| Spanish form change | Changed translation tuple for a retained identity; migration discovery also compares source-only form sets, with limits below. |
| Context | Identity/semantic-role changes, including introduction of contexts at migration. |
| Internal whitespace | Decoded string changes, such as a newline; distinguish from lexical edits. |
| Locations | Filename/reference metadata, independently compared for retained PO keys. |
| Flags/fuzzy state | Review/compilation state, independently compared for retained PO keys. |
| Headers | Catalog metadata, outside active-entry counts. |
| Raw/extraction formatting | Wrapping, ordering and generated layout; inspect raw diffs rather than count as rewords. |
| Additions/retirements | New/removed message units, requiring source review to distinguish from remapped identity. |
| Migration structure | Qt + PO consolidation, semantic contexts, marker/plural/formatter changes; can coexist with real wording changes. |

Mixed commits receive mixed labels. Entry counts, diff lines, removed/added
pairs and fixture results establish neither translator minutes/hours nor
future savings, translation-loss incidents or recurring maintenance frequency.

### Four reachable Spanish PO revisions

| Revision | Author date (-04:00) | Active entries | Plural identities | Change from prior PO snapshot |
|---|---|---:|---:|---|
| `d8d6a28bd5f2f1a0bd2689b0697188b2ef71a970` | 2026-08-13 | 14 | 2 | Initial PO, no contexts. |
| `aba35cd62388de156535268a0e7e30a2ae0aae9d` | 2026-09-24 | 432 | 5 | All 14 old exact keys removed; 432 contextual keys added; shared-catalog migration. |
| `2e9cad1d180b00485b7cfbc470ae6bed932119bc` | 2026-09-26 | 434 | 5 | Two additions, 432 retained keys. |
| `374fe86895aa1c456363412d8bc3aed675286b5b` | 2026-09-27 | 435 | 5 | One addition, 434 retained keys. |

The last snapshot is byte-identical at the research baseline. It has **25
contexts**. Each listed PO snapshot has zero active fuzzy entries and zero
empty forms. Across the two post-migration deltas there are **zero removed
existing keys, zero same-key Spanish changes, zero same-key location changes
and zero same-key flag changes**. These are snapshot observations, not claims
of zero intermediate work or future recurrence. Header and raw-format changes
are outside those zeros; no numeric TS-metadata claim is made.

### Migration was both structural and editorial

Legacy Qt snapshots contain 393, 379 and 390 active contextual entries at
`d8d6a28`, `e714c480255f8e3a908908fb472fc20f871c9b3a` and
`1f3a0e16827862a2a02b66e4641b78e02dc8faba`. The first transition removes 20
entries and adds six while retaining translations of unchanged keys; the next
removes three and adds 14, including whole-message construction and a
newline-only change. These are historical Qt changes, not demonstrated
recurrence in today's contextual gettext scheme.

At the migration boundary, the last legacy Qt catalog plus the unchanged
legacy PO contain **404 active entries / 393 distinct source strings**. The
new PO contains **432 / 415**. Source-only comparison finds **361 exact source
overlaps, 32 retired distinct sources and 54 new distinct sources**. The 361
overlapping sources have identical **sets of Spanish form tuples**, ignoring
context. That neither proves one-to-one semantic-role identity nor zero labor.

Appendix A reviews every one of the 32 retired-source candidates. Its primary
labels are seven semantic rewrites/shortenings, 13 formatting/substitution
changes, three plural/consolidation changes and nine retirements. They are
discovery labels, not an exhaustive count of English edits or avoidable jobs.
All rows also participate in structural migration. Two semantic shortenings
change substitutions; retirements remove words; localized-duration changes
move unit wording into formatters.

The strongest caution cuts both ways: “Remind me to sit and stand” became
“Move the desk for me”, and Spanish changed from “Recordarme sentarme y
levantarme” to “Mueve el escritorio por mí”. True IDs could retain the old
translation mechanically while its promise becomes wrong. Meaning changes
still require semantic review under any key scheme.

## Three options within the same shared catalog

| Option | Recurring maintenance | Migration work and cost |
|---|---|---|
| **Retain source + semantic context** | Readable English for translators and catalog misses; current literals, extraction and gates continue. English rewording changes identity and needs merge/review; semantic context already separates homonyms and survives class renames. | No migration. Current source/default and placeholder ownership remain together. Retain now given the bounded observed history. |
| **True stable IDs + registered English singular/plural defaults** | English-only rewords can retain Spanish. Maintain ID/context ownership, English defaults, translator-visible source/comments, placeholder schemas and a process to flag stale meaning. No English PO is intrinsically necessary, but a reviewed English register/fallback is. | Inventory and map identities; adapt markers, consumers, completeness, fuzzy/default-change review and rendered-equivalence checks; regenerate PO/MO. At least **435 contextual identities** require disposition, including **five plurals and 25 contexts**. This is not 435 unique English strings or 435 proven human edits. |
| **Selective hybrid for repeatedly edited copy** | Keep source-keyed and true ID-backed records in one catalog. Maintain two lookup/default/marker contracts, clear ownership and completeness rules; stable-ID semantic review still applies. | Identify a measured subset, map its translations and test both paths together. Smaller inventory can reduce migration scope, but adds mixed-contract maintenance. No repeatedly edited post-migration subset is established here. |

Each option must preserve the following, with different obligations:

| Contract | Retain | True IDs | Selective hybrid |
|---|---|---|---|
| Semantic contexts | Existing literal roles. | Keep roles or an explicit equivalent, with collision checks. | Preserve context across both identity styles. |
| Five plural identities | Existing `NP_`/`npgettext` and target-language rules. | Register both English defaults and stable plural lookup identifiers; preserve target-language form selection. | Inventory affected plural units; verify both paths. |
| Readable English fallback | Source text is the fallback. | Resolve missing IDs through registered English defaults; prevent opaque ID leakage. | Fallback must follow each record's contract. |
| Named placeholder schema | Current names/types checked against translations. | Compare defaults and translations even when lookup identity is unchanged; changed placeholders can invalidate retained Spanish. | Apply the right schema checks to both. |
| Literal extraction | Existing configured literal positions. | New literal ID markers can work; extracting IDs alone does not synchronize English defaults/comments. | Extract both marker sets without duplicates or omissions. |
| Translator-visible English | Direct `msgid` source. | Keep English meaning/defaults visible and current despite opaque lookup IDs. | Document which field is authoritative for each record. |
| Completeness/fuzzy handling | Existing gates and merge review; source edits can become fuzzy. | Extend gates for register coverage, default changes and stale meaning; unchanged IDs will not force fuzzy review automatically. | Enforce both sets and their subset ownership. |
| Rendered-message contracts | Existing whole-message, vocabulary and Activity Log checks. | Demonstrate equivalent fallback, substitution, plural and rendered output after consumer/gate adaptation. | Verify interaction and equivalence across both paths. |

A stable-looking token placed **only in `msgctxt`** leaves changing English
`msgid` in the lookup key and therefore does not provide stable identity.
Semantic context and stable identity address different maintenance needs.

## Bounded fixture observations

The temporary fixture uses Python stdlib `gettext` and real GNU gettext tools,
without importing or launching the application. It demonstrates:

- Contextual homonyms resolve separately: `Save` becomes `Guardar` for a button
  and `Ahorro` for a metric, including with the same `action.save` ID.
- A source reword to `Save changes` misses the old catalog. `msgmerge` marks a
  similar reword fuzzy; normal `msgfmt` compilation still yields English for
  the changed button message. The fixture's fuzzy observation is catalog-wide,
  not proof that every reword becomes fuzzy rather than untranslated.
- A true `action.save` ID retains `Guardar` while its registered English
  default changes to `Save changes`. On a missing catalog, the English register
  returns `Save changes`; raw gettext without that fallback leaks `action.save`.
- Named plural substitution produces `1 archivo` / `2 archivos`, and the
  missing-catalog register produces `1 file` / `2 files`.
- Custom literal `ID_` / `IDN_` markers extract contexts, singular/plural IDs
  and translator comments. English defaults are comments, not lookup keys.

This synthetic **two-form English/Spanish fixture** proves feasibility only.
It does not establish production marker, completeness, placeholder-review,
rendering, multi-form-language, collision or migration compatibility. It does
not implement a production register or measure translator effort. The fixture
ran on editable Python 3.14.8, not bundled Python 3.11.

Python's [gettext reference](https://github.com/python/cpython/blob/main/Doc/library/gettext.rst)
documents contextual lookup and fallback. GNU's
[fuzzy entries](https://www.gnu.org/software/gettext/manual/html_node/Fuzzy-Entries.html),
[translated entries](https://www.gnu.org/software/gettext/manual/html_node/Translated-Entries.html),
[msgmerge](https://www.gnu.org/software/gettext/manual/html_node/msgmerge-Invocation.html),
[xgettext](https://www.gnu.org/software/gettext/manual/html_node/xgettext-Invocation.html)
and [plural entries](https://www.gnu.org/software/gettext/manual/html_node/Entries-with-Plural-Forms.html)
document the relevant tooling contracts. Official references were fetched via
library-first Context7 during research on 2026-10-21; local results above are
separate direct observations.

## Re-evaluation triggers

Reopen the decision when one of these is observed:

1. Repeated, independently committed **English-only editorial rewords** require
   manual Spanish remapping, rather than new content or changed meaning.
2. Additional languages show recurring per-language remapping/review burden.
3. A separately selected integration requires durable translation identity.

Collect concrete revisions, examples and actual effort when available. Compare
a bounded true-ID or hybrid pilot against the source-key baseline, including
default/placeholder drift and semantic review costs. The current short window
does not quantify that benefit; technical feasibility alone is insufficient.

## Provenance, reproduction and limits

Research scripts and fixtures stay under `/tmp/idasen-phase35-evidence`; no
repository probe is retained. The durable measurements, classification and
decision are recorded here so their argument survives removal of temporary
files. Exact baseline inputs remain retrievable from Git. From the repo root:

```bash
git rev-parse HEAD
git rev-parse --is-shallow-repository
git rev-list --max-parents=0 8382394e0268f359aec79d616f14982fcc05bd83
git log --reverse --format='%H %aI %s' 8382394 -- po/es.po
git show aba35cd62388de156535268a0e7e30a2ae0aae9d:po/es.po
git diff 1f3a0e1 aba35cd -- src/idasen_companion/gui/pages/overview.py src/idasen_companion/gui/setup_wizard.py src/idasen_companion/gui/util.py src/idasen_companion/core/logmsg.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/idasen-phase35-evidence/history.py > /tmp/idasen-phase35-evidence/history-output.json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/idasen-phase35-evidence/proof.py > /tmp/idasen-phase35-evidence/proof-output.json
```

`history.py` writes `history.json` and emits two consecutive JSON documents to
`history-output.json`; that stdout file is not one JSON object. Its bounded
parser joins continuation strings and excludes obsolete/header entries; it is
not a general PO library or independent extraction oracle. Its TS comparison
does not measure TS headers/locations. Source-only overlap discovery ignores
context deliberately. The separate `translation-overlap.py` / JSON compare
Spanish form sets across exact overlapping sources, not role-by-role mappings.

`proof.py` writes `proof.json`, `proof-output.json` (redirected stdout),
`old.po`, `new.pot`, `stable.po`, `merged.po`, their three MOs, `markers.py`
and `ids.pot`. Captured GNU argv in `proof.json`, with
`E=/tmp/idasen-phase35-evidence`, are exactly:

```bash
msgmerge --previous --quiet "$E/old.po" "$E/new.pot" -o "$E/merged.po"
msgfmt "$E/old.po" -o "$E/old.mo"
msgfmt "$E/merged.po" -o "$E/merged.mo"
msgfmt "$E/stable.po" -o "$E/stable.mo"
xgettext --language=Python --from-code=UTF-8 --keyword= --keyword=ID_:1c,2 --keyword=IDN_:1c,2,3 --add-comments=Translators: --add-location=file "$E/markers.py" -o "$E/ids.pot"
```

Measured versions: **Git 2.56.0, editable Python 3.14.8, GNU gettext 0.25.1**.
No install or translation-build invocation is needed for this assessment.
Before the report commit, both bounded commands reproduced at baseline HEAD
on 2026-10-21. Appendix B hashes identify those exact inputs/results.
After the documentation commit, history reproduction reports the new execution
HEAD; immutable catalog measurements remain the same. `history.json` therefore
has a new hash. `ids.pot` has an unpinned generated timestamp, so its byte hash
may also differ while extracted identities remain equal.

The final-tree evidence runner is
`/tmp/idasen-phase35-final-evidence/run.py "$PWD"`, invoked with
`.venv/bin/python`. It records actual execution HEAD, UTC start/end, exact
argv, versions, environment changes, input/output/log hashes and results in a
unique run directory. It reruns both bounded scripts, collects the focused
suite, then runs the seven existing translation modules offscreen on a private
D-Bus session. The focused set is **165 cases**; the receipt, rather than this
pre-run report, establishes its final pass/skip counts.

The pytest command shape is:

```bash
dbus-run-session -- .venv/bin/python -m pytest -o addopts= -p no:cacheprovider -q \
  tests/test_gettext_translator.py tests/test_translation_markers.py \
  tests/test_extraction_scope.py tests/test_terminology.py \
  tests/test_baseline_vocabulary.py tests/test_whole_message_rendering.py \
  tests/test_log_catalog.py
```

The runner removes inherited `DBUS_SESSION_BUS_ADDRESS`, `DBUS_SESSION_BUS_PID`
and `DBUS_SESSION_BUS_WINDOWID`; sets `QT_QPA_PLATFORM=offscreen` and
`PYTHONDONTWRITEBYTECODE=1`; and assigns unique `XDG_CACHE_HOME`,
`XDG_CONFIG_HOME` and mode-0700 `XDG_RUNTIME_DIR` beneath its run directory.
It also writes JUnit results. No application/daemon entry point is invoked and
the user's live processes are not inspected or interrupted.

Retention is **0 added / 0 expanded / 0 removed permanent tests**, with no
retained repository probe. The final runner verifies all 173 protected inputs
and 46 capture hashes, including the user's dirty `AGENTS.md`, and the exact
one-report committed diff. Full-suite, mypy, Pylint and Python 3.11 compilation
are **not rerun** or presented as fresh evidence. Independent document review,
security review and canonical verification remain subsequent closure gates;
this report does not close a todo or capture.

## Appendix A: all 32 migration candidates

Window: last TS snapshot `1f3a0e16827862a2a02b66e4641b78e02dc8faba` plus root
legacy PO, compared with shared catalog `aba35cd62388de156535268a0e7e30a2ae0aae9d`.
Primary labels partition the discovery candidates; mixed changes remain visible.

| # | Old source | New source/role | Primary category; overlaps |
|---|---|---|---|
| 1 | `%d min` | `%(minutes)s min` | Formatting/placeholder. |
| 2 | `%n minute(s)` | Existing `%d minute` / `%d minutes` pair | Plural/consolidation. |
| 3 | `%s (%s)` | `%(name)s (%(height)s)` | Formatting/named placeholders. |
| 4 | `%s for %s` | `%(position)s for %(duration)s` | Formatting/named placeholders. |
| 5 | `%s · %s` | `%(position)s · %(status)s` and `%(status)s · %(countdown)s` | Formatting/named placeholders; one source had different roles. |
| 6 | `%s — the desk stays put` | Overview wrapper removed | Retirement/layout; words removed. |
| 7 | `Automation runs %s, %s–%s. Outside these hours the desk stays put.` | Named days/start/end, otherwise same sentence | Formatting/named placeholders. |
| 8 | `First run: imported settings from idasen CLI config (mac=%(mac)s, %(presets)s preset(s))` | Real preset/presets plural pair | Plural/consolidation. |
| 9 | `It will remind you to alternate sit and stand while you work.` | `It will move the desk between sit and stand while you work.` | Semantic rewrite. |
| 10 | `No timer and no reminders. Presets, the tray menu and the statistics all still work — the desk only moves when you say so.` | Same paragraph beginning `No timer.` | Semantic rewrite. |
| 11 | `Preset '%s' set to %s.` | `Preset '%(name)s' set to %(height)s.` | Formatting/named placeholders. |
| 12 | `Remind me to sit and stand` | `Move the desk for me` | Semantic rewrite. |
| 13 | `Scan finished: %(count)s device(s) found.` | Real device/devices plural pair | Plural/consolidation. |
| 14 | `Scanning… (about 10 s)` | `Scanning… (about %(duration)s)` | Formatting/localized duration. |
| 15 | `Snooze 10 min` | `Snooze %(duration)s` | Formatting/localized duration. |
| 16 | `Snoozed for %(minutes)s minutes.` | `Snoozed for %(duration)s.` | Formatting/localized duration; parameter/wire semantics change. |
| 17 | `Standing share = standing time / tracked time per day. 14-day average: %(pct)s%%.` | Same text with `%(pct)s.` | Formatting/localized percentage. |
| 18 | `The background service could not be started:\n%s\n\nTry running this in a terminal, then continue:\n  %s` | Named error/command | Formatting/named placeholders. |
| 19 | `The background service could not be started:\n%s\n\nTry running this in a terminal:\n  %s` | Named error/command | Formatting/named placeholders. |
| 20 | `Today: %s sitting / %s standing` | `Today: %(sitting)s sitting / %(standing)s standing` | Formatting/named placeholders. |
| 21 | `alternating sit / stand while you're at the desk` | Reason becomes empty | Retirement/content removal. |
| 22 | `automation resumes on its own` | Reason becomes empty | Retirement/content removal. |
| 23 | `no input for %s min — the timer is paused` | `no input for %(idle)s` | Semantic shortening AND localized substitution. |
| 24 | `presets and manual moves still work` | Reason becomes empty | Retirement/content removal. |
| 25 | `runs %s %s–%s` | `%(days)s %(start)s–%(end)s` | Semantic shortening AND named placeholders. |
| 26 | `runs on a schedule` | Config-absent reason becomes empty | Retirement/content removal. |
| 27 | `switched to another user or console — the timer is paused until you're back` | Reason becomes empty | Retirement/content removal. |
| 28 | `the desk couldn't be reached — the cycle keeps running and will try again` | `couldn't reach the desk` | Semantic shortening. |
| 29 | `the desk was moved off sit / stand — automation resumes when it's back at a preset` | `desk isn't at a preset` | Semantic shortening. |
| 30 | `the desk won't move until you resume` | Reason becomes empty | Retirement/content removal. |
| 31 | `the timer is paused until you're back` | Reason becomes empty | Retirement/content removal. |
| 32 | `— %(reason)s` | Wrapper removed, reason rendered directly | Retirement/layout punctuation. |

Totals: **7 semantic**, **13 formatting/substitution**, **3 plural/consolidation**,
**9 retirement**. This is not a bijective semantic migration map or seven
avoidable translator jobs. Review source/catalog diffs when challenging a row.

## Appendix B: baseline SHA-256 record

Hashes below were captured after the bounded pre-commit reproduction. Paths
under `E/` mean `/tmp/idasen-phase35-evidence/`. Final-run receipts hash current
versions again, including context/research, all protected inputs and the report.

| Input/result | SHA-256 |
|---|---|
| `E/history.py` | `9a54663a3d5a84a0c8360b7e7b4e150c1cfc292ea9b0414d6127857ff3a83106` |
| `E/proof.py` | `f55fafba32aef1b6c5f9211f25aad400c99503f056bf5c1d4cc429653a1b79e8` |
| `E/migration-classification.md` | `6b905c517a0c400826afa08c50322b8aad18cced515b96825b3c5744053e15ce` |
| `E/history.json` at baseline HEAD | `cdcbc0a595cfc9ea7879006f848fe7d9791eb15d295a25b697fa58f65c329bc8` |
| `E/proof.json` | `b9449a54d157d1ae7e197eddce3bbef81442352f44fb263eb17c4b85176706e7` |
| `E/old.po` | `d8f172cd9ea03bd288a77c6526c49928dd08a7e4281b855b0ed289f59c3dd67f` |
| `E/new.pot` | `1f6f61a75bae537a4658221ca3a88605b75e8f6d90b21e053c7518eb992e0c53` |
| `E/stable.po` | `9bcf6cbfb71906c9f0f142747eaf9b1aa0350f24d1f4d03da3c41dcc16402ef6` |
| `E/markers.py` | `6e8489b47388ae4d3fa8b821137774554769c878e180babb0c6894f5962e35ce` |
| `src/idasen_companion/core/i18n.py` | `2be2cf209843b2d5cd2adf8d7e927305b7945eee60de2672f5e6dfe7cf547a0d` |
| `src/idasen_companion/core/logmsg.py` | `128a6d9765a072f8fc5b18abad2c48abe9c0901d2d8058c89dfcceeb10c7c33f` |
| `scripts/build-translations.sh` | `40a1d3c5ce003bf4e41c0045792a198bdfea435716659c25810e5782033a75ec` |
| `po/es.po` | `fc37ce5f41a55d05fef15a91eec1c482d67552e2888efbb0ef75f203e6984c95` |
| `po/idasen_companion.pot` | `7cd9e57fa578ccb36abcded7788ef5d638e2cd858ec6399a494b153e4b58b304` |
