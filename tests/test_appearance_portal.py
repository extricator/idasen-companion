"""Tests for the desktop-portal appearance-preferences reader.

Mocked at the D-Bus boundary this module itself calls
(``QDBusConnection.sessionBus().call``), the same spirit as
``tests/test_background_portal.py``. The outgoing ``QDBusMessage`` is a real
one -- ``createMethodCall`` needs no bus -- so the fake reads the key off the
message the module actually built, and the timeout it was called with is
observable rather than assumed. No test here touches a real session bus
or exercises a real struct-shaped D-Bus payload -- every scenario is driven
synchronously by a fake that decides the reply itself.

The scalar payloads *are* built in the shape the wire really produces,
though: ``ReadOne``'s out-signature is ``v``, so a real reply's first
argument is a ``QDBusVariant`` wrapping the number, not the number. A
``QDBusVariant`` costs one offscreen constructor call and needs no bus, and
a suite that fed only bare ints once passed at 100% line coverage over a
reader that rejected every reply a real portal sends. So the happy path is
parametrised over both shapes, and the wrong-type cases cover the wrapped
forms too.

Skipped where PySide6 is missing, matching every other GUI test in this
suite.
"""

import pytest

pytest.importorskip("PySide6")

import ast  # noqa: E402
import inspect  # noqa: E402
import os  # noqa: E402

# Forced, not defaulted -- see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtDBus import QDBus, QDBusMessage, QDBusVariant  # noqa: E402
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


class _FakeConnection:
    """Stands in for the session-bus connection. ``call()`` returns the
    reply this test configured for the key named in the outgoing message,
    recording every call made with the timeout it was given."""

    def __init__(self, replies):
        self._replies = replies
        self.calls = []

    def call(self, message, mode, timeout_ms):
        arguments = message.arguments()
        self.calls.append((message.member(), tuple(arguments), mode,
                           timeout_ms))
        return self._replies.get(arguments[-1], _FakeReply(error=True))


class _FakeSessionBus:
    def __init__(self, connection):
        self._connection = connection

    def sessionBus(self):
        return self._connection


def _install(monkeypatch, replies: dict):
    """Wire the module to a fake bus; returns the connection, whose
    ``calls`` list records what was actually sent."""
    connection = _FakeConnection(replies)
    monkeypatch.setattr(ap, "QDBusConnection", _FakeSessionBus(connection))
    return connection


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

@pytest.mark.parametrize(
    "wrap", [lambda value: value, QDBusVariant],
    ids=["bare-scalar", "variant-wrapped"])
def test_happy_path_returns_both_values_and_logs_them(monkeypatch, wrap):
    replies = {
        "color-scheme": _FakeReply(args=[wrap(2)]),
        "contrast": _FakeReply(args=[wrap(0)]),
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


def test_every_read_is_bounded_by_the_module_s_own_timeout(monkeypatch):
    """The bound has to sit on the call itself, not on a proxy object.

    A ``QDBusInterface`` constructor blocks on an ``Introspect`` round trip
    at QtDBus's 25-second default *before* ``setTimeout`` can apply to
    anything, which on the GUI thread is a 25-second freeze with no window
    shown. Two halves are asserted: every call carries this module's own
    timeout, and the module imports no interface-proxy class at all, which
    is the only way to construct one. The second is read off the module's
    parsed import statements rather than its raw text, so the comment
    explaining why that class is avoided cannot satisfy the check that
    forbids it.
    """
    replies = {
        "color-scheme": _FakeReply(args=[QDBusVariant(2)]),
        "contrast": _FakeReply(args=[QDBusVariant(0)]),
    }
    connection = _install(monkeypatch, replies)
    _capture_journal(monkeypatch)

    ap.read_appearance_preferences()

    assert len(connection.calls) == 2, (
        f"expected one call per key, got {connection.calls}")
    for member, arguments, mode, timeout_ms in connection.calls:
        assert member == "ReadOne"
        assert arguments[0] == "org.freedesktop.appearance"
        assert mode == QDBus.CallMode.Block
        assert timeout_ms == ap._READ_TIMEOUT_MS, (  # pylint: disable=protected-access
            f"{member}({arguments}) was sent with timeout {timeout_ms}, not "
            "the module's own bound")
    imported = {
        alias.name
        for node in ast.walk(ast.parse(inspect.getsource(ap)))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "QDBusInterface" not in imported, (
        "the module imports an interface proxy again -- constructing one "
        "introspects at QtDBus's default timeout, outside the bound above")


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

@pytest.mark.parametrize(
    "bad_value",
    ["not-a-number", True, object(),
     QDBusVariant("not-a-number"), QDBusVariant(True)],
    ids=["string", "bool", "arbitrary-object", "wrapped-string",
         "wrapped-bool"])
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


@pytest.mark.parametrize("out_of_range", [-1, 3, 999, 2 ** 32 - 1],
                         ids=["negative", "just-past", "far-past",
                              "largest-uint32"])
def test_a_number_outside_the_key_s_defined_set_is_treated_as_absent(
        monkeypatch, out_of_range):
    """The portal defines colour scheme as 0/1/2 and contrast as 0/1.
    Anything else is another process's number for a meaning this app does
    not know -- the type check alone would pass it straight through to
    whatever eventually acts on it."""
    replies = {
        "color-scheme": _FakeReply(args=[QDBusVariant(out_of_range)]),
        "contrast": _FakeReply(args=[QDBusVariant(out_of_range)]),
    }
    _install(monkeypatch, replies)
    _capture_journal(monkeypatch)

    prefs = ap.read_appearance_preferences()

    assert prefs.color_scheme is None
    assert prefs.contrast is None


def test_contrast_rejects_a_value_colour_scheme_accepts(monkeypatch):
    """The range is per key, not one shared set: 2 is a valid colour scheme
    and is not a valid contrast."""
    replies = {
        "color-scheme": _FakeReply(args=[QDBusVariant(2)]),
        "contrast": _FakeReply(args=[QDBusVariant(2)]),
    }
    _install(monkeypatch, replies)
    _capture_journal(monkeypatch)

    prefs = ap.read_appearance_preferences()

    assert prefs.color_scheme == 2
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

# The module must have no way to read the portal's accent colour at all --
# the value is already available through theme().accent, and decoding the
# portal's own key for it crashes the interpreter (09-RESEARCH.md R-6).
def _code_string_literals(module) -> list[str]:
    """Every string literal in ``module``'s *code* -- docstrings excluded.

    Scanning names would range mostly over the module's imports and would
    pass a function called ``read_highlight``. Scanning the raw text would
    be tripped by the docstring that explains why the accent key is
    avoided, which has to be allowed to name it. What must not exist is a
    literal the module could actually send.
    """
    tree = ast.parse(inspect.getsource(module))
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            docstrings.add(id(first.value))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings]


def test_the_module_names_no_accent_key_it_could_ever_send():
    literals = _code_string_literals(ap)
    assert literals, "the module should carry at least its own key names"
    offenders = [text for text in literals if "accent" in text.lower()]
    assert not offenders, (
        f"the module carries a string literal naming the portal's accent "
        f"key: {offenders} -- D-14 keeps that key out of this module "
        "entirely")
