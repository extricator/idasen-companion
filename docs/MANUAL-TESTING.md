# Manual test checklist (hardware / desktop-session paths)

Unit tests cover the state machine, config, scheduling, stats and the BLE
connection policy against fakes. This file is for what they can't reach.

**It is deliberately not a list of everything the app does.** An earlier
version was, and it aged badly: 37 items, none ever ticked, most of them
things that get exercised several times a day just by using the app. A
checklist nobody works through implies zero coverage, which was never true —
so the parts that ordinary use already covers are recorded below as such,
without checkboxes, and the checklist proper is only the paths that need
deliberate setup to reach.

## How this gets run

**Interactively, one item at a time — not by reading top to bottom and ticking
boxes.** That is what produced 37 dead checkboxes. When the time is right, ask
a session to work through a subset: it prompts for what you observed after each
step, records the answer, and moves on. You watch the desk and answer; it keeps
the state.

That is what the tags are for. A session picks a runnable subset *up front* —
everything `[sweep]` today, `[GNOME]` once there is a VM — and confirms the
setup cost before starting, rather than stalling halfway through on a step that
needs the desk unpaired. The tags:

- **[GNOME]** — needs a GNOME session (a VM or a second login on the box).
- **[unpair]** — needs the desk unpaired, so the daily driver stops working
  until it is paired again.
- **[power]** — needs the desk physically unplugged or out of range.
- **[sweep]** — needs config settings cycled through their values, one run
  each, with the daemon reloading in between.
- **[split]** — needs the three-package COPR build, which is not what ships.
- **[flatpak]** — needs the CI-built `.flatpak` bundle installed user-scope.

## Covered by ordinary use — no checklist pass needed

Exercised continuously on the development machine (KDE, real desk, installed
RPM). Re-verify these only when the code behind them changes, not on a
schedule:

- **On-demand linger** — the Bluetooth applet lights on a move and drops after
  the linger window; the `idasen` CLI works again once it does. Timed
  precisely on 2026-08-01, including the cold-connect cost (2.2–2.6s typical,
  ~12.3s worst case).
- **Live height while moving**, and Stop halting mid-travel.
- **Transient BlueZ flake** — retries appear in the journal and commands still
  succeed. The July 2026 outage exercised the failure path hard.
- **Tray gestures and the CLI** — middle-click toggle plus
  `idasen-companion-cli status`, `toggle`, `sit`, `stand`, `stop`, `preset`
  and `log`, including the unknown-preset, missing-name and daemon-down exits.
  The deprecated `idasen-companion --toggle`-style compatibility flags still
  route to the same daemon during the migration window.
- **Single instance**, both halves: a second GUI activates the existing
  window; a second daemon exits rather than running a rival loop.
- **Daemon down** — the red banner and "Start daemon" button in the window.
- **KDE session paths** — tray icon and tooltip, the freedesktop ScreenSaver
  idle provider, lock and idle detection, suspend/resume, notifications.
- **Clock-format environments, window against daemon** — measured 2026-08-29,
  before the `[ui] clock_format` setting was designed, because the design
  hangs on whether the two processes see the same locale environment. The
  session carries `LANG=en_US.UTF-8`, `LC_TIME=C`, and neither `LC_ALL` nor
  `LANGUAGE` is set. The systemd user manager — the authoritative statement of
  what a freshly started `idasen-companiond.service` inherits — holds exactly
  the same two: `LANG=en_US.UTF-8` and `LC_TIME=C`. (No daemon was running at
  the time, so `/proc/<pid>/environ` had nothing to add; the manager's own
  block is the half that answers the question.) The two therefore agree. Under
  the precedence the setting's `system` value implements, `LC_TIME` is
  consulted before any language, `C` names no territory, and the answer is
  24-hour for both — which is what the window already showed, so a user who
  sets nothing sees no change. Note that **no shipped daemon code path renders
  a wall-clock time today**: the notifications speak in relative durations
  ("in about 5 minutes"), and the tray's snoozed-until line is rendered
  GUI-side from a raw timestamp the daemon exports. There is no notification
  clock to compare against the window's, and a later reader should not go
  looking for one.
