# Idasen Companion

Automatic sit/stand companion for the IKEA Idåsen desk on Linux.

This is an independent, unofficial project, not affiliated with, endorsed by,
or sponsored by Inter IKEA Systems B.V. IKEA and Idåsen are trademarks of
their respective owners.

Idasen Companion alternates your desk between sitting and standing based on
**active time at the computer** — time spent idle or with the session locked
doesn't count. A background daemon owns the Bluetooth connection and the
automation logic; a Qt 6 GUI gives you a tray icon, live status, manual
controls, presets, scheduling, statistics and desktop notifications.
Fedora-first, DE-agnostic: works on GNOME and KDE Plasma, on X11 and Wayland.

## Features

- **Active-time automation** — two idle thresholds: a lenient one for time
  accounting, and a strict recent-input gate so the desk never moves while
  you might be away from it. Lock counts as idle. Suspend/resume is detected
  (logind + wall-clock jump) and never causes a surprise move on wake.
- **Cycle variation** — each sit/stand period is extended by a random number
  of whole minutes (configurable) so transitions don't feel mechanical.
- **Interruption handling** — after each move the resulting height is
  verified against the preset target (±2 cm by default); if you grabbed the
  paddle mid-move, the desk retries once back to the original position.
- **On-demand Bluetooth** — connects only when there's work, then drops the
  connection after a short linger. Your Bluetooth applet isn't permanently
  lit and other apps (the idasen CLI, phone apps) can still reach the desk.
  Persistent mode is available in settings.
- **Manual control** — sit/stand/preset buttons, a height slider, stop.
- **Presets** — named positions with "capture current height"; existing
  positions from `~/.config/idasen/idasen.yaml` are imported on first run.
- **Scheduling** — active days/hours outside which automation stands down.
- **Notifications** — "Standing up in 30 s" with Snooze/Skip actions.
- **Statistics** — per-day sit/stand time and transition history (SQLite).
- **Activity log** — live log view in the GUI; full history in journald.

## Install

### From a GitHub release (single RPM)

