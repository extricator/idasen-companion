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
can't be localized). The canonical English and structure live once in
`core/logmsg.py`. The daemon renders stable English for the journal; the reader
passes the same `Message` through its selected gettext catalog and Babel-backed
value formatters. Unknown ids use the English text carried on the wire.
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

## Internationalization: one contextual app catalog

Compiled by `scripts/build-translations.sh`; see `docs/TRANSLATING.md`.

* GUI, daemon, shared presentation and Activity Log messages use stdlib
  gettext through `core/i18n.py`. English source plus a literal semantic
  context is the key; plurals use `npgettext` or deferred `NP_` keys.
* `scripts/build-translations.sh` scans every package Python file into one POT,
  merges every discovered `po/*.po`, and compiles the shipped `.mo` catalogs.
* `gui/i18n.py` also sets `QLocale` for native widget behavior and installs
  only Qt's prebuilt `qtbase` translator for standard dialog/widget text.
* The Activity Log wire continues to carry id, raw parameters and an English
  fallback. **journald stays English on purpose** (stable and greppable for bug
  reports), while a recognized Activity Log id renders in the reader's
  language.

The old app `.ts`/`.qm` files are frozen, inactive migration evidence until
Phase 7; they are not a second runtime catalog.

Compiled catalogs are committed, and ship via `MANIFEST.in` +
`[tool.setuptools.package-data]`.

## One locale value engine, independent display preferences

Every app-owned number, integer, percentage, date, time and unit is rendered by
`core/locale_profile.py` through Babel 2.18. GUI, daemon and future CLI code
therefore receive the same CLDR answer for the same explicit app locale.
`QLocale` remains in the GUI only for native widget input/display behavior,
layout direction, locale selection and Qtbase translations; it does not render
application labels.

`LocaleProfile` is immutable and Qt-free. Consumers ask it for operations
(`number`, `integer`, `percent`, `date`, `time`, `unit` and plural
category) with explicit precision/grouping/style arguments. They do not read
CLDR fields and assemble localized output themselves. The existing
`Formatter` facade owns product policy such as height conversion, duration
thresholds and whole-message composition, and delegates each atomic value to
the profile.

Three settings are intentionally independent:

- `[ui] language` selects the gettext app catalog, QLocale and Babel profile,
  so it controls words, number symbols, date names and localized meridiem text.
- `[ui] units` answers directly for `cm`/`in`; `system` follows
  `LC_ALL`, `LC_MEASUREMENT`, then `LANG`. US and Liberia default to
  inches; every other territory, including the UK, defaults to centimetres.
- `[ui] clock_format` answers directly for 12/24 hours; `system` follows
  `LC_ALL`, `LC_TIME`, then `LANG`, and asks Babel's short-time pattern.
  A missing, POSIX/C or unsupported time locale falls back to 24 hours.

Changing the app language never changes the resolved measurement system or
hour cycle. Both GUI and daemon resolve those preferences once from the same
explicit environment inputs and carry the result in `PresentationContext`.

Babel 2.18's observed `ar_EG` behavior is pinned in tests: it emits Arabic
decimal/group separators and localized date, meridiem and unit text, while the
digit glyphs remain Latin. The tests record that actual behavior rather than
claiming that every Arabic locale automatically substitutes native digits.

Compatibility names `PlainLocaleFormatter` and `QtLocaleFormatter` remain
temporarily so later phases can migrate callers independently, but both
delegate to `LocaleProfile`; they are not separate value engines. Fresh
process tests prove the daemon/shared path imports no PySide6 or shiboken.

## Config

`~/.config/idasen-companion/config.toml`, overridable with the
`IDASEN_COMPANION_CONFIG` env var (used by tests and dev). Read with stdlib
`tomllib`; **written with `tomlkit` so user comments and formatting survive**.

Durations are stored as compact strings (`"45m"`, `"1h30m"`) and held in memory
as integer **seconds**. The daemon polls the file mtime and **hot-reloads** — no
restart needed. On first run it imports MAC + presets from the `idasen` CLI's
`~/.config/idasen/idasen.yaml` (`core/migration.py`).

## Renaming anything

Identifiers here can be load-bearing beyond their own file and fail
**silently** — green build, shipped artifact, wrong behaviour:

- **Config dataclass attribute names *are* the TOML keys.** `core/config.py`
  does `hasattr(target, key)` / `getattr(target, key)` with `key` straight
  from `tomllib`. Renaming a config *field* changes the user-facing config
  file format and breaks existing user configs. Renaming a *local* named
  `cfg` is fine; renaming an attribute is not.
- **Gettext semantic contexts are public translation keys.** Rename a literal
  context only as an intentional catalog migration; class renames themselves
  are safe because contexts describe roles rather than Python class names.

So: never `sed` an identifier — it also renames same-named attributes on
unrelated objects. Use a scope-aware rename tool with a preview instead. After
any rename, run the suite **and**
`bash scripts/build-translations.sh`, then inspect the PO/POT diff for orphaned
or untranslated entries.

## Presets are special-cased today

`"sit"` and `"stand"` are protected presets hardcoded throughout: the engine
alternates exactly those two, and the config won't let you rename or delete
them. Making arbitrary presets first-class is a known, deliberately-deferred
cross-cutting refactor — see `TODO.md` before touching preset handling.

## Provenance

The project began as a single-file implementation. Behavior parity with it
(idle accounting, cycle variation, retry) is intentional.