- **Install and upgrade** — `systemctl --user enable --now` starting clean,
  the desktop entry appearing, and `dnf reinstall` restarting the user
  service. Never chain `systemctl --user restart` onto the install: the RPM's
  own scriptlet already marks the unit for restart, so appending one restarts
  the daemon twice within a couple of seconds and kills the second instance
  mid-startup BLE connect, orphaning the desk's connection slot.

## Other desktops

The tray is optional *by design* because GNOME may not show it, and that
design has never met a GNOME session.

- [ ] **[GNOME]** Tray without the AppIndicator extension: no tray, the main
      window opens on launch, closing it quits the GUI and the daemon keeps
      running.
- [ ] **[GNOME]** Tray with AppIndicator: behaves as on KDE.
- [ ] **[GNOME]** Tray tooltip with AppIndicator: we replace Qt's
      StatusNotifierItem object to split the tooltip into a bold title and
      lighter detail (`gui/sni.py`), verified on Plasma but never on GNOME's
      host. Check the tooltip still *appears* and reads correctly there — a
      host that renders `title` and `description` differently is fine, one that
      shows nothing is not. If the takeover fails outright the tray falls back
      to the plain uniform tooltip, which is also a pass.
- [ ] **[GNOME]** Tray context menu with AppIndicator: the menu is still Qt's
      DBusMenu at `/MenuBar`, which our SNI object only points at — so this is
      the check that the takeover left it intact off Plasma.
- [ ] **[GNOME]** Overview reports Mutter IdleMonitor as the idle provider;
      lock and idle flip the status within one check interval.
- [ ] **[GNOME]** Pre-move notification appears, and its Snooze / Skip
      buttons snooze and skip.
- [ ] **[GNOME]** `idasen-companion-cli toggle` bound to a key in the DE's
      keyboard settings works, on X11 and Wayland.
- [ ] Whichever of KDE X11 / KDE Wayland is *not* the daily driver: idle
      provider, lock, and the global shortcut still behave.

## Desk states that require breaking the setup

- [ ] **[unpair]** Discovery: Settings → "Find my desk…" with the desk in
      pairing mode lists `Desk XXXX` first; selecting it writes the MAC and
      the daemon reconnects without a restart.
- [ ] **[unpair]** First connect against a freshly paired desk: `Sit`/`Stand`
      move it, with the first command paying connect + DPG wakeup.
- [ ] **[power]** Out of range or powered off: manual commands fail with a
      clear error in the log, automation keeps ticking, and the daemon
      recovers when the desk returns.

## Policy matrices

Ordinary use only ever exercises whichever value is configured, so these need
a deliberate pass. All of them involve grabbing the physical paddle mid-move.

- [ ] **[sweep]** Interruption policy, automation path — wait for (or force) a
      scheduled transition and grab the paddle mid-move, once per
      `[automation] interruption_policy`:
      - `undo` — returns to the starting position; log: "… interrupted …;
        returned to start, now …".
      - `leave` — stays where the paddle left it; log: "… left at …". With the
        `yield` external-move policy the next sync then shows "automation
        paused".
      - `retry` — moves toward the target again; log: "… moved toward it again
        …". Grab the paddle a *second* time during that recovery move: there
        must be **no third move**.
- [ ] **[sweep]** Interruption policy, manual path — start a move by a
      companion command, then stop it with the paddle. Under `undo` the desk
      returns once to where it started; under **both** `leave` and `retry` it
      stays put, because retry is automation-only on purpose. The slider's
      explicit target never bounces back under any policy.
- [ ] **[sweep]** Repeat-move gesture, once per `[ui] tray_repeat_move`: with
      **Stop** the repeat halts the desk promptly rather than finishing the
      move; with **Reverse** it returns to the height the move began at; with
      **Off** it re-issues the move. A *different* gesture always redirects to
      its own target instead of stopping. Check both cold (on-demand connect)
      and already-connected.
