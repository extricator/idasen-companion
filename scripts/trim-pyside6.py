#!/usr/bin/env python3
"""Trim an installed PySide6 down to the Qt modules this app actually uses.

Usage: trim-pyside6.py <directory holding the installed PySide6 package>

Deletes, in place, every file under PySide6/ that is not reachable from
QtCore, QtGui, QtWidgets and QtDBus — plus QtSvg, which no module in this
project imports but every icon in it depends on, through the SVG icon engine.

The libraries are reached from what each shared object records that it needs,
so a Qt upgrade that moves a symbol from one library into another is followed
automatically. That is the whole reason that half is a graph walk and not a
list of filenames: a hand-written keep-list rots at the next Qt bump and fails
*silently* — the app still starts, and then finds no icon engine.

The plugins are a list of filenames, because for them no derivation exists.
Qt does not link a plugin; it scans `Qt/plugins/<kind>/`, opens each file it
finds there and reads the metadata inside it. So no record anywhere on disk
names the plugins this app needs, and the walk above cannot reach a single one
of them. Naming them is the only thing available — so both ways that list can
be wrong are made to fail the build instead of the desktop:

  * a name that no longer resolves means Qt has renamed or moved the plugin,
    and stops the run rather than being skipped;
  * every kind of plugin Qt ships has to appear below, kept or dropped with
    its reason, so a Qt release that adds one stops the run until somebody
    decides about it.

The second of those is the case a keep-list cannot see by itself, and it has
already cost something: the input-method plugins were simply never listed, and
nothing noticed until the plugin directories of a built package were read by
hand. Everything automated here runs on the offscreen platform, which loads
none of this.

Measured against PySide6-Essentials 6.11.1: 245 MB in, 91 MB out, with the
suite passing against the result.
"""

import glob
import os
import subprocess
import sys

# The Qt modules to keep, named as the extension modules that expose them.
SEED_MODULES = ("QtCore", "QtGui", "QtWidgets", "QtDBus", "QtSvg")

# The plugins to keep, under the directory Qt looks for that kind in. Each
# entry says what the app does that needs it, because that is what a later cut
# — or a later addition — has to be argued against.
SEED_PLUGINS = {
    # Something to draw on: the two display servers a desktop session offers,
    # and the two Qt falls back to when there is neither — offscreen is what
    # the suite and the package's own %check run on. The rest of this
    # directory is for machines with no window system at all (eglfs, linuxfb,
    # vnc), which is not what this app is.
    "platforms": ("libqxcb.so", "libqwayland.so", "libqoffscreen.so",
                  "libqminimal.so"),
    # Every icon this app draws is SVG, and this is the engine that renders
    # one when it is asked for by name through the icon theme.
    "iconengines": ("libqsvgicon.so",),
    # The SVG reader behind those icons, plus the raster formats a user's own
    # icon theme is made of. PNG needs nothing here — it is built into QtGui.
    "imageformats": ("libqsvg.so", "libqjpeg.so", "libqico.so", "libqgif.so"),
    # Colour scheme, fonts and file dialogs from the desktop, over the portal.
    # The GTK 3 theme beside it is deliberately dropped: it would work only
    # where GTK is installed, and it would add GTK, pango, cairo, atk and
    # gdk-pixbuf to what every install of this package requires — for an
    # appearance the portal already provides.
    "platformthemes": ("libqxdgdesktopportal.so",),
    # Typing. On X11 Qt has no input method of its own, so without these two
    # a compose sequence and a dead key produce nothing and an IBus user
    # cannot enter text at all. This app ships a Spanish catalog and has
    # free-text fields — a preset name — so typing "á" into one is an ordinary
    # path. The virtual keyboard beside them is dropped: it is driven from
    # QML, which this trim excludes on purpose.
    "platforminputcontexts": ("libcomposeplatforminputcontextplugin.so",
                              "libibusplatforminputcontextplugin.so"),
    # OpenGL under X11, by either of the two paths a driver may offer.
    "xcbglintegrations": ("libqxcb-glx-integration.so",
                          "libqxcb-egl-integration.so"),
    # Wayland: the shell protocol every mainstream compositor speaks, the
    # title bar Qt draws for its own windows there, and hardware buffers. The
    # Adwaita title bar beside the plain one is dropped — Qt asks for it by
    # name under GNOME but checks first that it is installed, so its absence
    # is how the window is framed, not whether it is.
    "wayland-shell-integration": ("libxdg-shell.so",),
    "wayland-decoration-client": ("libbradient.so",),
    "wayland-graphics-integration-client": ("libqt-plugin-wayland-egl.so",),
}

