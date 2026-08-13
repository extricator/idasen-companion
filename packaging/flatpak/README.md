# Flatpak packaging

Builds a single-app Flatpak that bundles both executables — the GUI
(`idasen-companion`, the app's default `command`) and the headless daemon
(`idasen-companiond`) — for `io.github.extricator.IdasenCompanion`.

## How it differs from the RPM

| | RPM | Flatpak |
|---|---|---|
| Qt / PySide6 | system packages | `org.kde.Platform` + the `io.qt.PySide.BaseApp` |
| Runtime deps | system RPMs / vendored | pinned pythonhosted wheels (`python3-deps.json`) |
| Daemon at login | systemd **user service** | **Background portal** autostart (Settings → *Run automation at login*) |
| Daemon on demand | — | **session D-Bus activation** (`…IdasenCompanion.service`) |
| Bluetooth | host BlueZ | `--system-talk-name=org.bluez` |

There is no systemd user service in the sandbox. The daemon starts two ways:

- **On demand** — the exported D-Bus activation file
  (`data/io.github.extricator.IdasenCompanion.service`) launches it the moment
  a client (the GUI, or a `idasen-companion --toggle` shortcut) connects to the
  well-known name.
- **At login** — not yet wired up. The systemd-based autostart toggle in
  Settings has no sandbox equivalent yet; the intended replacement is the
  Background portal (`org.freedesktop.portal.Background.RequestBackground`),
  tracked in `TODO.md`.

## Prerequisites

```bash
flatpak install --user flathub org.kde.Platform//6.10 org.kde.Sdk//6.10 \
    io.qt.PySide.BaseApp//6.10
```

## Build & install (local)

The app module builds from the sdist, so regenerate it first:

```bash
python3 -m build --sdist                 # -> dist/idasen_companion-1.0.0.tar.gz
flatpak-builder --user --force-clean --disable-cache --install \
    build-dir packaging/flatpak/io.github.extricator.IdasenCompanion.yaml
flatpak run io.github.extricator.IdasenCompanion
```

> **Rebuild gotcha:** the app module's source is a local sdist archive with no
> `sha256`, so flatpak-builder's cache key doesn't change when you regenerate
> the sdist — without `--disable-cache` it silently reuses the *previous*
> build and your source edits never make it into the bundle. Always pass
> `--disable-cache` (or `rm -rf .flatpak-builder`) after editing `src/`.

## Single-file bundle (distributable)

```bash
flatpak-builder --user --force-clean --repo=repo \
    build-dir packaging/flatpak/io.github.extricator.IdasenCompanion.yaml
flatpak build-bundle repo idasen-companion.flatpak \
    io.github.extricator.IdasenCompanion
```

## Size

The `io.qt.PySide.BaseApp` ships the *whole* of Qt/PySide6 — including
QtWebEngine (a full Chromium), its LLVM/clang toolchain, numpy, PyOpenGL and
ffmpeg — even though this GUI imports only `QtCore`/`QtGui`/`QtWidgets`/`QtDBus`
(plus QtSvg at runtime, from the `org.kde.Platform` runtime, for the themed SVG
icons). The BaseApp's own `cleanup-BaseApp.sh` strips the build-only bits but
leaves those heavy runtime modules in place.

The manifest's `cleanup-commands:` `rm -rf` the unused modules explicitly
(precise for nested paths in a way `cleanup:` globs aren't). A real local
build against this manifest installed at ~49 MB and produced an ~11 MB
single-file bundle — `flatpak info` and `du -h` on the bundle file are the
way to reproduce that measurement yourself; it will drift as dependencies do,
so treat it as a sanity check rather than a number to keep in sync here.

Biggest things removed and why they're safe (nothing here is imported or
`dlopen`ed by the app): **QtWebEngine** + its `libLLVM`/`libclang-cpp`,
`webenginedriver`, resource paks, spellcheck dictionaries and locale catalogs;
**numpy** + **PyOpenGL** (BaseApp extras); **ffmpeg** (`libav*`/`libsw*`,
bundled in the PySide6 wheel for QtMultimedia); and the PySide6 Python
bindings + `.pyi` stubs for the Qt modules the app never imports
(QtWebEngine/Pdf/Quick/Qml/3D/Charts/Multimedia/OpenGL/Designer/…).

Kept on purpose: `QtCore`/`QtGui`/`QtWidgets`/`QtDBus`/`QtSvg` bindings,
`shiboken6` (the binding runtime), and — from the shared `org.kde.Platform`
runtime, not `/app` — `libQt6Svg` and the `svg` image/icon plugins that
`QIcon.fromTheme` needs to render the icons. If you edit the trim list,
re-verify icons still render (the main risk) with a GUI launch, or headlessly:

```bash
flatpak-builder --run build-dir packaging/flatpak/io.github.extricator.IdasenCompanion.yaml \
    python3 -c "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; \
from PySide6.QtWidgets import QApplication; from PySide6.QtGui import QImageReader; \
QApplication([]); assert b'svg' in QImageReader.supportedImageFormats(); print('svg ok')"
```

The `share/runtime/locale` you'll see in `build-dir/files` is *not* part of
`/app`: flatpak-builder splits it into a separate `.Locale` extension and only
the user's configured languages are ever downloaded.

## Updating the Python deps

`python3-deps.json` is generated — never hand-edit it. After changing
`pyproject.toml`'s runtime dependencies:

```bash
python3 packaging/flatpak/gen-python-deps.py     # needs network + pip
```

It resolves the runtime's Python (CPython 3.13, x86_64) closure for exactly
the packages this project's own dependency list names — downloaded with
`--no-deps`, so a dependency one of those packages declares but this app
never exercises doesn't ride along uninvited — and pins each wheel by
pythonhosted URL + sha256. PySide6 is excluded on purpose — it comes from the
BaseApp.

## Toward Flathub

This manifest is Flathub-*shaped* but not yet submitted. For a submission,
replace the app module's local sdist `source` with a tagged release archive
(`type: archive` + `url` + `sha256`), keep the build offline (already the
case), and validate the metainfo and desktop file (the build already runs
`appstreamcli`/`desktop-file-validate` via the smoke-test steps in the repo
`README.md`).