- [ ] **[sweep]** Window and tray options: `close_action` tray vs quit,
      `minimize_to_tray`, `start_minimized`, and reassigning the left and
      middle click actions. (There is no double-click action: `tray_double_click`
      was removed — see the back-compat note in `core/config.py` — and README
      states it isn't offered.)
- [ ] **[sweep]** Height units — set Settings ▸ Height units to **Inches** and
      confirm every height follows without a restart: Overview's big label,
      spin box and rail; the Presets rail and rows; the tray's Presets
      submenu; the Activity Log; the wizard's success line. The spin box must
      span 24.41–50.00 in 0.25 steps. Press **Move** without touching the box
      — the desk must not shift. The unit is display-only: `[presets]` in
      `config.toml` stays in metres, and the journal keeps logging metres.
      Rail tick labels must not overlap or clip at either unit.
- [ ] **[sweep]** Clock format — walk the three values of Settings ▸ Clock
      format and confirm every wall-clock time follows without a restart:
      the Statistics page's Recent transitions list, and the Activity Log's
      row stamps, which keep their seconds on either clock. **The tray
      tooltip carries a clock in exactly one state — snoozed.** Every other
      line in it is a duration ("Sitting for 40m", "Standing up in 17m"), so
      snooze from the tray before looking or there is nothing there to read;
      and for a moment after snoozing it says "…until later" rather than a
      time, because the deadline is fetched asynchronously. A walker told to
      check "the tooltip's snoozed-until line" without that reported it
      missing, which it was not. At **System default** nothing changes from whatever the
      environment already produced; at **12-hour** the times read with AM/PM;
      at **24-hour** they read 14:32 whatever the environment says. Repeat
      the walk with the display language set to Spanish, where the window
      renders Spanish's own designator, in the case Spanish writes it —
      `2:32 p. m.`, lower case, with a no-break space inside the designator
      — at the 12-hour setting. English stays `2:32 PM`. A capitalised
      `P. M.` there is the defect this sweep is watching for.
      The `journalctl` output is *not* part of this sweep: it stays 24-hour by
      design, whatever the setting says.
- [ ] **[sweep]** Manual-only mode — turn off "Automate sit / stand", then:
      Overview reads "Automation off" with no countdown and offers "Turn on
      automation" in place of Pause / Skip / Snooze, while the tray keeps
      Toggle / Sit / Stand / Presets; moves still work by every route; the
      desk never moves on its own and no pre-move notification appears; a
      paddle move to an arbitrary height raises **no** "automation paused /
      unrecognized position" and Overview does not show "Off-cycle";
      statistics keep accruing and a paddle move is picked up within
      `sync_interval`; a daemon restart leaves it off (unlike Pause); turning
      it back on starts a full interval rather than resuming the old one.
- [ ] **[sweep]** Ambiguous idle window — a transition due while idle 3–10
      minutes must **not** move the desk; the first input triggers the pending
      transition.

## Packaging variant

The standalone full and headless bundled RPMs ship and are rebuilt constantly
from one spec. The distro-integrated split is documented in `CONTRIBUTING.md`,
honestly, as unverified between releases — nothing in CI builds it. All three specs have been built with `rpmbuild -bb`
in a fresh Fedora 43 container: the two library specs during this phase's
research, and the app spec by the fix that landed alongside this checklist
update. What remains genuinely manual:

- [ ] **[split]** `dnf install` of the three RPMs pulls only Fedora-repo
      dependencies.

### What the container proof cannot see

Every build runs `scripts/verify-rpm-portability.sh` against the package it
just made: it installs it in throwaway containers of two RPM lineages — Red
Hat, across three generations of it, and SUSE — and starts the daemon there
under a session bus. So "does it install elsewhere" and "does the daemon come
up elsewhere" are not manual work and are not listed here. One thing it does
*not* prove is the first command a SUSE user runs: see the note in the script,
and TODO.md.

The GUI is, because a container has no display and the offscreen platform
plugin sees none of what follows. The package now carries its own Qt, cut down
to the libraries the app can be shown to reach, and everything below is a way
that cut can be wrong while every automated check stays green. Do these from
the **installed package**, not from a checkout — the bundled copy is the point.

- [ ] Launch the GUI in a **Wayland** session and again in an **X11** one.
      Right: the window appears both times. A missing platform plugin does not
      degrade — Qt aborts on the spot and says which plugin it could not load,
      so there is no ambiguous outcome to record here.
- [ ] The tray icon appears, and is the app's icon rather than a placeholder
      square or a blank gap. Right: it is drawn, and its menu opens.
- [ ] The icons are the drawn artwork, not a fallback: the tray icon, the
      window icon, and the icons on the navigation rail. Right: each is the
      shape it is meant to be. A missing SVG icon engine shows up as
      nothing at all rather than as an error.
- [ ] In the **X11** session, rename a preset and type an accented character
      into the name — `á` by whatever this keyboard reaches it with (a dead
      key, or the compose key). Right: the character arrives. X11 is the case
      that matters: Qt handles none of this itself there, an input-method
      plugin does, and the app ships a Spanish catalog to be used with a
      keyboard that produces such characters. Nothing automated can see it —
      every check here runs on the offscreen platform, which loads no input
      method at all.

### What the offscreen suite cannot see

The suite forces `QT_QPA_PLATFORM=offscreen`, and three things follow from that
which nothing here or in CI will ever settle. `QIcon.fromTheme` resolves
nothing under the offscreen platform — it hands back a null icon whatever name
it is asked for, so an icon missing from every theme on the machine is
indistinguishable from one that is present. The Fusion pixel measurements the
control borders were built on were taken under that platform's single default
palette, so a rule that is right in one scheme and wrong in the other passes
every automated check there is. And the tests switch schemes by calling
`setPalette()` themselves, which is a plausible stand-in for what the desktop
does to a running app and not the same event.

`tests/test_sidebar_width.py` measures the navigation labels at the offscreen
platform's own font, Sans Serif 9pt, and asserts each shipped language's
`sizeHintForColumn(0)` fits inside the computed sidebar width, floor 176px and
ceiling 260px. That catches the offscreen regression — a wrong chrome constant,
a new label that no longer fits at that font. It cannot catch a real desktop
running a larger interface font, which widens every label the same test
measured narrower, so a real Spanish desktop still needs a human to confirm
`Registro de actividad` renders whole rather than eliding.

So, from the **installed package**, with the window already open — no restart
between the switch and the walk, and no navigating away and back to make a page
redraw:

- [ ] With the display language set to Spanish, walk the sidebar at the
      desktop's own interface font (not the offscreen suite's Sans Serif 9pt)
      and confirm `Registro de activi…` never shows: the fifth item reads
      `Registro de actividad` whole. Right: no navigation label elides. A
      desktop running a larger font than the offscreen test's is exactly the
      case the automated fit test above cannot see — it fits at the ceiling,
      260px, but a font large enough to widen the label past that is a human
      check, not an automated one.
