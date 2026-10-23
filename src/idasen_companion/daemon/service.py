# SPDX-License-Identifier: GPL-3.0-or-later
"""D-Bus service interfaces exported by the daemon.

Well-known name: io.github.extricator.IdasenCompanion
Object path:     /io/github/extricator/IdasenCompanion

Interfaces:
  .Desk1        - desk state and manual control
  .Automation1  - automation state machine control and status
  .Presets1     - named position presets
  .Stats1       - sit/stand statistics
  .Log1         - recent activity log (ring buffer)

Live updates come as flat, basic-typed signals (HeightChanged,
StatusChanged, ...) in addition to standard PropertiesChanged, and
tabular data is returned as JSON strings: PySide6's QtDBus cannot
demarshal non-variant container types, so the wire format sticks to
what every binding handles.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, TYPE_CHECKING

from dbus_fast.annotations import (
    DBusBool, DBusDouble, DBusInt32, DBusUInt32, DBusStr, DBusSignature,
)

from dbus_fast.service import ServiceInterface, dbus_property, dbus_method, dbus_signal
from dbus_fast.constants import PropertyAccess

from .. import DBUS_NAME
from ..core.decoded_data import LogEntry
from ..core.lengths import Length

if TYPE_CHECKING:
    from .main import Daemon

EmptyResult = Annotated[None, DBusSignature("")]
ProgressPayload = Annotated[tuple[float, float], DBusSignature("dd")]
PositionObservationPayload = Annotated[tuple[str, bool, float, float, float], DBusSignature("sbddd")]
WarningPayload = Annotated[tuple[str, int], DBusSignature("su")]
TransitionPayload = Annotated[tuple[str, str, bool], DBusSignature("ssb")]
LogPayload = Annotated[tuple[float, str, str, str, str, str], DBusSignature("dsssss")]

# The exported members below (methods, properties, signals) are PascalCase by
# the D-Bus wire-protocol convention documented in the project's "D-Bus wire
# format" section: they are called by exact string name off-process, over the
# bus, so they cannot be renamed to snake_case. Each carries its own inline
# naming-check suppression rather than a file-level one, so a genuinely new,
# non-framework name here still fails the check.


class Desk1(ServiceInterface):
    def __init__(self, daemon: Daemon) -> None:
        super().__init__(f"{DBUS_NAME}.Desk1")
        self.d = daemon

    @dbus_method()
    def GetPositionObservation(self) -> PositionObservationPayload:  # pylint: disable=invalid-name
        return self.d.position_observation_snapshot()

    @dbus_signal()
    def PositionObservationChanged(  # pylint: disable=invalid-name
            self, position: DBusStr, known: DBusBool, started: DBusDouble,
            elapsed: DBusDouble, remaining: DBusDouble) -> PositionObservationPayload:
        return position, known, started, elapsed, remaining

    @dbus_property(access=PropertyAccess.READ)
    def Connected(self) -> DBusBool:  # pylint: disable=invalid-name
        return self.d.desk_connected

    @dbus_property(access=PropertyAccess.READ)
    def Height(self) -> DBusDouble:  # pylint: disable=invalid-name
        height = self.d.machine.last_height
        return height.metres if height is not None else 0.0

    @dbus_property(access=PropertyAccess.READ)
    def Moving(self) -> DBusBool:  # pylint: disable=invalid-name
        return self.d.moving

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> DBusStr:  # pylint: disable=invalid-name
        return self.d.position_string()

    @dbus_method()
    async def Sit(self) -> EmptyResult:  # pylint: disable=invalid-name
        await self.d.manual_move_to_preset("sit")

    @dbus_method()
    async def Stand(self) -> EmptyResult:  # pylint: disable=invalid-name
        await self.d.manual_move_to_preset("stand")

    @dbus_method()
    async def MoveToPreset(self, name: DBusStr) -> EmptyResult:  # pylint: disable=invalid-name
        await self.d.manual_move_to_preset(name)

    @dbus_method()
    async def Toggle(self) -> EmptyResult:  # pylint: disable=invalid-name
        """Flip the desk between sit and stand (opposite of its current
        position). Moves unconditionally; see GestureMove for the
        repeat-to-cancel tray/shortcut variant."""
        await self.d.toggle_sit_stand()

    @dbus_method()
    async def GestureMove(self, action: DBusStr) -> EmptyResult:  # pylint: disable=invalid-name
        """A tray/keyboard gesture move (``toggle``/``sit``/``stand``) with
        repeat-to-cancel semantics per ``[ui] tray_repeat_move``: repeating the
        same gesture mid-move stops or reverses it. Used by the tray gestures
        and the shared command's movement subcommands."""
        await self.d.gesture_move(action)

    @dbus_method()
    async def MoveToHeight(self, height: DBusDouble) -> EmptyResult:  # pylint: disable=invalid-name
        await self.d.manual_move_to_height(Length(height))

    @dbus_method()
    async def Stop(self) -> EmptyResult:  # pylint: disable=invalid-name
        await self.d.stop_movement()

    @dbus_method()
    async def Discover(self, timeout: DBusInt32) -> DBusStr:  # pylint: disable=invalid-name
        """Scan for nearby BLE desks; returns JSON [[name, mac], ...].
        timeout=0 returns paired devices and cached scan results instantly."""
        return json.dumps(await self.d.discover(timeout))

    @dbus_method()
    async def Setup(self, mac: DBusStr) -> DBusDouble:  # pylint: disable=invalid-name
        """Verified onboarding: connect, pair (best-effort) and read the
        height BEFORE saving the address. Returns the current height."""
        return (await self.d.setup_desk(mac)).metres

    @dbus_signal()
    def HeightChanged(self, height: DBusDouble) -> DBusDouble:  # pylint: disable=invalid-name
        return height

    @dbus_signal()
    def PositionChanged(self, position: DBusStr) -> DBusStr:  # pylint: disable=invalid-name
        return position

    @dbus_signal()
    def ConnectedChanged(self, connected: DBusBool) -> DBusBool:  # pylint: disable=invalid-name
        return connected

    @dbus_signal()
    def MovingChanged(self, moving: DBusBool) -> DBusBool:  # pylint: disable=invalid-name
        return moving


