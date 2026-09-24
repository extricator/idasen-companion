# Translating Idasen Companion

All app-owned messages use one contextual GNU gettext catalog. GUI, daemon,
Activity Log and future CLI strings are extracted into
`po/idasen_companion.pot`; each language edits `po/<lang>.po`; compiled `.mo`
files ship under `src/idasen_companion/locale/`.

Qt remains responsible only for standard widget text such as dialog buttons.
`gui/i18n.py` installs Qt's prebuilt `qtbase` translator, not an app-owned Qt
catalog. The committed `.ts`/`.qm` files are frozen migration evidence and are
inactive at runtime; do not edit them. Phase 7 removes them after the migration
audit is no longer needed.

## What is translated

The shared catalog covers:

- windows, pages, tray menus and app-owned dialogs;
- daemon desktop notifications;
- shared presentation vocabulary and plurals;
- Activity Log messages, rendered in the reader's selected language;
- CLI messages when the CLI is added.

Journald and free-form diagnostic lines deliberately remain stable English.
Activity Log entries are different: the daemon sends a stable message id,
English fallback and raw parameters, and the reader renders a recognized id
through its own catalog. An older reader therefore still shows a newer
daemon's English fallback instead of failing.

`[ui] language` binds the app gettext catalog in every process. `system`
follows the process environment; another value names a catalog such as `es`.
Missing catalogs and missing individual entries fall back to the English source
string. The GUI applies a changed language after restart; the daemon rebinds on
config reload.

## Semantic contexts

Messages are keyed by English source plus a literal semantic context. Contexts
describe the role—`overview`, `settings`, `activity-log.entry`—rather than a
Python class name. This lets identical English words translate differently
when they mean different things and avoids class renames orphaning messages.

Use whole sentences and named placeholders whenever a translator may need to
reorder values:

```python
text = pgettext(
    "tray",
    "%(position)s for %(duration)s",
) % {"position": position, "duration": duration}
```

Source and translation must preserve the same placeholder names and conversion
types. Escape a literal percent as `%%`.

For real counts, use the catalog's plural rule rather than `(s)` or a Python
`count == 1` branch:

```python
text = npgettext(
    "activity-log.entry",
    "%(count)s device found.",
    "%(count)s devices found.",
    count,
) % {"count": formatted_count}
```

Spanish currently has two forms, but the code must remain valid for languages
with more.

## Translator comments

Put a comment immediately before the extraction call and begin it with
`Translators:`. The build passes that prefix to `xgettext`:

```python
# Translators: Text shown by the desktop's permission dialog.
reason = pgettext("background-permission", "Start automatically at login")
```

Keep the comment about meaning, grammar or placeholder content. Do not restate
the English sentence.

## Glossary

Established terminology is enforced in `tests/test_terminology.py`. Add a term
to its `TERMS` mapping when the project needs a stable cross-screen word. The
check ignores named placeholder identifiers, which are code and remain
byte-identical in every translation.

## Prerequisites

Install GNU gettext tools: `xgettext`, `msginit`, `msgmerge` and `msgfmt`.
PySide or Qt Linguist tools are not part of the app-catalog workflow.

## Add a language

Example: French (`fr`).

1. Refresh the template:

   ```bash
   bash scripts/build-translations.sh
   ```

2. Create the PO file:

   ```bash
   msginit --no-translator --locale=fr \
     -i po/idasen_companion.pot -o po/fr.po
   ```

3. Translate `po/fr.po`. Preserve every `msgctxt`, placeholder and plural form.
4. Re-run `bash scripts/build-translations.sh`. Languages are discovered from
   `po/*.po`, so no source-code list needs editing.
5. Commit the `.po` and compiled `.mo` together.

English is the source language and needs no catalog.

### First right-to-left catalog

The GUI already maps its known asymmetric layouts and custom painting through
Qt's selected layout direction, but that is structural readiness rather than a
claim that an RTL language is supported. Before the first Arabic, Hebrew or
other right-to-left catalog is released, it requires both a native-speaker
linguistic review and the installed-GUI visual walk in
`docs/MANUAL-TESTING.md`. Do not add the language to a release based only on
the offscreen geometry suite or machine-generated translations.

## Update catalogs after a string change

Run:

```bash
bash scripts/build-translations.sh
git diff --check
```

The build scans every Python file under `src/idasen_companion`, records
filename-only locations, pins the POT creation date, merges each discovered PO
and compiles its MO. Running it twice without source or translation edits must
produce no diff.

The one-time migration can be audited or replayed while the frozen Qt catalog
exists:

```bash
.venv/bin/python scripts/migrate-contextual-gettext.py rewrite --check
.venv/bin/python scripts/migrate-contextual-gettext.py catalog \
  --po /path/to/pre-migration-es.po --output /tmp/replayed-es.po
```

The rewrite command uses Python AST source locations and refuses dynamic
`tr(...)` calls. The catalog command combines the new POT, old PO and frozen TS
data and refuses ambiguous translations.

## Developer API

Import runtime lookups from `core.i18n`:

- `_`, `pgettext` for immediate singular messages;
- `ngettext`, `npgettext` for immediate plurals.

Calls intended for extraction must pass literal contexts and source strings.
The extraction-freshness tests catch markers outside the configured keyword
positions.

For a message stored at module import and translated later, use `P_` or `NP_`
from `core.presentation.register`. They return string-compatible keys carrying
their semantic context; `GettextTranslator` performs the lookup at render time,
so a later language rebind remains visible.

Do not use `QObject.tr`, `QCoreApplication.translate`, `QT_TRANSLATE_NOOP`,
opaque gettext source ids, sentence fragments, or hand-written plural
selection for app-owned messages.

## Try it

Choose **Settings → General → Language** and relaunch, or test from the
environment:

```bash
LANGUAGE=es LANG=es_ES.UTF-8 .venv/bin/idasen-companion
```