- [ ] Switch the desktop from light to dark, then walk all seven pages:
      Overview, Automation, Presets, Statistics, Activity Log, Settings,
      About. Then switch back to light and walk them again. Right: on every
      page nothing has become unreadable against the surface behind it — no
      white on white, no grey on grey — and the card backgrounds, the sidebar,
      the connection footer and the status dot have all moved to the new
      scheme. A page that corrects itself only once you leave it and come back
      is a fail, not a pass.
- [ ] The two lists that are destroyed and rebuilt at runtime: on **Presets**
      and on **Statistics**, switch the theme and then force a rebuild — rename
      a preset, refresh the statistics. Right: rows built before the switch and
      rows built after it are indistinguishable. The Statistics transitions
      list is the one to read closely.
- [ ] On **Settings**, Restore Defaults and Reset each carry an icon and Apply
      deliberately carries none. Right: two icons, one bare button. If an icon
      is missing, record which one — the candidate names were picked for Breeze
      and Adwaita, and a real icon theme is the only place resolution can be
      observed at all.
- [ ] The controls, in **both** schemes: an unchecked checkbox has a visible
      box rather than a faint hairline, a checked one still shows its check,
      and combos and spin boxes have a visible frame with their drop-down arrow
      and stepper buttons intact. Right: all four hold in light and in dark.
      Looking only at the scheme you just switched to is how the failure this
      guards against survives.

