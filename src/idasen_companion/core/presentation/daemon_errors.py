"""What a daemon D-Bus error *name* means, in the **reader's** language.

Deliberately its own module, with no :class:`~.formatter.Formatter` method —
the one word in this package that does not get D-01's two doors, and this is
the reason.

**The failure this shape prevents.** The daemon raises ``DBusError`` with an
English body, and that body crosses the wire. It cannot be the user-facing
text: rendering it through the daemon's own gettext would give a Spanish
user the *daemon's* language rather than their own, and nothing anywhere in
the build would fail. Keying on the stable error name and owning the
sentence on the reading side is what makes these translatable at all. The
English body stays diagnostic detail.

**Why no ``Formatter`` method.** The daemon owns a ``Formatter`` of its own,
built from its config. A ``Formatter.daemon_error_message`` would put this
table one attribute access away from the process that must never render it,
and leave the mistake reachable with nothing but review standing in the way.
Two doors is the rule for a word both front ends may say; this is a word
only a *reader* may say, so it has one door and a test —
``tests/test_daemon_error_import_guard.py`` — that fails the build if
anything under ``daemon/`` reaches for it.

**Why it left ``gui/`` at all.** The GUI is not the only D-Bus reader. The
CLI planned for v1.2 hits the same error names, and leaving the table in
``gui/`` books a second copy of every one of these sentences later — the
precise drift this milestone exists to remove. A reader imports this module
directly.
"""

from __future__ import annotations

from .protocols import Translator
from .register import DAEMON_ERROR_GENERIC, DAEMON_ERROR_MESSAGES


def daemon_error_message(translator: Translator, name: str,
                         detail: str = "") -> str:
    """A translated sentence for a daemon D-Bus error name.

    ``name`` may be the full ``…Error.MoveFailed`` or the bare tail. Falls
    back to the daemon's English ``detail`` — untranslated, but better than
    silence — and finally to a generic line.
    """
    key = name.rsplit(".", 1)[-1] if name else ""
    source = DAEMON_ERROR_MESSAGES.get(key)
    if source is not None:
        return translator.message(source)
    if detail:
        return detail
    return translator.message(DAEMON_ERROR_GENERIC)