class Automation1(ServiceInterface):
    def __init__(self, daemon: Daemon) -> None:
        super().__init__(f"{DBUS_NAME}.Automation1")
        self.d = daemon

    @dbus_property(access=PropertyAccess.READ)
    def Enabled(self) -> DBusBool:  # pylint: disable=invalid-name
        return self.d.config.automation.enabled

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> DBusStr:  # pylint: disable=invalid-name
        return self.d.status_string()

    @dbus_property(access=PropertyAccess.READ)
    def ActiveTime(self) -> DBusDouble:  # pylint: disable=invalid-name
        return self.d.machine.active_time.seconds

    @dbus_property(access=PropertyAccess.READ)
    def TargetDuration(self) -> DBusDouble:  # pylint: disable=invalid-name
        return self.d.machine.target_duration.seconds

    @dbus_property(access=PropertyAccess.READ)
    def TimeRemaining(self) -> DBusDouble:  # pylint: disable=invalid-name
        return self.d.machine.time_remaining().seconds

    @dbus_property(access=PropertyAccess.READ)
    def SnoozeUntil(self) -> DBusDouble:  # pylint: disable=invalid-name
        deadline = self.d.machine.snooze_until
        if deadline is None:
            return 0.0
        return deadline.epoch_seconds or 0.0

    @dbus_property(access=PropertyAccess.READ)
    def SkipNextPending(self) -> DBusBool:  # pylint: disable=invalid-name
        return self.d.machine.skip_next

    @dbus_property(access=PropertyAccess.READ)
    def IdleProvider(self) -> DBusStr:  # pylint: disable=invalid-name
        return self.d.idle_provider_name()

    @dbus_method()
    def SetEnabled(self, enabled: DBusBool) -> EmptyResult:  # pylint: disable=invalid-name
        self.d.set_automation_enabled(enabled)

    @dbus_method()
    def Pause(self) -> EmptyResult:  # pylint: disable=invalid-name
        self.d.pause()

    @dbus_method()
    def Resume(self) -> EmptyResult:  # pylint: disable=invalid-name
        self.d.resume()

    @dbus_method()
    def SkipNext(self) -> EmptyResult:  # pylint: disable=invalid-name
        self.d.skip_next()

    @dbus_method()
    def Snooze(self, minutes: DBusInt32) -> EmptyResult:  # pylint: disable=invalid-name
        self.d.snooze(minutes)

    @dbus_method()
    def ReloadConfig(self) -> EmptyResult:  # pylint: disable=invalid-name
        self.d.reload_config()

    @dbus_signal()
    def StatusChanged(self, status: DBusStr) -> DBusStr:  # pylint: disable=invalid-name
        return status

    @dbus_signal()
    def ProgressChanged(self, active_time: DBusDouble, target_duration: DBusDouble) -> ProgressPayload:  # pylint: disable=invalid-name
        return (active_time, target_duration)

    @dbus_signal()
    def PreMoveWarning(self, to_state: DBusStr, seconds: DBusUInt32) -> WarningPayload:  # pylint: disable=invalid-name
        return (to_state, seconds)

    @dbus_signal()
    def TransitionCompleted(self, from_state: DBusStr, to_state: DBusStr,  # pylint: disable=invalid-name
                            interrupted: DBusBool) -> TransitionPayload:
        return (from_state, to_state, interrupted)


