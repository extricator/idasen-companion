# Translating Idasen Companion

Thanks for helping translate! Adding a language needs **no Python changes** —
you add a language code, translate two text files, and recompile.

## What is (and isn't) translated

The app is two programs, so there are **two catalogs**:

| Surface | Mechanism | Source file | Compiled |
|---|---|---|---|
| **GUI** (windows, tray, dialogs) | Qt Linguist | `translations/idasen_companion_<lang>.ts` | `src/idasen_companion/gui/translations/*.qm` |
| **Daemon desktop notifications** | GNU gettext | `po/<lang>.po` | `src/idasen_companion/locale/<lang>/LC_MESSAGES/*.mo` |

The GUI can't share the daemon's mechanism: the daemon is intentionally
Qt-free, so it uses `gettext` instead of Qt's `tr()`.

**Deliberately left in English** (not a translation gap):

- The daemon's **journald** output. Kept stable and greppable because that is
  what a bug report needs.
- Free-form **diagnostic** lines (`RingLog.diag`), which exist to be pasted
  into a bug report.

The **Activity Log is translated**, and its strings live in
`gui/log_catalog.py` under the `LogMessage` context — that is a real catalog
context with real work in it, so do not skip it. The daemon sends a stable
message id plus raw parameters over the wire (`Log1.Entry`) and the GUI
composes the sentence itself; see `docs/LOGGING.md`.

At runtime the language comes from the **`[ui] language`** config setting
(**Settings → General → Language** in the app). Its default, `"system"`,
follows the desktop locale (`QLocale.system()` for the GUI; `LANGUAGE`/`LC_*`/
`LANG` for the daemon); any other value is a catalog code like `es`. A missing
catalog just falls back to English, so a partial translation is fine. The GUI
bakes strings at construction, so changing the language applies after a
restart; the daemon re-binds its catalog on config reload.

## Glossary

One English concept gets one Spanish word, and one Spanish word must not
cover two English concepts. On 2026-08-01, "preset" shipped as two different
Spanish words in the same session, and one of those words was *also* the
translation of the desk's physical position -- a translator picking a word
mid-sentence had no way to know it collided with an established term
elsewhere in the catalog.

The terms are declared in `tests/test_terminology.py`, not restated here --
a second copy is a second thing to keep in sync, and a document nobody
re-reads while writing a string is exactly what let the 2026-08-01 drift
through. Adding a term means adding it to that file's `TERMS` mapping. The
suite fails a translation that uses a different word for a term the file
already declares, so a colliding word choice is caught before it ships
rather than found later.

## Translation-key collisions

