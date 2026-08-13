"""Idasen Companion — automatic sit/stand companion for the IKEA Idåsen desk."""

import os as _os
import sys as _sys

__version__ = "1.0.1"

# The bundled single-RPM build vendors bleak/idasen here. Prepended so the
# app always runs the exact library versions it shipped with, regardless of
# whatever pip/RPM copies exist on the machine. No-op when the directory is
# absent; IDASEN_COMPANION_NO_VENDOR=1 disables it (development override).
_VENDOR_DIR = "/usr/lib/idasen-companion/vendor"
if (_os.path.isdir(_VENDOR_DIR)
        and _VENDOR_DIR not in _sys.path
        and not _os.environ.get("IDASEN_COMPANION_NO_VENDOR")):
    _sys.path.insert(0, _VENDOR_DIR)

APP_ID = "io.github.extricator.IdasenCompanion"
DBUS_NAME = APP_ID
DBUS_PATH = "/io/github/extricator/IdasenCompanion"