Download `idasen-companion-<version>.noarch.rpm` from the
[releases page](https://github.com/extricator/idasen-companion/releases) and:

```
sudo dnf install ./idasen-companion-*.noarch.rpm
```

Everything else (Qt, D-Bus libraries, …) comes from the regular Fedora
repos. This build bundles the two Python libraries Fedora doesn't package
(`bleak`, `idasen`) inside the RPM — see `packaging/idasen-companion-bundled.spec`.
Updates are manual: download the new release and `dnf install` it again.

To build it yourself:

```
python3 -m build --sdist && cp dist/idasen_companion-*.tar.gz rpmbuild/SOURCES/
spectool -g -C rpmbuild/SOURCES packaging/idasen-companion-bundled.spec
rpmbuild --define "_topdir $PWD/rpmbuild" -ba packaging/idasen-companion-bundled.spec
```

### From a GitHub release (.deb)

Download `idasen-companion_<version>-1_all.deb` from the
[releases page](https://github.com/extricator/idasen-companion/releases) and:

```
sudo apt install ./idasen-companion_*_all.deb
```

Use `apt` rather than `dpkg -i`: it pulls the dependencies in, where `dpkg`
would leave the package unconfigured until you resolved them by hand. Updates
are manual, as with the RPM: download the new release and install it again.

Supported releases: **Debian 13 (trixie) or newer, Ubuntu 25.10 (questing) or
newer.** PySide6 isn't packaged in Ubuntu's oracular (24.10) or plucky (25.04)
releases, and Debian 12 has no PySide6 packages at all, so the `.deb` can't
install cleanly there. On an older release, `apt` refuses the install with an
unmet-dependency message naming what's missing, rather than half-installing —
nothing is left partially in place. Below the floor, the Flatpak is the
supported path.

Unlike the RPM, this package bundles nothing: every dependency, including
`idasen` and `bleak`, comes from the distribution's own archive.

Installing does not start or enable the daemon — see [First
run](#first-run) below.

To build it yourself, from a checkout with the build dependencies installed:

```
dpkg-buildpackage -us -uc -b
```

### From a GitHub release (Flatpak bundle)

The bundle is a single file, `idasen-companion-<version>.flatpak`, attached to
each release. Download it from the
[releases page](https://github.com/extricator/idasen-companion/releases) and
install it user-scope:

```
flatpak install --user ./idasen-companion-*.flatpak
```

The [Flathub](https://flathub.org) remote is needed only to supply the KDE
runtime the bundle depends on, not to fetch the app itself — this is the
path for anyone below the `.deb`'s Debian 13 / Ubuntu 25.10 floor, or not on
Fedora, Debian, or Ubuntu at all. As with the RPM, updates are manual:
download the new bundle and install it again.

The app is not on Flathub and isn't planned to go there — its policy on
AI-assisted contributions doesn't fit this project.

There is no systemd user unit under the Flatpak; "Run automation at login"
is granted instead through the desktop's Background-permission dialog.

To build the bundle yourself, see `packaging/flatpak/README.md`. A local build
writes an unversioned `idasen-companion.flatpak`, unlike the attached asset.

### Build the RPMs locally

The app depends on two Python libraries not packaged in Fedora — `bleak`
and `idasen` — so this repo ships three spec files under `packaging/`.

The build uses a project-local RPM tree (`./rpmbuild/`), not `~/rpmbuild`.

```
sudo dnf install rpm-build rpmdevtools python3-devel python3-pip \
    python3-uv-build systemd-rpm-macros desktop-file-utils \
    python3-pytest python3-pytest-asyncio python3-tomlkit python3-dbus-fast \
    python3-pyyaml python3-pyside6
mkdir -p rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
alias rpmb='rpmbuild --define "_topdir $PWD/rpmbuild"'

# 1. Dependencies (downloaded from PyPI)
spectool -g -C rpmbuild/SOURCES packaging/python-bleak.spec
spectool -g -C rpmbuild/SOURCES packaging/python-idasen.spec
rpmb -ba packaging/python-bleak.spec
rpmb -ba packaging/python-idasen.spec
sudo dnf install rpmbuild/RPMS/noarch/python3-bleak-*.rpm \
                 rpmbuild/RPMS/noarch/python3-idasen-*.rpm

# 2. The app itself
python3 -m build --sdist   # or: pip install build && python3 -m build --sdist
cp dist/idasen_companion-*.tar.gz rpmbuild/SOURCES/
rpmb -ba packaging/idasen-companion.spec
sudo dnf install rpmbuild/RPMS/noarch/idasen-companion-*.rpm
```

### First run

Installing the package does **not** start the daemon. Fedora policy is that
packages don't enable services on install, and a systemd *user* preset would
apply to every account on the machine — so installing the app system-wide
would silently run a desk daemon for people who never asked for one. Just
launch the GUI and let it set itself up for your account:

```
idasen-companion
```

On first launch the GUI opens a setup wizard. It starts the background
service if needed and lists your desk immediately when it's already known —
either paired via the system Bluetooth settings or found by the daemon's
automatic scan; otherwise put the desk in pairing mode (hold the button on
the control box until the light flashes) and scan. Finishing the wizard
performs a verified setup: the daemon connects, pairs and reads the desk
height before anything is saved — and *then* enables the service, so it
comes back at every graphical login from that point on.

You can change that afterwards under **Settings → General → Start
automatically at login**, or from a terminal if you prefer:

```
systemctl --user enable --now idasen-companion.service   # on
systemctl --user disable idasen-companion.service        # off (at next login)
```

Bonus for `idasen` CLI users: the daemon imports your desk's address and
all saved positions from `~/.config/idasen/idasen.yaml` on first start —
no wizard needed.

### Verifying a download

Every release carries a `SHA256SUMS` asset covering all three artifacts.
Download it alongside whichever one you took, and from that directory run:

```
sha256sum --ignore-missing -c SHA256SUMS
```

`--ignore-missing` is what makes that work with a single artifact in hand: the
file lists all three, and without it the two you didn't download are reported
as failures.

This detects a corrupted or substituted download. It is not a signature and
does not prove who built the file — the checksums are published on the same
release page as the artifacts, so anyone who could replace one could replace
the other.

## Desktop environment notes

- **KDE Plasma** — everything works out of the box, including the tray icon
  and idle detection (`org.freedesktop.ScreenSaver`), on X11 and Wayland.
- **GNOME** — idle detection uses Mutter's IdleMonitor (X11 and Wayland).
  GNOME has no built-in tray icon support: install the
  [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/)
  (`gnome-shell-extension-appindicator` in Fedora) to see the tray icon.
  Without it the app still works fully — every tray action is also in the
  main window, which opens automatically when no tray is available.
- **Other DEs/WMs** — any StatusNotifier host shows the tray; on plain X11
  setups idle detection falls back to the XScreenSaver extension. The
  Overview tab shows which idle backend is in use.
- **Wayland compositors that aren't GNOME or KDE** (sway, Hyprland, river) —
  the app currently has no way to read idle time or lock state on these, so it
  can't tell whether you're at the keyboard and will move the desk on schedule
  regardless. It says so at startup in the log, and Overview reports the idle
  backend as `none`. Everything else works; support for the `ext-idle-notify`
  protocol these compositors do implement is on the list.

## Sharing one desk between several accounts

One machine with several logged-in accounts and a single desk is a supported
arrangement, not a conflict. The desk's controller accepts exactly one
Bluetooth client at a time, so the app hands it to whoever is **in front of the
seat** — the session logind reports as active, which is the same thing that
decides where your keyboard goes.

While you are switched away (VT switch or fast-user-switch), your daemon
neither moves the desk nor reads it, and drops its Bluetooth connection so the
other session can have it. Switch back and it re-reads the desk, picks up
anything that changed while you were gone, and carries on. You can still drive
the desk explicitly from a backgrounded session (over D-Bus or the CLI) — it
just gives the connection back afterwards.

Short handovers don't cost you anything: locking your screen or letting someone
take a five-minute turn leaves your sit/stand progress where it was. Only a real
break — longer than the idle threshold, ten minutes by default — starts you over.

Each account keeps **its own statistics**: the numbers are your sit/stand time,
so hours the other account spent at the desk aren't in your history.

An account with **no desktop session** — logged in over SSH, or a service left
running from boot — doesn't automate anything. There's no desk to sit at, and no
way to tell whether anyone is at it, so it leaves the desk alone for whoever is
actually logged in. You can still move the desk from it explicitly.

Note the app no longer starts a daemon for every account on install — enable it
per account, from the setup wizard or Settings → "Start automatically at login".

## Global keyboard shortcuts

The GUI binary doubles as a tiny remote — these fire one command at the
running daemon and exit:

```
idasen-companion --toggle       # sit <-> stand (opposite of where it is)
idasen-companion --sit
idasen-companion --stand
idasen-companion --preset NAME  # move to a named preset (e.g. sit, stand, focus)
idasen-companion --stop
```

Bind them to keys in your desktop's own keyboard settings (KDE: System
Settings → Shortcuts → Custom Shortcuts; GNOME: Settings → Keyboard →
Custom Shortcuts). Reliable on X11 and Wayland, every desktop. The same
list is shown, ready to copy, under Settings → Global shortcuts.

### While the screen is locked

Screen lockers take an exclusive input grab, so **no** desktop shortcut fires
while the session is locked. That is deliberate, and true of every desktop —
not something this app can opt out of. The daemon keeps running and automation
carries on; only the manual trigger is unavailable.

If you want one anyway, bind it *below* the compositor with
[keyd](https://github.com/rvaiya/keyd), which reads `/dev/input` directly, so
the locker's grab never hides the keys from it. (Packaged for most distros; on
Fedora it comes from COPR.) In `/etc/keyd/<your-keyboard>.conf`:

```ini
[main]
# Tap right Ctrl to toggle the desk; held, it stays a normal Ctrl.
rightcontrol = overload(control, command(setsid -f runuser -u USER -- env DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/UID/bus idasen-companion --toggle))
```

Substitute your username and UID. keyd runs as root, so `runuser` drops to your
session and `DBUS_SESSION_BUS_ADDRESS` points at the bus the daemon listens on;
`setsid -f` detaches, because `--toggle` blocks until the move finishes. Run
`keyd check` before `sudo keyd reload` — a bad config can leave the keyboard
unusable (panic sequence: backspace + escape + enter).

keyd matches each keyboard to exactly one config, most specific first, so a
wildcard `[ids] *` file will not reach a keyboard that has its own — repeat the
binding per keyboard you want it on.

Worth knowing what you are trading: an evdev daemon sees every keystroke,
including the password you type into the lock screen.

## Tray icon & window behaviour

Left-clicking the tray icon opens the window by default; middle-click
toggles sit/stand. Settings → Window & tray lets you assign an action —
open window, toggle sit/stand, sit, stand, or nothing — to left and middle
click. (Double-click isn't offered: StatusNotifierItem trays — KDE, GNOME,
most modern Linux — don't deliver it.) Repeating the same move gesture while the
desk is still moving stops it (or reverses it to where it started, or does
nothing — your choice). The same card chooses what the close
button does (hide to tray vs quit), whether minimising hides to the tray,
and whether the app starts hidden in the tray or with the window open.
These need a system tray; without one the window always opens and closing
it exits.

## Configuration

`~/.config/idasen-companion/config.toml` — all durations accept `45m`,
`1h30m`, `90s` style values. See the Settings tab for the same options with
explanations. The daemon logs to journald:

```
journalctl --user -t idasen-companion -f
```

## D-Bus API

The daemon exposes `io.github.extricator.IdasenCompanion` on the session
bus (object path `/io/github/extricator/IdasenCompanion`) with interfaces
`Desk1` (manual control, discovery), `Automation1` (pause/resume/skip/
snooze, status, config reload), `Presets1`, `Stats1` and `Log1`. Scripting
example:

```
busctl --user call io.github.extricator.IdasenCompanion \
    /io/github/extricator/IdasenCompanion \
    io.github.extricator.IdasenCompanion.Desk1 Stand
```

Note: tabular results are JSON strings and live updates are flat typed
signals — a deliberate choice so PySide6's QtDBus (which cannot demarshal
non-variant containers) and every other binding can consume them.

## Development

```
python3 -m venv .venv
.venv/bin/pip install -e . pytest pytest-asyncio PySide6-Essentials
.venv/bin/python -m pytest              # runs the full unit suite, no hardware needed
.venv/bin/idasen-companiond --mock-desk --config /tmp/ic-test.toml
IDASEN_COMPANION_CONFIG=/tmp/ic-test.toml .venv/bin/idasen-companion
```

`--mock-desk` runs the daemon against a simulated desk — the full GUI works
without hardware. Hardware-dependent behavior is covered by
`docs/MANUAL-TESTING.md`.

See `CONTRIBUTING.md` for the pre-pull-request checks, the naming rule, the
translation workflow and the release procedure.

Idasen Companion began as a single-file script that tracked active time
via X11 idle detection and moved the desk on a sit/stand cycle. Its
automation semantics — the two idle thresholds, active-time accounting,
and cycle variation — were preserved when it was rebuilt as a daemon plus
GUI.

## License

Copyright © 2026 extricator

Idasen Companion is free software under the **GNU General Public License,
version 3 or later**. The full text is in [`LICENSE`](LICENSE).

The GUI uses Qt 6 through [Qt for Python
(PySide6)](https://doc.qt.io/qtforpython/), which is licensed under the LGPL
version 3; PySide6 is a separate package and is not distributed as part of this
project's source. The daemon does not link Qt at all — it is deliberately
Qt-free so it can run headless.

`bleak` and `idasen` are MIT-licensed and are bundled inside the released RPM,
whose `License:` field is therefore `GPL-3.0-or-later AND MIT`; their license
texts ship alongside ours in that package, and the spec declares each one as
`Provides: bundled(...)` so the bundled versions stay auditable. In the
three-package split they are ordinary dependencies instead.
