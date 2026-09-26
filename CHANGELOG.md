# Changelog

Notable changes to Idasen Companion, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.1] - 2026-09-26

### Changed

- Exercise automatic release preparation verification across the five package assets.

## [1.2.0] - 2026-09-25

### Added

- **A first-class command-line client can inspect and control the desk without
  Qt.** It reports status and recent activity, and provides toggle, sit, stand,
  preset and stop commands through the daemon. Its output follows the selected
  language, measurement units and clock format.
- **RPM and Debian downloads now come in full and headless variants.** The full
  packages contain the desktop app, command-line client and daemon; the
  smaller headless packages contain only the Qt-free client and daemon.
- **The clock format can be selected independently of the app language.**
  Settings offers system, 12-hour and 24-hour choices, applied immediately
  across status text, schedules, activity timestamps and tray content.

### Changed

- App-owned numbers, percentages, dates, times and units now use one
  Babel-backed locale engine in the GUI, daemon and command-line client.
  Language, measurement units and 12/24-hour preference remain independent:
  choosing another app language changes its words and symbols without silently
  changing inches or the hour cycle selected by the system measurement/time
  locales.
- GUI, daemon and command-line messages now share one contextual gettext
  catalog, keeping the same concepts and translations consistent across every
  interface.
- Configuration from a newer build no longer prevents an older GUI or daemon
  from starting merely because it contains an unknown section or option. The
  app warns visibly and preserves the unknown data, comments and ordering when
  it saves known settings; malformed values for settings it does understand
  remain errors.
- The sidebar measures its translated labels instead of assuming an English
  width, and asymmetric controls now follow the interface direction in
  preparation for future right-to-left translations.
- Release builds now produce and verify five artifacts: full and headless RPMs,
  full and headless Debian packages, and the Flatpak bundle.

### Fixed

- **Clock output now agrees with the selected format throughout the app.**
  Schedule summaries and out-of-schedule status text no longer remain in
  24-hour form after choosing 12-hour time; Spanish meridiem text uses its
  language-appropriate case, and system-format detection handles territory
  priority lists and non-ASCII digits correctly.
- **Overview status notes are clearer and translated labels fit the sidebar.**
  Each note presents one fact without the old separator, and longer labels no
  longer get clipped.
- Package smoke tests no longer leave daemon processes behind, and the staged
  secret-scan canary no longer risks marking a linked worktree's repository as
  bare.

## [1.1.1] - 2026-08-20

### Fixed

- **The Statistics range slider labelled its presets in English.** The ticks
  under the range rail printed the raw preset name — lowercase `sit` and
  `stand` — one screen away from Presets buttons reading the same two words
  translated and capitalised. Both now read the same vocabulary as the rest of
  the window. A preset you named yourself is still shown exactly as you typed
  it.
- **The daily chart's tooltip was never translated.** Hovering a bar on the
  Statistics page showed English whatever language the rest of the window was
  in.

### Changed

- **Every message is translated as a whole sentence now, rather than assembled
  from translated pieces.** Heights, day and clock labels, day ranges, preset
  ticks, the status reason, the statistics footer, position transitions, the
  About desk line and the copied chip each became one catalog entry with its
  substitutions named. A fragment glued to another fragment fixes English word
  order for every language, and the seam shows up only in a language that needs
  the parts in a different order — so nothing looked wrong before, and nothing
  reads differently in English or Spanish now.
- **A word that means one thing has one catalog entry.** Eight concepts reached
  the catalog twice, once from the shared vocabulary and once from a page's own
  copy of the wording. Copying wording between two places is not a mechanism for
  keeping them in sync; the pages read the shared entry.
- The suite fails a change that glues a translated value to anything, that lets
  a concept reach the catalog twice, or that ships a catalog with an
  untranslated entry.

## [1.1.0] - 2026-08-18

### Added

- **The Activity Log dates its rows.** Entries sit under a dated separator, so
  you can see which day a line belongs to without counting back from the top.

### Changed

- **The RPM installs on any RPM-based distribution, not only Fedora.** It
  carries its own Python and Qt rather than relying on the machine's, so it
  depends on nothing but the processor architecture.
- **The window follows the desktop's theme more closely,** including a switch
  between light and dark while it is open, which previously needed a relaunch.
- **The Activity Log redraws faster,** without the stutter a long list used to
  show.

### Fixed

- **The Activity Log no longer scrolls past its last line** when it redraws.

