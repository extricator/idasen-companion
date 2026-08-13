"""Tests for the Flatpak login-autostart portal module.

Mocked at the D-Bus boundary this module itself calls
(``QDBusConnection``/``QDBusInterface``), the same spirit as
``gui/service_ctl``'s own tests monkeypatching its subprocess helper rather
than shelling out. No test here touches a real session bus or requires a
portal to exist — every scenario, including the deadline expiry, is driven
synchronously by a fake that decides the outcome itself.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

# Forced, not defaulted -- see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtDBus import QDBusMessage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.gui import background_portal as bp  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """A live event loop -- set_autostart runs a real nested QEventLoop.

    QApplication, not the plain QCoreApplication this module itself needs --
    every other GUI test file in this suite creates a QApplication, and the
    app singleton is process-wide. Whichever test file runs first decides its
    concrete class; instantiating QApplication once a QCoreApplication
    instance already exists is a fatal Qt error, aborting the whole run
    rather than failing one test.
    """
    return QApplication.instance() or QApplication([])


class _FakeConnection:
    """Stands in for QDBusConnection at the one boundary this module calls."""

    def __init__(self, *, connected=True):
        self.connected = connected
        self.connect_calls = []
        self.disconnect_calls = []
        self.waiter = None

    def isConnected(self):
        return self.connected

    def baseService(self):
        return ":1.999"

    def connect(self, service, path, interface, name, receiver, slot):
        self.connect_calls.append((service, path, interface, name, receiver, slot))
        self.waiter = receiver
        return True

    def disconnect(self, service, path, interface, name, receiver, slot):
        self.disconnect_calls.append((service, path, interface, name, receiver, slot))
        return True


class _FakeSessionBus:
    """Stands in for the QDBusConnection class; sessionBus() is the only
    member this module reads off it."""

    def __init__(self, connection):
        self._connection = connection

    def sessionBus(self):
        return self._connection


class _FakeReply:
    def __init__(self, *, error=""):
        self._error = error

    def type(self):
        return (QDBusMessage.MessageType.ErrorMessage if self._error
                else QDBusMessage.MessageType.ReplyMessage)

    def errorMessage(self):
        return self._error


class _FakeInterface:
    """Stands in for QDBusInterface. A `call()` drives the connected
    waiter's Response synchronously and records the arguments it was sent."""

    def __init__(self, connection, *, call_error="", response=0, results=None):
        self.connection = connection
        self.call_error = call_error
        self.response = response
        self.results = {} if results is None else results
        self.calls = []

    def call(self, method, *args):
        self.calls.append((method, args))
        if not self.call_error and self.connection.waiter is not None:
            self.connection.waiter.on_response(self.response, dict(self.results))
        return _FakeReply(error=self.call_error)


def _install(monkeypatch, *, connected=True, call_error="", response=0, results=None):
    """Wire the module to a fake bus; returns (connection, [captured interface])."""
    connection = _FakeConnection(connected=connected)
    made = []

    def fake_interface_ctor(service, path, interface, conn):
        iface = _FakeInterface(conn, call_error=call_error, response=response, results=results)
        made.append(iface)
        return iface

    monkeypatch.setattr(bp, "is_flatpak", lambda: True)
    monkeypatch.setattr(bp, "QDBusConnection", _FakeSessionBus(connection))
    monkeypatch.setattr(bp, "QDBusInterface", fake_interface_ctor)
    return connection, made


# ----- sandbox detection -----

def test_is_flatpak_true_when_marker_present(monkeypatch):
    monkeypatch.setattr("os.path.exists", lambda path: path == "/.flatpak-info")
    assert bp.is_flatpak() is True


def test_is_flatpak_false_when_marker_absent(monkeypatch):
    monkeypatch.setattr("os.path.exists", lambda path: False)
    assert bp.is_flatpak() is False


# ----- outside Flatpak: both entry points, both directions -----

def test_set_autostart_outside_flatpak_enable_is_noop(monkeypatch):
    monkeypatch.setattr(bp, "is_flatpak", lambda: False)
    assert bp.set_autostart(True) == (True, "")


def test_set_autostart_outside_flatpak_disable_is_noop(monkeypatch):
    monkeypatch.setattr(bp, "is_flatpak", lambda: False)
    assert bp.set_autostart(False) == (True, "")


