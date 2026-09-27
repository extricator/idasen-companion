# Idasen Companion — TODO

Glanceable task list for anyone working on this project. Keep it current:
add new items as they're discovered, and **delete** finished ones outright —
no checkmarks, no Done section. This file is what's left to do; git history is
the record of what was done.

## Next phase — session-switch recovery and live release validation

- [ ] **Diagnose and fix the KDE Xorg fast-user-switch stall before preparing
      the next release.** After this desktop session spends roughly 15–20
      minutes in the background, the Bluetooth indicator can remain engaged
      and tray/shortcut commands queue without taking effect. Turning Bluetooth
      off and on releases the queue. On 2026-09-26 the daemon logged a switch
      away at 10:42:45 and no return until 11:11:43, just after the adapter
      reset; earlier switches logged multi-minute control-loop overruns. The
      "desk released" activity line reports the requested handoff, not proof
      that BlueZ dropped the link. Investigate which await holds the daemon's
      desk lock (especially the return-side height sync and BLE connect/read),
      then test bounded recovery with a hanging fake and a real KDE Xorg
      session switch. Acceptance: the background session releases the link,
      does no desk I/O, and responds to a command after return without an
      adapter reset or replaying a backlog of old commands. Do not stop or
      restart the installed daemon just to collect evidence.
      Failed switches showed BlueZ connected while Bleak reported disconnected;
      one also replayed a Sit request after Stop. Reads and move connections
      now have deadlines, and Stop invalidates a pending move. Session handoff
      releases this app's Bleak client and logs a remaining BlueZ link; it
      cannot safely disconnect a device-wide link with no known owner.
      Instrumented short and roughly 15-minute awake background switches
      passed, including a suspend and one fresh Stand command after return.
      Do not repeat the duration check solely to reach exactly 20 minutes.
      The intermittent orphan's source remains unproven; use the captured
      traces to diagnose it before calling the stall fixed or preparing the
      release PR.
- [ ] **Exercise the first unreleased-version main CI candidate.** Prepare a
      normal version-and-notes PR after the session-switch fix, require its
      automatic exact-head release-preparation proof, then merge. Confirm that
      full `main` CI passes on the actual merge SHA, retains one unexpired
      `release-assets` artifact with five verified packages and provenance,
      and removes its intermediate artifacts. PR #2's merged-commit run
      [36251547265](https://github.com/extricator/idasen-companion/actions/runs/36251547265)
      passed all proofs but correctly retained no candidate for tagged 1.2.0.
- [ ] **Test Release on that merged commit.** With separate authorization,
      run a `main` release dry run and check its five-asset assembly without
      publishing. With explicit publication authorization, dispatch Release
      in promotion mode using the successful exact-SHA main CI candidate;
      verify its source-job checks, version, names, notes, provenance and
      checksums, then inspect the created tag, release body, and downloaded
      bytes. If the one-day candidate expires, obtain fresh authorized source
      evidence or explicitly choose the full-rebuild path; never silently
      switch modes. Record the run IDs and results. A dry run or publication
      must not be started merely because this checklist exists.

## 1.0 release gate — manual verification

Run these immediately before the repository and the release go public, against
the **published artifacts** rather than CI builds. Deliberately batched here
rather than done piecemeal during development: verifying the thing users will
actually download, once, is worth more than verifying a CI build twice.

Nothing below is reachable from an automated test — each needs a real desktop,
a real portal backend or a real machine. A green CI run says nothing about any
of them.

**BLE hazard, applies to all of these.** The RPM daemon is normally installed,
enabled and active, and it holds the desk's single LE slot. The Flatpak and the
`.deb` each ship their own daemon. Stop the RPM unit *cleanly* before starting
another — never mid-move, never `kill -9` — or two clients race for the one
slot and wedge the Bluetooth stack. Re-enable it afterwards.

- [ ] **Verify login autostart under the Flatpak sandbox** — the code exists: a
      Flatpak-detection branch, the QtDBus
      `org.freedesktop.portal.Background.RequestBackground` call, translated
      prompt text, and a persisted config flag standing in for the readback API
      the portal does not offer. What has *not* happened is the only thing that
      can settle it: a real portal backend raising its dialog, a real host
      autostart entry, and a real logout and login. Bus-mocked tests cannot
      reach any of that. Procedure in `docs/MANUAL-TESTING.md`; background in
      `packaging/flatpak/README.md`'s "How it differs from the RPM" table.
      Check **both** directions — turning it off is where the event-loop
      deadlock and the checkbox-that-lied both lived.
- [ ] **Install the `.deb` on a real Debian 13 or Ubuntu 25.10+ machine** — CI
      genuinely proves what PKG-02 and PKG-03 ask for: `apt install` resolves
      every dependency in a clean Debian 13 container, the user unit lands
      present and in a normal off state, `enable --now` starts it, and the GUI
      entry point resolves against the archive's PySide6. None of that is a
      desktop. Unproven: that the tray icon appears, that the desktop entry and
      the AppStream metainfo show up in a software centre, and that the app
      actually drives the desk from a distro-packaged PySide6 rather than the
      wheel every other path uses. Also worth confirming the honest failure on
      an *unsupported* release — an older LTS should refuse with an unmet
      dependency rather than half-installing.
- [ ] **Confirm the RPM and Flatpak beyond "it installed"** — both are installed
      and nominally working as of 2026-08-09, which covers install and launch
      but not the software-centre presentation the metainfo was added for, nor
      a full automation cycle against the desk from inside the sandbox.

## Features / enhancements (deferred)
- [x] **A `status` command, so the desk can be read from a terminal** — delivered
      by `idasen-companion status`, with Desk / Automation / Today sections,
      localized values and explicit exit/stdout/stderr behavior. The original
      design record follows: the
      command line can only *write* today: `--toggle`, `--sit`, `--stand`,
      `--stop` and `--preset` (`gui/main.py:39`) each fire one method and exit,
      and every readable fact — height, sit/stand word, connection, cycle
      position, next move — exists only in the GUI, so answering "am I due to
      stand up?" means launching a window. Nothing is missing from the daemon:
      `Desk1` and `Automation1` publish all of it as properties
      (`daemon/service.py:44-56`, `daemon/service.py:129-157`) and
      `Stats1.GetDaily` returns the day's totals as JSON. **Shape is settled**
      (2026-08-19) — three labelled sections, Desk / Automation / Today,
      carrying the Overview page's content in the *tray tooltip's* wording,
      since the tooltip is the one place already tuned for a glance and its
      "Standing for 42 min" and "sitting down in 17 min" both say things
      Overview does not. **The height and duration vocabulary is no longer
      the obstacle it was.** It now lives under `core/presentation/`,
      unit-explicit and Qt-free, reached through a `Formatter` built onto an
      explicit `PresentationContext` a caller constructs — no module global,
      no argument-less `QLocale()` read, nothing that only resolves correctly
      after a GUI-specific startup sequence has run. What a status command
      needs from the shared vocabulary is fully available now: the status,
      position, preset and trigger words (Phase 14) and the four date/time
      helpers (Phase 15) all render through `core/presentation/`, reachable
      with no `gui/util.py` involvement. Full design, traps and open
      decisions (what it exits with when the daemon is down) in
      `.planning/todos/pending/2026-08-19-add-cli-status-command.md`.
- [ ] **Clear statistics / history button** — a control on the Statistics page to
      wipe the recorded sit/stand history (the daily-totals data and the recent
      transitions). Needs a daemon-side method to clear the stats DB (wire
      change) plus a confirmation dialog in the GUI (destructive, irreversible);
      refresh the chart + transitions list afterward. Note the DB still holds
      two batches of junk left there deliberately: dev mock
      transitions from before 2026-07-18 18:00, and phantom
      `sitting→standing external` rows written by daemon restarts while
      standing. Neither is worth its own cleanup, but a wipe-everything button
      clears both for free.
- [ ] **In-app Light / Dark / System theme control** (proposed: top of Settings,
      persisted to config). The live-restyle plumbing this needed now exists —
      a restyle registry (`gui/restyle.py`) with one wiring point in
      `gui/main.py`, swept on every `QApplication.paletteChanged`, which is
      also what fixed the *system* light↔dark switch going stale. What remains
      for this feature is the setting itself: a config key, a Settings row,
      and a manual trigger that calls the same sweep the desktop switch
      already drives.
      A mechanical check that a future styled widget can't silently skip
      registration exists too: a runtime standing test in
      `tests/test_theme_restyle.py` builds a fully populated window and
      asserts every live stylesheet names only the current theme's tokens,
      rather than an AST script over `scripts/` — a source-level check can't
      see a token read into a local a few lines above the call or a baked icon
      tint, and a test importing `scripts/` needs its own `MANIFEST.in` entry
      or the RPM's install check dies at collection while every local run
      stays green.
- [ ] **Setup wizard** (`gui/setup_wizard.py`) still uses the pre-redesign look;
      design README §6 pages "remain to be done in this style". It carries no
      theme-derived stylesheet at all, so the live-switch work above left it
      untouched — what remains here is purely the visual redesign.
- [ ] **The date shape has no user override, now that the clock does** —
      `[ui] clock_format` lets a user pin 12- or 24-hour, and the app resolves
      it once in `core/clock_format.py` and hands a `TimeStyle` to both
      backends. `DateStyle` has no equivalent: the window still renders
      whatever `QLocale` says and the Qt-free backend still renders ISO,
      with nothing the user can say about either. Nobody has asked for it,
      and it was left out of the clock work deliberately rather than
      overlooked — widening into it without deciding out loud is what that
      restraint was protecting. Recorded so the asymmetry is a decision on
      the record rather than something the next reader discovers.
- [ ] **Non-Latin digit sets aren't handled by any locale backend's `integer()`
      implementation** — the routing half of this item is now fully solved:
      both `Formatter.duration_hm`'s zero-padded minutes (`"1h 05m"`) and
      `fmt_countdown`'s `"2:05"` (via `core/presentation/words.py`'s
      `countdown`, converted in Phase 14) go through the locale backend's own
      `integer(IntegerSpec(min_digits=2))` operation rather than a Python
      f-string at the call site. What is left is inside that operation
      itself: `QtLocaleFormatter.integer`'s non-grouping path still renders
      with `f"{value:d}"`, plain ASCII digits, so a backend for a language
      with its own digit set would need to override this method — the shared
      layer no longer stands in the way, but nothing implements it yet. The
      standing judgement is unchanged: only worth revisiting once a language
      with non-Latin digits actually ships.
- [ ] **Proactive BLE warm-up** — connect *before* the user asks, so a tray
      click lands on a warm link. Measured cold connect is 2.2–2.6s in the good
      case and ~12.3s in the bad one (a discrete ~10.2s penalty inside BlueZ's
      LE link establishment, invisible over D-Bus — an HCI-level question that
      would need `btmon` to answer); the warm path is 62ms. So this is the only
      option that removes the wait rather than merely showing it (the tray's
      "Connecting…" label does the latter). Candidate triggers: tray
      hover/menu-open, and shortly before a scheduled transition. Deferred
      because it is the most invasive of the four options considered: it must
      respect the seat lease (a backgrounded daemon does no desk IO of its own
      and holds no link) and the desk's single-BLE-client rule, and it trades
      the on-demand design's whole point — a desk left free for other clients
      and an unlit Bluetooth indicator — for latency. Note the cheap version
      already exists as config: raising `[desk] linger` widens the warm window,
      with the same trade-off and none of the code.

