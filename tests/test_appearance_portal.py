"""Tests for the desktop-portal appearance-preferences reader.

Mocked at the D-Bus boundary this module itself calls
(``QDBusConnection``/``QDBusInterface``), the same spirit as
``tests/test_background_portal.py``. No test here touches a real session bus
or exercises a real struct-shaped D-Bus payload -- every scenario is driven
synchronously by a fake that decides the reply itself.

Skipped where PySide6 is missing, matching every other GUI test in this
suite.
"""

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

# Forced, not defaulted -- see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtDBus import QDBusMessage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core import journal  # noqa: E402
from idasen_companion.core.logmsg import Channel  # noqa: E402
from idasen_companion.gui import appearance_portal as ap  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeReply:
    """Stands in for QDBusMessage -- the one boundary this module reads."""

    def __init__(self, *, error=False, args=None):
        self._error = error
        self._args = [] if args is None else list(args)

    def type(self):
        return (QDBusMessage.MessageType.ErrorMessage if self._error
                else QDBusMessage.MessageType.ReplyMessage)

    def arguments(self):
        return self._args


class _FakeInterface:
    """Stands in for QDBusInterface. `call()` returns the reply this test
    configured for the requested key, recording every call made."""

    def __init__(self, service, path, interface, connection, *, replies):
        self.service = service
        self.path = path
        self.interface = interface
        self.connection = connection
        self.timeout_ms = None
        self._replies = replies
        self.calls = []

    def setTimeout(self, milliseconds):
        self.timeout_ms = milliseconds

    def call(self, method, *args):
        self.calls.append((method, args))
        key = args[-1]
        return self._replies.get(key, _FakeReply(error=True))


class _FakeConnection:
    """A placeholder object -- nothing in this module reads anything off
    the connection it's handed besides passing it through to the fake
    interface constructor below."""


class _FakeSessionBus:
    def __init__(self, connection):
        self._connection = connection

    def sessionBus(self):
        return self._connection


def _install(monkeypatch, replies: dict):
    """Wire the module to a fake bus; returns the interfaces built, one per
    ReadOne call, so a test can inspect what was actually sent."""
    connection = _FakeConnection()
    made = []

    def fake_interface_ctor(service, path, interface, conn):
        iface = _FakeInterface(service, path, interface, conn, replies=replies)
        made.append(iface)
        return iface

    monkeypatch.setattr(ap, "QDBusConnection", _FakeSessionBus(connection))
    monkeypatch.setattr(ap, "QDBusInterface", fake_interface_ctor)
    return connection, made


def _capture_journal(monkeypatch):
    """Patch over conftest's own no-op journal.send stub so a test can
    inspect what this module actually logged."""
    sent = []

    def _record(message, level="info", **kwargs):
        sent.append((message, level, kwargs))
        return True

    monkeypatch.setattr(journal, "send", _record)
    return sent


# ================= 1. Happy path =================

def test_happy_path_returns_both_values_and_logs_them(monkeypatch):
    replies = {
        "color-scheme": _FakeReply(args=[2]),
        "contrast": _FakeReply(args=[0]),
    }
    _install(monkeypatch, replies)
    sent = _capture_journal(monkeypatch)

    prefs = ap.read_appearance_preferences()

    assert prefs.color_scheme == 2
    assert prefs.contrast == 0
    assert len(sent) == 1, "at most one diagnostic line per call"
    message, level, kwargs = sent[0]
    assert level == "debug"
    assert kwargs.get("channel") == Channel.DIAGNOSTIC.value
    assert "2" in message and "0" in message, (
        "the diagnostic line must name both values it read")


# ================= 2. No portal (D-15) =================

def test_missing_portal_degrades_to_none_and_logs_once_at_debug(monkeypatch):
    _install(monkeypatch, {})  # every key falls through to an error reply
    sent = _capture_journal(monkeypatch)

    prefs = ap.read_appearance_preferences()  # must not raise

    assert prefs.color_scheme is None
    assert prefs.contrast is None
    assert len(sent) == 1, "at most one diagnostic line per call"
    _message, level, kwargs = sent[0]
    assert level == "debug"
    assert kwargs.get("channel") == Channel.DIAGNOSTIC.value


# ================= 3. Wrong type (the untrusted-input assertion) =================

@pytest.mark.parametrize("bad_value", ["not-a-number", True, object()],
                          ids=["string", "bool", "arbitrary-object"])
def test_a_reply_of_the_wrong_type_is_treated_as_absent(monkeypatch, bad_value):
    replies = {
        "color-scheme": _FakeReply(args=[bad_value]),
        "contrast": _FakeReply(args=[bad_value]),
    }
    _install(monkeypatch, replies)
    _capture_journal(monkeypatch)

    prefs = ap.read_appearance_preferences()

    assert prefs.color_scheme is None, (
        f"a {type(bad_value).__name__} reply must not be returned as a "
        "value -- it must be treated as absent")
    assert prefs.contrast is None


def test_an_empty_reply_is_treated_as_absent(monkeypatch):
    replies = {
        "color-scheme": _FakeReply(args=[]),
        "contrast": _FakeReply(args=[]),
    }
    _install(monkeypatch, replies)
    _capture_journal(monkeypatch)

    prefs = ap.read_appearance_preferences()

    assert prefs.color_scheme is None
    assert prefs.contrast is None


# ================= 4. Nothing acts on it (D-13) =================

def test_reading_a_high_contrast_reply_changes_no_theme_token(qapp, monkeypatch):
    from idasen_companion.gui.theme import theme

    before = theme()
    replies = {
        "color-scheme": _FakeReply(args=[2]),
        "contrast": _FakeReply(args=[1]),  # the portal's "high contrast" value
    }
    _install(monkeypatch, replies)
    _capture_journal(monkeypatch)

    ap.read_appearance_preferences()

    after = theme()
    assert before == after, (
        "reading the contrast preference must not change a single theme() "
        "token -- nothing in the app acts on it yet (D-13)")


# ================= 5. No accent-reading entry point (D-14) =================

# The module must expose no way to read the portal's accent colour at all --
# the value is already available through theme().accent, and decoding the
# portal's own key for it crashes the interpreter (09-RESEARCH.md R-6).
def test_the_module_exposes_no_accent_reading_entry_point():
    public_names = [name for name in vars(ap) if not name.startswith("_")]
    assert public_names, "the module should expose at least its public API"
    lowered = [name.lower() for name in public_names]
    assert not any("accent" in name for name in lowered), (
        f"found an accent-reading entry point among the module's public "
        f"names: {public_names}")