## [1.0.2] - 2026-08-14

### Fixed

- **The Bluetooth link no longer survives a suspend.** Suspending the machine
  while the daemon still held the desk — which happens whenever you suspend
  shortly after a move, inside the linger window — left the link up for the
  whole sleep, and it never dropped on waking. The desk takes one connection
  at a time, so nothing else could reach it until the link was broken by
  hand. The daemon now hands the desk back before the machine sleeps, asking
  the system to wait the second or two that takes, and checks the link again
  on resume in case it never saw the sleep announced.
- **A stalled Bluetooth disconnect no longer blocks every later desk command.**
  The disconnect had no time limit of its own. If the connection stopped
  answering, every later sit, stand or preset command waited behind it, with
  no error shown, until the daemon was restarted. The disconnect now gives up
  after a set time, and the next command starts a fresh connection.

### Changed

- The screenshots on this page are fetched from the default branch rather
  than the release tag. Replacing one is now a plain overwrite of the file,
  with no release needed to make the link valid.

## [1.0.1] - 2026-08-13

### Fixed

- **Screenshots in software centres.** The AppStream metainfo pointed its five
  screenshots at the 1.0.0 tag, which does not carry them, so a software
  centre had nothing to show on the app's page. The URLs now name the release
  that carries the files, and a test holds them to the package version.

### Changed

- Five screenshots composed for a software centre replace the three functional
  captures shipped before, one per page of the window.
- The README follows the standard layout and is about half its former length.
  The package build instructions moved to `CONTRIBUTING.md`.
- Each release body now ends with a link comparing it against the previous
  release.

## [1.0.0] - 2026-08-09

First public release. Idasen Companion alternates an IKEA Idåsen desk between
sitting and standing based on **active time at the computer** — time spent
idle or with the session locked doesn't count. A background daemon owns the
Bluetooth connection and the automation logic; a Qt 6 GUI gives you a tray
icon, live status and manual control. Fedora-first and DE-agnostic: GNOME and
KDE Plasma, X11 and Wayland.

### Added

- **Active-time automation.** Each sit or stand period ends after a
  configurable amount of active time, and the desk moves itself to the other
  position. Every period is extended by a random number of whole minutes
  (cycle variation) so transitions don't feel mechanical.
- **Presence gating.** Two idle thresholds: a lenient one for time accounting,
  and a strict recent-input gate so the desk never moves while you might be
  away from it. A locked session counts as idle. Suspend and resume are
  detected (logind plus a wall-clock jump) and never cause a surprise move on
  wake.
- **Manual control and presets.** Sit, stand, preset and stop buttons plus a
  height slider. Presets are named positions with "capture current height";
  positions already saved in `~/.config/idasen/idasen.yaml` are imported on
  first run, along with the desk's address.
- **Interruption handling.** The resulting height is verified against the
  preset target after every move, and the desk retries once back to the
  original position if you grabbed the paddle mid-move.
- **On-demand Bluetooth.** The daemon connects only when there's work and
  drops the link after a short linger, so the desk stays reachable from other
  apps. A persistent-connection mode is available in settings.
- **Scheduling.** Active days and hours, outside which automation stands down.
- **Statistics.** Per-day sit and stand totals and a transition history, kept
  in SQLite, with a recent-transitions view in the GUI.
- **Activity log.** A live log view in the GUI, with the full history in
  journald.
- **Tray icon and window behaviour.** The GUI runs from the system tray with
  status in its tooltip; closing the window can hide it to the tray rather
  than quit, and it can start hidden at login. Desktop notifications announce
  an upcoming move ("Standing up in 30 s") with Snooze and Skip actions.
- **First-run wizard.** Finds or pairs the desk, then performs a verified
  setup — the daemon connects, pairs and reads the desk height before anything
  is saved — and enables the background service for your account only.
- **A D-Bus API.** The daemon exports its state, statistics and desk commands
  on the session bus; the GUI is a client of it and never touches the desk
  directly. Anything else on the session bus can drive the desk the same way.
- **Localisation.** English and Spanish, in both the GUI and the daemon's
  notifications.
- **Three installable formats.** A bundled RPM for Fedora, which vendors the
  two Python libraries Fedora doesn't package; a `.deb` for Debian 13 (trixie)
  or newer and Ubuntu 25.10 (questing) or newer, which vendors nothing; and a
  Flatpak bundle for everything below those floors or off those distributions
  entirely. See the README for installation and checksum verification.