def test_reconcile_outside_flatpak_is_noop(monkeypatch):
    # Under the RPM systemd owns autostart; the portal must never be called.
    monkeypatch.setattr(bp, "is_flatpak", lambda: False)
    calls = []
    monkeypatch.setattr(bp, "set_autostart", lambda enable: calls.append(enable))
    bp.reconcile_autostart(True)
    assert calls == []


def test_reconcile_disabled_is_noop_inside_flatpak(monkeypatch):
    # The default (disabled) case must not touch the portal on every launch.
    monkeypatch.setattr(bp, "is_flatpak", lambda: True)
    calls = []
    monkeypatch.setattr(bp, "set_autostart", lambda enable: calls.append(enable))
    bp.reconcile_autostart(False)
    assert calls == []


def test_reconcile_disabled_is_noop_outside_flatpak(monkeypatch):
    monkeypatch.setattr(bp, "is_flatpak", lambda: False)
    calls = []
    monkeypatch.setattr(bp, "set_autostart", lambda enable: calls.append(enable))
    bp.reconcile_autostart(False)
    assert calls == []


def test_reconcile_enabled_inside_flatpak_reasserts_once(monkeypatch):
    monkeypatch.setattr(bp, "is_flatpak", lambda: True)
    calls = []
    monkeypatch.setattr(bp, "set_autostart", lambda enable: calls.append(enable))
    bp.reconcile_autostart(True)
    assert calls == [True]


def test_reconcile_swallows_a_raising_set_autostart(monkeypatch):
    # A launch must not be disrupted by this, ever -- not even by a bug.
    monkeypatch.setattr(bp, "is_flatpak", lambda: True)

    def boom(_enable):
        raise RuntimeError("boom")

    monkeypatch.setattr(bp, "set_autostart", boom)
    bp.reconcile_autostart(True)  # must not raise


# ----- granted / cancelled / other, both directions -----

def test_set_autostart_enable_granted(monkeypatch):
    connection, made = _install(monkeypatch, response=0, results={"autostart": True})
    assert bp.set_autostart(True) == (True, "")
    assert made[0].calls
    assert connection.disconnect_calls


def test_disable_success_with_autostart_false_is_reported_as_success(monkeypatch):
    # This is the specific bug this line exists to prevent: a disable call
    # that succeeds gets back autostart: False, and a check written against
    # a hardcoded true would misread that as a failure. Written so it fails
    # against exactly that implementation -- see the mutation proof recorded
    # in 03-07-SUMMARY.md, which was run for real against this test.
    _install(monkeypatch, response=0, results={"autostart": False})
    assert bp.set_autostart(False) == (True, "")


def test_response_disagreeing_with_request_is_non_success_enabling(monkeypatch):
    _install(monkeypatch, response=0, results={"autostart": False})
    ok, err = bp.set_autostart(True)  # asked True, portal answered False
    assert ok is False
    assert err


def test_response_disagreeing_with_request_is_non_success_disabling(monkeypatch):
    _install(monkeypatch, response=0, results={"autostart": True})
    ok, err = bp.set_autostart(False)  # asked False, portal answered True
    assert ok is False
    assert err


def test_set_autostart_cancelled_is_distinguishable_not_an_exception(monkeypatch):
    connection, _ = _install(monkeypatch, response=1, results={})
    ok, err = bp.set_autostart(True)
    assert ok is False
    assert err
    assert connection.disconnect_calls


def test_set_autostart_other_response_code_is_non_success(monkeypatch):
    _install(monkeypatch, response=2, results={})
    ok, err = bp.set_autostart(True)
    assert ok is False
    assert err


# ----- the disable call's actual wire arguments -----

def test_disable_call_sends_autostart_false(monkeypatch):
    _connection, made = _install(monkeypatch, response=0, results={"autostart": False})
    bp.set_autostart(False)
    method, args = made[0].calls[0]
    assert method == "RequestBackground"
    _parent_window, options = args
    assert options["autostart"] is False


def test_disable_call_restates_every_other_option_unchanged(monkeypatch):
    # The portal decides autostart together with the rest of the request;
    # a disable call that silently dropped an option while flipping
    # autostart could revoke more than intended. Prove the two calls' option
    # sets agree on everything except the flag that actually changed,
    # against the captured arguments rather than inferred.
    connection_a, made_a = _install(monkeypatch, response=0, results={"autostart": True})
    bp.set_autostart(True)
    enable_options = made_a[0].calls[0][1][1]

    connection_b, made_b = _install(monkeypatch, response=0, results={"autostart": False})
    bp.set_autostart(False)
    disable_options = made_b[0].calls[0][1][1]

    unchanged = {"reason", "commandline", "dbus-activatable"}
    for key in unchanged:
        assert enable_options[key] == disable_options[key]
    assert enable_options["autostart"] is True
    assert disable_options["autostart"] is False


