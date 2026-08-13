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

from dbus_fast.service import ServiceInterface, dbus_property, method, signal
from dbus_fast.constants import PropertyAccess

from .. import DBUS_NAME

# The exported members below (methods, properties, signals) are PascalCase by
# the D-Bus wire-protocol convention documented in CLAUDE.md's "D-Bus wire
# format" section: they are called by exact string name off-process, over the
# bus, so they cannot be renamed to snake_case. Each carries its own inline
# naming-check suppression rather than a file-level one, so a genuinely new,
# non-framework name here still fails the check.


class Desk1(ServiceInterface):
    def __init__(self, daemon):
        super().__init__(f"{DBUS_NAME}.Desk1")
        self.d = daemon

    @dbus_property(access=PropertyAccess.READ)
    def Connected(self) -> "b":  # pylint: disable=invalid-name
        return self.d.desk_connected

    @dbus_property(access=PropertyAccess.READ)
    def Height(self) -> "d":  # pylint: disable=invalid-name
        return self.d.machine.last_height or 0.0

    @dbus_property(access=PropertyAccess.READ)
    def Moving(self) -> "b":  # pylint: disable=invalid-name
        return self.d.moving

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> "s":  # pylint: disable=invalid-name
        return self.d.position_string()

    @method()
    async def Sit(self):  # pylint: disable=invalid-name
        await self.d.manual_move_to_preset("sit")

    @method()
    async def Stand(self):  # pylint: disable=invalid-name
        await self.d.manual_move_to_preset("stand")

    @method()
    async def MoveToPreset(self, name: "s"):  # pylint: disable=invalid-name
        await self.d.manual_move_to_preset(name)

    @method()
    async def Toggle(self):  # pylint: disable=invalid-name
        """Flip the desk between sit and stand (opposite of its current
        position). Moves unconditionally; see GestureMove for the
        repeat-to-cancel tray/shortcut variant."""
        await self.d.toggle_sit_stand()

    @method()
    async def GestureMove(self, action: "s"):  # pylint: disable=invalid-name
        """A tray/keyboard gesture move (``toggle``/``sit``/``stand``) with
        repeat-to-cancel semantics per ``[ui] tray_repeat_move``: repeating the
        same gesture mid-move stops or reverses it. Used by the tray gestures
        and the CLI shortcut flags."""
        await self.d.gesture_move(action)

    @method()
    async def MoveToHeight(self, height: "d"):  # pylint: disable=invalid-name
        await self.d.manual_move_to_height(height)

    @method()
    async def Stop(self):  # pylint: disable=invalid-name
        await self.d.stop_movement()

    @method()
    async def Discover(self, timeout: "i") -> "s":  # pylint: disable=invalid-name
        """Scan for nearby BLE desks; returns JSON [[name, mac], ...].
        timeout=0 returns paired devices and cached scan results instantly."""
        return json.dumps(await self.d.discover(timeout))

    @method()
    async def Setup(self, mac: "s") -> "d":  # pylint: disable=invalid-name
        """Verified onboarding: connect, pair (best-effort) and read the
        height BEFORE saving the address. Returns the current height."""
        return await self.d.setup_desk(mac)

    @signal()
    def HeightChanged(self, height: "d") -> "d":  # pylint: disable=invalid-name
        return height

    @signal()
    def PositionChanged(self, position: "s") -> "s":  # pylint: disable=invalid-name
        return position

    @signal()
    def ConnectedChanged(self, connected: "b") -> "b":  # pylint: disable=invalid-name
        return connected

    @signal()
    def MovingChanged(self, moving: "b") -> "b":  # pylint: disable=invalid-name
        return moving


