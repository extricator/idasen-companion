# Architecture

Why the code is shaped the way it is — the reasoning behind the rules
`CONTRIBUTING.md` points here for, read this before you change the shape of
something rather than just work within it.

**Layered so the automation logic is UI- and IO-free.** Dependencies point
inward: `gui`/`daemon` → `core` → nothing; the desk is behind a Protocol.

The app ships **two executables that share no process state**, communicating
only over the session D-Bus: `idasen-companiond` (headless daemon, owns the BLE
connection and the state machine) and `idasen-companion` (Qt 6 / PySide6 GUI, a
thin D-Bus client plus a tray icon that never touches the desk directly).

## `core/machine.py` — the automation brain

`StateMachine` is a pure, synchronous-in-spirit state machine:
`tick()`/`start()`/`force_sync()` mutate internal state and **return a list of
`Event` dataclasses** (`StateSynced`, `TransitionCompleted`,
`TransitionSkipped`, `IdleChanged`, …). It does no logging, no stats, no D-Bus.
This is why `tests/test_machine.py` can drive it directly and assert on the
emitted events.

The daemon's `_handle_event` (`daemon/main.py`) is the *only* place events
become side effects (stats rows, ring-log lines, D-Bus signals). When changing
automation behavior, prefer emitting or altering an event over reaching into
the daemon.

## Two idle thresholds