# ----- deadline and portal errors -----

def test_set_autostart_deadline_expires_without_a_response(monkeypatch):
    monkeypatch.setattr(bp, "_RESPONSE_DEADLINE_MS", 20)  # milliseconds, not seconds
    connection = _FakeConnection()

    class _NeverRespondsInterface:
        def __init__(self, service, path, interface, conn):
            pass

        def call(self, method, *args):
            return _FakeReply()  # the call itself "succeeds"; no Response ever fires

    monkeypatch.setattr(bp, "is_flatpak", lambda: True)
    monkeypatch.setattr(bp, "QDBusConnection", _FakeSessionBus(connection))
    monkeypatch.setattr(bp, "QDBusInterface", _NeverRespondsInterface)

    ok, err = bp.set_autostart(True)
    assert ok is False
    assert err
    assert connection.disconnect_calls  # disconnected even after a timeout


def test_set_autostart_portal_call_error_returns_short_string(monkeypatch):
    connection, _made = _install(monkeypatch, call_error="org.freedesktop.DBus.Error.ServiceUnknown")
    ok, err = bp.set_autostart(True)
    assert ok is False
    assert err
    assert connection.disconnect_calls  # disconnected even though the call failed


def test_set_autostart_no_session_bus_connection(monkeypatch):
    connection = _FakeConnection(connected=False)
    monkeypatch.setattr(bp, "is_flatpak", lambda: True)
    monkeypatch.setattr(bp, "QDBusConnection", _FakeSessionBus(connection))
    ok, err = bp.set_autostart(True)
    assert ok is False
    assert err


def test_set_autostart_absent_or_refusing_portal_degrades_to_error_text(monkeypatch):
    # A portal missing or denied at the bus is a normal decline, not a crash
    # -- this is also what stands in for the connect() call itself failing.
    class _BoomConnection:
        def isConnected(self):
            return True

        def baseService(self):
            return ":1.1"

        def connect(self, *_args, **_kwargs):
            raise ValueError("no such interface")

    monkeypatch.setattr(bp, "is_flatpak", lambda: True)
    monkeypatch.setattr(bp, "QDBusConnection", _FakeSessionBus(_BoomConnection()))
    ok, err = bp.set_autostart(True)
    assert ok is False
    assert err == "no such interface"


def test_could_not_listen_for_response_is_non_success(monkeypatch):
    class _RefusingConnection(_FakeConnection):
        def connect(self, *args, **kwargs):
            super().connect(*args, **kwargs)
            return False

    connection = _RefusingConnection()
    monkeypatch.setattr(bp, "is_flatpak", lambda: True)
    monkeypatch.setattr(bp, "QDBusConnection", _FakeSessionBus(connection))
    ok, err = bp.set_autostart(True)
    assert ok is False
    assert err
    assert not connection.disconnect_calls  # nothing to disconnect


# ----- listener cleanup across every outcome -----

def test_response_listener_disconnected_on_success_failure_and_timeout(monkeypatch):
    connection_ok, _ = _install(monkeypatch, response=0, results={"autostart": True})
    bp.set_autostart(True)
    assert connection_ok.disconnect_calls

    connection_cancelled, _ = _install(monkeypatch, response=1, results={})
    bp.set_autostart(True)
    assert connection_cancelled.disconnect_calls

    monkeypatch.setattr(bp, "_RESPONSE_DEADLINE_MS", 20)
    connection_timeout = _FakeConnection()

    class _NeverRespondsInterface:
        def __init__(self, service, path, interface, conn):
            pass

        def call(self, method, *args):
            return _FakeReply()

    monkeypatch.setattr(bp, "is_flatpak", lambda: True)
    monkeypatch.setattr(bp, "QDBusConnection", _FakeSessionBus(connection_timeout))
    monkeypatch.setattr(bp, "QDBusInterface", _NeverRespondsInterface)
    bp.set_autostart(True)
    assert connection_timeout.disconnect_calls
