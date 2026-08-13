# Changelog

Notable changes to Idasen Companion, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
