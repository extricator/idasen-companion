# Security

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** — the *Security* tab,
then *Report a vulnerability* — rather than opening a public issue. That keeps
the report private until there is a fix to describe.

## Scope

Idasen Companion is a desktop application that runs entirely as your own user.
It has no network listener, no privileged component, and no setuid binary. The
interesting surfaces are:

- **The session D-Bus service** (`io.github.extricator.IdasenCompanion`). Any
  process in your session can call it — that is by design, since that is how
  the GUI, the tray and `idasen-companion --toggle` reach the daemon. It can
  move your desk and edit your config; it cannot do anything you could not do
  yourself.
- **Bluetooth LE** to the desk, via BlueZ. The desk's own protocol is
  unauthenticated — that is a property of the hardware, not of this app.
- **Files under `$XDG_CONFIG_HOME` and `$XDG_STATE_HOME`**, written with your
  own permissions.
- **The libraries a build bundles.** The single RPM carries the app's whole
  Python runtime, Qt and PySide6 among it, and the Flatpak carries its Python
  dependencies inside the sandbox on top of the KDE runtime's Qt. A
  vulnerability in any of those ships inside the artifact and is fixed by
  refreshing the bundle, not by a distribution update. Every one is vendored
  at a pinned version: the RPM's set is named in
  `packaging/idasen-companion-bundled.spec`, one `Provides: bundled(...)` line
  each, and the Flatpak's in `packaging/flatpak/python3-deps.json`. Report
  such issues upstream, but do report them here too so the bundle can be
  refreshed. The `.deb` bundles nothing and takes its libraries from the
  archive.