class Automation1(ServiceInterface):
    def __init__(self, daemon):
        super().__init__(f"{DBUS_NAME}.Automation1")
        self.d = daemon

    @dbus_property(access=PropertyAccess.READ)
    def Enabled(self) -> "b":  # pylint: disable=invalid-name
        return self.d.config.automation.enabled

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":  # pylint: disable=invalid-name
        return self.d.status_string()

    @dbus_property(access=PropertyAccess.READ)
    def ActiveTime(self) -> "d":  # pylint: disable=invalid-name
        return self.d.machine.active_time

    @dbus_property(access=PropertyAccess.READ)
    def TargetDuration(self) -> "d":  # pylint: disable=invalid-name
        return float(self.d.machine.target_duration)

    @dbus_property(access=PropertyAccess.READ)
    def TimeRemaining(self) -> "d":  # pylint: disable=invalid-name
        return self.d.machine.time_remaining()

    @dbus_property(access=PropertyAccess.READ)
    def SnoozeUntil(self) -> "d":  # pylint: disable=invalid-name
        return self.d.machine.snooze_until or 0.0

    @dbus_property(access=PropertyAccess.READ)
    def SkipNextPending(self) -> "b":  # pylint: disable=invalid-name
        return self.d.machine.skip_next

    @dbus_property(access=PropertyAccess.READ)
    def IdleProvider(self) -> "s":  # pylint: disable=invalid-name
        return self.d.idle_provider_name()

    @method()
    def SetEnabled(self, enabled: "b"):  # pylint: disable=invalid-name
        self.d.set_automation_enabled(enabled)

    @method()
    def Pause(self):  # pylint: disable=invalid-name
        self.d.pause()

    @method()
    def Resume(self):  # pylint: disable=invalid-name
        self.d.resume()

    @method()
    def SkipNext(self):  # pylint: disable=invalid-name
        self.d.skip_next()

    @method()
    def Snooze(self, minutes: "i"):  # pylint: disable=invalid-name
        self.d.snooze(minutes)

    @method()
    def ReloadConfig(self):  # pylint: disable=invalid-name
        self.d.reload_config()

    @signal()
    def StatusChanged(self, status: "s") -> "s":  # pylint: disable=invalid-name
        return status

    @signal()
    def ProgressChanged(self, active_time: "d", target_duration: "d") -> "dd":  # pylint: disable=invalid-name
        return [active_time, target_duration]

    @signal()
    def PreMoveWarning(self, to_state: "s", seconds: "u") -> "su":  # pylint: disable=invalid-name
        return [to_state, seconds]

    @signal()
    def TransitionCompleted(self, from_state: "s", to_state: "s",  # pylint: disable=invalid-name
                            interrupted: "b") -> "ssb":
        return [from_state, to_state, interrupted]


class Presets1(ServiceInterface):
    def __init__(self, daemon):
        super().__init__(f"{DBUS_NAME}.Presets1")
        self.d = daemon

    @method()
    def List(self) -> "s":  # pylint: disable=invalid-name
        return json.dumps(self.d.config.presets)

    @method()
    def Save(self, name: "s", height: "d"):  # pylint: disable=invalid-name
        self.d.save_preset(name, height)

    @method()
    async def CaptureCurrent(self, name: "s") -> "d":  # pylint: disable=invalid-name
        return await self.d.capture_current_preset(name)

    @method()
    def Rename(self, old: "s", new: "s"):  # pylint: disable=invalid-name
        self.d.rename_preset(old, new)

    @method()
    def Delete(self, name: "s"):  # pylint: disable=invalid-name
        self.d.delete_preset(name)

    @signal()
    def PresetsChanged(self, presets_json: "s") -> "s":  # pylint: disable=invalid-name
        return presets_json


class Stats1(ServiceInterface):
    def __init__(self, daemon):
        super().__init__(f"{DBUS_NAME}.Stats1")
        self.d = daemon

    @method()
    def GetDaily(self, start: "s", end: "s") -> "s":  # pylint: disable=invalid-name
        return json.dumps(self.d.stats.daily_totals(
            date.fromisoformat(start), date.fromisoformat(end)))

    @method()
    def GetTransitions(self, limit: "i") -> "s":  # pylint: disable=invalid-name
        return json.dumps(self.d.stats.recent_transitions(limit))


class Log1(ServiceInterface):
    def __init__(self, daemon):
        super().__init__(f"{DBUS_NAME}.Log1")
        self.d = daemon

    @method()
    def GetRecent(self) -> "s":  # pylint: disable=invalid-name
        # Safe unguarded: entry params are made JSON-serializable when the
        # line is recorded (see ringlog.Entry).
        return json.dumps([e.as_dict() for e in self.d.activity_log.entries()])

    @signal()
    def Entry(self, timestamp: "d", level: "s", channel: "s", msg_id: "s",  # pylint: disable=invalid-name
              params: "s", text: "s") -> "dsssss":
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
        return [timestamp, level, channel, msg_id, params, text]