## Refactoring / structure
- [x] **Make `idasen-companion` the single user-facing command** — route GUI
      launches and Qt-free CLI subcommands through one entry point in full and
      headless packages. This is the first public command interface, so remove
      `idasen-companion-cli` and the old movement flags. Make `toggle`, `sit`,
      and `stand` use the daemon's repeat-aware gesture method for shortcuts.
- [x] **Decide whether the command line becomes a first-class front end** — yes:
      `idasen-companion` now owns status, log and movement subcommands without
      importing Qt; full/headless artifact publication remains packaging work.
      The original analysis follows: it
      is not one now: five flags living inside the GUI, declared at
      `gui/main.py:135` and short-circuiting at `gui/main.py:150` before any
      `QApplication` exists. That was right for what they are, and stops being
      right the moment the command line has to *report* anything, which the
      `status` item above starts doing. A CLI and a GUI over one daemon is the
      ordinary arrangement for this kind of tool; what exists instead is a GUI
      with flags attached, and the asymmetry already shows in packaging —
      PySide6 is an *optional* extra (`pyproject.toml:29`) yet the
      `idasen-companion` entry point runs `gui.main:main`, which imports
      `QtWidgets` at module scope, so the flags need the GUI extra to fire one
      D-Bus method. **The code separation is nearly free and the vocabulary
      separation is most of the way done already.** `dbus-fast` is already a
      base dependency, so a Qt-free client needs no new package, and the wire
      format is deliberately flat-and-JSON already. The height and duration
      words such a client would need are no longer the obstacle: they live
      under `core/presentation/`, unit-explicit and Qt-free, reached through
      a `Formatter` built onto an explicit context rather than through
      `gui/util.py`'s `QCoreApplication.translate("util", …)` (`gui/util.py:27`)
      against the Qt catalog. The status, position, preset and trigger words
      (Phase 14) and the four date/time helpers (Phase 15) have since moved
      to `core/presentation/` too, so nothing left in `gui/util.py` would
      cross catalogs for a Qt-free client to reach. **The prize is a headless
      package** — daemon plus command line, no PySide6 anywhere. Measured
      untrimmed, Qt is 648 MB against ~7.9 MB for the whole rest of the
      closure, so it is not a component of this app's weight, it is nearly all
      of it; the split spec is already `noarch` and needs only a GUI
      subpackage to carry its unconditional `Requires: python3-pyside6`
      (`packaging/idasen-companion.spec:28`), and the bundled spec might stop
      vendoring an interpreter altogether — its reason for doing so is
      cross-distro correctness rather than Qt, but the only compiled
      extensions left outside Qt are `dbus-fast`'s nine and PyYAML's one, both
      with pure-Python fallbacks nothing here is fast enough to miss.
      **Deferred deliberately**: adding `status` needs none of this and would
      be held up by all of it. All four options weighed — status-in-place,
      extract the vocabulary into `core/`, a separate binary with duplicated
      formatters (rejected on the naming rule), and a full surface redesign
      covering subcommand grammar, the fate of the existing flags, `--json`,
      `--watch`, the packaging split and configuration — are written up in
      `.planning/todos/pending/2026-08-19-rethink-the-command-line-surface.md`.
      **Configuration is the third front-end question and repeats the same
      shape.** There is no way to change a setting outside the GUI, and the GUI
      binary cannot even be pointed at another file (`--config` exists on the
      daemon, `IDASEN_COMPANION_CONFIG` in `core/config.py:21`, neither on the
      GUI). A generic `config set <section>.<key> <value>` is unusually cheap
      because the dataclasses already *are* the schema and `_apply_section`
      (`core/config.py:188`) already resolves, coerces and type-checks keys —
      parse the argv value as a one-line TOML document and the types match the
      file exactly. What blocks it is the same invariant problem as the
      vocabulary: `AppContext.write_config` (`gui/context.py:62`) is the single
      writer and owns tomlkit-preserving saves, the `configChanged` signal and
      the `ReloadConfig` nudge, of which a CLI needs two and not the third.
      Note also that temporary overrides mostly should *not* be config —
      `Pause`, `Resume`, `SkipNext` and `Snooze` already exist as transient
      daemon state (`daemon/service.py:161-177`) and a CLI should surface those
      rather than coin a second way to say "not right now".
- [ ] **Declare D-Bus signatures with `Annotated` so `service.py` is checked**
      — `daemon/service.py` is the only module excluded from type checking, via
      a scoped `disable_error_code` in `pyproject.toml`. It is the project's
      largest remaining suppression (**51 errors**) now that everything else
      sits at zero. dbus-fast wants wire signatures in the annotation slot
      (`def Height(self) -> "d"`), which mypy reads as a forward reference to a
      type named `d` and cannot resolve. The real cost is not the count: the
      bodies of those 51 members go unchecked, on the module that *is* the
      daemon's public contract with the GUI. **The proper fix is verified to
      work**: `-> Annotated[float, DBusSignature("d")]` gives mypy a real type
      while dbus-fast reads the metadata, and diffing the introspection output
      confirms the wire signatures are byte-identical. **Deferred on version
      floor, not on difficulty** — `dbus_fast.annotations` first appears in
      dbus-fast **4.0.0 (2026-02-01)**, so adopting it raises
      `pyproject.toml`'s `dbus-fast>=2.0` to `>=4.0`; 2.x was the current line
      for over two years and is likely what conservative distros still ship.
      The RPM is unaffected either way (unversioned `Requires`, Fedora 43 has
      4.0.4). **Before doing it, check the one thing that was never
      established: whether dbus-fast 4+ has reached Debian stable and Ubuntu
      LTS** — Repology did not answer on 2026-08-06, and that is the entire
      cost side of the decision.
- [ ] **Logging follow-ups** (the policy itself is settled — see
      `docs/LOGGING.md`, which now governs every new line):
      - **A brief interruption says nothing about timing.** The reset variants
        state the new cycle ("Next change after 25m of active time"); the
        *kept* variants ("keeping this cycle's progress") deliberately say
        nothing, because the full target would be wrong when progress was
        retained. The genuinely useful number there is the time *remaining*,
        which needs a second note format and a `time_remaining` parameter.
        Left out on purpose rather than shipping a misleading number.
      - **Diagnostic lines are English-only by design, and one of them is
        user-shaped.** "Another idasen-companiond already owns the bus name"
        is diagnostic today, but a second daemon is a real thing a user might
        need to know about. Revisit if it ever shows up in a support thread.
      - **The Activity Log seeds from journald with a 7-day window and no
        paging.** Fine for the ring-sized case it replaced; if anyone wants
        real history the window should be a control, not a constant.
      - **`journalctl` is shelled out to.** `core/journal.py` writes natively
        to the journal socket but reads through a subprocess, so a reader
        that can't run `journalctl` silently gets no backlog (it degrades to
        the daemon's ring, which is the old behavior). Reading natively means
        parsing the journal file format or taking a `systemd-python`
        dependency; neither is worth it yet.