The central design point. A **lenient** threshold gates time *accounting* (how
long you've been at the desk); a **strict** recent-input threshold gates
*movement* (never move the desk while you might be away).

Lock counts as idle. Suspend/resume is caught via a wall-clock jump and never
triggers a surprise move. Stats time is attributed in the daemon's `_tick` to
the position held, independent of automation freeze states.

## A brief absence doesn't reset the cycle

Lock and away flip the idle flag the instant they happen, with no duration
attached, so the plain idle→active reset used to discard a whole cycle for a
60-second screen lock. `tick` measures the absence instead, backdated to when
the user actually left (plain idleness is only noticed once `idle_ms` has
already crossed the threshold), and only one lasting `idle_threshold` abandons
the cycle.

This is a deliberate divergence from the reference script, which resets on any
lock.

## A shared desk is the design, not a conflict

One machine, several accounts, one desk is the *expected* arrangement.

Ownership is logind's `Session.Active` on the user's Display session
(`daemon/idle.py` `SessionActiveMonitor`): the kernel guarantees exactly one
active session per seat, so foreground is a free, race-free lease — there is
deliberately **no lock file or cross-user coordination**.

While backgrounded, a daemon does no desk IO *of its own* (no periodic sync, no
held poll, no startup read, no adapter scan) and releases the BLE link; it still
obeys explicit D-Bus/CLI requests and hands the link straight back after.
Returning to the seat reconciles unconditionally, since the desk may have moved
however brief the switch. Every uncertainty degrades to "foreground", so a
single-user machine is unaffected.

Statistics are **per-user** by decision — it's *your* sit/stand time — so each
account's history omits the other's hours, and a position change found on
return is still recorded as an external move.

Known limits: multi-seat setups, and daemons with no graphical session, all
read as foreground. Both are recorded in `TODO.md`.

### The four `SEAT_*` verdicts

The load-bearing distinction is `SEAT_NONE` (logind answered: this account has
no session *on a seat* → stand down) versus `SEAT_UNKNOWN` (couldn't ask →
carry on, as always). Conflating them would let one logind hiccup switch a
working install off.

`SEAT_NONE` matters because every presence signal fails open there at once: the
idle providers are session-scoped, so with none available `get_idle_ms` returns
a flat 0 — *"at the keyboard right now"* — and lock detection reports unlocked.

### Two logind traps, both verified on a live system

* `User.Display` is *not* necessarily graphical. logind prefers a graphical
  session but falls back to a tty one, so an SSH login lands there.
* Every *seatless* session reports `Active=true`, because `session_is_active()`
  is "no seat, **or** I am my seat's active session".

So the check is `Session.Seat` first — no seat means not physically at this
machine — and only then `Active`. Reading `Active` alone takes an SSH login for
someone sitting at the desk.

## `desk/port.py` — the `DeskPort` Protocol

`get_height` / `move_to` / `stop`. Two implementations: `desk/ble.py` `BleDesk`
(real, on-demand BLE that connects only when there's work, then lingers) and
`desk/mock.py` `MockDesk` (tests + `--mock-desk`).

`move_to` returning True does **not** mean the target was reached — callers
verify by reading the height back (mirrors the reference script), which is how
interruption and retry are detected.

## `daemon/` — orchestration + IO

`main.py` wires config, desk, idle/lock monitors, notifications, stats, and the
D-Bus service; the control loop calls `machine.tick()` every `check_interval`.
`service.py` defines the D-Bus interfaces `Desk1`, `Automation1`, `Presets1`,
`Stats1`, `Log1`. `idle.py` abstracts idle/lock detection across backends
(logind, Mutter IdleMonitor, XScreenSaver, `org.freedesktop.ScreenSaver`).
`ringlog.py` is the in-memory activity log the GUI reads; `stats.py` is the
SQLite store.

### The D-Bus surface is public, including the parts the GUI doesn't use

`service.py` is an API, not an internal seam: the interfaces are on the
session bus under a well-known name, and `idasen-companion --toggle` is not
the only thing entitled to call them. A few members therefore exist with no
in-tree reader, deliberately:

- `Automation1.TimeRemaining` and `Automation1.SkipNextPending` — the GUI
  derives both from `ProgressChanged` and its own state rather than reading
  them, but they are the obvious things a status-bar script or a keyboard
  shortcut wants, and they cost a property getter each.

Anything else with no reader is dead and should go. `Desk1.HeightTimestamp`
was removed before 0.1.0 on exactly that basis — it had no client, published a
timestamp whose epoch was undocumented on the wire, and was the only reason
`StateMachine.last_height_at` existed.

`tests/test_dbus_contract.py` checks every member the GUI asks for exists on
the daemon side, in the shape it asks for it.

### Why the D-Bus wire format avoids containers

PySide6's QtDBus cannot demarshal non-variant container types. So tabular data
is returned as JSON strings and live updates are flat, basic-typed signals
(`HeightChanged`, `StatusChanged`, …) alongside standard `PropertiesChanged`.
New methods must not return arrays of structs or maps — serialize to JSON
instead.

## Logging has two axes

`docs/LOGGING.md` is the rule; this is why it exists.

**Channel** says *who a line is for* (`activity` — the person asking why their
desk moved; `diagnostic` — whoever is reading a bug report). **Level** says only
*how bad it is*. Splitting those is what stopped every level choice needing its
own argument: a BLE connect retry is a real `warning` that simply isn't for the
user, which `debug` used to stand in for.

Activity lines are **catalogued** in `core/logmsg.py` as an id plus raw
parameters (seconds, metres, state names — never pre-formatted strings, which
can't be localized). The daemon renders English for the journal; the GUI renders
its own translated sentence from `gui/log_catalog.py`, which repeats the same
English inside `QT_TRANSLATE_NOOP` because `lupdate` can't read it out of
`core/`. `tests/test_log_catalog.py` fails the build if the two drift.
Diagnostic lines stay free-form English — never translated, since they exist to
be pasted into a bug report.

**The invariant worth knowing:** any message that changes when the desk will
next move must carry `next_target`, and declares `cycle_note=True` so the
renderer appends "Next change after …". It's a catalog property rather than a
call-site habit precisely because as a habit it was forgotten on four of the
nine events that needed it.

`core/journal.py` writes structured entries straight to the systemd journal
socket (stdout capture would flatten them to `MESSAGE` and lose the id), and
reads them back via `journalctl -o json` so the Activity Log survives a daemon
restart. The GUI writes there too, for actions it takes while the daemon is down
(autostart).

## `gui/` — PySide6 client

`dbus_client.py` `DaemonClient` wraps the D-Bus calls and signals. `context.py`
`AppContext` holds the two genuinely shared things (the client + on-disk config)
and emits `configChanged`.

**Every config write goes through `AppContext.write_config(mutate)`** — nothing
else in the GUI calls `save_config`. The write is not just a write: it has to
persist, emit `configChanged` for the read-only pages, and nudge the daemon, in
that order, and one writer is what keeps those three from drifting apart. Every
page other than the settings-class ones is a read-only `configChanged`
subscriber.

Config is read with stdlib `tomllib` but **written with `tomlkit`, so user
comments and formatting survive** the round trip. This matters because a
user's config file is theirs — hand-edited comments and layout included — and
a writer that silently eats them on the next save is a bug, not a
simplification.

Each page under `gui/pages/` is an independent `Page` (see `pages/base.py`) that
owns its widgets, subscribes to the client signals it needs, and reloads lazily
via an `on_shown()` hook. `main.py` enforces single-instance (a second launch
calls `Activate()` over D-Bus) and is tray-optional.

### Two settings-class pages, one shape

Settings (how the *app* is set up: language, autostart, window & tray, desk
connection) and Automation (how the *cycle behaves*: intervals, thresholds,
policies, plus Schedule and Notifications, which exist only to serve the cycle).

Both subclass `pages/settings_form.py` `SettingsFormPage`, which owns the shared
shape — scrolling card column, label-plus-control rows, and the button footer —
and calls into `_build_cards` / `_load` / `_apply` / `_validate` /
`_update_dimming` / `_keep_on_defaults`. **Commits stay explicit and per-page**:
each page writes only its own fields, so the two can't clobber one another's
staged edits.

Overview vs. Automation: Overview acts on *this* cycle (pause, skip, snooze),
the Automation pane configures *every* cycle.

### The footer is a `QDialogButtonBox`, and that matters for more than looks

Apply, Reset, Restore Defaults. Buttons are declared by *role* and the current
Qt style lays them out (`KdeLayout`, `GnomeLayout`, `WinLayout`, `MacLayout`),
which is what keeps a deliberately desktop-agnostic app from hardcoding one
desktop's button order the way the old hand-laid row did. Their labels come from
Qt's `qtbase` catalog (installed in `gui/i18n.py`), so standard buttons need no
entry in our catalogs.

There is deliberately **no OK and no Cancel**: both mean "… *and close*", and
these are pages in a stack with nothing to close. (Okular can afford them
because its settings are a dismissable `KConfigDialog`; ours aren't.)

Dirty and at-defaults are derived by running the page's own `_apply` onto a
*copy* of the config and comparing dataclasses — never a hand-maintained list of
fields, which would drift from what the page actually writes. Apply and Reset
light up only when dirty, and **greying the footer back out is the save
confirmation**: there is no "Settings saved." message, which used to steal
layout height from the scroll viewport and clip the buttons.

Restore Defaults *stages* rather than writes, so Reset still undoes it, and
`_keep_on_defaults` names the fields it must not touch — today the Bluetooth
address, because defaults are a preference reset, not a factory wipe.

### Leaving a settings page with staged edits is gated

Page switches, window close and the tray's Quit all route through
`MainWindow.confirm_unapplied_edits` (Apply / Discard / Cancel). Because leaving
is what's gated, **only the current page can ever be dirty** — rely on that
rather than scanning every page.

Sidebar navigation therefore runs through the single `_on_nav_changed` slot: a
veto has to leave the stack index, the bold highlight and the sidebar selection
all agreeing on the old page, which three separate `currentRowChanged`
connections could not do.

Minimising to the tray deliberately does *not* prompt — the window is put away,
not dismissed, and a lit Apply says the values are unwritten.

### The tray tooltip is a hand-served StatusNotifierItem

`gui/sni.py` replaces Qt's own SNI object so the tooltip can have a bold title
and lighter detail, which `QSystemTrayIcon.setToolTip()` cannot express. Its
module docstring carries the full reasoning, including why Qt's DBusMenu
survives the takeover untouched. Any failure falls back to the plain
`QSystemTrayIcon`.

## Internationalization: two catalogs, because the daemon is Qt-free

Compiled by `scripts/build-translations.sh`; see `docs/TRANSLATING.md`.

* **GUI** uses Qt Linguist. Strings are wrapped in `self.tr(...)` /
  `QCoreApplication.translate(...)`; `gui/i18n.py` installs the `QTranslator` at
  startup (before any widget is built) for the `[ui] language` config value
  (default `"system"` = `QLocale.system()`). Sources: `translations/*.ts` →
  shipped `gui/translations/*.qm`. The language is chosen in **Settings →
  General**; because strings bake at construction it applies on relaunch.
* **Daemon notifications** use stdlib `gettext` (`_()` / `ngettext`, in
  `core/i18n.py` so any Qt-free caller can reach it), since the daemon can't
  depend on Qt. Sources: `po/*.po` → shipped `locale/<lang>/LC_MESSAGES/*.mo`.
  `daemon/i18n.py` keeps only `human_delay`, whose plural literals are
  extracted from a `daemon/`-scoped scan.
* **The Activity Log** takes a third route, because the daemon composes it and
  can't use Qt: the wire carries a message id plus raw parameters, and the GUI
  renders from `gui/log_catalog.py`. **journald stays English on purpose**
  (stable and greppable for bug reports) — same event, two renderings.

Compiled catalogs are committed, and ship via `MANIFEST.in` +
`[tool.setuptools.package-data]`.

## The presentation invariant: rendering vs. policy

**The rule.** A surface backend may decide **how an atomic value is
rendered** — a number's decimal point, a time's hour format, where a
message's text comes from — and may **not** independently decide **product
formatting policy**: which threshold applies, which fields compose a
sentence, whether a value shows at all. Concretely, a backend's protocol
exposes operations (`number`, `integer`, `time`, `date`, `message`,
`plural`) and never a locale-database field — no `decimal_separator()`, no
`month_names()`, no `am_text()`, no `first_day_of_week()`. A capability the
shared layer needs is an operation a caller asks the backend for, never a
field a caller reads and formats itself.

**The sanctioned divergence.** The permission is a category, not a list:
any of the seam's four `LocaleFormatter` operations may render an atomic
value differently between backends — the same latitude the paragraph
above grants, applied to a value's own representation rather than to
whether it appears at all — and none may differ in product formatting
policy. Swept and recorded cell by cell across the seam's closed
surface, six of the seam's eight surface cells diverge; the two that do
not, `NumberSpec.trim_trailing_zeroes` and
`IntegerSpec.min_digits`, both resolve through Python's own string
handling before either backend renders a digit. The worked example is the
four date/time helpers: `fmt_clock`, `fmt_day_label`, `fmt_day_heading`
and `fmt_day_and_clock` (`core/presentation/dates.py`'s `clock`,
`day_short`, `day_heading`, `day_and_clock`, reached through `Formatter`).
Qt renders through `QLocale` — `lun 17 ago 2026`, `14:32` in `es`;
`Mon 17 Aug 2026`, `2:32 PM` (with a narrow no-break space) in `en`. The
Qt-free backend renders both `DateStyle` members as one ISO 8601 date,
`2026-08-17`, in both shipped languages, and `14:32` for the time style,
unchanged. Numbers diverge on the same permission: a height renders
`110,5` through Qt in `es` and `110.5` through the Qt-free backend, which
reaches every height the app shows — `height_value`, `height` and
`preset_tick`.

**`grouping` is named, and answered.** `NumberSpec.grouping` and
`IntegerSpec.grouping` are a divergence the seam permits that no shipped
caller reaches: both default to `False`, and only tests pass `True`. Were
one to, Qt would render `12.345,5` in `es` against the Qt-free backend's
`12,345.5` — five integer digits, not four, because Qt's Spanish CLDR data
inserts no group separator below five, so a four-digit example would show
only the decimal point differing. A backend answering a *style* or a
*spec* differently, as all of the above do, is inside the permission; one
deciding which threshold applies, which fields compose a sentence, or
whether a value shows at all is not.

**Why.** glibc defines the 12-hour clock format as the empty string for
`es_ES`, so deriving a 12-hour flag from the process locale would hand a
Spanish reader a *worse* answer than a plain 24-hour `14:32` — not a
locally correct one this backend happened to skip. The divergence between
the two backends does not disappear; it is now `lun 17 ago 2026` versus
`2026-08-17`, where it used to be against a private table of fixed English
weekday and month names. What changed is that the Qt-free side no longer
disagrees with the window *in English words*.

**This is this project's own policy, not a claim about CLDR.** A
wall-clock time and a calendar date are the two places where the locale
genuinely owns the product decision on one surface — Qt's `QLocale` has a
real answer — and cannot supply one at all on the other, since a Qt-free
process has none. That is also why these four moved last: designing the
whole abstraction around its one exception is how the exception stops
looking like one.

**Every formatter PRES-01 names, and where it ended up.** Sixteen of them —
the height, duration, countdown, status/position/preset/trigger word,
day-list and snooze/due/position-or-custom renderers, plus the four
date/time helpers above — moved to `core/presentation/`, each with a thin
`gui/util.py` forwarder of unchanged signature. Three did not move, and are
recorded here rather than left for the next reader to find by searching:

| Formatter | Disposition |
|---|---|
| `connection_state` | Its *words* moved to `words.connection_phrases`; what stays in `gui/util.py` is pairing them with a theme colour, and a theme is a Qt concept the `gui`/`daemon` → `core` → nothing rule keeps out of `core/`. A caller wanting only the wording asks a `Formatter` for `connection_phrases` instead. |
| `daemon_error_message` | Moved to `core/presentation/daemon_errors.py`, deliberately with **no** `Formatter` method — its sentences must come from the *reader's* catalog, not the daemon's own. |
| `suffix_height` / `suffix_minutes` / `suffix_seconds` | Stay in `gui/util.py`, solely because `QAbstractSpinBox.setSuffix` takes a bare string and inserts no separating space of its own — which is also why each keeps a deliberate leading space. Not named by PRES-01, but recorded here as the standing GUI-only exception it is. |

**Where this is held mechanically, not just by review.**
`tests/test_qt_free_imports.py` proves the Qt-free path never loads
`PySide6`; `tests/test_golden_presentation_contract.py` pins Qt/Qt-free
agreement for the shared formatters and the four date/time helpers'
deliberate disagreement, hand-typed as an expectation rather than captured
from a run; `tests/test_presentation_seam_sweep.py` sweeps the seam's
whole surface — every `LocaleFormatter` operation crossed with every spec
field and style member — with a recorded verdict per cell, so an
operation or a field added later with no verdict fails the build rather
than quietly widening the claim above.

The Qt-free backend's own independence has two axes, and they are held in
two different places. The **app language** — Qt's default `QLocale` and the
gettext catalog — is varied per shipped language by the golden contract
module, which renders every shared formatter through the journal pairing in
each and requires the results to agree. The **POSIX locale** is the axis a
reintroduced `import locale` or C-library date conversion would follow, and
nothing in the app language loop touches it: the proof there is
`tests/test_plain_locale.py`'s structural gate, which parses every module of
`core/presentation/` and runs everywhere the suite runs, including a
buildroot carrying no non-English langpack. Beside it, the golden module
renders the same formatters under a Spanish or German numeric and time
locale where the machine has one generated, and skips saying so where it
does not — corroboration, not the proof.

## Config

`~/.config/idasen-companion/config.toml`, overridable with the
`IDASEN_COMPANION_CONFIG` env var (used by tests and dev). Read with stdlib
`tomllib`; **written with `tomlkit` so user comments and formatting survive**.

Durations are stored as compact strings (`"45m"`, `"1h30m"`) and held in memory
as integer **seconds**. The daemon polls the file mtime and **hot-reloads** — no
restart needed. On first run it imports MAC + presets from the `idasen` CLI's
`~/.config/idasen/idasen.yaml` (`core/migration.py`).

## Renaming anything

Two identifiers here are load-bearing beyond their own file, and both fail
**silently** — green build, shipped artifact, wrong behaviour:

- **Config dataclass attribute names *are* the TOML keys.** `core/config.py`
  does `hasattr(target, key)` / `getattr(target, key)` with `key` straight
  from `tomllib`. Renaming a config *field* changes the user-facing config
  file format and breaks existing user configs. Renaming a *local* named
  `cfg` is fine; renaming an attribute is not.
- **Qt translation contexts *are* class names.** Rename a GUI class and every
  `<message>` under its `<name>` context in `translations/*.ts` orphans — the
  strings fall back to English with nothing failing.

So: never `sed` an identifier — it also renames same-named attributes on
unrelated objects. Use a scope-aware rename tool with a preview instead. After
any rename, run the suite **and**
`PATH="$PWD/.venv/bin:$PATH" bash scripts/build-translations.sh`, then diff
for new `type="unfinished"` entries — that diff is the only signal a rename
broke a catalog.

## Presets are special-cased today

`"sit"` and `"stand"` are protected presets hardcoded throughout: the engine
alternates exactly those two, and the config won't let you rename or delete
them. Making arbitrary presets first-class is a known, deliberately-deferred
cross-cutting refactor — see `TODO.md` before touching preset handling.

## Provenance

The project began as a single-file implementation. Behavior parity with it
(idle accounting, cycle variation, retry) is intentional.