Source-as-key (see the [Glossary](#glossary) above) cuts both ways: that
section is one concept ending up with two words, and this one is the
opposite — two concepts wanting the same word. One English source string
maps to exactly one Spanish string project-wide, so when a second concept
wants a source string another concept already owns, that's a collision.

This project carries **no standing rewording rule** for it — that was a
deliberate decision (D-05 in
`.planning/phases/12-the-capability-seam-the-fakes-and-the-before-picture/12-CONTEXT.md`),
taken because collisions may not materialise at all, and a rule invented
before any instance exists is a rule invented without evidence. What exists
instead is a check that makes each one visible the moment it happens, so it
gets decided deliberately rather than resolved by reflex inside a large
diff — which is exactly the failure the batching requirement (`CAT-08`)
exists to prevent.

**Procedure**, when one English source string is wanted for two different
concepts:

1. Decide case by case: reword one side's English so the two no longer
   share a source string, accept the shared string as correct (the two
   concepts genuinely mean the same thing, the way window chrome often
   does), or split it another way.
2. Record the decision as a new row in the collision log below, **in its
   own commit** — never folded into a batch of string moves.
3. If the decision keeps the shared string, also add the source string to
   `REGISTERED_SHARED_STRINGS` in `tests/test_translation_collisions.py`,
   with a one-line reason. A new log row and a new register entry are the
   two halves of one decision; that test is what stops the second half
   being forgotten — it fails until both exist.

### Collision log

Empty today, on purpose: no formatter has moved yet. Phases 13-15, which
merge roughly twenty formatters into one shared vocabulary, are expected to
produce the first rows.

| Source string | The two concepts that wanted it | Decision | Commit |
|---|---|---|---|
| _none yet_ | | | |

## Prerequisites

- PySide6 tools on `PATH`: `pyside6-lupdate`, `pyside6-lrelease`, and
  optionally `pyside6-linguist` for the Qt Linguist GUI. They live in the
  project venv, not the system `PATH` — run
  `PATH="$PWD/.venv/bin:$PATH" ./scripts/build-translations.sh` rather than
  invoking them directly.
- GNU gettext: `xgettext`, `msginit`, `msgmerge`, `msgfmt`.

**Renaming a GUI class is a translation trap.** Qt translation contexts *are*
class names, so renaming one orphans every `<message>` under its old `<name>`
context in `translations/*.ts` — the strings fall back to English with
nothing failing. See `docs/ARCHITECTURE.md` § "Renaming anything" for the
recovery procedure.

## Add a new language

Example: French (`fr`).

1. Add the code to `LANGS` in `scripts/build-translations.sh`:

   ```bash
   LANGS=(es fr)
   ```

2. Generate the empty catalogs (extracts current strings, creates the files):

   ```bash
   PATH="$PWD/.venv/bin:$PATH" ./scripts/build-translations.sh
   ```

   This creates `translations/idasen_companion_fr.ts` and `po/fr.po`.

3. Translate the two files:
   - **GUI:** open the `.ts` in Qt Linguist (`pyside6-linguist
     translations/idasen_companion_fr.ts`) and fill in translations, or edit
     the XML directly (set each `<translation>` and drop its
     `type="unfinished"`).

     The catalog stores no source file/line references, so Linguist cannot
     jump to the code a string came from. That is deliberate: a line number
     moves whenever anything above the string moves, and the resulting churn
     is indistinguishable — to the CI check that regenerates the catalogs and
     diffs them — from a string shipped untranslated. Use the [Glossary](#glossary)
     for the context those references used to supply; the `<name>` context on
     each message also tells you which screen it belongs to.
   - **Notifications:** edit `po/fr.po`, filling each `msgstr`. Make sure the
     header says `charset=UTF-8` if you use accents.

4. Recompile (produces the shipped `.qm` and `.mo`):

   ```bash
   PATH="$PWD/.venv/bin:$PATH" ./scripts/build-translations.sh
   ```

5. Commit **both** the sources (`.ts`, `.po`) **and** the compiled catalogs
   (`.qm`, `.mo`) — the compiled files ship inside the package (sdist/wheel/RPM
   include them via `MANIFEST.in` + `[tool.setuptools.package-data]`).

## Update an existing language after strings change

Just re-run the build script: `lupdate` and `msgmerge` merge new/changed
strings into the existing files (keeping your translations, flagging changed
ones as unfinished), then `lrelease`/`msgfmt` recompile. Fill in the new
entries and re-run.

## Try it

Pick the language in **Settings → General → Language** (relaunch to apply), or
force it via the environment for a quick check:

```bash
LANGUAGE=es LANG=es_ES.UTF-8 .venv/bin/idasen-companion
```

## For developers: wrapping new strings

- **GUI:** wrap user-facing literals in `self.tr("...")` (inside a `QObject`
  subclass) or `QCoreApplication.translate("<Context>", "...")`. Use `%s`/`%d`
  Python formatting *after* `tr()` — PySide6's `tr()` returns a plain `str`, so
  **`.arg()` does not exist** (`self.tr("x=%s") % v`, not `.arg(v)`). Escape a
  literal `%` as `%%`. Plurals: `self.tr("%n item(s)", "", n)`.
- **`lupdate` only extracts literals inside recognized calls** (`.tr(`,
  `QCoreApplication.translate(`, `QT_TRANSLATE_NOOP(`). A `tr(variable)` or a
  custom wrapper hides the string. For module-level constants (evaluated before
  the translator is installed), mark them with `QT_TRANSLATE_NOOP("<Context>",
  "...")` and translate at the use-site — see `gui/util.py` and
  `gui/main_window.py`'s `NAV_ITEMS`.
- **Daemon:** wrap notification strings in `_("...")` / `ngettext(...)` from
  `core/i18n.py`. Keep journald/Activity-Log strings in English.
- **Shared layer (`core/`):** wrap a translatable constant with `N_("...")`
  or, for a plural pair, `NP_("singular", "plural")` — both from
  `core/presentation/register.py` — then have a `Formatter` method render it
  through the injected `Translator`. Two things about these markers differ
  from the GUI's `QT_TRANSLATE_NOOP`: neither takes a context argument,
  because `po/idasen_companion.pot` is one flat catalog with no per-context
  split for one to select; and `NP_` takes both plural forms on one call,
  written down once in the register, rather than needing both literals again
  at every call site the way gettext's own `ngettext()` does. The scope this
  register is extracted from covers every source file in the package except
  `gui/`; `tests/test_extraction_scope.py` fails the suite if a marker call
  outside that scope, or a marker the extraction keyword list doesn't
  recognize, has a literal that never made it into the `.pot`. This
  register's own entries so far: `%d hour` / `%d hours` (Spanish `%d hora` /
  `%d horas`), reusing the existing `%d minute` / `%d second` plural pairs,
  and the joining pattern `%(hours)s %(minutes)s`, which substitutes two
  already-translated duration messages into one sentence fragment (Spanish
  `%(hours)s y %(minutes)s` — the conjunction Spanish uses where English
  keeps a bare space; match this terminology rather than inventing a second
  phrasing for the same duration vocabulary).
- **Numbers and units:** render a height (or any other locale-sensitive
  decimal) with `gui/util.py`'s `fmt_number()`, not an f-string — it reads the
  default `QLocale` so `110.5` becomes `110,5` under `es`. Get a spin box's
  unit suffix from `suffix_cm()`/`suffix_minutes()`/`suffix_seconds()` rather
  than a literal `setSuffix(" cm")`, which is invisible to `lupdate` and to
  every non-English user. Both live in the `util` catalog context, so a new
  call site adds no new translation entry.
- **A translatable unit is a whole message with its substitutions named, not
  a translated fragment joined to something else** with `+`, `+=`, an
  f-string, or `.join()` — a translator can't reorder pieces the code has
  already stuck together, and a broken one still ships looking fine in
  English. The three
  spin-box suffix helpers above are the only exception, because
  `QAbstractSpinBox`'s suffix API takes a plain string and adds no space of
  its own. `tests/test_translation_markers.py` enforces this in every scope
  of every file under `src/idasen_companion` — module and class bodies
  included, which is where a string that has to exist before the translator
  loads lives; see `CLAUDE.md` § "Adding user-facing strings" for the full
  rule.
- After adding strings, run `scripts/build-translations.sh` and commit.