- [ ] **Fire the pre-move warning at exactly the configured lead time** — the
      warning is currently tick-driven: `_maybe_warn` (`daemon/main.py:305`) arms on
      the reliable window `max(lead_time, check_interval)`, so when `lead_time <
      check_interval` the notification fires up to one update-interval *early* (and
      where exactly depends on which tick lands in the window) instead of exactly
      `lead_time` before the move. Root cause is that the move itself is
      tick-quantized — `active_time` advances in `check_interval` chunks and the
      move fires on the tick that crosses the target (`core/machine.py:266`), so the
      warning can't be timed finer than one tick. This is why `lead_time` and
      `check_interval` are effectively intertwined today (they *shouldn't* be). Real
      fix: when a move enters its final approach, schedule the warning (and possibly
      the move) on a precise timer/counter — `fire_at = now + time_remaining`,
      warning at `fire_at - lead_time` — decoupled from the tick cadence,
      re-checking idle/lock at fire time and cancelled on pause/snooze/idle/
      reconcile/config-reload. Removes the coupling entirely (no caption/clamp
      needed; `lead_time` honored exactly at any `check_interval`). Tradeoff: adds
      timer + cancellation state to the deliberately-pure tick machine — scope the
      concurrency carefully. Interim (already done): the `max()` window guarantees
      the warning always fires, never silently skipped.
- [ ] **Reconsider the emphasis mechanism (QFont-everywhere vs. rich-text `QLabel`)**
      — a prior change standardized *all* emphasis to a single `emphasize()` helper
      (`widgets.py:108`, `Weight.DemiBold`, no letter-spacing) and dropped RichText
      from Overview, splitting the status/countdown into discrete `QLabel`s. Rich
      text in `QLabel` (`<b>`) is actually a first-class Qt idiom, and for
      *inline-mixed* text ("**Active** — snoozed until 3pm") it's the *natural*
      tool — splitting one sentence into 3–4 labels to force whole-widget `QFont`
      weight is arguably the hackier move. Costs of the current approach: (a) "one
      emphasis span = one label" — mid-sentence emphasis now needs an extra label;
      (b) empty labels (`setText("")`) still occupy layout slots → stray-gap risk;
      (c) `emphasize()` is global, so headings share inline-emphasis weight (the
      big "Sitting" heading no longer stands out by weight alone); (d) two
      independent "semibold" defs now exist (`emphasize()` vs `section_label()`).
      Reconsider: keep `QFont` for genuinely whole-label emphasis (preset names,
      position word) but allow rich-text `QLabel` back for inline-mixed runs (as
      the Activity Log already does), and/or expose a `bold`/weight *option* rather
      than one hardcoded weight. Re-evaluate after real-Breeze visual sign-off
      (DemiBold's true face is unverified until then). Don't treat "no HTML
      anywhere" as a rule to defend.
- [ ] **Make non-default presets first-class citizens** — right now the two
      `PROTECTED_PRESETS` ("sit" / "stand") are hardcoded throughout: the
      automation engine alternates between exactly those two, the Overview Sit /
      Stand buttons and height-rail marks assume them, schedules cycle them, and
      the config treats them specially (can't rename/delete). A user should be
      able to build automation around *any* preset(s) — e.g. cycle among three
      heights, or drive the schedule off arbitrary named presets — with the UI
      generated from the preset list instead of the two fixed names. Likely a
      large cross-cutting refactor spanning the daemon automation engine, the
      wire protocol / config schema, and the GUI (Overview buttons, schedule,
      rail marks); scope it carefully and stage it. Keep sit/stand as sensible
      defaults for the common case. Includes the **"Next:" target**: today the
      GUI correctly infers it as the opposite of the current position, but once
      more than two presets cycle that's no longer a binary flip — the daemon
      must report the next cycle target (a wire-protocol addition) since the GUI
      can't infer it.
- [ ] **Split `daemon/main.py`** — still ~1650 lines after the 2026-08-06
      simplification pass, which extracted the oversized inline blocks but
      deliberately did *not* move anything out of the module. Two cohesive
      candidates were identified and rejected **on coupling, not on size**, so
      recheck that before designing around it: the BlueZ/recovery group
      (`discover`, `_bluez_*`, `_handle_connect_exhausted`,
      `_other_companion_daemons`, ~130 lines) reads `self.ring`, `self.config`,
      `self._system_bus`, `self.mock_mode` and `self._scan_cache`, so it needs a
      collaborator threading all five — and `tests/test_ble_link_recovery.py`
      monkeypatches `_other_companion_daemons` and `_bluez_property` as bound
      attributes, which a move would break. The preset-CRUD group (~110 lines)
      has the same coupling and is fenced off by the preset item above.
- [ ] **Small cleanups found during the 2026-08-06 simplification pass**, each
      skipped there because it costs more than it buys on its own — worth doing
      opportunistically when next in the file:
      - `Daemon._handle_event`'s `trigger` parameter is dead (the body never
        reads it; `_on_transition` uses `event.trigger`, a different thing).
        Removing it means touching 15 test call sites for no runtime gain.
      - `StateMachine.__init__` takes `desk` untyped while `desk/port.py`
        defines `DeskPort` for exactly this. Documentation-only.
      - `desk/port.py` declares `last_error` as a `@property` but `MockDesk`
        implements it as a plain settable attribute. Fine at runtime and
        intentional (the docstring says so), but a strict Protocol checker
        would flag it — worth a note in the Protocol before any such check
        lands.
      - `daemon/main.py` declares the one-shot flags twice (`_COMMAND_FLAGS`
        for dispatch, argparse for validation/help). Unifying entangles help
        text with dispatch.
      - `tray.py` and `pages/overview.py` each carry their own copy of the
        `_RESUMABLE_VALUES` / `_COUNTDOWN_VALUES` frozensets and an identical
        `_toggle_pause`. Both derive independently from `core.machine`, so
        there is no drift risk — only inert repetition. The natural shared home
        would be `gui/util.py`, which would muddy its stated remit.
      - `DaemonClient.refresh_all`'s seven repeated `get_property` + emit
        blocks. The obvious helper would silently drop seven members out of
        `tests/test_dbus_contract.py`'s coverage, which scans for calls naming
        them — so it has to land together with a widened scan, the same way the
        `_iface(...).call()` gap was closed.
- [ ] **ID-keyed translation (scheme C), deferred on sequencing rather than
      merit** — settled during the Phase 12 discussion. Today's catalogs key on
      the English source string; this reworks that to key on a stable id, e.g.
      `Msg("status_standing", "Standing")` in a register, with the id reaching
      the lookup and the register's own English serving as the runtime fallback
      on a miss. It buys three things: rewording the English no longer orphans
      the translation (today it does, silently); collisions between two
      concepts that want the same English word stop being possible, since each
      keeps its own id; and it deletes the class-rename trap `CLAUDE.md`
      documents, because the Qt key stops being `(context, source)` with the
      context a class name — renaming a GUI class today orphans every
      `<message>` under its old context with nothing failing.
      Not done now because re-keying while roughly twenty formatters are
      simultaneously being merged into one shared vocabulary (Phases 13-15)
      would put two changes in every diff — when a Spanish string lands wrong,
      nothing says whether the move or the re-key did it. Doing it afterwards
      instead means re-keying a settled target with the baseline harness this
      milestone built already in place, the instrument that can prove a re-key
      changed no rendered string. Whether it is worth doing at all is itself
      evidence Phases 13-15 are expected to produce: reword-driven orphaning
      and source-string collisions are being logged as they happen (see the
      collision log in `docs/TRANSLATING.md`), and whether either actually
      bites is the case for or against this.
      Two obstacles are already verified on the Qt side rather than assumed:
      PySide6's `QtCore` exposes `qtTrId` but not `QT_TRID_NOOP` (confirmed by
      import — `QT_TRID_NOOP` is absent from `dir(QtCore)`), so the register
      marker this shape needs is not available out of the box; and
      `tests/test_catalog_contexts.py` is built entirely around Qt contexts,
      which id-keying makes vestigial, so it needs substantial rework rather
      than a small edit. `pyside6-lupdate` itself does already recognise
      `qtTrId`, `QT_TRID_NOOP`, `QT_TRID_N_NOOP` and `qsTrId` as keywords.
## UI polish
- [ ] **The setup wizard opens off-centre** — reported on the maintainer's
      Fedora/KDE machine, 2026-08-13. Two facts, both confirmed by reading the
      tree rather than inferred: `gui/setup_wizard.py` contains no positioning
      call of any kind — no resize, no move, no geometry — and *nothing
      anywhere under `gui/` centres a window or saves and restores geometry.
      So every window this app opens lands wherever the window manager decides,
      and the wizard is simply the case where that reads as a defect.
      The likely mechanism, to be confirmed before it is designed around:
      `gui/main.py` calls `window.show()` and then `wizard.open()` a few lines
      later, in the same turn of the event loop. `show()` only *requests*
      mapping, so at the moment the wizard is opened its parent has no
      real geometry yet, and a window manager asked to centre a dialog on a
      parent that is not yet mapped has nothing to centre it on. That fits the
      report and fits first-run specifically, which is the only path that opens
      the wizard.
      Worth deciding once for the whole app rather than patching the wizard
      alone: whether windows centre on the primary screen, centre on their
      parent, or persist their geometry between runs. Note Wayland does not let
      a client position its own top-level window at all, so "centre on screen"
      is not portable — parent-relative placement and letting the compositor
      decide is, which argues for fixing the ordering rather than adding
      coordinates.
- [ ] **Redesign the app icon and the tray icon** — both shipped icons are
      first-draft placeholders drawn to have *something* there, not designed:
      `data/icons/io.github.extricator.IdasenCompanion.svg` (64×64, a blue
      rounded square with a white desk and a rising arrow, ~1 KB of hand-written
      SVG) and `data/icons/io.github.extricator.IdasenCompanion-symbolic.svg`
      (16×16 monochrome). They install to `hicolor/scalable/apps/` from the spec
      and are referenced by `APP_ID` / `APP_ID-symbolic` in `gui/main.py`, so a
      redesign is a straight file swap — no code change unless the naming
      scheme changes.
      **Light and dark are two different problems here, and only one of them
      wants two files:**
      - *Tray/symbolic — must recolour on **both** Plasma and GNOME.* Neither
        gets a `-dark` twin: symbolic icons are recoloured by the panel, so a
        second file would break that. The catch is that **the two desktops
        recolour by different conventions, and today's file implements only
        one of them.** Ours is written to Breeze's: a `<style
        id="current-color-scheme">` block defining `.ColorScheme-Text`, with
        `fill="currentColor"` on the group. GTK/GNOME ignores all of that —
        Adwaita's own symbolic icons (`/usr/share/icons/Adwaita/symbolic/`)
        are plain `<path fill="#2e3436"/>` with no classes at all, because
        GTK overrides the fills itself, and GTK4 goes further: the `fill`
        attribute and any `style`/`color` are *ignored*, with recolouring
        driven by `gpa:fill` or by the recognised classes `foreground-fill` /
        `success-fill` / `warning-fill` / `error-fill`. So our icon may be
        rendering with its hardcoded `#232629` on GNOME — near-black on a
        near-black panel, i.e. invisible rather than visibly wrong. **Verify
        before redesigning, because it decides whether this is an art task or
        also a bug fix.**
        The target is one file both honour: keep the Breeze style block and
        `currentColor`, and *also* carry GTK's `foreground-fill` class (the
        two coexist — `class="ColorScheme-Text foreground-fill"`). If that
        proves unreliable, the documented escape hatch is
        `gtk-encode-symbolic-svg` (already on the box, from `gtk3-devel`),
        which bakes the SVG into `.symbolic.png` files that GTK recolours
        reliably and faster; they install alongside the SVG in fixed-size
        icon dirs.
        One precondition is already satisfied and worth not breaking: GTK only
        recolours icons looked up **by name through the icon theme**, never
        ones loaded from a file path. `gui/main.py:144` asks for
        `APP_ID-symbolic` by name and the spec installs it under
        `hicolor/scalable/apps/`, so that part is fine.
        Testing needs `gnome-shell-extension-appindicator` **v50 or newer**
        (that is where the `St.IconTheme` symbolic-loading path landed;
        recolouring is a known long-standing gap in older versions). It is not
        installed on this machine and this is a Plasma box, so GNOME
        verification needs a VM or a second session — which is precisely why
        it has gone unchecked.
        Also keep the design legible as a flat silhouette at 16px; the current
        one is close to the limit already. GTK4's format is stricter than
        plain SVG: geometry attributes are mandatory (`d` on paths, `x`/`y`/
        `width`/`height` on rects, `cx`/`cy`/`r` on circles) and strokes must
        be converted to paths. Today's file happens to satisfy those — a
        redesign drawn in Inkscape easily won't.
        Sources for the above, so none of it has to be re-derived:
        - GTK4 symbolic icon format (`gpa:fill`, the recognised classes, the
          ignored attributes, mandatory geometry):
          <https://docs.gtk.org/gtk4/icon-format.html>
        - The by-name-through-the-icon-theme rule, and the `was_symbolic`
          return value that tells you whether recolouring actually happened:
          <https://docs.gtk.org/gtk3/method.IconInfo.load_symbolic.html>
        - Authoring guidance (no unfilled shapes, strokes to paths, `class`
          to colour a specific part):
          <https://wiki.gnome.org/HowDoI/CreateSymbolicIconsThatChangeColorAccordingToTheme>
        - The appindicator extension's long-standing "indicator icons don't
          take the panel colour" issue, which is what v50's `St.IconTheme`
          path addresses:
          <https://github.com/ubuntu/gnome-shell-extension-appindicator/issues/253>
        - Local reference implementation to compare against:
          `/usr/share/icons/Adwaita/symbolic/actions/*.svg`
      - *Main app icon.* Full-colour and sits on the app's own surface, so it
        does not need a dark variant *if* it stays a filled shape with its own
        background. It would need one the moment the design goes transparent-
        background with dark strokes, which is exactly the trap a "modern,
        minimal" redesign walks into. Decide that deliberately rather than
        discovering it on a dark theme.
      Also worth settling in the same pass: whether to ship raster fallbacks
      (some environments still prefer PNG sizes over scalable SVG), and
      whether the icon should reflect *state* (sitting vs standing vs
      automation paused) in the tray rather than being static — that is a
      genuine feature, not just art, and would need its own set of glyphs.
- [ ] **Scroll wheel over settings spin/combo controls changes the value** — when
      scrolling a settings-class page with the mouse wheel, hovering over a
      `QSpinBox` (`_minutes_spin`/`linger_spin`/`lead_spin`), a `QComboBox`
      (Language, tray actions), or a `QTimeEdit` makes the wheel
      *increment/decrement the control* instead of scrolling the page — so you
      silently change a number you only meant to scroll past. Standard Qt fix:
      give these controls `Qt.StrongFocus` and swallow `wheelEvent` unless the
      control actually has focus (an event filter or small subclass), letting
      the wheel scroll the surrounding `QScrollArea` instead. Applies to both
      `settings.py` and `automation.py`; the natural home for the fix is the
      shared helpers in `pages/settings_form.py` (`_minutes_spin`,
      `_themed_combo`), which is where both pages get these controls from.
## Known issues / cleanups
- [ ] **`_TRANSLATOR_SEEDS` hand-lists `Formatter` method names, so the
      concatenation check can quietly narrow** — the seed set in
      `tests/test_translation_markers.py` began as two structurally complete
      names (`_tr`, `GettextTranslator`), which caught *any* value reaching a
      translator. It now also names `day_and_clock`, `snooze_line` and
      `later_label` by hand. A new message-rendering `Formatter` method
      reached from `gui/util.py` would not be seeded, the mark it should have
      demanded would never be asked for, and the suite would stay green.

      **Two approaches were tried and both were wrong — do not repeat them.**
      Deriving the expected set with the module's own `_reaches_tr` is
      *circular*: that helper is seeded by `_TRANSLATOR_SEEDS`, so removing a
      seed removes it from both sides and the check can never fail (verified
      by mutation). Deriving it by intersecting "methods in `formatter.py`
      that mention a translator" with "attribute names called in
      `gui/util.py`" *over-reaches*: names are matched bare, so `util`'s own
      `preset_label` collides with a same-named `Formatter` method and eleven
      false positives are reported. A correct guard has to resolve the
      receiver, not just the attribute name. Fragility only — nothing is
      mis-translated today.