class Presets1(ServiceInterface):
    def __init__(self, daemon: Daemon) -> None:
        super().__init__(f"{DBUS_NAME}.Presets1")
        self.d = daemon

    @dbus_method()
    def List(self) -> DBusStr:  # pylint: disable=invalid-name
        return json.dumps(self.d.config.presets)

    @dbus_method()
    def Save(self, name: DBusStr, height: DBusDouble) -> EmptyResult:  # pylint: disable=invalid-name
        self.d.save_preset(name, Length(height))

    @dbus_method()
    async def CaptureCurrent(self, name: DBusStr) -> DBusDouble:  # pylint: disable=invalid-name
        return (await self.d.capture_current_preset(name)).metres

    @dbus_method()
    def Rename(self, old: DBusStr, new: DBusStr) -> EmptyResult:  # pylint: disable=invalid-name
        self.d.rename_preset(old, new)

    @dbus_method()
    def Delete(self, name: DBusStr) -> EmptyResult:  # pylint: disable=invalid-name
        self.d.delete_preset(name)

    @dbus_signal()
    def PresetsChanged(self, presets_json: DBusStr) -> DBusStr:  # pylint: disable=invalid-name
        return presets_json


class Stats1(ServiceInterface):
    """Statistics named rows retain their field order as JSON arrays."""

    def __init__(self, daemon: Daemon) -> None:
        super().__init__(f"{DBUS_NAME}.Stats1")
        self.d = daemon

    @dbus_method()
    def GetDaily(self, start: DBusStr, end: DBusStr) -> DBusStr:  # pylint: disable=invalid-name
        return json.dumps(self.d.stats.daily_totals(
            date.fromisoformat(start), date.fromisoformat(end)))

    @dbus_method()
    def GetTransitions(self, limit: DBusInt32) -> DBusStr:  # pylint: disable=invalid-name
        return json.dumps(self.d.stats.recent_transitions(limit))


class Log1(ServiceInterface):
    def __init__(self, daemon: Daemon) -> None:
        super().__init__(f"{DBUS_NAME}.Log1")
        self.d = daemon

    @dbus_method()
    def GetRecent(self) -> DBusStr:  # pylint: disable=invalid-name
        # Safe unguarded: entry params are made JSON-serializable when the
        # line is recorded (see ringlog.Entry).
        entries: list[LogEntry] = [e.as_dict() for e in self.d.activity_log.entries()]
        return json.dumps(entries)

    @dbus_signal()
    def Entry(self, timestamp: DBusDouble, level: DBusStr, channel: DBusStr, msg_id: DBusStr,  # pylint: disable=invalid-name
              params: DBusStr, text: DBusStr) -> LogPayload:
        """One log line.

        ``channel`` says who it is for and ``level`` how bad it is — two axes,
        because one was doing both jobs (see docs/LOGGING.md). ``msg_id`` plus
        ``params`` let the GUI compose its own translated sentence; ``text`` is
        the English the daemon already composed, and is what a client shows
        when it doesn't recognize the id.

        ``params`` is a JSON string rather than a dict because PySide6's QtDBus
        cannot demarshal non-variant containers — the same constraint that
        keeps every other table on this bus in JSON.
        """
        return (timestamp, level, channel, msg_id, params, text)
