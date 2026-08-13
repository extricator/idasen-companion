"""Qt-side client for the daemon's D-Bus service.

Wraps QtDBus in a QObject that re-emits daemon state as Qt signals, so
the tray and windows stay live without polling. Desk commands are sent
asynchronously — a moving desk must never freeze the UI. The two exceptions
are ``rename_preset_sync`` and ``capture_preset``, which block because the
caller has a field to put right or a value to show; both are marked Blocking
in their docstrings and both raise a busy cursor.

Wire format note: PySide6's QtDBus cannot demarshal non-variant D-Bus
container types, so the daemon exposes flat basic-typed signals
(HeightChanged, StatusChanged, ...) and JSON strings for tabular data.
Scalar properties are read individually via org.freedesktop.DBus.
Properties.Get, which QtDBus handles fine.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Signal, Slot, SLOT
from PySide6.QtDBus import (
    QDBusConnection,
    QDBusInterface,
    QDBusMessage,
    QDBusPendingCallWatcher,
    QDBusServiceWatcher,
    QDBusVariant,
)

from .. import DBUS_NAME, DBUS_PATH

IFACE_DESK = f"{DBUS_NAME}.Desk1"
IFACE_AUTO = f"{DBUS_NAME}.Automation1"
IFACE_PRESETS = f"{DBUS_NAME}.Presets1"
IFACE_STATS = f"{DBUS_NAME}.Stats1"
IFACE_LOG = f"{DBUS_NAME}.Log1"


def _reply_args(reply: QDBusMessage) -> list | None:
    """A successful reply's arguments, or None when there is nothing to read.

    An error reply and a reply carrying no arguments are the same answer to
    every caller here — neither has a value in it — so they collapse into one
    check rather than being spelled out at each call site.
    """
    if reply.type() != QDBusMessage.MessageType.ReplyMessage:
        return None
    return reply.arguments() or None


def _unwrap(value):
    """A property value out of its QDBusVariant wrapper, when it is in one."""
    return value.variant() if isinstance(value, QDBusVariant) else value


class DaemonClient(QObject):
    availableChanged = Signal(bool)

    # Desk1
    heightChanged = Signal(float)
    positionChanged = Signal(str)  # sitting / standing
    connectedChanged = Signal(bool)
    movingChanged = Signal(bool)

    # Automation1
    statusChanged = Signal(str)
    progressChanged = Signal(float, float)  # active_time, target_duration
    transitionCompleted = Signal(str, str, bool)
    snoozeUntilChanged = Signal(float)  # unix ts, 0.0 when not snoozed

    #: A fire-and-forget command came back an error. (error name, detail).
    #: Every _async_call used to discard its reply, so a desk that could not
    #: be reached made Overview's Sit/Stand/Move/Stop appear to do nothing at
    #: all: the daemon's DBusError went nowhere, and `machine.move_failed` is
    #: only set by the *automation* path, so no status changed either.
    commandFailed = Signal(str, str)

    # Presets1 / Log1
    presetsChanged = Signal(dict)
    # ts, level, channel, msg_id, params, English text. The id and params are
    # what let the Activity Log compose a translated sentence; the text is the
    # fallback for ids this build doesn't know. See docs/LOGGING.md.
    logEntry = Signal(float, str, str, str, dict, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bus = QDBusConnection.sessionBus()
        self.available = False
        self._snooze_until = 0.0

        self._watcher = QDBusServiceWatcher(
            DBUS_NAME, self.bus,
            QDBusServiceWatcher.WatchForRegistration
            | QDBusServiceWatcher.WatchForUnregistration,
            self)
        self._watcher.serviceRegistered.connect(lambda _: self._set_available(True))
        self._watcher.serviceUnregistered.connect(lambda _: self._set_available(False))

        def subscribe(iface: str, signal_name: str, slot_name: str) -> None:
            self.bus.connect(DBUS_NAME, DBUS_PATH, iface, signal_name,
                             self, SLOT(f"{slot_name}(QDBusMessage)"))

        subscribe(IFACE_DESK, "HeightChanged", "_on_height")
        subscribe(IFACE_DESK, "PositionChanged", "_on_position")
        subscribe(IFACE_DESK, "ConnectedChanged", "_on_connected")
        subscribe(IFACE_DESK, "MovingChanged", "_on_moving")
        subscribe(IFACE_AUTO, "StatusChanged", "_on_status")
        subscribe(IFACE_AUTO, "ProgressChanged", "_on_progress")
        subscribe(IFACE_AUTO, "TransitionCompleted", "_on_transition")
        subscribe(IFACE_PRESETS, "PresetsChanged", "_on_presets_changed")
        subscribe(IFACE_LOG, "Entry", "_on_log_entry")

        if self._ping():
            self._set_available(True)

    # ----- availability -----

    def _ping(self) -> bool:
        iface = self.bus.interface()
        if iface is None:
            return False
        reply = iface.call("NameHasOwner", DBUS_NAME)
        return bool(reply.arguments() and reply.arguments()[0])

    def _set_available(self, available: bool) -> None:
        self.available = available
        self.availableChanged.emit(available)
        if available:
            self.refresh_all()

    # ----- signal handlers (all take the raw message; args are flat) -----

    @Slot(QDBusMessage)
    def _on_height(self, message: QDBusMessage) -> None:
        self.heightChanged.emit(float(message.arguments()[0]))

    @Slot(QDBusMessage)
    def _on_position(self, message: QDBusMessage) -> None:
        self.positionChanged.emit(str(message.arguments()[0]))

    @Slot(QDBusMessage)
    def _on_connected(self, message: QDBusMessage) -> None:
        self.connectedChanged.emit(bool(message.arguments()[0]))

    @Slot(QDBusMessage)
    def _on_moving(self, message: QDBusMessage) -> None:
        self.movingChanged.emit(bool(message.arguments()[0]))

    @Slot(QDBusMessage)
    def _on_status(self, message: QDBusMessage) -> None:
        status = str(message.arguments()[0])
        self._note_status(status)
        self.statusChanged.emit(status)

    @Slot(QDBusMessage)
    def _on_progress(self, message: QDBusMessage) -> None:
        active_time, target = message.arguments()
        self.progressChanged.emit(float(active_time), float(target))

    @Slot(QDBusMessage)
    def _on_transition(self, message: QDBusMessage) -> None:
        from_state, to_state, interrupted = message.arguments()
        self.transitionCompleted.emit(str(from_state), str(to_state),
                                      bool(interrupted))

    @Slot(QDBusMessage)
    def _on_presets_changed(self, message: QDBusMessage) -> None:
        self.presetsChanged.emit(json.loads(message.arguments()[0]))

    @Slot(QDBusMessage)
    def _on_log_entry(self, message: QDBusMessage) -> None:
        # Unpacked positionally rather than by destructuring: an RPM upgrade
        # restarts the daemon under an *already running* GUI, so a client can
        # meet a payload of a different length than it was built for. The
        # tuple-unpack version raised ValueError on every single log line —
        # once per entry, forever, until the GUI was relaunched. Reading what
        # is there and defaulting the rest degrades instead.
        args = message.arguments()
        if len(args) < 3:
            return
        entry_timestamp, level = args[0], args[1]
        if len(args) >= 6:
            channel, msg_id, params, text = args[2], args[3], args[4], args[5]
        else:
            # An older daemon: (ts, level, message). No id to render from, so
            # the English it sent is the line, and its audience is unknown —
            # treat it as activity, which is what that build only ever emitted.
            channel, msg_id, params, text = "activity", "", "", args[2]
        try:
            decoded = json.loads(str(params)) if params else {}
        except ValueError:
            decoded = {}
        if not isinstance(decoded, dict):
            decoded = {}
        self.logEntry.emit(float(entry_timestamp), str(level), str(channel), str(msg_id),
                           decoded, str(text))

    # ----- reads -----

    def _iface(self, name: str) -> QDBusInterface:
        return QDBusInterface(DBUS_NAME, DBUS_PATH, name, self.bus)

    def get_property(self, iface_name: str, name: str):
        props = QDBusInterface(DBUS_NAME, DBUS_PATH,
                               "org.freedesktop.DBus.Properties", self.bus)
        args = _reply_args(props.call("Get", iface_name, name))
        return _unwrap(args[0]) if args else None

    def get_property_async(self, iface_name: str, name: str, then) -> None:
        """Non-blocking ``Properties.Get``; ``then(value)`` on success only.

        ``PropertiesChanged`` would be the obvious way to keep a property
        live, but its signature is ``sa{sv}as`` — precisely the container
        QtDBus cannot demarshal (see the module docstring), which is why the
        daemon carries flat signals at all. So a property that has to stay
        current is re-read, and this is how that happens without parking the
        GUI thread on a round-trip."""
        message = QDBusMessage.createMethodCall(
            DBUS_NAME, DBUS_PATH, "org.freedesktop.DBus.Properties", "Get")
        message.setArguments([iface_name, name])
        watcher = QDBusPendingCallWatcher(self.bus.asyncCall(message), self)

        def finished(property_watcher: QDBusPendingCallWatcher) -> None:
            property_watcher.deleteLater()
            args = _reply_args(property_watcher.reply())
            if args:
                then(_unwrap(args[0]))

        watcher.finished.connect(finished)

    def _call_for_json(self, iface: str, member: str, *args):
        replied = _reply_args(self._iface(iface).call(member, *args))
        return json.loads(replied[0]) if replied else None

    def refresh_all(self) -> None:
        height = self.get_property(IFACE_DESK, "Height")
        if height is not None:
            self.heightChanged.emit(float(height))
        position = self.get_property(IFACE_DESK, "Position")
        if position is not None:
            self.positionChanged.emit(str(position))
        connected = self.get_property(IFACE_DESK, "Connected")
        if connected is not None:
            self.connectedChanged.emit(bool(connected))
        moving = self.get_property(IFACE_DESK, "Moving")
        if moving is not None:
            self.movingChanged.emit(bool(moving))
        status = self.get_property(IFACE_AUTO, "Status")
        if status is not None:
            self._note_status(str(status))
            self.statusChanged.emit(str(status))
        active_time = self.get_property(IFACE_AUTO, "ActiveTime")
        target = self.get_property(IFACE_AUTO, "TargetDuration")
        if active_time is not None and target is not None:
            self.progressChanged.emit(float(active_time), float(target))
        self.presetsChanged.emit(self.list_presets())

    def set_automation_enabled(self, enabled: bool) -> None:
        self._async_call(IFACE_AUTO, "SetEnabled", bool(enabled))

    def _note_status(self, status: str) -> None:
        """Keep the snooze deadline cached alongside the status it belongs to.

        Reading it is a round-trip, and the Overview drew it straight from a
        blocking ``Properties.Get`` on the GUI thread every time it rendered
        the snoozed state. The value can only have moved when the status is
        announced — including a second snooze extending the first, which
        re-announces ``snoozed`` — so this is the one place it needs fetching,
        asynchronously, with ``snooze_until()`` served from cache."""
        if status == "snoozed":
            self.get_property_async(IFACE_AUTO, "SnoozeUntil",
                                    self._set_snooze_until)
        else:
            self._set_snooze_until(0.0)

    def _set_snooze_until(self, value) -> None:
        value = float(value or 0.0)
        if value != self._snooze_until:
            self._snooze_until = value
            self.snoozeUntilChanged.emit(value)

    def snooze_until(self) -> float:
        """Cached, never a round-trip — see ``_note_status``. 0.0 when the
        cycle isn't snoozed, and briefly when a snooze has just been announced
        but its deadline hasn't arrived yet; ``snoozeUntilChanged`` says when
        it has."""
        return self._snooze_until

    def idle_provider(self) -> str:
        return str(self.get_property(IFACE_AUTO, "IdleProvider") or "unknown")

    def list_presets(self) -> dict:
        presets = self._call_for_json(IFACE_PRESETS, "List")
        return ({name: float(h) for name, h in presets.items()}
                if isinstance(presets, dict) else {})

    def get_daily_stats(self, start: str, end: str) -> list:
        rows = self._call_for_json(IFACE_STATS, "GetDaily", start, end)
        return [tuple(row) for row in rows] if rows else []

    def get_transitions(self, limit: int = 50) -> list:
        rows = self._call_for_json(IFACE_STATS, "GetTransitions", limit)
        return [tuple(row) for row in rows] if rows else []

    def get_recent_log(self) -> list[dict]:
        """The daemon's in-memory backlog, as entry dicts.

        Only what the *running* daemon has seen. History from before it
        started comes from the journal instead (``core.journal.read_recent``),
        which is what makes the Activity Log survive a restart."""
        rows = self._call_for_json(IFACE_LOG, "GetRecent")
        return [row for row in rows if isinstance(row, dict)] if rows else []

    def discover(self, timeout: int = 8) -> list:
        """Blocking scan call — run from the wizard with a busy cursor.
        timeout=0 returns paired devices + cached scan instantly."""
        iface = self._iface(IFACE_DESK)
        iface.setTimeout(45_000)
        args = _reply_args(iface.call("Discover", timeout))
        return [tuple(row) for row in json.loads(args[0])] if args else []

    def setup(self, mac: str) -> tuple[bool, float | str]:
        """Verified onboarding: (True, height) or (False, error message).
        Blocking; the daemon connects, pairs and reads the height."""
        iface = self._iface(IFACE_DESK)
        iface.setTimeout(90_000)
        reply = iface.call("Setup", mac)
        args = _reply_args(reply)
        if args:
            return True, float(args[0])
        return False, reply.errorMessage() or "no reply from daemon"

    # ----- commands (async unless a docstring says Blocking) -----

    def _async_call(self, iface_name: str, member: str, *args) -> None:
        """Fire-and-forget method call, but not fire-and-forget *errors*.

        Built from a raw QDBusMessage because PySide6's
        QDBusAbstractInterface.asyncCall binding does not accept call
        arguments. The reply is watched only to surface a failure — the
        success path stays asynchronous and unblocking, which is the whole
        point of these; a moving desk must never freeze the UI.
        """
        message = QDBusMessage.createMethodCall(DBUS_NAME, DBUS_PATH,
                                                iface_name, member)
        if args:
            message.setArguments(list(args))
        watcher = QDBusPendingCallWatcher(self.bus.asyncCall(message), self)

        def finished(command_watcher: QDBusPendingCallWatcher) -> None:
            command_watcher.deleteLater()
            reply = command_watcher.reply()
            if reply.type() == QDBusMessage.MessageType.ErrorMessage:
                self.commandFailed.emit(reply.errorName() or "",
                                        reply.errorMessage() or "")

        watcher.finished.connect(finished)

    def sit(self) -> None:
        self._async_call(IFACE_DESK, "Sit")

    def stand(self) -> None:
        self._async_call(IFACE_DESK, "Stand")

    def toggle(self) -> None:
        self._async_call(IFACE_DESK, "Toggle")

    def gesture_move(self, action: str) -> None:
        # A tray/shortcut gesture with repeat-to-cancel semantics; the daemon
        # decides stop/reverse/redirect from its authoritative movement state.
        self._async_call(IFACE_DESK, "GestureMove", action)

    def move_to_preset(self, name: str) -> None:
        self._async_call(IFACE_DESK, "MoveToPreset", name)

    def move_to_height(self, height: float) -> None:
        self._async_call(IFACE_DESK, "MoveToHeight", float(height))

    def stop(self) -> None:
        self._async_call(IFACE_DESK, "Stop")

    def pause(self) -> None:
        self._async_call(IFACE_AUTO, "Pause")

    def resume(self) -> None:
        self._async_call(IFACE_AUTO, "Resume")

    def skip_next(self) -> None:
        self._async_call(IFACE_AUTO, "SkipNext")

    def snooze(self, minutes: int) -> None:
        self._async_call(IFACE_AUTO, "Snooze", int(minutes))

    def reload_config(self) -> None:
        self._async_call(IFACE_AUTO, "ReloadConfig")

    def save_preset(self, name: str, height: float) -> None:
        self._async_call(IFACE_PRESETS, "Save", name, float(height))

    def rename_preset_sync(self, old: str, new: str) -> tuple[bool, str]:
        """Blocking Rename — one daemon-side write, so it cannot half-happen.

        Blocking because the caller has an edited field to put right if the
        daemon refuses (a duplicate name, a protected preset). Returns
        (True, "") or (False, err)."""
        reply = self._iface(IFACE_PRESETS).call("Rename", old, new)
        if reply.type() == QDBusMessage.MessageType.ReplyMessage:
            return True, ""
        return False, reply.errorMessage() or "no reply from daemon"

    def capture_preset(self, name: str) -> tuple[bool, float | str]:
        """Capture the desk's current height into a preset. Blocking — the
        daemon may need a BLE connect to read the height — so callers show
        a busy cursor. Returns (True, height) or (False, error message)."""
        iface = self._iface(IFACE_PRESETS)
        iface.setTimeout(30_000)
        reply = iface.call("CaptureCurrent", name)
        args = _reply_args(reply)
        if args:
            return True, float(args[0])
        return False, reply.errorMessage() or "no reply from daemon"

    def delete_preset(self, name: str) -> None:
        self._async_call(IFACE_PRESETS, "Delete", name)