- [ ] **`gui/util.py`'s `fmt_clock` is a forwarder with no production
      callers** — it earned its place before Phase 19, when it built a
      `QtLocaleFormatter(QLocale())` its callers could not. It is now
      `return fmt.clock(when)`. Five test modules still import it, so
      deleting it is a test-only change of moderate churn; `fmt_day_and_clock`
      beside it is still a real whole-message renderer and stays.
- [ ] **The tray tooltip's refresh on Apply is incidental, and its test fakes
      the trigger** — `tests/test_tray_tooltip.py` forces the redraw with
      `snoozeUntilChanged`, while the tray's own `ctx.configChanged`
      subscription only rebuilds the presets submenu. So a clock-format change
      reaches the tooltip via the daemon echoing `StatusChanged`, not via
      Apply. Narrow in practice — the tooltip carries a clock only while
      snoozed — but the test claims to pin a mechanism it does not exercise.
- [ ] **CI generates no POSIX locale for any shipped language, so a
      locale-sensitive gate only ever runs on a developer machine** — two
      different things are called a language here and CI has only one of them.
      The *catalog code* (`es`, from a compiled catalog) is committed and
      ships, so the runner has it. The *POSIX locale* (`es_ES.UTF-8`,
      generated in the operating system) is absent from both the GitHub runner
      and the RPM buildroot. Any check needing the second kind skips there.
      Today that is
      `tests/test_golden_presentation_contract.py`'s
      `test_the_qt_free_backend_ignores_the_posix_locale_too`, which renders
      every shared formatter under a non-English numeric and time locale and
      requires the output to match the `C` baseline — `BACK-04` as a
      behavioural check rather than a promise, and the leg that caught the real
      hole in Phase 17 when a mutant using a C-library number and date
      conversion passed everything else. The proof that does run everywhere is
      the structural gate in `tests/test_plain_locale.py`, which parses every
      module under `core/presentation/`, so the gap is narrow rather than open:
      a source-level reintroduction is still caught, a behavioural one is not.
      Closing it is one step in the test workflow, no new runtime dependency —
      but generate the list **from the shipped catalogs** rather than naming a
      language, and fix the test's own hardcoded candidate locales the same
      way, or language three lands in exactly this position again. The catalog
      code to locale name mapping is not mechanical (`pt` has two territories)
      and wants an explicit answer in committed source. The RPM buildroot is a
      separate decision — no workflow step reaches it, and closing it means a
      langpack build dependency per language.
- [ ] **The window's minimum size is a pixel constant chosen against English,
      and Spanish page content clips below it** — `gui/main_window.py` declares
      a fixed minimum size, but the width the layout actually needs is a
      function of the translated strings inside it. Measured offscreen through
      `tests/test_baseline_window.py`'s own harness,
      `window.minimumSizeHint().width()` is 658 for English and 779 for
      Spanish, so the app permits a Spanish window narrow enough to cut its own
      Settings content off — which is exactly what a maintainer hit, at the
      window size English had trained them to use. Pre-existing: Spanish
      already needed 770 before Phase 16's sidebar work, ten over the declared
      minimum; that phase's nine-pixel sidebar growth moved it to 779, making
      it a contributor rather than the cause. Same root-cause family as both
      defects Phase 16 fixed — a pixel constant measured against English with
      nothing checking whether a translation fits — which is the argument for
      fixing it by measuring rather than by raising the number. Measurements,
      four options and the shape of the test that would catch it are written up
      in `2026-08-24-window-minimum-width-clips-translated-pages.md`, with its
      reproduction script beside it; read that rather than re-deriving any of
      it. Found during the Phase 16 bilingual walk.
- [ ] **Six translated messages carry unnamed format slots a translator
      cannot reorder** — each is a single whole catalog entry, so the
      concatenation gate correctly reports no offender and no v1.1.1
      requirement is unmet: the rule those requirements enforce is about
      joining a translated fragment to something else, and none of these
      does that. What they do instead is take two substitutions positionally.
      Python's percent-formatting has no indexed form, so the order the
      English fixed is the order every language inherits, and a language
      needing the two swapped has no way to ask for it. That is the same
      shape of silent failure the milestone was built to remove — correct in
      English, discovered only by a language whose word order differs. Six
      sites, all with two or more slots: five in `gui/tray.py` (the
      position-and-detail separator, the held-for line, the status-and-change
      line, the daily totals line, and the preset menu's name-and-height
      entry) and one in `gui/pages/presets.py` (the preset-set confirmation).
      Spanish needs no reorder in any of them today, which is why nothing is
      visibly wrong. The fix is to give each slot a name, the way the sites
      converted in phase 11 already do, and to re-translate — mechanical, but
      it moves catalog entries, so it wants its own change with the catalogs
      regenerated alongside. Consider whether the concatenation gate should
      grow a companion check for multi-slot unnamed formatting, since nothing
      currently stops the next one. Found during the v1.1.1 milestone audit.
- [ ] **CLAUDE.md's documented development setup command is missing two
      packages the CI gates section immediately below it depends on** —
      the venv-creation line names `pytest` and `pytest-asyncio` and the GUI
      extra by hand, but installs neither the coverage plugin the pytest
      invocation two sections down requires, nor the stub package mypy needs
      to run cleanly against this tree. Both already ship under the
      project's `test` extra, so the documented line is what's wrong, not
      the dependency set — pointing it at that extra (or adding the two
      packages by name) is the fix. As written, a fresh clone following the
      doc verbatim hits an unrecognized-argument error from the coverage
      gate before a single test runs, and a naive `mypy` run reports
      unrelated import errors. Found re-running the CI gates from a freshly
      recreated venv during Phase 10; recorded rather than fixed here since
      the section it sits in is being rewritten in the next phase.
- [ ] **CLAUDE.md's coverage-floor parenthetical quotes a stale measured
      total** — the note beside the pass threshold cites a specific
      percentage as "the measured" total; the suite has grown since, and the
      real number now sits well clear of both that quoted figure and the
      floor. What it explains — that the coverage tool can print a failing
      line and still exit success at the exact boundary, and that the total
      wobbles slightly between identical runs — is still correct and worth
      keeping; only the one number embedded in it has drifted. Prefer
      unnumbered phrasing when this is corrected, the way this project's
      README test-count claim was, since a number written into prose drifts
      again the moment the suite grows.
- [ ] **The Activity Log's colours are baked in at render time and do not
      follow a palette change** — every row is written as rich text with its
      timestamp, level and message colours resolved from `theme()` at the
      moment it is rendered (`_row_html` in `gui/pages/activity_log.py`).
      Everything else in the GUI restyles through `restyle.register`, which
      re-runs on a palette change; the log view has no such hook, so switching
      the desktop between light and dark leaves whatever rows are already on
      screen in the old scheme. New rows arriving afterwards use the new one,
      so the view can end up in two colour schemes at once, and the mismatch
      persists until something rebuilds the document — a filter change, or
      leaving and reopening the page.
      Pre-existing, and untouched by the redraw and scroll work in
      `3b29fa5`..`ca36a95`. The fix is to re-render on a palette change rather
      than to change how a row is coloured: register the view with `restyle`
      and have the callback force a rebuild. Note the rebuild now short-circuits
      when the rendered rows are unchanged, and since the colours are part of
      that rendered string a palette change already produces different rows —
      so the skip does not stand in the way, and a call to `_redraw` is enough.