### First right-to-left catalog release gate

Structural RTL tests mirror the known asymmetric controls, but they cannot
validate language quality or reveal every interaction between real text,
desktop fonts and widget geometry. Run this block before releasing the first
right-to-left catalog; it is not required while no such catalog ships.

- [ ] A native speaker reviews every translated message in context, including
      plurals, units, clock text, punctuation and mixed-direction values. Right:
      the catalog is linguistically owned, not machine-generated guesswork.
- [ ] From the installed full package, walk all seven pages and every dialog in
      that language. Right: the sidebar moves to the right, its divider stays
      beside the content, forward/action icons face the reading direction,
      joined controls keep one shared seam, and no label overlaps or elides.
- [ ] Exercise the Overview height rail by clicking and dragging both ends,
      inspect the Presets vertical rail, and inspect Statistics with non-empty
      daily bars. Right: painting, labels, fills, targets and pointer hit-testing
      mirror together rather than only looking mirrored.
- [ ] Inspect Activity Log rows containing Latin command text, numbers and
      timestamps. Right: mixed-direction content remains readable and the copy
      icon follows the selected layout direction without reversing the command.

### Flatpak Background portal autostart

Unreachable any other way: `RequestBackground` talks to a real portal
backend and writes real host state, so the branch in
`gui/pages/settings.py` is only unit-tested against a fake bus
(`tests/test_background_portal.py`, `tests/test_settings_autostart_flatpak.py`).
No prior research run ever watched the actual `RequestBackground` call
succeed end to end — the exact autostart entry a live portal backend
generates was never observed, so record what you actually see rather than
comparing it against an expected value.

- [ ] **[flatpak]** Install the CI-built `.flatpak` bundle user-scope
      (`flatpak install --user <bundle>.flatpak`) rather than system-wide, so
      no root step is needed to clean it up afterwards.
- [ ] **[flatpak]** Launch the app from that install and open
      **Settings → General → Start automatically at login**. The row must be
      enabled (not dimmed) and its note must say the grant is managed by the
      desktop's own permission dialog, not by systemd.
- [ ] **[flatpak]** Turn the toggle on. The desktop's own Background-portal
      dialog must appear, asking to let Idasen Companion "run in the
      background" (wording is the desktop's, not ours) and naming the reason
      text this app supplies: "Start the desk automation automatically at
      login". Accept it.
- [ ] **[flatpak]** Confirm a host autostart entry now exists — look under
      `~/.config/autostart/` for a new `.desktop` file naming this app. Open
      it and check its `Exec=` line resolves through the Flatpak launcher
      (`flatpak run …`), not a bare path to `idasen-companiond` on the host —
      the daemon only exists inside the sandbox.
- [ ] **[flatpak]** Log out and back in for real (not just close/reopen the
      window), then confirm the daemon is running — the tray icon appears, or
      `flatpak ps` lists it.
- [ ] **[flatpak]** Turn the toggle off, accept the (likely dialog-free)
      request, and confirm the `.desktop` entry from above is gone.
- [ ] **[flatpak]** The denial path — turn the toggle on and dismiss/refuse
      the permission dialog instead of accepting it. The toggle must return
      to off (never stay ticked on a denial) and a warning dialog must
      explain that the change did not take effect.
- [ ] **[flatpak]** Record, either way: the exact dialog wording your desktop
      showed, the `.desktop` file's path and full `Exec=` line, and whether
      any step needed more than one attempt.

**Not covered here:** BLE through the sandbox. That path was
hardware-verified on the branch this was ported from and is not re-tested by
this checklist.
