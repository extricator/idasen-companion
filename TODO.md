# Idasen Companion — TODO

Glanceable task list for anyone working on this project. Keep it current:
add new items as they're discovered, and **delete** finished ones outright —
no checkmarks, no Done section. This file is what's left to do; git history is
the record of what was done.

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
      persisted to config). Needs live-restyle plumbing: rebuild page
      stylesheets on `QEvent.ApplicationPaletteChange` and on manual toggle —
      colors currently bake at widget construction, so styled surfaces go stale
      until restart. This also fixes the *system* light↔dark switch being stale.
- [ ] **Setup wizard** (`gui/setup_wizard.py`) still uses the pre-redesign look;
      design README §6 pages "remain to be done in this style".
- [ ] **`widgets.py`'s `DailyBarsChart._tooltip_for` is untranslated** — its
      Statistics-chart tooltip is built as a bare f-string
      (`f"{label}: sitting {…}, standing {…}"`, `f"{label}: no data"`),
      user-facing and not in any catalog. Pre-existing, not introduced by the
      locale-formatting work above; needs its own new catalog entries.
- [ ] **Non-Latin digit sets aren't handled by `fmt_hm`/`fmt_countdown`** — the
      locale-aware formatting task deliberately routed only the fractional
      centimetre values through `QLocale`; the small integers in
      `fmt_hm`/`fmt_duration`/`fmt_countdown` keep native Python formatting
      because `QLocale.toString` has no padded-integer overload (breaking
      `fmt_hm`'s `"1h 05m"` zero-padding and `fmt_countdown`'s `"2:05"`), and
      padding a native-digit string with an ASCII `0` would be wrong. Only
      worth revisiting once a language with non-Latin digits actually ships.
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
- [ ] **`packaging/idasen-companion-bundled.spec` carries a stale `Requires:
      python3-voluptuous`** — nothing in `src/` imports `voluptuous` and
      `pyproject.toml` does not declare it; the sibling
      `packaging/idasen-companion.spec` does not list it either, and nothing
      enforces the two specs' `Requires:` lists staying consistent with real
      imports. Harmless (the package exists and installs) but is dependency
      drift. Phase 3 deliberately did not copy it into `debian/control`.
      Generalisable gap: `tests/test_packaging.py` pins `Version:` agreement
      between the specs but not `Requires:`.
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
      never met a GNOME session), the other KDE session type, the three-package
      COPR split build, fresh pairing/discovery, out-of-range desk, and the policy
      matrices (ordinary use only exercises whichever value is configured).
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