# The kinds of plugin this package ships none of, and why. Nothing reads the
# text; it is here so that every directory Qt ships has a decision recorded
# against it, which is what lets a Qt release that adds a new one stop the
# build instead of quietly shipping without it.
DROPPED_PLUGINS = {
    "designer": "the form editor's widget plugins; a development tool",
    "egldeviceintegrations": "eglfs, for a machine running no window system",
    "generic": "evdev input devices, read only by eglfs and linuxfb",
    "networkinformation": "QtNetwork is not in the closure",
    "printsupport": "nothing in this app prints",
    "qmllint": "QML tooling, and the QML binding is excluded below",
    "qmltooling": "the QML debug server, likewise",
    "sqldrivers": "the statistics database is opened by Python's own sqlite3, "
                  "never through QtSql",
    "tls": "QtNetwork again — nothing here opens a socket",
    "vectorimageformats": "Lottie animations, which this app has none of",
    "wayland-graphics-integration-server": "the compositor half of Qt's "
                                           "Wayland support; this is a client",
}

# Qt's own catalog of standard dialog button labels, which this project relies
# on instead of translating those strings itself.
KEEP_TRANSLATIONS = "Qt/translations/qtbase_*.qm"


def dynamic_dependencies(path):
    """Sonames the shared object at `path` records as required."""
    dumped = subprocess.run(["objdump", "-p", path], capture_output=True,
                            text=True, check=False).stdout
    return [line.split()[1] for line in dumped.splitlines() if "NEEDED" in line]


def _library_index(root, qtlib):
    """Every shared library the walk can follow, keyed by its filename."""
    index = {os.path.basename(p): p
             for p in glob.glob(qtlib + "/*") if os.path.isfile(p)}
    for path in glob.glob(root + "/*.so*"):
        index.setdefault(os.path.basename(path), path)
    return index


def plugin_seed_paths(plugins):
    """The plugins to keep, once every one of them has been accounted for.

    Both halves of that are checked here rather than worked around, because
    the failure this file exists to prevent is a plugin quietly not shipping.
    """
    if not os.path.isdir(plugins):
        sys.exit(f"trim-pyside6: no Qt plugin directory at {plugins}")

    kinds = {name for name in os.listdir(plugins)
             if os.path.isdir(os.path.join(plugins, name))}
    undecided = sorted(kinds - set(SEED_PLUGINS) - set(DROPPED_PLUGINS))
    if undecided:
        sys.exit("trim-pyside6: Qt ships plugins of a kind this file has no "
                 f"decision about: {', '.join(undecided)}")

    seeds = []
    for directory, names in SEED_PLUGINS.items():
        for name in names:
            candidate = os.path.join(plugins, directory, name)
            if not os.path.isfile(candidate):
                sys.exit("trim-pyside6: a plugin this app needs is not where "
                         f"Qt used to keep it: {candidate}")
            seeds.append(candidate)
    return seeds


def _seed_paths(root, plugins):
    seeds = [f"{root}/{module}.abi3.so" for module in SEED_MODULES]
    # The QML binding is deliberately excluded. Seed it and the closure drags
    # Qml, Quick, QmlModels and Network back in — 8 MB, measured — for a
    # module nothing in this project imports.
    seeds += [p for p in glob.glob(root + "/libpyside6*") if "qml" not in p]
    seeds += glob.glob(root + "/libshiboken6*")
    return seeds + plugin_seed_paths(plugins)


def reachable(seeds, index):
    """Every file reachable from `seeds` through the dependency records."""
    keep = set()
    pending = list(seeds)
    while pending:
        path = pending.pop()
        if path in keep or not os.path.isfile(path):
            continue
        keep.add(path)
        for soname in dynamic_dependencies(path):
            if soname in index:
                pending.append(index[soname])
    return keep


def main(appdir):
    root = os.path.join(appdir, "PySide6")
    keep = reachable(_seed_paths(root, os.path.join(root, "Qt", "plugins")),
                     _library_index(root, os.path.join(root, "Qt", "lib")))
    keep |= set(glob.glob(root + "/*.py"))
    keep |= set(glob.glob(os.path.join(root, KEEP_TRANSLATIONS)))

    removed = 0
    for base, _directories, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            if path not in keep:
                os.unlink(path)
                removed += 1
    for base, directories, _files in os.walk(root, topdown=False):
        for name in directories:
            try:
                os.rmdir(os.path.join(base, name))
            except OSError:
                pass

    print(f"trim-pyside6: kept {len(keep)} files, removed {removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
