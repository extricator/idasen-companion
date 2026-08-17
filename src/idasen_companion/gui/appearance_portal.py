"""Reads the host's stated appearance preferences via the desktop portal.

A sibling of ``background_portal.py`` -- the same
``org.freedesktop.portal.Desktop`` service, a different interface
(``org.freedesktop.portal.Settings`` rather than ``Background``). This module
does not import that one; each portal module defines its own copy of the
shared service/path constants deliberately, so the two stay independent.

**What this reads, and what it deliberately does not.** Colour scheme and
contrast are plain ``u`` (uint32) values wrapped in a variant. QtDBus
demarshals the *outer* variant into a ``QDBusVariant`` wrapper and stops
there -- it does not hand back a Python ``int``, so the wrapper is unwrapped
here (measured against a live portal: the reply's first argument is a
``QDBusVariant`` whose ``variant()`` is the ``int``). That one unwrap is the
whole of the manual decoding, because the payload underneath it is a scalar.
Accent colour is never read here, for two independent
reasons. First, the portal's accent colour already reaches the app: an exact
byte-for-byte match was measured between a direct portal read and
``QApplication.palette().color(QPalette.ColorRole.Highlight)`` on a real
desktop session, sourced through the bundled portal platform theme that
already feeds ``theme().accent`` (``gui/theme.py``) -- reading it again here
would be duplicate machinery for a value the app already has. Second, the
accent key's wire type is a struct of three doubles nested inside a variant,
which QtDBus does not demarshal; the natural way to decode it by hand (the
streaming idiom Qt's own C++ API uses) aborted the interpreter with SIGABRT
rather than raising a catchable exception, when tried against a real portal.
No code path here may go anywhere near that shape.

**Why ``ReadOne`` and not the interface's other two methods.** The
interface's ``version`` property is 2, which makes the single-key ``Read``
method the deprecated predecessor of ``ReadOne`` -- ``ReadOne`` is used
instead of ``Read`` for that reason alone. The interface's third method reads
the whole requested namespace back as one opaque, un-demarshalled nested
container -- worse than the accent-colour trap above, since decoding it means
walking the same crash-prone struct-decoding surface just to reach two
scalars this module can read individually and safely.

**Why a missing portal stays quiet rather than sounding an alarm.** A session
with no ``xdg-desktop-portal`` -- a minimal window manager, a container -- is
the *normal* case for a package that has to run on any distribution, not a
degraded one; the app is not missing anything it needs, it simply has no
extra preference data. So the absent-portal path logs one line at the lowest
severity on the diagnostic channel, purely so a bug reporter can tell "no
portal" from "portal returned nothing" -- never a dialog, never anything on
the activity channel, since nothing about the desk changed.

Both keys degrade to ``None`` on any failure -- an absent service, an absent
namespace, an absent key, or an unwrapped value that fails an ``isinstance``
check (rejecting a Python ``bool``, which subclasses ``int``).
No exception ever escapes this module: the values it reads come from another
process on the session bus, and that is the plan's only untrusted input.
Nothing in the app acts on either value yet, and nothing retains them
either: the caller drops the returned ``AppearancePreferences`` on the
floor, so the one durable effect of a read is the diagnostic line below.
Whether the contrast preference should change any pixel is a later phase's
decision, and this module never renders anything with it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtDBus import (QDBus, QDBusConnection, QDBusMessage,
                            QDBusVariant)

from ..core import journal
from ..core.logmsg import Channel

_SERVICE = "org.freedesktop.portal.Desktop"
_PATH = "/org/freedesktop/portal/desktop"
_SETTINGS_INTERFACE = "org.freedesktop.portal.Settings"
_NAMESPACE = "org.freedesktop.appearance"

#: The keys this module reads, each with every value the portal
#: specification defines for it: colour scheme is no-preference / dark /
#: light, contrast is normal / high. A reply outside its key's set is
#: another process's value for a meaning this app does not know, so it is
#: treated as absent rather than passed on as a number a later caller would
#: have to guess about.
_VALID_VALUES = {
    "color-scheme": (0, 1, 2),
    "contrast": (0, 1),
}

#: A property read is not a permission dialog and should return in
#: milliseconds; bounded so an unresponsive portal cannot hang GUI startup.
#: This bound is only real because the call below is sent as a plain
#: ``QDBusMessage`` through ``QDBusConnection.call``, which takes the timeout
#: on the *first* round trip. Building a ``QDBusInterface`` instead would
#: block on an ``Introspect`` call inside its own constructor, at QtDBus's
#: 25-second default, before ``setTimeout`` could apply to anything -- on the
#: GUI thread, before any window is shown. ``gui/main.py``'s one-shot command
#: path sends its calls the same way, for the same reason.
_READ_TIMEOUT_MS = 3_000


@dataclass(frozen=True)
class AppearancePreferences:
    """The two portal preferences this module reads.

    Both fields are ``None`` when the portal, the namespace or the key is
    unavailable, or when the value the portal sent back is not one of the
    plain integers the portal defines for that key.
    """

    color_scheme: int | None
    contrast: int | None


def _read_one(connection: QDBusConnection, key: str) -> int | None:
    """One ``ReadOne(namespace, key)`` call, degrading to ``None`` on any
    failure -- a missing portal, a missing key, a reply shaped unlike what
    was asked for, or a number outside the set the portal defines for this
    key."""
    message = QDBusMessage.createMethodCall(
        _SERVICE, _PATH, _SETTINGS_INTERFACE, "ReadOne")
    message.setArguments([_NAMESPACE, key])
    reply = connection.call(message, QDBus.CallMode.Block, _READ_TIMEOUT_MS)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        return None
    arguments = reply.arguments()
    if not arguments:
        return None
    value = arguments[0]
    # ReadOne's out-signature is `v`, and QtDBus demarshals that outer
    # variant into a QDBusVariant rather than into the scalar inside it.
    # Type-checking the wrapper instead of its payload rejects every
    # successful reply a real portal sends -- measured, and the reason this
    # unwrap exists. A bare scalar is accepted too, since a caller-supplied
    # double-unwrap or a future QtDBus that unwraps for us must not start
    # failing.
    if isinstance(value, QDBusVariant):
        value = value.variant()
    # The untrusted step: this is a value from another process and nothing
    # here assumes the reply actually matches what was requested. `bool` is
    # rejected explicitly -- it subclasses `int` in Python, so
    # `isinstance(value, int)` alone would silently accept it.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value not in _VALID_VALUES[key]:
        return None
    return value


def read_appearance_preferences() -> AppearancePreferences:
    """Read colour-scheme and contrast from the desktop portal, once.

    Never raises. Degrades to an ``AppearancePreferences`` of two ``None``
    fields on any failure, silently as far as the user is concerned -- the
    caller falls back to ``QPalette``-derived behaviour exactly as it does
    today. Logs at most one diagnostic line per call.
    """
    connection = QDBusConnection.sessionBus()
    color_scheme = _read_one(connection, "color-scheme")
    contrast = _read_one(connection, "contrast")
    if color_scheme is None and contrast is None:
        journal.send(
            "no org.freedesktop.portal.Settings answer for "
            "org.freedesktop.appearance -- the palette is what the app "
            "uses, as always",
            "debug", channel=Channel.DIAGNOSTIC.value)
    else:
        journal.send(
            f"read appearance preferences from the desktop portal: "
            f"color-scheme={color_scheme!r} contrast={contrast!r} -- "
            f"nothing in the app acts on either value yet",
            "debug", channel=Channel.DIAGNOSTIC.value)
    return AppearancePreferences(color_scheme=color_scheme, contrast=contrast)
