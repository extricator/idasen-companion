"""A daemon command that fails must reach the user.

Every `_async_call` discarded its reply. dbus-fast *does* send an error reply
for both DBusError and unexpected exceptions, so the information existed — the
GUI simply never looked at it. With the desk unreachable, Overview's
Sit / Stand / Move / Stop appeared to do nothing at all: no dialog, and no
status change either, because `machine.move_failed` is set only by the
automation path, so the "Last move failed" status never appears for a manual
move.

The message is composed GUI-side from the D-Bus error *name*. The daemon's own
body crosses the wire in English and is in neither catalog, so it cannot be
translated where it is raised.
"""

import os

import pytest

pytest.importorskip("PySide6")

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion import DBUS_NAME  # noqa: E402
from idasen_companion.core import i18n as core_i18n  # noqa: E402
from idasen_companion.core.i18n import (  # noqa: E402
    DAEMON_ERROR_MESSAGES,
)
from idasen_companion.gui.util import daemon_error_message  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_a_known_error_name_gets_its_own_sentence(qapp):
    msg = daemon_error_message(f"{DBUS_NAME}.Error.MoveFailed",
                               "desk command failed; see daemon log")
    assert "did not respond" in msg
    assert "daemon log" not in msg, "leaked the daemon's internal wording"


def test_a_bare_name_works_too(qapp):
    assert daemon_error_message("MoveFailed") == daemon_error_message(
        f"{DBUS_NAME}.Error.MoveFailed")


def test_an_unknown_error_falls_back_to_the_daemons_detail(qapp):
    # Untranslated, but a specific English reason beats a generic sentence.
    msg = daemon_error_message("org.freedesktop.DBus.Error.NoReply",
                               "Message recipient disconnected")
    assert msg == "Message recipient disconnected"


def test_an_unknown_error_with_no_detail_still_says_something(qapp):
    msg = daemon_error_message("", "")
    assert msg
    assert "could not carry out" in msg


@pytest.mark.parametrize("name", sorted(DAEMON_ERROR_MESSAGES))
def test_every_mapped_error_is_translated_in_spanish(qapp, name):
    """These are the app's error messages; shipping them English-only on a
    Spanish install is the failure this mapping exists to prevent.

    Spanish is bound through the gettext catalog, not by loading the Qt
    ``.qm``: the sentences moved to ``core/presentation.py`` so the future CLI
    can reach them without a second copy, and a shared word is looked up in
    the shared catalog. The claim under test is unchanged — every mapped
    name renders differently in Spanish than in English.
    """
    english = daemon_error_message(name)
    core_i18n.set_language("es")
    try:
        spanish = daemon_error_message(name)
    finally:
        core_i18n.set_language(core_i18n.SYSTEM)
    assert spanish != english, f"{name} is not translated"


def test_every_daemon_error_name_has_a_message():
    """A name raised by the daemon with no entry here reaches the user as the
    daemon's English body — the thing this mapping exists to stop."""
    import re
    from pathlib import Path

    src = Path("src/idasen_companion/daemon/main.py").read_text()
    raised = set(re.findall(r'Error\.([A-Za-z]+)"', src))
    # UnknownGesture is a programming error in a client, not a user-facing
    # condition: the GUI only ever sends the three valid actions.
    raised.discard("UnknownGesture")
    missing = raised - set(DAEMON_ERROR_MESSAGES)
    assert not missing, f"no user-facing message for: {sorted(missing)}"