- [ ] **Why a BLE link survived a suspend was never narrowed to one mechanism**
      — the fix (release the link before the sleep under a logind delay lock,
      reconcile against BlueZ on resume) is written to hold either way, and the
      question only becomes worth settling if it turns out not to. Two
      candidates remain, both inferred from vendored bleak 3.0.2's
      `BleakClientBlueZDBus.disconnect()` and neither observed: **(b)** bleak's
      cached `is_connected` flag goes false across the sleep, so it never sends
      `Device1.Disconnect` at all, returns success, and BlueZ keeps the link;
      **(c)** bleak's per-connection `MessageBus` stalls, so the untimed bus
      call never returns and hangs holding `BleDesk._lock`. The experiment that
      distinguishes them is one live suspend entered inside the linger window
      with `--verbose` on (so bleak's own BlueZ logging reaches the journal),
      reading both BlueZ `Device1.Connected` and the daemon's `Desk1.Connected`
      immediately on resume: (b) logs "Disconnecting …" with no
      `Device1.Disconnect` and shows the two disagreeing; (c) logs
      "Disconnecting …" and then nothing, and a later desk operation never
      returns. It was skipped by choice — a real suspend/resume cycle against
      the real desk, which is the sharpest form of the BLE hazard this file
      keeps warning about. Full evidence in the debug session
      `ble-link-survives-suspend`.
- [ ] **`gui/setup_wizard.py` is the least-tested file in the project, and it
      is untested rather than untestable** — 152 statements, 127 uncovered,
      **16%**, against 96% for `core/` and 99% for `core/machine.py`. Nothing
      in `tests/` imports it at all, so the whole first-run path — discovery,
      MAC selection, preset capture — has never run under a test. It is also
      the first code a new user meets.
      Nothing about it is hardware-bound by construction: the daemon half of
      the same flow carries an explicit mock branch in its setup-verify path,
      so the whole sequence is reachable with `--mock-desk` and no Bluetooth.
      This matters more than the aggregate coverage number suggests, because
      that number cannot tell "cannot be tested here" from "nobody wrote the
      test". Most of the rest of the shortfall is the former — `paintEvent`
      bodies, one-line D-Bus proxies, X11 idle providers that need a real
      `DISPLAY`, the BLE driver — and this is the clearest case of the latter.
      Covering it would also move the total more than anything else available.
      The cost that keeps deferring it: `_scan` calls `client.discover(8)`
      synchronously on the GUI thread with `processEvents()` pumped around it,
      so `DaemonClient` has to be stubbed — and since `260731-tr3` made
      `DeviceSelectPage.initializePage` scan lazily, the stub must be in place
      *before* the page is shown. That change shipped without coverage
      precisely because the first wizard test is bigger than the fix was.
      Worth covering: instant list → no scan; empty list → auto-scan; a
      successful scan clearing a stale "Nothing found."; single-candidate
      preselection. While in there, consider whether `_scan` should lose the
      blocking-plus-`processEvents` shape — the seam that makes it testable is
      probably the better GUI shape too.
      Follow the GUI-test rules in `CLAUDE.md` when writing them: force
      `QT_QPA_PLATFORM=offscreen` before importing `QtWidgets` (`setdefault`
      is not enough), and destroy any tray icon explicitly at teardown.
- [ ] **Nothing installs the compiled Spanish catalog and renders a
      catalogued message through it** — `tests/test_log_catalog.py` and
      `tests/test_command_errors.py` are thorough about *structure* (every id
      has a twin, every parameter kind has a formatter, sample values render),
      but every one of those checks runs the English source; a malformed
      Spanish `%(...)s` substitution has no test that would notice.
      `core/logmsg.py:560` and `:568` both swallow the `KeyError`/`ValueError`/
      `TypeError` a bad substitution raises and silently render the raw
      template instead — so a Spanish user would read the unsubstituted
      pattern with the build staying green. The one-message-per-translatable-
      unit milestone raises this item's value rather than lowering it: it
      added several new `%(name)s`-substituted entries (`fmt_height`,
      `fmt_days`' range/pair patterns, the About desk line, the Statistics
      transition arrow, the setup wizard's success paragraphs) to exactly the
      catalog surface this gap covers, on top of `core/logmsg.py`'s existing
      62 `LogMessage` ids. `tests/test_command_errors.py:65` already installs
      a compiled `.qm` and asserts on translated output for eight daemon error
      strings — the template to extend, not a new mechanism to invent.
- [ ] **Reassess `scripts/scan-secrets.sh` once GitHub's own secret scanning is
      on** — Phase 04.1 documented enabling it as the first post-flip step
      (`CONTRIBUTING.md` § "Cutting a release"), and once that lands the
      script's remaining unique job narrows to proving a tree is clean before a
      rewrite or a visibility change — the one moment GitHub will not do it for
      you. Drop-candidates for a thinner version: the podman fallback, the ANSI
      stripping, the evidence-directory plumbing and the history mode's rev-list
      walk cross-check. The one part that must survive whatever replaces it is
      the canary: a scan that walked nothing exits 0 and reports no leaks
      (upstream gitleaks#2129), and a marketplace action inherits that
      identically — worse in CI, where a green check is exactly what nobody
      reads. Check the premise before designing around it: the script now takes
      a mode and has three callers (the pre-commit hook, the `secrets` CI job
      and this one-time pre-flip scan), so thinning it is no longer the
      single-caller change the source note assumed.
- [ ] **A `git commit` given a trailing pathspec can trip the pre-commit
      hook's canary into a false refusal** — found and root-caused during
      Phase 15, unrelated to that phase's own changes. `git commit -- <paths>`
      makes git export a temporary lock-index path via `GIT_INDEX_FILE`; the
      hook's nested canary `git -C $CANARY_DIR init`/`add` calls inherit that
      variable because `-C` does not clear it, so the canary's synthetic
      secret gets written into the *outer* repository's temp lock-index
      instead of the canary's own fresh index. The containerized scanner never
      sees `GIT_INDEX_FILE` and falls back to the canary's untouched real
      index, finds nothing, and the hook correctly refuses on "canary reported
      no findings" — its designed response to a broken scan, working exactly
      as intended against a corrupted setup it didn't cause. Reproduced
      deterministically: the same staged content commits cleanly with a plain
      `git commit -m "..."` (no trailing pathspec) every time. Fix is to clear
      `GIT_INDEX_FILE` (and `GIT_DIR`/`GIT_WORK_TREE`) before the nested canary
      `git` calls in `scripts/scan-secrets.sh`; not fixed here since the
      workaround (omit the trailing pathspec) is reliable for as long as a
      caller stages exactly what it intends to commit.
- [ ] **Fedora 42 cannot *build* this project's RPM: `setuptools>=77` unmet** —
      `pyproject.toml`'s `[build-system] requires` floors `setuptools` at 77,
      needed for PEP 639's SPDX `license`/`license-files` metadata. Fedora 42
      ships only `python3-setuptools-74.1.3`, with no newer version in its own
      repos, so a build there dies on the app's own wheel either way: the split
      spec in `%generate_buildrequires`, the bundled one during `%install`,
      where pip builds that wheel with isolation off and therefore checks the
      floor against what is already installed. Fedora 43 ships 78.1.1 and is
      unaffected. This is a limitation of the *build host* and says nothing
      about where the package runs — the shipped RPM is built once, and what it
      asks of the machine it installs on is an interpreter, not a build
      toolchain. Building on 42 means either dropping the PEP 639 metadata or
      waiting for a newer `python3-setuptools` to reach it.
- [ ] **The RPM is built for x86_64 only, and aarch64 needs no new design —
      but it now needs a second pinned asset** — PySide6-Essentials and
      shiboken6 publish `manylinux` aarch64 wheels, and nothing in the spec,
      the launcher or either trimmer is written for one architecture, so the
      work is still one more build of the same spec on an aarch64 host (or an
      emulated one) and a second uploaded artifact.
      What has grown is the edit. The recorded cost was one change to
      `scripts/fetch-bundled-runtime.sh`, and that estimate predates the
      bundled interpreter — recheck it rather than designing around it. The
      interpreter tarball is architecture-specific too, and it is named three
      times at x86_64: a download URL and an asset filename in that script, and
      a `Source2:` line in the spec that has to match the filename. So a second
      architecture means a second pinned asset with its own SHA256 alongside
      the wheel platform, and the two have to be selected together. Note the
      script cannot merely be *run* on an aarch64 host as it stands: it
      resolves the wheel set by running the interpreter it just unpacked, and
      that binary is the x86_64 one.
      Left unbuilt because nobody has asked and each extra build costs a full
      container run; recorded so the shape does not have to be researched
      again.
- [ ] **The bundled RPM renders in Fusion rather than the desktop's Breeze, and
      the shipped screenshots still show Breeze** — two halves of one cause,
      found when the 1.0.2 bundled package was installed on the maintainer's
      machine (2026-08-15).
      *The look.* The package used to declare `Requires: python3-pyside6`, so
      the app ran on the same Qt build as the desktop and picked up KDE's
      platform theme and the Breeze style for free. The bundled package carries
      its own Qt 6.11.1 out of the `PySide6-Essentials` wheel instead, and that
      wheel ships **no `styles` plugin directory at all**; the only platform
      theme left in the bundle after the trim is `libqxdgdesktopportal.so`. So
      Qt falls back to Fusion — the tell is style `fusion`, a "Restore
      Defaults" button label, and no icon on it. This is not the interpreter
      bump: the dev venv, which that phase never touched, reproduces the same
      rendering identically, so the venv is the cheap place to test any fix
      without rebuilding an RPM. Whatever the fix is, it has to work on a
      machine whose desktop is *not* KDE too, which is the whole reason the
      bundle exists.
      *The screenshots.* The five captures in `data/screenshots/` are dated
      2026-08-13, one day before bundling landed, so both the README's strip of
      thumbnails and the five `<screenshot>` URLs in
      `data/io.github.extricator.IdasenCompanion.metainfo.xml` advertise an
      application the shipped package no longer produces. Re-shoot them from
      the *installed* package rather than the venv, and note the metainfo
      declares `width="990" height="826"` for each, so a re-shoot at another
      size means editing those attributes as well. The images are deliberately
      absent from the sdist and are fetched from the forge's default branch, so
      replacing a file is a plain overwrite — but renaming or deleting one
      breaks the picture for every install already out there, and
      `tests/test_packaging.py` holds each URL against a file in the tree.
      Decide the look first: re-shooting before the style question is settled
      buys a second set of stale images.
- [ ] **The rebuilt control styling has not been looked at on the real
      desktop** — the maintainer ran the pass against the installed 1.0.2
      package on Fedora KDE (2026-08-16) and turned the Phase 8 styling down
      twice, in his own words: *"borders are more visible but they don't have
      the style. they're too rectangular and just hard to look at unlike the
      old ones."* Then, after a corner radius was added: *"it looks better but
      if you see the outline in the old screenshots it was a little bit
      fainter and either the padding or margins of some controls was bigger.
      the text looks too close t the outline in some (like dropdown for
      'Language' and others)… also the radios of the buttons doesn't seem big
      enough. also look at the checkbox, no outline!"* "Radios" there is not
      the radio-button indicators — he confirmed directly that he meant the
      corner radius was not round enough, so read that sentence as a complaint
      about how square the corners still looked, not about control size.
      Phase 9 replaced the mechanism: the stylesheet rules are gone and
      `gui/style.py`'s `QProxyStyle` draws through to Fusion and overlays one
      rounded, theme-derived stroke, so Fusion's padding, focus ring, hover,
      disabled and HiDPI handling are kept rather than forfeited to the
      stylesheet engine. What has *not* happened is the look being judged:
      nobody has seen the result on a real display. The border weight
      (`theme().border`), the two corner radii
      (`theme.SURFACE_RADIUS` at 6px for cards, panels and pills,
      `theme.CONTROL_RADIUS` at 4px for buttons, combo and spin frames, the
      checkbox indicator and the segmented control) and whether
      `ConnectionChip` should stay a capsule or fold into the surface radius
      are all decided by eye, from the installed package, and only there.
      A single value was tried for both and rejected on the real desktop —
      it moved the controls up to the surfaces' 6px rather than the surfaces
      down, and the buttons stopped looking like the originals.
      A second real-desktop pass (2026-08-16) turned down the *push buttons*
      specifically — *"the buttons borders are still too coarse, and the
      corner too narrow compared to previous look"*, with the tell that
      *"the 'move' button has the radios and the border (even if diff color)
      similar to or the same as it used to be"*. Move is a `primary_button`
      and carries a stylesheet; every other button on the pane was a bare
      `QPushButton` drawn entirely by Fusion, at `#ababab` on a 2px corner
      against the app's own `#c7c7c7` and 4px. The app now draws a push
      button's whole panel itself — fill, edge and corner in one pass, with
      no Fusion underneath — as `primary_button` *without the accent*: the
      same corner radius, the same border weight (`theme().border`) and,
      through a `CT_PushButton` size override, the same padding. So an
      accent-filled button and a bare one are now the same size by
      construction. Whether that weight, that radius and that face are right
      is still the same by-eye judgement as the rest of this item.
      A third real-desktop pass (2026-08-16) accepted the geometry —
      *"much better"*, *"the corner artifacts are gone"* — and turned down
      two colour weights. The button ramp was **inverted**: a disabled
      button rendered `#f7f7f7` against a resting enabled one's `#e8e8e8`
      on a white card, so the control that could not be pressed was the
      crisper of the two, and the enabled face was a grey slab rather than
      a step off the card. The ramp now runs resting nearest the card,
      hover and pressed further out, disabled further than resting but no
      further than pressed. And the frames were too heavy: the spin box
      read `#9C9D9F` against the `#C8CACB` of the look he approves of,
      because `control_border` sat at 0.45 of the palette's ink axis purely
      to clear the 3:1 floor that has since been dropped. Re-derived by
      eye, it landed on the decorative `border`'s own 0.22, and the two
      tokens were collapsed into one — the split had nothing left to
      distinguish.
      A fourth real-desktop pass (2026-08-16) said the state *"looks
      better"* and asked for three refinements, all landed. The buttons
      were still short of the reference — a vertical pixel slice through
      Sit measured 35px against the app's 32px, with the same 30-row fill
      in both, so the difference is edge and shadow treatment a 1px stroke
      cannot reproduce — and the vertical padding token was raised, which
      moves a bare button and `primary_button` together. It also asked for
      a hover highlight in the desktop's own colour, and a push button's
      *face* was washed with `QPalette::Highlight` to provide it. And a
      push button's icon now stands clear of its label by a fraction of the
      label's own line height, because Qt's own spacing is a hardcoded
      2 drawn pixels at every font size.
      A fifth real-desktop pass (2026-08-16) corrected the hover
      highlight. The one meant was the reference look's, which moves a
      control's **border** to the accent and leaves the face alone —
      *"border just changed to highlight color not 'foreground' color"* —
      and it applies to every control, not only to push buttons. So the
      pointer faces went back to their neutral steps (which made the
      separate combo-box face tokens duplicates, and they were folded
      away), and `theme().hover_border` now strokes the push button panel,
      the combo frame, the spin frame and the checkbox indicator alike.
      Hover and keyboard focus are separated by weight rather than by
      thickness — focus keeps `theme().accent` outright, hover takes the
      resting edge carried 0.65 of the way to it — because a frame already
      turns accent on focus and a non-editable `QComboBox` has no other
      focus affordance at all. The same pass halved the icon gap —
      *"the icon gap is too big now. should be half that"* — so
      `theme._ICON_GAP_FRACTION` is 0.225 of the label's line height, 5
      logical pixels on his own 22px metrics — and Move now takes the same
      gap as the buttons beside it, which it did not before, because a
      stylesheet declaring a border routes the whole label through
      `QStyleSheetStyle` and Qt's stylesheet syntax has no icon-spacing
      property to declare it with. Whether that weight and that gap are
      right is the same by-eye judgement as the rest of this item.
      A sixth real-desktop pass (2026-08-17) said *"much better"* of the
      accent hover border and closed the Overview pane, with two changes to
      the neutral face ramp. The pointer was still moving a control's
      **face** as well as its border — the accent wash was gone but the
      face still stepped along its own neutral axis — and that was turned
      down too, which is what settles that the objection is to the face
      moving at all rather than to the colour it moved to. Measured on the
      same screenshot, the reference renders a resting and a hovered button
      the same colour to the channel. `button_hover_fill` is therefore gone
      rather than retuned. The second is that the resting face itself sat
      too far out: at 0.05 of the ink axis it measured `#f4f4f4` on a white
      card while a disabled control sat at `#e2e3e3`, so an unusable
      control was nearer an available one than the available one was to its
      own card. That reads worst on a combo box, which has no fill but this
      one and sits beside a spin box keeping Fusion's own white Base fill,
      and it was reported that way on the Automation pane — the dropdowns
      look disabled. At 0.02 the face is a step out of the card and no
      more, against the reference's own 0.014.
      The disabled treatment is on that list too. The desktop's own palette
      repeats its Active colour group in its Disabled one, so Fusion rendered
      an enabled and a disabled push button with pixel-identical fills and the
      Stop button read as usable while the desk was still. The app supplies
      its own: a disabled control's face, its edge, its label *and its icon*
      all come from `theme()`, and what makes it read as unavailable is that
      the edge and the label each sit about a quarter as far from the fill as
      an enabled control's do. How far each should go is a judgement to make
      from the installed package alongside the border weight.
      *The checkbox with no outline is closed (2026-08-17).* It was the
      **checked** state, and it reproduced on the Automation pane of the
      installed package: zero frame pixels inside the checked indicator's
      rect against the 24 the unchecked box beside it drew. It never
      reproduced offscreen because it was being measured as "is there any
      frame", and Fusion supplies one of its own there; measured instead as
      "does the app's own border token appear", it reproduces exactly. The
      style used to leave the checked and tristate glyphs entirely to
      Fusion, so whether a checked box had a box at all was a property of
      whichever palette turned up. It now strokes all four states alike.
      A seventh pass (2026-08-17) then asked for the ticked box to carry
      the reference's bluish fill and a smoother mark than Fusion's, and
      **that is the second deliberate widening of this phase's scope**
      after push buttons (D-17): until then the style owned frames and one
      panel, and a check mark is a glyph. The ticked and tristate states
      are now painted outright — `theme().accent_fill` inside, the app's
      own two-segment mark with a round cap and join on top, both from
      fractions of the box so they are the same drawing at 150% text.
      The edge is deliberately *not* bluish, unlike the reference's: every
      edge the style strokes is one token, and that is what keeps hover
      (0.65 toward the accent) and focus (the accent outright) orderable
      on this control.
      An eighth pass (2026-08-17) settled that edge the other way: the
      reference marks a ticked state in the accent on the border as well
      as the fill, so a ticked box now strokes `theme().accent_border` and
      that is the **single, written-down exemption** from the one-edge-
      token rule. The three edge states stay ordered through it (measured
      light against the card: resting 148, hover 252, focus 297) because
      `accent_border` mixes the accent *into the card* while hover and
      focus are carried from the neutral edge toward the accent itself; a
      five-palette test holds that rather than leaving it to reasoning.
      The same pass sized the indicator from the label's own line height
      instead of Qt's hardcoded 14 — 15 at his 22px metrics, matching the
      reference, and 23 at 150% text where Fusion would still say 14 — and
      filled a dropdown from the card like the field it is, since Fusion
      routes a combo's body through the push button's panel and the spin
      box beside it never entered that ramp at all.
      *The capability question is settled, with evidence.* The desktop's own
      style cannot be loaded into the bundled Qt, but not for the reason first
      assumed: Breeze itself references only public `Qt_6` / `Qt_6.10`, and Qt
      permits a plugin built against an older 6.x minor to load into a newer
      one, so neither the version gap nor the shared sonames is the blocker.
      Four KDE Frameworks libraries in Breeze's dependency graph —
      `KF6WindowSystem`, `KF6IconThemes`, `KF6ColorScheme`, `KF6GuiAddons` —
      bind `Qt_6.10_PRIVATE_API`, which the bundled Qt 6.11.1 does not provide,
      and Qt guarantees no binary compatibility for private or QPA API across
      minor releases. Reproduce with `readelf --version-info` over that graph
      before anyone reopens this. Bundling Qt and using the host's styles are
      mutually exclusive by construction; the Flatpak escapes it only because
      its whole runtime is `org.kde.Platform`, which ships a matching Breeze.
      What *does* cross the boundary is preferences, not renderers, which is
      what `gui/appearance_portal.py` now reads.
      Do not re-derive any of this; it cost a full research pass.
- [ ] **The 3:1 non-text contrast floor now lives nowhere in the app** — WCAG
      2.1 SC 1.4.11 was dropped as a standing invariant (a deliberate decision,
      not a drift: the app's control-border weight is a look choice and is
      expected to sit below it), and the desktop portal's high-contrast
      preference is read but acted on by nothing. So a user who has asked their
      desktop for high contrast gets the same pixels as everyone else. Deciding
      what to do about that is a scope question in its own right: honouring the
      preference means a second set of border tokens and a rule for which
      surfaces they cover — and note the app now has *one* edge token rather
      than two, since the split that existed to hold control frames to the
      floor was collapsed once the floor went. The answer probably belongs
      with the deferred
      in-app Light/Dark/System theme control rather than beside it.
      `gui/appearance_portal.py` already returns the value; nothing consumes it.
- [ ] **Two control primitives are still drawn by Fusion alone** —
      `gui/style.py` overlays the checkbox indicator, the combo frame, the
      spin frame and the push button frame. `QLineEdit`
      (`PE_FrameLineEdit`/`PE_PanelLineEdit`) and
      `QRadioButton` (`PE_IndicatorRadioButton`) are not touched, so they keep
      Fusion's own untheme'd hairline, and since the control edge was
      re-weighted that hairline is the *heavier* of the two: measured in one
      card in the light scheme, the line edit's first border pixel is
      `#ababab` where the combo, spin and time edit beside it read `#c7c7c7`.
      That is visible on the Settings page, where the MAC address field sits
      beside the Language dropdown, in every preset row, and in the setup
      wizard, where two radio buttons render to different rules than the app's
      checkboxes. Extending the overlay is small (a radio needs an ellipse
      rather than a rounded rect), but it is a look change, so it belongs in
      the same real-desktop pass as the border weight above rather than being
      landed unseen.
      **Half of this closed on 2026-08-17.** On a scrolling page the line
      edit had no frame at all, because the scroll body's unqualified
      `background: transparent` took every descendant off the style's box
      model. Fixing that put Fusion's own hairline back and made the
      mismatch real — `#ababab` against the `#cfcfd0` of the spin box in
      the same card — so `QLineEdit` was brought onto the app's own
      draw-through-then-overlay path, unchanged from the one the combo and
      spin frames already use. **`QRadioButton` is what is left**, and it
      is only reachable in the setup wizard, which no real-desktop pass has
      covered yet; a radio needs an ellipse rather than a rounded rect.
- [ ] **The scrollbar is Fusion's entirely, and is the least reference-like
      control on screen** — reported 2026-08-17 from the installed package as
      looking "cut off to the right" on the Automation page. It is Fusion as
      designed: stepper arrows top and bottom, a 14px track, and a slider with
      almost no contrast against its own groove, where the reference has no
      arrows and a slim inset rounded bar. **Deferred by an explicit scope
      decision, not overlooked** — owning it makes the scrollbar a fourth
      control family the app draws, after frames, the button panel and the
      checkbox indicator, and Phase 9's own constraint is not to widen what the
      app overrides one complaint at a time. Two dead ends are already measured
      out so nobody re-derives them: the desktop's own scrollbar cannot be
      adopted, because it lives in the Breeze *style plugin* and a plugin loads
      whole or not at all, so the private-API blocker takes it too; and there is
      no cheap hook, because a scrollbar reaches `gui/style.py` as exactly one
      `drawComplexControl(CC_ScrollBar)` call with Fusion painting groove,
      slider and arrows internally. A working prototype (~55 lines over
      `pixelMetric`, `subControlRect` and `drawComplexControl`) is described in
      full in `.planning/todos/pending/2026-08-17-draw-the-scrollbar.md`,
      together with what it still owes: hover, pressed and disabled states, a
      horizontal orientation actually exercised, and the five-palette tests.
- [ ] **The emphasis tint's weight is still undecided, now that selections
      have stopped using it** — reported 2026-08-17 from the installed package,
      dark scheme: the selection highlight read "a little bit muted", with the
      maintainer's own qualification that on the other controls sharing the
      same fill "it doesn't look as bad actually". That split turned out to be
      the answer rather than a hedge. The sidebar's selected row and the
      dropdown's highlighted option were *selections*, and a selection is the
      one thing the user has a reference for in every other Qt application on
      the machine, so both now take `QPalette::Highlight` and its
      `HighlightedText` partner at full strength instead of `accent_fill` —
      nothing tuned, nothing to choose. What is left is the narrower question
      the report also raised: whether `accent_fill = _mix(base, accent, 0.16)`
      is the right weight for the three consumers that mark **emphasis** and
      not selection — a ticked checkbox, a chosen `SegmentedControl` segment,
      and `primary_button`. Judge those on a real desktop in both schemes
      together rather than one at a time, since a fraction that reads well on a
      22px segment can wash out inside a 15px checkbox, and the fraction is
      measured from the card, whose distance to the accent differs between the
      schemes. If it moves, `tests/test_control_tokens.py` already pins the
      three relationships it has to keep across five palettes. Worth deciding
      alongside the high-contrast preference item above: a user who asked their
      desktop for more contrast is exactly the user this tint is quietest for.
- [ ] **The trimmed Qt is verified by nothing but the offscreen platform** —
      the RPM ships Qt cut down by ELF reachability, and every automatic check
      of it runs headless: the spec's `%check` and the suite force
      `QT_QPA_PLATFORM=offscreen`, and the container portability proof starts
      the daemon, which does not link Qt at all. The xcb and wayland platform
      plugins, the icon engine against a real theme, and the tray are reached
      only by hand, from `docs/MANUAL-TESTING.md`. A trim that dropped
      something one of those needs passes every gate this project has and fails
      on the first desktop.
- [ ] **The split spec has no build gate and has now drifted much further from
      the one that ships** — `packaging/idasen-companion.spec` plus
      `python-bleak.spec` and `python-idasen.spec` build the repo-shaped
      three-package set, and nothing in CI builds any of them; it shipped once
      with a broken `%install`, unbuilt and undetected. The risk grew rather
      than shrank: the bundled spec is now a different kind of package
      altogether — private runtime directory, run-time interpreter choice,
      trimmed Qt, architecture-specific, no `python3-*` requires — so reading
      one of the two tells you nothing about the other, and the version
      agreement a test does pin is most of what they still share. Either gate
      it in CI or decide out loud that it is unsupported, somewhere a packager
      will see it.
- [ ] **Nothing watches the versions of anything the RPM bundles, and the
      interpreter is now one of them** — `scripts/fetch-bundled-runtime.sh`
      pins the nine distributions the package vendors *and* the CPython it
      carries, and the spec restates each of the ten in a bundled-component
      line, nine of them with a licence text as well. That those agree is now
      checked; what nothing checks is how old any of them is. A security fix
      reaches a user only when somebody bumps that script by hand and rebuilds.
      There is no schedule, no advisory feed and no check that notices a pin
      has aged, and bundling is precisely what makes that this project's
      problem rather than the distribution's. Same gap as the scheduled
      dependency audit further down, for what ships inside the package rather
      than what it declares.
      **The interpreter statically links its own OpenSSL, so the machine's
      security updates do not reach it.** Nothing about installing a
      distribution's `openssl` update touches the copy inside this package —
      `objdump` shows no `libssl` in what the binary links, because the library
      is compiled in. The only answer to a CVE there is to rebuild at a newer
      python-build-standalone release and ship a new package; there is no
      in-place patch path and there cannot be one. That is an accepted
      consequence of carrying an interpreter, not a defect — the same trade
      made knowingly when the package stopped asking the machine for a Python
      — and it is written here so that it stays a decision rather than becoming
      a discovery. The same applies to the six other C libraries compiled into
      it (ncurses, Berkeley DB, libmpdec, liblzma, zlib, bzip2); OpenSSL is
      simply the one whose advisories arrive most often.
- [ ] **Nothing holds the licence expression against what the interpreter
      actually links** — the spec now names fourteen terms and ships a text for
      each, and two standing tests hold those two lists against *each other* in
      both directions. Neither can tell you the list is still right. The terms
      come from python-build-standalone's own build metadata, and that file
      ships only in their multi-hundred-megabyte debug archives, not in the
      `install_only` tarball this project downloads — so the mapping was
      established by fetching an archive that is not part of the build, and
      cross-checking each component's version out of the shipped binary. An
      interpreter bump that adds, drops or swaps a statically linked library
      changes the answer, and nothing in this repository would notice: the
      build stays green, the tests stay green, and the field quietly describes
      the previous interpreter. Cheapest honest fix is a script that reads the
      metadata out of the matching full archive at bump time and diffs the term
      set against the spec — run by hand when the pin moves, not in CI, since
      it needs a download the build deliberately avoids.
- [ ] **The bundled interpreter's symbol table is no longer stripped, because
      the 3.14.7 pin carries BOLT** — `trim-cpython.py` detects BOLT's rewrite
      markers in the interpreter binary's own section headers and declines to
      strip a binary that carries them, because every strip implementation
      tried against this toolchain (`strip`, `strip --strip-debug`, `objcopy
      --strip-unneeded`, `eu-strip`) corrupts one into a binary that exits 127
      while still passing the trim's own before/after size check. This is no
      longer a hypothetical: the pin moved to 3.14.7 in the CPython-version
      bump, and the skip fires on every build now, confirmed by a real
      `rpmbuild -bb`. A second, related fact the bump also surfaced: RPM's own
      automatic `__brp_strip` build-root policy runs `strip` over the whole
      buildroot *again* after `%install`, independent of `trim-cpython.py`,
      and corrupted the same binary the manual skip was protecting — closed by
      setting `__brp_strip`, `__brp_strip_comment_note` and `__brp_strip_lto`
      to `%{nil}` in the spec (`%undefine` measurably left the platform's own
      definition running; only overwriting the name took). That switch cannot
      be scoped to one path, so it spared every ELF file in the buildroot;
      `scripts/strip-bundled-tree.sh` now runs the same pass by hand over
      everything but the rewritten binary, and `verify-bundled-elf.sh` refuses
      a tree where anything else still carries a symbol table. Measured cost of
      leaving the interpreter unstripped: ~3 MB uncompressed (32,062,496 →
      29,076,616 bytes is the reduction a working strip would have performed,
      measured on the corrupted output before its symbol table broke it). The
      maintainer accepted the skip and the ~3 MB it costs when the CPython
      bump handed it over, so the package ships unstripped deliberately rather
      than by omission. Two untried alternatives came with that decision. The
      one worth trying — an alternate strip toolchain inside the CI
      container — is its own item below. The other was looked at and not
      chosen: a targeted section-preserving `objcopy` that keeps `.dynstr`
      intact, never attempted, recorded here only so nobody rediscovers it as
      novel.
- [ ] **Try an alternate strip toolchain inside the disposable Fedora 43 CI
      container** — the reason the interpreter ships unstripped is that every
      strip implementation on this workstation's binutils 2.45.1 corrupts a
      BOLT-rewritten binary (see the item above). Neither a newer binutils nor
      `llvm-strip` has been tried, because neither is installed here and
      installing one on a persistent workstation to test a packaging question
      is the wrong trade. The CI container is disposable, so the same
      experiment is cheap there: install the alternate toolchain, strip the
      3.14.7 interpreter, and run `prove_standard_library()` against the
      result — that is the check that already catches the corruption, so a
      pass is a real answer and a failure costs a container. Worth ~3 MB
      uncompressed if it works. Recheck the premise first: the corruption was
      measured on one binutils version against one asset, and a later
      python-build-standalone build or a later binutils may simply not
      reproduce it.
- [ ] **A regression test asserting `libcrypt.so.1` has left `Requires`** —
      offered during the CPython 3.14 bump and declined (D-06): the crypt
      extension's departure from CPython means the interpreter trim no longer
      links it, and the built package's `Requires` lost the two `libcrypt.so.1`
      lines the 1.0.2 (3.11) artifact carried, confirmed on a real
      `rpmbuild -bb` at 3.14.7. The departure is recorded in the spec's own
      comment above `Requires:` rather than gated by a test. Reconsider only
      if a later change is suspected of bringing the dependency back.
- [ ] **A shared module list between `trim-cpython.py` and
      `verify-rpm-portability.sh`** — offered during the CPython 3.14 bump and
      declined (D-14): the portability script already imports `bleak` and
      `idasen` and runs a real statistics round trip on five images, and the
      trimmer already imports thirteen modules and completes a `sqlite3` round
      trip at build time, so repeating the module list post-install would only
      catch a `%files` omission that packaging the whole private tree already
      rules out. Revisit only if the two lists actually drift.
- [ ] **Half of what the RPM build downloads is authenticated and half is not**
      — `fetch-bundled-runtime.sh` fetches the interpreter from a pinned URL
      and holds it to a pinned SHA256 *before* anything unpacks it or runs it,
      so that payload is either the reviewed bytes or the build stops. The nine
      wheels are not: they are pinned by version only, which says what to fetch
      and nothing about what came back, so an index URL in the environment
      still redirects those downloads silently — and they end up inside a
      signed release artifact carrying a private Qt. Closing the second half
      means generating a requirements file with hashes and requiring them.
      One smaller gap sits with it, and one has gone. Still open: the archive
      step records mtimes, ownership and directory order, so two runs on one
      host do not produce identical bytes; normalising the archive's metadata
      closes that. No longer true: which wheels arrive used to depend on the
      build host's Python, and the set is now resolved by the pinned
      interpreter the package carries, so every host fetches the same files.
- [ ] **Review the admin/owner branch-protection bypass before the repository
      goes public** — Phase 4 applies branch protection to `main` with
      `enforce_admins: false`, a deliberate, temporary accommodation so the
      solo maintainer isn't locked out while the repository is private. It
      deviates from CI's own point: a red run should not be overridable, and
      right now the owner can override one anyway. Revisit — most likely
      flip to `enforce_admins: true` — the moment the repository is made
      public, the same trigger as the `SECURITY.md` item directly below.
- [ ] **`SECURITY.md` points at a button that does not exist yet** — it tells
      reporters to use Security tab → Report a vulnerability, and
      `.github/ISSUE_TEMPLATE/config.yml` links to the advisory page. GitHub only
      offers private vulnerability reporting on **public** repositories, and on
      org-owned private ones with Advanced Security — not on a private repo owned
      by a personal account, which is what this is today. Verified by running the
      same `PUT /repos/.../private-vulnerability-reporting` call against three
      repos on the same account: it succeeds on a public one and 404s on private
      ones, so it is visibility, not a token scope problem. Harmless while the
      repo is private and has no other readers. **Enable it the moment the repo
      goes public** — it is free there, and that is exactly when the instruction
      starts being read by people who need it. Nothing else to change if enabled
      then; the wording is already correct for that state.
- [ ] **Per-file SPDX headers** — `README.md` and `pyproject.toml` now name the
      copyright holder, but no source file carries
      `SPDX-License-Identifier: GPL-3.0-or-later`, which is what the GPL's own
      "How to Apply These Terms" and REUSE both ask for. Deliberately skipped
      during the release review: 47 one-line changes would have buried the rest
      of that branch. Mechanical whenever someone wants it.
- [ ] **The GUI reads tabular D-Bus data as bare tuples** — `get_daily_stats`,
      `get_transitions` and `discover` return `list` of positional tuples that
      widgets destructure by index (`pages/statistics.py`, `gui/tray.py`), so
      reordering a `SELECT` in `daemon/stats.py` breaks the GUI silently and
      mypy sees `Any`. The log-entry shape is worse: it is hand-rebuilt in
      three places (`daemon/ringlog.Entry`, `ActivityLogPage._normalize`,
      `core/journal.read_recent`). A `core/wire.py` holding frozen dataclasses
      with `from_json` classmethods would give the wire one parse point, in
      `core/` because both processes need it. The JSON-string wire format
      itself is fine and stays — this is about decoding it once instead of
      four times. Not urgent; it is an internal shape, not a compatibility
      commitment.
- [ ] **`tests/` has seven independent `Daemon.__new__` harnesses** — plus 13
      copies of the `qapp` fixture, 12 near-identical `FakeClient` QObjects and
      3 copies of the tray teardown (a `QSystemTrayIcon` collected after the
      offscreen platform is gone segfaults the interpreter at exit, so each
      copy must destroy it explicitly). The divergence is not cosmetic: some
      harnesses use a `MagicMock()` config, where every unset attribute is
      truthy, and others a real `AppConfig()`, so a new config gate silently
      takes opposite branches in different files. Adding one instance
      attribute to `Daemon` during the release review meant patching 20 sites
      by hand, twice. A shared `conftest.py` builder would fix both.
- [ ] **`tests/test_machine.py` is ~1400 lines** with 14 section banners that
      are the natural split points (lifecycle / presence / moves / sync /
      controls). Only `SIT_H`/`STAND_H`, `make_config`, `ZeroRng`/`MaxRng` and
      `Driver` bind them together; move those to a shared harness and the split
      is mechanical. `test_ble_link_recovery.py` and `test_config_reload.py`
      also hand-roll `StateMachine(cfg, MockDesk(), now=0.0)` and would use it.
- [ ] **The app tracks active time, never time in position** — `active_time` is
      credit toward the next move, not how long the desk has been sitting or
      standing, and the two diverge whenever the accumulator is frozen (idle,
      lock, away, pause, snooze, out-of-hours, held). The tray tooltip used to
      render it as "Sitting for 22m", which reads as the latter; a prior change
      stopped showing it once the cycle stops running down, since there it is a
      stopped clock that looks like a running one. The feature underneath is
      still missing: when you snooze you are still sitting there, and "how long
      have I been in this position" is a real question the app cannot answer.
      Needs a wall-clock `position_since` stamp (distinct from `_begin_cycle`,
      which an adopted external move does not call), a new D-Bus property
      carrying the timestamp rather than a duration so the GUI can age it, and
      recovery across a daemon restart from the `transitions` table. Would
      dissolve the stopped-clock problem entirely and retire
      `gui/tray.py`'s `_cycle_stopped()`.
- [ ] **The recent-input gate acts on an idle reading taken before the BLE
      connect** — `recently_active` is computed once at the top of `tick()`
      from the `idle_ms` sampled at line `daemon/main.py:450`, but with
      `notifications.enabled = false` `_sync_lead_time()` returns 0, so the
      pre-decide sync (`core/machine.py:471`) and the move itself both run
      *later in that same tick*, behind an on-demand BLE connect. The move
      therefore executes against an idle value that is stale by however long
      the connect and height read took. Bounded by the connect, so seconds
      rather than minutes — not a reason for a move to fire while the user is
      genuinely away — but it does mean the gate is slightly more permissive
      than `recent_input_threshold` states. Fix is cheap: re-sample idle (or
      pass a callable) and re-evaluate `recently_active` immediately before
      `_execute_transition`. Not done yet because it needs a way for the core
      to ask for a fresh reading without depending on the daemon's monitors.
- [ ] **Idle detection only covers GNOME, KDE and X11** — the three providers
      are Mutter's IdleMonitor, `org.freedesktop.ScreenSaver` (KDE) and the X11
      XScreenSaver extension (`daemon/idle.py`). A Wayland compositor that is
      neither GNOME nor KDE — sway, Hyprland, river — matches none of them, and
      lock detection fails the same way. `get_idle_ms` then returns a flat `0`,
      which reads as "at the keyboard right now", so the app cannot keep its
      central promise (never move the desk while you might be away) and cycles
      on a plain schedule instead. Deliberately still moving the desk rather
      than standing down — silently disabling automation for setups that work
      acceptably today would be the worse surprise — but it now warns loudly at
      startup. Fix (design settled 2026-07-28): add a
      `WaylandIdleProvider` on `ext-idle-notify-v1` at the *bottom* of the chain, so
      GNOME/KDE/X11 machines are untouched. The notification-vs-polling shape
      mismatch dissolves at the provider boundary — synthesize `get_idle_ms` from
      the `idled`/`resumed` events, since two of its three consumers are threshold
      comparisons and the third (backdating) is served better by an event timestamp
      than by a `check_interval` sample. `python3-pywayland` is packaged in Fedora
      and ships the generated bindings, so it can be a `Recommends:` with the
      provider raising from `__init__` when it isn't usable. Rejected: logind's
      `Session.IdleHint` (nothing sets it on a bare wlroots session, so it fails
      open exactly like today *and* silences the `IDLE_NO_PROVIDER` warning).
      Unchanged: with no provider at all, still move and warn loudly.
- [ ] **Two workstations on one machine can't be told apart** — with a
      multi-seat setup (two monitors/keyboards/GPUs on one box) both sessions
      are legitimately `Active` on their own seats, so both daemons believe
      they own the desk, though the desk physically stands at one of them.
      logind cannot answer this: "which seat is the desk at" is not a question
      about seats. Deliberately unhandled — every candidate fix (naming the
      seat in config, a per-account role, a first-come ownership claim) either
      requires the *other* user to configure their own copy, or settles it by
      who booted first, which can hand the desk to the person sitting at the
      other workstation. Revisit if anyone reports it; the workaround is to
      turn `[automation] enabled = false` on the account that isn't at the desk.
- [ ] **Automation cycle progress is lost on daemon restart → moves get deferred**
      — `StateMachine.start()` seeds `active_time` at 0 and rolls a fresh target
      every launch; it reads the desk *height* (to recover sit/stand state) but
      **not** how long you've already been in that position, and nothing persists
      cycle state. A restart landing late in an interval pushes the next move out
      by a whole new interval. Confirmed 2026-07-20: desk stayed standing because
      a 12:25 restart reset a ~25-min stand cycle to a fresh 30-min one.
      The **silent** half is fixed — startup emits `startup.cycle_reset`, so the
      Activity Log says the clock restarted rather than leaving you to work out
      why the desk never switched. The move is still late.
      Scope is narrower than it looks: a fresh cycle after a *reboot* is arguably
      correct (new work session), and any conservative staleness guard rejects a
      reboot's downtime anyway — so the fix only really helps **short service
      restarts** (`systemctl restart`, a `dnf update` of this package while you're
      sat there). Developer-facing plus rare package updates; low priority.
      Fix: persist `active_time` + `target_duration` + a write timestamp to
      `$XDG_STATE_HOME`, restore on startup, don't restore if the timestamp is
      stale. `target_duration` is the part that *forces* persistence — it's a
      fresh random roll and isn't recoverable from disk. Note
      `TIME_JUMP_THRESHOLD_SECONDS` is **not** the constant to reuse: it's checked
      against the gap between two ticks of a *live* process, so it never sees a
      restart's downtime.
- [ ] **Tray icon should signal an imminent/active move** — when automation is
      about to move the desk (during the pre-move lead-time window / on
      `PreMoveWarning`) and while `Moving` is true, show something distinct in the
      tray as ambient feedback: e.g. a different/annotated icon (up/down arrow
      overlay), an attention state, or a tooltip change, reverting once settled.
      Goal: the user can tell at a glance the desk is about to move or is moving,
      not just infer it from the Bluetooth indicator. Feasibility TBD —
      `QSystemTrayIcon` supports swapping the icon and `showMessage`, but a
      themed symbolic-icon variant/overlay that recolors with the panel may be
      fiddly (see the symbolic tray icon work); may not be fully doable, scope
      before committing.
- [ ] **Untested: GNOME X11/Wayland, the non-default KDE session, the split RPM**
      — `docs/MANUAL-TESTING.md`
      was 37 items with none ever ticked, which read as "never tested against
      hardware". Untrue: most of it (linger, live height, tray gestures, CLI,
      single-instance, KDE idle/lock/suspend, install and upgrade) is exercised
      daily, and the July 2026 outage hammered the BLE failure path. Rewritten to
      record that as covered and keep a checklist only of what needs deliberate
      setup — ~15 items, each tagged with its cost (`[GNOME]`, `[unpair]`,
      `[power]`, `[sweep]`, `[split]`). Real gaps: **every GNOME path** (the tray
      is optional *by design* because GNOME may not show it, and that design has
      never met a GNOME session), the other KDE session type, the split spec —
      it builds by hand (fixed and proven this phase) but nothing in CI gates
      it, so it can go stale again — fresh pairing/discovery, out-of-range desk,
      and the policy matrices (ordinary use only exercises whichever value is
      configured). Newest and now the largest of them: **the window, the tray
      and the icons under the trimmed bundled Qt**, on both session types, from
      the installed package — every desktop path the RPM has now runs on a Qt
      this project assembled rather than on the distribution's, and no
      automatic check ever leaves the offscreen platform.
      **Run it interactively** — ask a session to work a tagged subset, prompting
      for what you observed at each step; reading top to bottom is what produced
      the 37 dead checkboxes. If the GNOME block is never realistically going to
      run, decide that explicitly and say so in `README.md` rather than carrying
      the items forever.
- [ ] **OSS hygiene files deferred from the release-readiness audit** — that
      audit (`RELEASE-READINESS.md`, kept in the parent directory rather than
      in the repo, since it documents where a credential lived) lists 18 tasks.
      Phase 04.1 carries the publication-risk ones and explicitly rejects
      `CODEOWNERS`, Dependabot and the workflow consolidation. These are what
      is left, none of them a publication risk, all cheap:
      `.editorconfig` (T-009) and `.gitattributes` (T-010) — the repo ships
      Python, Markdown, YAML, TOML, shell, XML, `.desktop`, `.spec`, PO/TS
      sources plus PNG screenshots and compiled `.qm`/`.mo` catalogs, and
      nothing currently declares which of those are binary; `examples/config.toml`
      (T-016) — README documents the config path but ships no sample; a Makefile
      or task runner (T-017) wrapping the commands `CONTRIBUTING.md` already
      spells out.
- [ ] **A scheduled dependency audit, once the repository is public** (T-015 in
      `RELEASE-READINESS.md`) — CI has tests, type checks, artifact audit,
      catalog checks, AppStream validation and packaging, but nothing watches
      the dependencies over time, and `pyproject.toml` uses lower bounds with no
      lockfile. A weekly `pip-audit` workflow is the obvious shape. Deliberately
      **not** in Phase 04.1: a scheduled safety net only starts earning after
      the flip, and it drags in a vulnerability-triage policy that a
      pre-publication hardening pass should not be deciding in passing.
- [ ] **Decide provenance vs. signatures for release artifacts** (T-018 in
      `RELEASE-READINESS.md`) — releases publish `SHA256SUMS`, and README is
      already careful to say checksums detect corruption rather than forgery.
      Closing that gap means either Sigstore/GitHub artifact attestations or
      detached signatures over the RPM, `.deb`, Flatpak bundle and the checksum
      file, plus a documented verification command. This is a real design
      decision, not a chore — attestation needs no key custody, a signing key
      does.
- [ ] **Nothing cleans up the KDE-side remnant of the removed shortcuts portal**
      — `core/config.py` drops the obsolete `[hotkeys]` TOML table on load, but
      a `[token_io_github_extricator_IdasenCompanion_shortcuts]` section is left
      behind in the user's `~/.config/kglobalshortcutsrc` by the in-app XDG
      global-shortcuts portal that was removed. It has no active bindings, so it
      is inert, but it shows up as a phantom "xdg-desktop-portal-kde" component
      in System Settings → Shortcuts. Either a migration note or an
      uninstall-cleanup step. Found 2026-08-10 while diagnosing why a Plasma
      custom shortcut would not fire from the lock screen (Phase 5).
- [ ] **Rotate the `GH_TOKEN` in `.envrc` onto a `gh` keyring login** — one
      line, `export GH_TOKEN=github_pat_…`, written on 9 May for `direnv`. The
      release-readiness audit calls it a release blocker (T-001); it is not,
      and Phase 04.1 records why — the file was gitignored, untracked and in
      zero commits, so publication could never have exposed it. It was moved
      out of the repository entirely on 2026-08-10, which settles the only part
      that touched this project: it can no longer be committed by accident or
      trip a working-tree scan. What remains is ordinary credential hygiene and
      is now *wider*, not narrower — from the parent directory `direnv` exports
      the PAT into every process started in any sibling project, not just this
      one. Do not simply revoke it: `gh auth status` reports **no logged-in
      host** once the variable is unset, so this token is currently the only
      thing authenticating `gh`, and Phase 04.1's criterion 4 plus Phase 4's
      branch-protection and private-vulnerability-reporting steps are all `gh
      api` calls. Order that works: `gh auth login`, confirm `gh auth status`
      without the variable, then delete `.envrc`, then revoke the old PAT at
      GitHub.
- [ ] **`connection_state`'s mark says "returns translated text" and one
      member of what it returns is a theme colour** — the helper hands back a
      colour plus two translated strings, and the self-enforcing guard
      *forces* the mark on it because its body reaches the translation
      wrapper. So the registry's stated meaning and the guard's enforcement
      disagree at this one member. Downstream, the concatenation check treats
      the colour as translated text: it discards a subscript's index when it
      resolves, and since unpacking now binds every name to the whole
      right-hand side, all three unpacked names resolve that way. Harmless
      today — nothing glues the colour, and erring toward flagging is the
      safe direction — but it is the accuracy slip the naming convention's
      first tier is about. Two ways out: soften the registry's wording to
      "reaches a translation", or split the colour out into its own helper so
      the mark means exactly what it says. Found reviewing the phase that
      added the mark.
